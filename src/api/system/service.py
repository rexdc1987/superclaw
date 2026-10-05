"""Build metadata plus the Gitee-backed auto-update engine.

The server never updates itself in place. It downloads a signed-by-hash payload
into ``data/updates/staging/<version>/`` and then asks the launcher to restart;
the launcher swaps ``app/`` while nothing holds those files open. That keeps a
failed download from ever leaving a half-updated installation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

GITEE_API = os.environ.get("SUPERCLAW_UPDATE_API", "https://gitee.com/api/v5").rstrip("/")
DEFAULT_TIMEOUT = 20
DOWNLOAD_TIMEOUT = 60

_state_lock = threading.Lock()
_download_thread: Optional[threading.Thread] = None
_state: Dict[str, object] = {
    "phase": "idle",
    "version": "",
    "progress": 0.0,
    "downloaded_bytes": 0,
    "total_bytes": 0,
    "message": "",
    "error": "",
}


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #

def app_root() -> Path:
    """<install>/app in a packaged install, the repo root when running from source."""
    return Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    configured = os.environ.get("SUPERCLAW_DATA_DIR")
    if configured:
        return Path(configured)
    root = app_root()
    if (root.parent / "runtime").is_dir():
        return root.parent / "data"
    return root / "data"


def updates_dir() -> Path:
    return data_dir() / "updates"


def staging_dir() -> Path:
    return updates_dir() / "staging"


def instance_settings() -> Dict[str, object]:
    path = data_dir() / "instance.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


# --------------------------------------------------------------------------- #
# build metadata
# --------------------------------------------------------------------------- #

def read_version() -> str:
    path = app_root() / "VERSION"
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text.lstrip("vV")
    return "0.0.0"


def read_build_manifest() -> Dict[str, object]:
    path = app_root() / "BUILD.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


# Captured once, at import time. ``build_info()`` compares this against the
# VERSION sitting on disk to answer a question the version number alone cannot:
# *is this process running the code that is actually installed?* The updater
# rewrites app/ on disk and then asks the launcher to re-exec; a process that
# skipped the re-exec keeps serving its already-imported modules while happily
# reporting the new version, because that is read from disk.
_LOADED_VERSION = read_version()
_PROCESS_STARTED_AT = datetime.now().isoformat(timespec="seconds")


def update_repo() -> str:
    for candidate in (
        os.environ.get("SUPERCLAW_UPDATE_REPO"),
        instance_settings().get("update_repo"),
    ):
        if candidate and str(candidate).strip():
            return str(candidate).strip().strip("/")
    return ""


def update_token() -> str:
    return os.environ.get("SUPERCLAW_UPDATE_TOKEN", "").strip()


def current_execution_mode() -> str:
    return os.environ.get("SUPERCLAW_EXECUTION_MODE", "embedded")


def build_info() -> Dict[str, object]:
    manifest = read_build_manifest()
    on_disk = read_version()
    return {
        "version": on_disk,
        # What this process actually has loaded. Equal to `version` unless an
        # update was applied without the launcher re-exec'ing — see above.
        "loaded_version": _LOADED_VERSION,
        "code_current": _LOADED_VERSION == on_disk,
        "runtime_pid": os.getpid(),
        "started_at": _PROCESS_STARTED_AT,
        "git_sha": str(manifest.get("git_sha") or "unknown"),
        "built_at": manifest.get("built_at"),
        "edition": str(manifest.get("edition") or "server"),
        "execution_mode": current_execution_mode(),
        "install_root": str(app_root()),
        "update_repo": update_repo(),
    }


# --------------------------------------------------------------------------- #
# http helpers (stdlib only — keeps the shipped runtime lean)
# --------------------------------------------------------------------------- #

def _opener() -> urllib.request.OpenerDirector:
    if os.environ.get("SUPERCLAW_UPDATE_BYPASS_PROXY", "").strip() in ("1", "true", "yes"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _fetch_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": "SuperClaw-Updater"})
    with _opener().open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "SuperClaw-Updater"})
    with _opener().open(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace").strip()


# --------------------------------------------------------------------------- #
# version comparison
# --------------------------------------------------------------------------- #

def parse_version(raw: str) -> Tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)*)", str(raw or ""))
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    left, right = parse_version(latest), parse_version(current)
    length = max(len(left), len(right))
    left += (0,) * (length - len(left))
    right += (0,) * (length - len(right))
    return left > right


# --------------------------------------------------------------------------- #
# gitee release lookup
# --------------------------------------------------------------------------- #

def _release_assets(release: Dict[str, object], repo: str) -> List[Dict[str, object]]:
    assets = release.get("assets") or []
    if isinstance(assets, list) and assets:
        return [a for a in assets if isinstance(a, dict)]
    release_id = release.get("id")
    if not release_id:
        return []
    url = "%s/repos/%s/releases/%s/attach_files" % (GITEE_API, repo, release_id)
    token = update_token()
    if token:
        url += "?access_token=" + token
    try:
        payload = _fetch_json(url)
    except (urllib.error.URLError, OSError, ValueError):
        return []
    return [a for a in payload if isinstance(a, dict)] if isinstance(payload, list) else []


def _asset_name(asset: Dict[str, object]) -> str:
    for key in ("name", "title", "attach_file_name", "filename"):
        value = asset.get(key)
        if value:
            return str(value)
    return ""


def _asset_url(asset: Dict[str, object]) -> str:
    for key in ("browser_download_url", "download_url", "url"):
        value = asset.get(key)
        if value and str(value).startswith("http"):
            return str(value)
    return ""


def web_base() -> str:
    """Human-facing host for a release, derived from the configured API base.

    Lets the same code serve gitee.com, a self-hosted Gitea, or a local test
    double without hardcoding the public domain into the release link.
    """
    base = GITEE_API
    for suffix in ("/api/v5", "/api/v1", "/api"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def _result(**overrides: object) -> Dict[str, object]:
    """Every return path must carry the full response shape.

    The router declares ``UpdateCheckResponse``; a short dict (the easy mistake
    when bailing out early) turns into a 500 instead of a readable message.
    """
    payload = {
        "configured": False,
        "update_available": False,
        "current_version": read_version(),
        "latest_version": "",
        "notes": "",
        "published_at": "",
        "release_url": "",
        "asset": None,
        "message": "",
    }
    payload.update(overrides)
    return payload


def fetch_latest_release() -> Dict[str, object]:
    repo = update_repo()
    if not repo:
        return _result(message="尚未配置更新源，请在 data/instance.json 里填写 update_repo（形如 owner/superclaw）。")

    url = "%s/repos/%s/releases/latest" % (GITEE_API, repo)
    token = update_token()
    if token:
        url += "?access_token=" + token
    try:
        release = _fetch_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            return _result(configured=True, message=(
                "更新源不可用（HTTP %d）。若是私有仓库，请配置 SUPERCLAW_UPDATE_TOKEN。" % exc.code))
        return _result(configured=True, message="查询更新失败：HTTP %d" % exc.code)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return _result(configured=True, message="查询更新失败：%s" % exc)

    if not isinstance(release, dict):
        return _result(configured=True, message="更新源返回了非预期的内容")

    tag = str(release.get("tag_name") or release.get("name") or "").strip()
    version = tag.lstrip("vV")
    current = read_version()
    settings = instance_settings()
    channel = str(settings.get("update_channel") or "stable")
    if release.get("prerelease") and channel != "prerelease":
        return _result(configured=True, current_version=current, latest_version=version,
                       message="远端最新版本是预发布版，当前通道为 %s，已跳过。" % channel)

    assets = _release_assets(release, repo)
    app_asset = None
    sha_asset = None
    wanted = "SuperClaw-app-%s.zip" % version
    for asset in assets:
        name = _asset_name(asset)
        if name == wanted:
            app_asset = asset
        elif name == wanted + ".sha256":
            sha_asset = asset
    if app_asset is None:
        # Tolerate a hand-built release that only carries the full package.
        for asset in assets:
            if _asset_name(asset).startswith("SuperClaw-app-") and _asset_name(asset).endswith(".zip"):
                app_asset, wanted = asset, _asset_name(asset)
                break

    if app_asset is None:
        return _result(configured=True, current_version=current, latest_version=version,
                       message="远端 %s 未附带应用更新包（期望 %s）。" % (tag or version, wanted))

    available = is_newer(version, current)
    return _result(
        configured=True,
        update_available=available,
        current_version=current,
        latest_version=version,
        notes=str(release.get("body") or "")[:4000],
        published_at=str(release.get("created_at") or ""),
        release_url="%s/%s/releases/tag/%s" % (web_base(), repo, tag or version),
        asset={
            "name": _asset_name(app_asset),
            "size": int(app_asset.get("size") or app_asset.get("file_size") or 0),
            "url": _asset_url(app_asset),
            "sha256": _asset_url(sha_asset) if sha_asset else "",
        },
        message=("发现新版本 v%s，当前 v%s。" % (version, current)) if available
        else "当前已是最新版本 v%s。" % current,
    )


# --------------------------------------------------------------------------- #
# download state machine
# --------------------------------------------------------------------------- #

def download_state() -> Dict[str, object]:
    with _state_lock:
        return dict(_state)


def reset_download_state() -> None:
    """Return the updater to idle. Called on every app startup.

    The launcher applies an update and then re-runs the app *in the same
    process*, so this module's state survives the restart. Without an explicit
    reset the UI keeps reporting the pre-restart "applying…" phase forever.
    """
    _set_state(phase="idle", version="", progress=0.0, downloaded_bytes=0,
               total_bytes=0, message="", error="")


def _set_state(**kwargs: object) -> None:
    with _state_lock:
        _state.update(kwargs)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_to(url: str, dest: Path, total_hint: int = 0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "SuperClaw-Updater"})
    with _opener().open(request, timeout=DOWNLOAD_TIMEOUT) as response:
        total = int(response.headers.get("Content-Length") or 0) or total_hint
        done = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                _set_state(
                    downloaded_bytes=done,
                    total_bytes=total,
                    progress=round(done / total, 4) if total else 0.0,
                )


def _verify_zip_manifest(archive: Path, version: str) -> Tuple[bool, str]:
    """Cross-check the archive against the BUILD.json it carries."""
    try:
        with zipfile.ZipFile(archive) as zf:
            bad = zf.testzip()
            if bad:
                return False, "压缩包损坏：%s" % bad
            try:
                manifest = json.loads(zf.read("app/BUILD.json").decode("utf-8"))
            except KeyError:
                return False, "更新包里缺少 app/BUILD.json"
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return False, "更新包无法读取：%s" % exc

    if str(manifest.get("version") or "") != version:
        return False, "更新包版本号不一致（包内 %s，期望 %s）" % (manifest.get("version"), version)
    for item in manifest.get("files", []):
        rel = item.get("path")
        if not rel or rel == "BUILD.json":
            continue
        try:
            with zipfile.ZipFile(archive) as zf:
                digest = hashlib.sha256(zf.read("app/" + rel)).hexdigest()
        except KeyError:
            return False, "更新包缺少文件：%s" % rel
        if digest != item.get("sha256"):
            return False, "更新包文件校验失败：%s" % rel
    return True, ""


def _discard_staging(version: str) -> None:
    """Drop this version's staging dir.

    Called before a download starts (a previous attempt may have left a partial
    tree) and again on failure, so a rejected package never lingers on disk
    waiting to be mistaken for a usable one.
    """
    target = staging_dir() / version
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)


def _run_download(asset: Dict[str, object], version: str) -> None:
    try:
        _set_state(phase="downloading", version=version, progress=0.0,
                   downloaded_bytes=0, total_bytes=0, error="",
                   message="正在下载 v%s…" % version)
        url = str(asset.get("url") or "")
        if not url:
            raise RuntimeError("更新源没有给出下载地址")

        _discard_staging(version)
        version_dir = staging_dir() / version
        archive = version_dir / str(asset.get("name") or ("SuperClaw-app-%s.zip" % version))
        _download_to(url, archive, int(asset.get("size") or 0))

        _set_state(message="正在校验…")
        expected = str(asset.get("sha256") or "").strip()
        if expected:
            if "://" in expected:
                sidecar = _fetch_text(expected).split()
                expected = sidecar[0] if sidecar else ""
            if expected and sha256_file(archive) != expected:
                raise RuntimeError("sha256 校验不通过，更新包可能不完整")
        elif not expected:
            # No sidecar published — fall back to the in-archive manifest.
            pass

        ok, reason = _verify_zip_manifest(archive, version)
        if not ok:
            raise RuntimeError(reason)

        with zipfile.ZipFile(archive) as zf:
            zf.extractall(version_dir)

        digest = sha256_file(archive)
        pending = {
            "version": version,
            "asset": archive.name,
            "sha256": digest,
            "staged_at": datetime.now().isoformat(timespec="seconds"),
            "staging_dir": str(version_dir),
        }
        (updates_dir() / "pending.json").write_text(
            json.dumps(pending, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        _set_state(phase="ready", progress=1.0,
                   message="v%s 已下载并校验通过，可以重启更新。" % version)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        _discard_staging(version)
        _set_state(phase="failed", error=str(exc), message="更新下载失败：%s" % exc)


def start_download(asset: Dict[str, object], version: str) -> Dict[str, object]:
    global _download_thread
    with _state_lock:
        if _download_thread is not None and _download_thread.is_alive():
            return dict(_state)
    _download_thread = threading.Thread(
        target=_run_download, args=(asset, version), name="superclaw-update", daemon=True,
    )
    _download_thread.start()
    return download_state()


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #

def pending_update() -> Dict[str, object]:
    path = updates_dir() / "pending.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def request_apply() -> Dict[str, object]:
    """Ask the launcher to swap app/ and restart. Returns (ok, message)."""
    pending = pending_update()
    version = str(pending.get("version") or "")
    if not version:
        return {"ok": False, "message": "没有已下载的更新，请先下载。"}
    staged = staging_dir() / version / "app" / "BUILD.json"
    if not staged.is_file():
        return {"ok": False, "message": "暂存目录不完整，请重新下载更新。"}

    try:
        updates_dir().mkdir(parents=True, exist_ok=True)
        (updates_dir() / "apply.flag").write_text(version, encoding="utf-8")
        (updates_dir() / "restart.flag").write_text(version, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "message": "无法写入更新标记：%s" % exc}

    _set_state(phase="applying", message="v%s 即将应用，服务正在重启…" % version)
    return {"ok": True, "message": "已安排重启，服务将在几秒内自动替换为 v%s。" % version}
