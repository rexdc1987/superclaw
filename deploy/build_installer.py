#!/usr/bin/env python
"""Compile the Windows installer (SuperClaw-Setup-<version>.exe).

Wraps the two steps that have to happen together:

  1. ``build_server_package.py`` produces the self-contained payload tree under
     ``dist/server/SuperClaw``  (runtime + app + launcher + data skeleton)
  2. Inno Setup compiles that tree into a proper Windows installer: Start-menu
     entry, uninstaller, optional desktop icon / autostart / firewall rule

Run it from the repo root:

    python deploy/build_installer.py                       # 走 VERSION 里的版本号
    python deploy/build_installer.py --version 1.0.4       # 指定版本
    python deploy/build_installer.py --skip-package        # 复用已有 payload（快）
    python deploy/build_installer.py --iscc D:\\Inno\\ISCC.exe

If ISCC is missing the script explains how to install it rather than failing
with a bare traceback.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
ISS = DEPLOY / "installer.iss"

ISCC_CANDIDATES = (
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def human(num: int) -> str:
    return "%.2f MB" % (num / 1024 / 1024)


def read_version() -> str:
    text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    return text or "0.0.0"


def normalize_version(raw: str) -> str:
    cleaned = raw.strip().lstrip("vV")
    if not re.fullmatch(r"\d+\.\d+\.\d+", cleaned):
        raise SystemExit("版本号必须是 X.Y.Z 形式（Inno 的版本资源也要求这样），收到 %r" % raw)
    return cleaned


def find_iscc(explicit: str = "") -> Path:
    for candidate in (explicit, os.environ.get("SUPERCLAW_ISCC", "")):
        if candidate and Path(candidate).is_file():
            return Path(candidate)

    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return Path(found)

    for candidate in ISCC_CANDIDATES:
        if Path(candidate).is_file():
            return Path(candidate)

    # Scoop installs land outside Program Files.
    for home in (Path.home() / "scoop" / "apps" / "inno-setup", Path("C:/scoop/apps/inno-setup")):
        if home.is_dir():
            for candidate in sorted(home.glob("*/ISCC.exe"), reverse=True):
                return candidate

    raise SystemExit(
        "找不到 Inno Setup 的编译器 ISCC.exe。\n"
        "装一个再跑（任选其一）：\n"
        "    scoop install inno-setup\n"
        "    winget install --id JRSoftware.InnoSetup\n"
        "    或到 https://jrsoftware.org/isdl.php 下载安装\n"
        "也可以直接指定路径：python deploy/build_installer.py --iscc <ISCC.exe 的完整路径>"
    )


def _scalar_value(text: str, key: str) -> str:
    match = re.search(r"(?m)^\s*%s\s*:\s*(.*)$" % re.escape(key), text)
    if not match:
        return ""
    return match.group(1).split("#")[0].strip().strip("'\"")


def payload_has_credentials(payload: Path) -> bool:
    """Does the shipped preset carry real database credentials?

    The placeholder template writes ``password: ''`` — a naive "is there
    anything after the colon" test matches those two quote characters and warns
    on every single build, which is how a real warning gets ignored. Strip the
    quotes before deciding.
    """
    preset = payload / "app" / "config" / "local.yaml.preset"
    if not preset.is_file():
        return False
    text = preset.read_text(encoding="utf-8", errors="replace")
    return bool(_scalar_value(text, "password") or _scalar_value(text, "auth_secret"))


# What the installer drops at the install root, beside app/. Step [4] of the
# package build copies these, and step [4] is skipped entirely by --app-only —
# so a payload left over from an app-only build silently ships an old stub.
ROOT_FILES = ("start_superclaw.bat", "README.txt")

# app/launcher.py ships *inside* the app payload (so the updater can fix it).
# It is written by step [2], which --app-only does run, but a payload that
# predates the move still has it at the root instead.
APP_FILES = ("launcher.py",)


def stale_payload_files(payload: Path) -> list:
    stale = []
    for rel in ROOT_FILES:
        source, shipped = DEPLOY / rel, payload / rel
        if source.is_file() and shipped.is_file() and source.read_bytes() != shipped.read_bytes():
            stale.append(rel)
    for rel in APP_FILES:
        source, shipped = DEPLOY / rel, payload / "app" / rel
        if not shipped.is_file():
            stale.append("app/" + rel + "（缺失）")
        elif source.is_file() and source.read_bytes() != shipped.read_bytes():
            stale.append("app/" + rel)
    # Leftover from the pre-1.0.5 layout: a second, frozen copy at the root that
    # the updater can never reach.
    if (payload / "launcher.py").is_file():
        stale.append("launcher.py（旧布局残留，应删除）")
    return stale


def check_ps1_encoding() -> None:
    """Shipped .ps1 files must carry a UTF-8 BOM.

    Windows PowerShell 5.1 (still what `powershell.exe` resolves to on Win10/11)
    decodes a BOM-less script using the ANSI code page. Our Chinese comments then
    turn to mojibake and — worse — a trailing byte can swallow a quote, which
    makes the script fail with bogus "unexpected token" syntax errors before it
    does anything at all.
    """
    broken = []
    for path in sorted(DEPLOY.glob("*.ps1")):
        if not path.read_bytes().startswith(b"\xef\xbb\xbf"):
            broken.append(path.name)
    if broken:
        raise SystemExit(
            "这些 .ps1 缺少 UTF-8 BOM：%s\n"
            "Windows PowerShell 5.1 会把它们按 ANSI 解码，中文注释会乱码甚至报语法错误。\n"
            "修法：以 utf-8-sig 重新保存，例如\n"
            "    python -c \"import pathlib;p=pathlib.Path(r'%s');p.write_bytes(b'\\xef\\xbb\\xbf'+p.read_bytes())\""
            % ("、".join(broken), DEPLOY / broken[0])
        )


def check_bat_encoding() -> None:
    """Shipped .bat files must be pure ASCII, with CRLF line endings.

    cmd.exe parses a .bat using the *console code page*, so a UTF-8 file breaks
    before it does anything: a multi-byte character can end in a lead byte that
    swallows the trailing newline, gluing the next line onto this command, and
    the user double-clicking the shortcut gets

        'xxx' is not recognized as an internal or external command

    This is not theoretical — it took out the whole entry point once. Chinese
    messages belong in app/launcher.py, which writes Unicode safely.
    """
    broken = []
    for path in sorted(DEPLOY.glob("*.bat")):
        raw = path.read_bytes()
        if any(byte > 127 for byte in raw):
            broken.append("%s（含非 ASCII 字节）" % path.name)
        elif b"\r\n" not in raw or raw.replace(b"\r\n", b"").count(b"\n"):
            broken.append("%s（换行不是 CRLF）" % path.name)
    if broken:
        raise SystemExit(
            "这些 .bat 不能直接发给用户：%s\n"
            "cmd.exe 按控制台代码页解析批处理，非 ASCII 字节会吞掉换行、把下一行并进当前命令，\n"
            "表现为双击后报「'xxx' 不是内部或外部命令」而根本没启动。\n"
            "把中文提示挪到 app/launcher.py，.bat 保持纯 ASCII + CRLF。" % "、".join(broken)
        )


def build_package(version: str, embed_config: bool) -> Path:
    cmd = [sys.executable, str(DEPLOY / "build_server_package.py"), "--version", version]
    if embed_config:
        cmd.append("--embed-config")
    # Reuse the already-extracted runtime; rebuilding it byte-for-byte changes
    # nothing and costs a full re-copy of ~44MB of site-packages.
    if (ROOT / "dist" / "server" / "SuperClaw" / "runtime" / "python.exe").is_file():
        cmd.append("--skip-runtime")
    log("→ %s" % " ".join(cmd[1:]))
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        raise SystemExit("打 payload 失败，退出码 %d" % result.returncode)
    return ROOT / "dist" / "server" / "SuperClaw"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile the SuperClaw Windows installer")
    parser.add_argument("--version", help="覆盖版本号（默认读 VERSION）")
    parser.add_argument("--skip-package", action="store_true",
                        help="复用 dist/server/SuperClaw，不重新打 payload")
    parser.add_argument("--embed-config", action="store_true",
                        help="把 config/local.yaml 内嵌为预设（含真实凭据，仅限内部机器安装包）")
    parser.add_argument("--iscc", default="", help="ISCC.exe 路径")
    parser.add_argument("--out", default=str(ROOT / "dist" / "release"), help="安装包输出目录")
    args = parser.parse_args()

    version = normalize_version(args.version or read_version())
    out_dir = Path(args.out)

    log("=== SuperClaw 安装包编译 ===")
    log("版本 %s" % version)
    log("")

    log("[1/3] 准备 payload")
    payload = ROOT / "dist" / "server" / "SuperClaw"
    if args.skip_package:
        if not (payload / "app" / "src" / "api" / "main.py").is_file():
            raise SystemExit("payload 不存在或不完整：%s（去掉 --skip-package 重新生成）" % payload)
        log("  复用 %s" % payload)
        stale = stale_payload_files(payload)
        if stale:
            raise SystemExit(
                "payload 里这几个文件与 deploy/ 下的不一致：%s\n"
                "多半是上次只跑了 --app-only（它不刷新 start_superclaw.bat / README），"
                "照这样打出来的安装包会带着旧启动桩。\n"
                "去掉 --skip-package 重新生成 payload 即可。" % "、".join(stale)
            )
    else:
        payload = build_package(version, args.embed_config)
    log("  payload: %s" % payload)

    if payload_has_credentials(payload):
        log("")
        log("  ⚠ app/config/local.yaml.preset 里带着真实数据库口令 / auth_secret。")
        log("    这个安装包只能给内部可信机器用，不要放到公开仓库或对外分发。")

    log("")
    log("[2/3] 定位 Inno Setup 编译器")
    check_ps1_encoding()
    check_bat_encoding()
    iscc = find_iscc(args.iscc)
    log("  ISCC: %s" % iscc)
    version_out = subprocess.run([str(iscc), "/?"], capture_output=True, text=True)
    banner = (version_out.stdout or "").strip().splitlines()
    if banner:
        log("  %s" % banner[0])

    log("")
    log("[3/3] 编译安装包")
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(iscc),
        "/DMyAppVersion=%s" % version,
        "/DPayloadDir=%s" % payload,
        "/DOutputDir=%s" % out_dir,
        str(ISS),
    ]
    log("→ %s" % " ".join('"%s"' % part if " " in part else part for part in cmd[1:]))
    result = subprocess.run(cmd, cwd=str(DEPLOY))
    if result.returncode != 0:
        raise SystemExit("Inno Setup 编译失败，退出码 %d" % result.returncode)

    setup = out_dir / ("SuperClaw-Setup-%s.exe" % version)
    if not setup.is_file():
        raise SystemExit("编译报成功但找不到产物：%s" % setup)

    digest = sha256_file(setup)
    (setup.with_suffix(setup.suffix + ".sha256")).write_text(
        "%s  %s\n" % (digest, setup.name), encoding="utf-8"
    )

    log("")
    log("完成：%s  %s" % (setup.name, human(setup.stat().st_size)))
    log("      sha256 %s" % digest[:16])
    log("")
    log("这个 .exe 就是给同事的完整安装包：双击 → 下一步 → 开始菜单出现 SuperClaw。")
    log("它同时可以做覆盖升级：再跑一次新版安装包即可，data\\instance.json 会保留。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
