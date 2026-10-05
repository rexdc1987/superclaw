#!/usr/bin/env python
"""Build the SuperClaw server package (dashboard / control-plane edition).

This produces a self-contained Windows folder that needs no Python, no Node and
no build toolchain on the target machine. Two artifacts come out of one run:

  * ``SuperClaw-server-<version>.zip``  full install payload (runtime + app)
  * ``SuperClaw-app-<version>.zip``     app-only payload, used by the in-app
                                        auto updater (a few MB instead of ~25MB)

Both are paired with a ``.sha256`` sidecar. Gitee caps a single release
attachment at 100MB, so the builder fails loudly if either zip crosses it.

Layout produced under the install root::

    SuperClaw/
      runtime/            Python embeddable + the pinned site-packages subset
      app/                replaces wholesale on update
        src/  frontend/dist/  config/default.yaml  launcher.py  BUILD.json  VERSION
      data/               never touched by updates
        config/  logs/  screenshots/  updates/
      start_superclaw.bat double-click entry point (stable stub, never updated)
      README.txt

``launcher.py`` sits inside ``app/`` on purpose. The updater only rewrites
``app/``, so a launcher kept at the install root could never ship a fix — not
even the fix that makes updates reload the new code. The root keeps only the
.bat, which stays a three-line stub.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as md
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GITEE_ATTACHMENT_LIMIT = 100 * 1024 * 1024
RUNTIME_ZIP = "python-3.8.10-embed-amd64.zip"
RUNTIME_URL = "https://www.python.org/ftp/python/3.8.10/" + RUNTIME_ZIP

# Directories the updater must never overwrite or delete, relative to app/.
PRESERVED_IN_APP = ("config/local.yaml", "config/instance.yaml", "logs", ".run")

SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", "tests", "node_modules"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".log", ".tmp")


def log(msg: str) -> None:
    print(msg, flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dir_size(path: Path) -> int:
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def human(num: int) -> str:
    return "%.2f MB" % (num / 1024 / 1024)


def read_version() -> str:
    for candidate in (ROOT / "VERSION", ROOT / "app" / "VERSION"):
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8").strip()
            if text:
                return text
    return "0.0.0"


def normalize_version(raw: str) -> str:
    cleaned = raw.strip().lstrip("vV")
    if not re.fullmatch(r"\d+\.\d+\.\d+", cleaned):
        raise SystemExit(
            "版本号必须是 X.Y.Z 形式，收到 %r。自动更新靠它做比较，不能随意写。"
            % raw
        )
    return cleaned


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# --------------------------------------------------------------------------- #
# runtime assembly
# --------------------------------------------------------------------------- #

def ensure_runtime_zip(cache_dir: Path) -> Path:
    target = cache_dir / RUNTIME_ZIP
    if target.is_file() and target.stat().st_size > 1_000_000:
        log("  复用已下载的 %s" % RUNTIME_ZIP)
        return target
    cache_dir.mkdir(parents=True, exist_ok=True)
    log("  下载 %s" % RUNTIME_URL)
    # The host injects HTTP(S)_PROXY values that python.org does not honour here,
    # so go direct — matches the verified manual fetch.
    cmd = ["curl", "-sS", "-L", "--noproxy", "*", "-m", "300", "-o", str(target), RUNTIME_URL]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not target.is_file():
        raise SystemExit(
            "下载 Python 运行时失败：%s\n可手动下载 %s 放到 %s"
            % ((result.stderr or "").strip(), RUNTIME_URL, cache_dir)
        )
    return target


def extract_runtime(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    # The embeddable ships a restricted import path. Open it up for
    # Lib/site-packages and let site.py run so .pth files are honoured.
    pth = next(iter(sorted(dest.glob("python*._pth"))), None)
    if pth is None:
        raise SystemExit("运行时包里找不到 python*._pth，无法放开 import 路径")
    pth.write_text(
        "\n".join([
            pth.stem.split(".")[0] + ".zip",
            ".",
            "Lib\\site-packages",
            "import site",
            "",
        ]),
        encoding="utf-8",
    )
    log("  已放开 import 路径: %s" % pth.name)


def load_runtime_distributions() -> list:
    spec = json.loads((ROOT / "deploy" / "runtime-requirements.json").read_text(encoding="utf-8"))
    names = []
    seen = set()
    for raw in spec["distributions"]:
        try:
            dist = md.distribution(raw)
        except md.PackageNotFoundError:
            raise SystemExit(
                "当前 venv 里没有安装 %s。先把 requirements 装齐再打包。" % raw
            )
        canonical = re.sub(r"[-_.]+", "-", dist.metadata["Name"] or raw).lower()
        if canonical in seen:
            continue
        seen.add(canonical)
        names.append(raw)
    return names


def copy_site_packages(names: list, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in names:
        dist = md.distribution(name)
        for entry in dist.files or []:
            rel = str(entry)
            if "__pycache__" in rel or rel.endswith(SKIP_SUFFIXES):
                continue
            src = Path(dist.locate_file(entry))
            if not src.is_file():
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
            copied += 1
        log("    %-22s %s" % (name, dist.version))
    return copied


# --------------------------------------------------------------------------- #
# app assembly
# --------------------------------------------------------------------------- #

def copy_tree(src: Path, dest: Path, written: set, prefix: str) -> int:
    """Copy ``src`` under ``dest``, recording every app-relative path written.

    The recorded set is what BUILD.json gets built from, so anything left in the
    tree by an earlier build is simply never mentioned — and therefore never
    shipped by make_zip(). The client prunes it on the next update, because the
    path is in its old manifest but not the new one.
    """
    if not src.is_dir():
        raise SystemExit("缺少目录: %s" % src)
    count = 0
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIR_NAMES]
        rel_base = Path(base).relative_to(src)
        (dest / rel_base).mkdir(parents=True, exist_ok=True)
        for name in files:
            if name.endswith(SKIP_SUFFIXES):
                continue
            shutil.copy2(Path(base) / name, dest / rel_base / name)
            written.add((Path(prefix) / rel_base / name).as_posix())
            count += 1
    return count


def write_file(path: Path, text: str, written: set, app_dir: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    written.add(path.relative_to(app_dir).as_posix())


def build_app_dir(app_dir: Path, version: str, embed_config: bool) -> set:
    """Refill app/ with the current sources and return what this build wrote.

    Overwrites in place instead of wiping the directory first: the file set
    barely changes between releases, so an ``rmtree`` buys nothing, costs a full
    re-copy, and is indistinguishable from a destructive accident to anything
    watching file deletions. Stale files are handled by scoping the manifest —
    see copy_tree().
    """
    written: set = set()
    app_dir.mkdir(parents=True, exist_ok=True)

    n_src = copy_tree(ROOT / "src", app_dir / "src", written, "src")
    log("    src/                 %d 个文件" % n_src)

    dist_src = ROOT / "frontend" / "dist"
    if not (dist_src / "index.html").is_file():
        raise SystemExit(
            "frontend/dist/index.html 不存在 —— 先在 frontend/ 里跑一次 npm run build。"
        )
    n_dist = copy_tree(dist_src, app_dir / "frontend" / "dist", written, "frontend/dist")
    log("    frontend/dist/       %d 个文件" % n_dist)

    shutil.copy2(ROOT / "run_api.py", app_dir / "run_api.py")
    written.add("run_api.py")

    # Ships with the app so a launcher fix can reach existing installs through
    # the normal app-only update (the updater never touches the install root).
    launcher_src = ROOT / "deploy" / "launcher.py"
    if not launcher_src.is_file():
        raise SystemExit("缺少 deploy/launcher.py")
    shutil.copy2(launcher_src, app_dir / "launcher.py")
    written.add("launcher.py")
    log("    launcher.py          已随 app 一起下发（可自动更新）")

    # default.yaml ships a localhost placeholder DB; the instance config
    # (local.yaml) is the only place a real host belongs.
    shutil.copy2(ROOT / "config" / "default.yaml", app_dir / "config" / "default.yaml")
    written.add("config/default.yaml")

    local_src = ROOT / "config" / "local.yaml"
    if embed_config and local_src.is_file():
        shutil.copy2(local_src, app_dir / "config" / "local.yaml.preset")
        written.add("config/local.yaml.preset")
        log("    config/local.yaml.preset  已内嵌（含真实凭据，注意外发风险）")
    else:
        write_file(
            app_dir / "config" / "local.yaml.preset",
            "# 首次启动时 launcher 会把本文件复制为 local.yaml，请填入真实值。\n"
            "database:\n"
            "  engine: mysql\n"
            "  host: 127.0.0.1\n"
            "  port: 3306\n"
            "  name: superclaw\n"
            "  user: superclaw\n"
            "  password: ''\n"
            "security:\n"
            "  auth_required: true\n"
            "  auth_secret: ''\n",
            written, app_dir,
        )
        log("    config/local.yaml.preset  占位模板（未内嵌真实凭据）")

    write_file(app_dir / "VERSION", version + "\n", written, app_dir)
    return written


def write_manifest(app_dir: Path, version: str, git_rev: str, written: set) -> dict:
    files = []
    for rel in sorted(written):
        if rel == "BUILD.json":
            continue
        full = app_dir / rel
        if not full.is_file():
            raise SystemExit("清单里出现了不存在的文件：%s" % rel)
        files.append({
            "path": rel,
            "size": full.stat().st_size,
            "sha256": sha256_file(full),
        })
    manifest = {
        "product": "SuperClaw",
        "edition": "server",
        "version": version,
        "git_sha": git_rev,
        "built_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "update_scope": "app",
        "preserved": list(PRESERVED_IN_APP),
        "file_count": len(files),
        "files": files,
    }
    (app_dir / "BUILD.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    # BUILD.json is the manifest, so it never lists itself — but it *is* part of
    # what this build produced: the launcher reads it out of the staged update
    # to verify every file, and make_zip ships exactly this set.
    written.add("BUILD.json")
    return manifest


# --------------------------------------------------------------------------- #
# packaging
# --------------------------------------------------------------------------- #

def make_zip(source: Path, arc_prefix: str, out: Path, skip=None) -> None:
    """Zip ``source``. ``skip(rel)`` lets a caller drop paths it did not build."""
    out.parent.mkdir(parents=True, exist_ok=True)
    # Mode "w" truncates an existing archive in place, so rebuilding a release
    # never has to delete the previous one first.
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for base, dirs, names in os.walk(source):
            # Same filter the copy steps use: the app tree is updated in place,
            # so a stray __pycache__ from a local run must not end up inside the
            # payload (it would also change the sha256 of an otherwise
            # byte-identical release).
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIR_NAMES)
            for name in sorted(names):
                if name.endswith(SKIP_SUFFIXES):
                    continue
                full = Path(base) / name
                rel = full.relative_to(source).as_posix()
                if skip is not None and skip(rel):
                    continue
                zf.write(full, (arc_prefix + "/" + rel) if arc_prefix else rel)


def write_sidecar(artifact: Path) -> Path:
    digest = sha256_file(artifact)
    sidecar = artifact.with_suffix(artifact.suffix + ".sha256")
    sidecar.write_text("%s  %s\n" % (digest, artifact.name), encoding="utf-8")
    return sidecar


def enforce_limit(artifact: Path) -> int:
    size = artifact.stat().st_size
    if size > GITEE_ATTACHMENT_LIMIT:
        raise SystemExit(
            "%s 体积 %s 超过 Gitee 单附件 100MB 上限。请检查 runtime-requirements.json，"
            "或改用分卷发布。" % (artifact.name, human(size))
        )
    return size


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the SuperClaw server package")
    parser.add_argument("--version", help="覆盖版本号（默认读 VERSION 文件）")
    parser.add_argument("--out", default=str(ROOT / "dist"), help="输出根目录")
    parser.add_argument("--embed-config", action="store_true",
                        help="把 config/local.yaml 内嵌为预设（含真实凭据，谨慎外发）")
    parser.add_argument("--skip-runtime", action="store_true",
                        help="跳过 runtime 组装，复用已解包的 runtime（仅本地迭代用）")
    parser.add_argument("--app-only", action="store_true",
                        help="只产出 app 增量更新包（日常发版用，秒级完成）")
    parser.add_argument("--no-zip", action="store_true", help="只产出目录，不压缩")
    args = parser.parse_args()

    version = normalize_version(args.version or read_version())
    rev = git_sha()
    out_root = Path(args.out)
    staging = out_root / "server" / "SuperClaw"
    release_dir = out_root / "release"
    cache_dir = out_root / "_cache"

    log("=== SuperClaw 服务端打包 ===")
    log("版本 %s  (git %s)" % (version, rev))
    log("输出 %s" % out_root)
    log("")

    log("[1/5] 组装 Python 运行时")
    runtime_dir = staging / "runtime"
    if args.app_only:
        log("  跳过（--app-only：只发 app 增量包）")
    elif args.skip_runtime and (runtime_dir / "python.exe").is_file():
        log("  复用已有 runtime（--skip-runtime）")
    else:
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir)
        extract_runtime(ensure_runtime_zip(cache_dir), runtime_dir)
        site_packages = runtime_dir / "Lib" / "site-packages"
        names = load_runtime_distributions()
        log("  复制 %d 个运行时依赖" % len(names))
        copied = copy_site_packages(names, site_packages)
        log("  依赖文件合计 %d 个" % copied)
    log("  runtime 体积 %s" % human(dir_size(runtime_dir)))

    log("")
    log("[2/5] 组装应用目录 app/")
    app_dir = staging / "app"
    written = build_app_dir(app_dir, version, args.embed_config)

    log("")
    log("[3/5] 生成文件清单 BUILD.json")
    manifest = write_manifest(app_dir, version, rev, written)
    log("  收录 %d 个文件" % manifest["file_count"])
    log("  app 体积 %s" % human(dir_size(app_dir)))

    log("")
    log("[4/5] 布置启动桩 / 数据目录 / 文档")
    if args.app_only:
        log("  跳过（--app-only 不产全量包）")
    else:
        # Only the stub and the readme live at the root; everything that may
        # need fixing later is inside app/ (see the module docstring).
        for rel in ("start_superclaw.bat", "README.txt"):
            src = ROOT / "deploy" / rel
            if not src.is_file():
                raise SystemExit("缺少 deploy/%s" % rel)
            shutil.copy2(src, staging / rel)
        (staging / "launcher.py").unlink(missing_ok=True)
        for rel in ("config", "logs", "screenshots", "updates"):
            (staging / "data" / rel).mkdir(parents=True, exist_ok=True)
        (staging / "VERSION").write_text(version + "\n", encoding="utf-8")
        (staging / "data" / "instance.json").write_text(
            json.dumps(
                {
                    "_comment": "本机实例设置。自动更新永远不会覆盖这个文件。",
                    "port": 8987,
                    "execution_mode": "api",
                    "open_browser": True,
                    "auto_check_update": True,
                    "update_repo": "",
                    "update_channel": "stable",
                },
                indent=2, ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
        log("  launcher / 数据目录 / README 就位")

    log("")
    log("[5/5] 打包")
    # app/ is updated in place, so it can hold leftovers from an earlier build.
    # They are absent from the manifest; keep them out of both zips too.
    def not_in_manifest(rel: str) -> bool:
        return rel not in written

    def staging_leftover(rel: str) -> bool:
        # Root launcher.py is the pre-1.0.5 layout; the live one is app/launcher.py
        # (it ships inside app/ so updates can replace it).
        if rel == "launcher.py":
            return True
        return rel.startswith("app/") and rel[4:] not in written

    if args.app_only:
        app_zip = release_dir / ("SuperClaw-app-%s.zip" % version)
        make_zip(app_dir, "app", app_zip, skip=not_in_manifest)
        enforce_limit(app_zip)
        write_sidecar(app_zip)
        log("  %s  %s" % (app_zip.name, human(app_zip.stat().st_size)))
        log("")
        log("app 增量包完成（发版时把它和 .sha256 传到 Gitee Release 即可）")
        return

    total = dir_size(staging)
    log("  解包后总计 %s" % human(total))
    if args.no_zip:
        log("  跳过压缩（--no-zip）")
    else:
        full_zip = release_dir / ("SuperClaw-server-%s.zip" % version)
        make_zip(staging, "SuperClaw", full_zip, skip=staging_leftover)
        enforce_limit(full_zip)
        write_sidecar(full_zip)
        log("  %s  %s" % (full_zip.name, human(full_zip.stat().st_size)))

        app_zip = release_dir / ("SuperClaw-app-%s.zip" % version)
        make_zip(app_dir, "app", app_zip, skip=not_in_manifest)
        enforce_limit(app_zip)
        write_sidecar(app_zip)
        log("  %s  %s" % (app_zip.name, human(app_zip.stat().st_size)))

        release_meta = release_dir / ("release-%s.json" % version)
        release_meta.write_text(json.dumps({
            "version": version,
            "git_sha": rev,
            "built_at": manifest["built_at"],
            "full_asset": full_zip.name,
            "full_sha256": sha256_file(full_zip),
            "update_asset": app_zip.name,
            "update_sha256": sha256_file(app_zip),
            "notes": "",
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log("  %s" % release_meta.name)

    log("")
    log("完成。绿色版目录: %s" % staging)
    if args.embed_config:
        log("注意：本次内嵌了 config/local.yaml.preset（含真实数据库口令与 auth_secret），"
            "不要把发布物放到公开仓库。")


if __name__ == "__main__":
    main()
