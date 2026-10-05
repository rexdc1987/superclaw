#!/usr/bin/env python
"""Publish a built release to Gitee so other machines pick it up.

This closes the loop the whole update mechanism depends on:

    build  →  Gitee Release  →  in-app "check update"  →  one-click update

Without it you would hand-upload a zip and a .sha256 to the release page every
time, and any typo in the asset name silently breaks the updater (it looks for
exactly ``SuperClaw-app-<version>.zip``).

Typical use, from the repo root:

    python deploy/build_server_package.py --version 1.0.4     # 或 build_installer.py
    python deploy/publish_release.py --version 1.0.4 --notes "修复了 X"

The token is read from --token, then SUPERCLAW_UPDATE_TOKEN, then
deploy/.gitee-token (git-ignored). A Gitee token needs the ``projects`` scope.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API = "https://gitee.com/api/v5"

# What the in-app updater looks for, and what a human needs for a fresh install.
REQUIRED_ASSETS = ("SuperClaw-app-{v}.zip",)
OPTIONAL_ASSETS = (
    "SuperClaw-app-{v}.zip.sha256",
    "SuperClaw-server-{v}.zip",
    "SuperClaw-server-{v}.zip.sha256",
    "SuperClaw-Setup-{v}.exe",
    "SuperClaw-Setup-{v}.exe.sha256",
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def normalize_version(raw: str) -> str:
    cleaned = raw.strip().lstrip("vV")
    if not re.fullmatch(r"\d+\.\d+\.\d+", cleaned):
        raise SystemExit("版本号必须是 X.Y.Z 形式，收到 %r" % raw)
    return cleaned


def read_version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"


def resolve_token(explicit: str) -> str:
    for candidate in (explicit, os.environ.get("SUPERCLAW_UPDATE_TOKEN", "")):
        if candidate and candidate.strip():
            return candidate.strip()
    token_file = ROOT / "deploy" / ".gitee-token"
    if token_file.is_file():
        text = token_file.read_text(encoding="utf-8").strip()
        if text:
            return text
    raise SystemExit(
        "缺少 Gitee 访问令牌。三种给法（任选其一）：\n"
        "    python deploy/publish_release.py --token <TOKEN>\n"
        "    set SUPERCLAW_UPDATE_TOKEN=<TOKEN>\n"
        "    把令牌写进 deploy/.gitee-token（该文件已在 .gitignore 里）\n"
        "令牌需要勾选 projects 权限，在 https://gitee.com/profile/personal_access_tokens 生成。"
    )


def api_base() -> str:
    return os.environ.get("SUPERCLAW_UPDATE_API", DEFAULT_API).rstrip("/")


# --------------------------------------------------------------------------- #
# http
# --------------------------------------------------------------------------- #

def _opener() -> urllib.request.OpenerDirector:
    # The host injects HTTP(S)_PROXY values; honour them unless explicitly told not to.
    if os.environ.get("SUPERCLAW_UPDATE_BYPASS_PROXY", "").strip() in ("1", "true", "yes"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _request(url: str, data=None, headers=None, method=None):
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with _opener().open(request, timeout=180) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise SystemExit("HTTP %d：%s\n%s" % (exc.code, url, detail)) from None
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit("请求失败：%s\n%s" % (exc, url)) from None
    if not body.strip():
        return None
    try:
        return json.loads(body)
    except ValueError:
        return body


def api_get(path: str, token: str, params: dict | None = None):
    query = {"access_token": token}
    query.update(params or {})
    return _request("%s%s?%s" % (api_base(), path, urllib.parse.urlencode(query)))


def api_post_json(path: str, token: str, payload: dict):
    body = json.dumps(payload).encode("utf-8")
    return _request(
        "%s%s?access_token=%s" % (api_base(), path, urllib.parse.quote(token)),
        data=body,
        headers={"Content-Type": "application/json;charset=UTF-8"},
        method="POST",
    )


def api_upload(path: str, token: str, file_path: Path):
    """POST multipart/form-data with a single ``file`` part."""
    boundary = "----SuperClawBoundary%s" % uuid.uuid4().hex
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

    head = (
        "--%s\r\n"
        'Content-Disposition: form-data; name="file"; filename="%s"\r\n'
        "Content-Type: %s\r\n\r\n"
    ) % (boundary, file_path.name, content_type)
    tail = "\r\n--%s--\r\n" % boundary

    body = head.encode("utf-8") + file_path.read_bytes() + tail.encode("utf-8")
    return _request(
        "%s%s?access_token=%s" % (api_base(), path, urllib.parse.quote(token)),
        data=body,
        headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary},
        method="POST",
    )


# --------------------------------------------------------------------------- #
# release helpers
# --------------------------------------------------------------------------- #

def get_release_by_tag(repo: str, tag: str, token: str):
    try:
        payload = api_get("/repos/%s/releases/tags/%s" % (repo, tag), token)
    except SystemExit:
        return None
    return payload if isinstance(payload, dict) and payload.get("id") else None


def create_release(repo: str, tag: str, name: str, notes: str, token: str, target: str):
    payload = {"tag_name": tag, "name": name, "body": notes, "prerelease": False}
    if target:
        payload["target_commitish"] = target
    result = api_post_json("/repos/%s/releases" % repo, token, payload)
    if not isinstance(result, dict) or not result.get("id"):
        raise SystemExit("创建发行版失败，返回：%r" % (result,))
    return result


def release_attachments(repo: str, release_id, token: str):
    try:
        # Gitee's own field name is attach_files for a release; the assets key of
        # the release object is often empty, so ask explicitly.
        payload = api_get("/repos/%s/releases/%s/attach_files" % (repo, release_id), token)
    except SystemExit:
        return []
    return [a for a in payload if isinstance(a, dict)] if isinstance(payload, list) else []


def attachment_name(asset: dict) -> str:
    for key in ("name", "title", "attach_file_name", "filename"):
        if asset.get(key):
            return str(asset[key])
    return ""


def delete_attachment(repo: str, release_id, attach_id, token: str):
    return _request(
        "%s/repos/%s/releases/%s/attach_files/%s?access_token=%s"
        % (api_base(), repo, release_id, attach_id, urllib.parse.quote(token)),
        method="DELETE",
    )


def human(num: int) -> str:
    return "%.2f MB" % (num / 1024 / 1024)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="把已构建的版本发布到 Gitee Release")
    parser.add_argument("--version", help="版本号（默认读 VERSION）")
    parser.add_argument("--repo", help="owner/repo（默认读 data/instance.json 或 --repo）")
    parser.add_argument("--token", default="", help="Gitee 访问令牌")
    parser.add_argument("--notes", default="", help="发行说明（会显示在更新提示里）")
    parser.add_argument("--release-dir", default=str(ROOT / "dist" / "release"), help="构建产物目录")
    parser.add_argument("--target", default="", help="tag 指向的分支/提交（默认仓库默认分支）")
    parser.add_argument("--force", action="store_true", help="同名附件已存在时先删除再上传")
    parser.add_argument("--dry-run", action="store_true", help="只检查产物与连通性，不实际上传")
    args = parser.parse_args()

    version = normalize_version(args.version or read_version())
    tag = "v%s" % version
    release_dir = Path(args.release_dir)
    repo = (args.repo or os.environ.get("SUPERCLAW_UPDATE_REPO", "")).strip().strip("/")
    if not repo:
        raise SystemExit(
            "没有指定仓库。用 --repo owner/name，或在 data/instance.json 里填好 update_repo。\n"
            "例：python deploy/publish_release.py --version %s --repo rexdc1987/superclaw" % version
        )

    log("=== 发布 SuperClaw v%s 到 Gitee ===" % version)
    log("仓库 %s   标签 %s" % (repo, tag))
    log("")

    log("[1/4] 检查构建产物")
    present, missing_required = [], []
    for template in REQUIRED_ASSETS + OPTIONAL_ASSETS:
        name = template.format(v=version)
        path = release_dir / name
        if path.is_file():
            present.append(path)
            log("  ✓ %-34s %s" % (name, human(path.stat().st_size)))
        elif template in REQUIRED_ASSETS:
            missing_required.append(name)
            log("  ✗ %-34s 缺失（必需）" % name)
        else:
            log("  · %-34s 无（可选）" % name)

    if missing_required:
        raise SystemExit(
            "\n缺少必需产物：%s\n"
            "先构建再发布：\n"
            "    python deploy/build_server_package.py --version %s\n"
            "    python deploy/build_installer.py    --version %s"
            % ("、".join(missing_required), version, version)
        )

    app_zip = release_dir / ("SuperClaw-app-%s.zip" % version)
    log("")
    log("  app 更新包 sha256 = %s" % sha256_file(app_zip)[:16])

    token = resolve_token(args.token)
    log("  API: %s" % api_base())

    if args.dry_run:
        log("")
        log("--dry-run：产物齐全。查一下更新源连通性…")
        existing = get_release_by_tag(repo, tag, token)
        log("  发行版 %s %s" % (tag, "已存在（会用 --force 覆盖同名附件）" if existing else "尚不存在，将会创建"))
        log("结束（未做任何改动）")
        return 0

    log("")
    log("[2/4] 创建 / 复用发行版")
    release = get_release_by_tag(repo, tag, token)
    if release:
        log("  已存在 release id=%s，复用" % release.get("id"))
    else:
        release = create_release(
            repo, tag, "SuperClaw %s" % tag,
            args.notes or "SuperClaw %s" % tag, token, args.target,
        )
        log("  已创建 release id=%s" % release.get("id"))

    release_id = release.get("id")

    log("")
    log("[3/4] 上传附件")
    existing = {attachment_name(a): a for a in release_attachments(repo, release_id, token)}
    uploaded, skipped = 0, 0
    for path in present:
        prior = existing.get(path.name)
        if prior and not args.force:
            log("  = %-34s 已存在，跳过（要覆盖加 --force）" % path.name)
            skipped += 1
            continue
        if prior and args.force:
            delete_attachment(repo, release_id, prior.get("id"), token)
            log("  - %-34s 已删除旧附件" % path.name)
        result = api_upload(
            "/repos/%s/releases/%s/attach_files" % (repo, release_id), token, path
        )
        if result is None:
            log("  ? %-34s 上传返回空，请在发行版页面上确认" % path.name)
        else:
            log("  ↑ %-34s %s" % (path.name, human(path.stat().st_size)))
        uploaded += 1

    log("")
    log("[4/4] 完成")
    log("  发行版页面: https://gitee.com/%s/releases/tag/%s" % (repo, tag))
    log("  上传 %d 个，跳过 %d 个" % (uploaded, skipped))
    log("")
    log("其他电脑上的动作：")
    log("  已装过的机器 —— 打开系统，顶部提示「发现新版本 v%s」，点「立即更新」。" % version)
    log("  新电脑       —— 下载 SuperClaw-Setup-%s.exe 双击安装。" % version)
    log("")
    log("提醒：目标机器的 data/instance.json 里 update_repo 必须是 %s，否则查不到更新。" % repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
