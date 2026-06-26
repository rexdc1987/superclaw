"""SuperClaw 系统健康检查。

检查所有模块可用性、配置合法性、资源状态。

使用方式:
    python -m rpa.healthcheck
    # 或
    from rpa.healthcheck import health_check
    report = await health_check()
"""

import asyncio
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict

# ============================================================
# 检查项
# ============================================================


def _check_python_version() -> Dict[str, Any]:
    """检查 Python 版本"""
    ver = sys.version_info
    ok = ver >= (3, 8)
    return {
        "name": "python_version",
        "status": "ok" if ok else "error",
        "value": f"{ver.major}.{ver.minor}.{ver.micro}",
        "message": "Python >= 3.8" if ok else f"需要 Python >= 3.8，当前 {ver.major}.{ver.minor}",
    }


def _check_modules() -> Dict[str, Any]:
    """检查核心模块是否可导入"""
    modules = [
        "rpa.http.client",
        "rpa.http.retry",
        "rpa.http.middleware",
        "rpa.account.models",
        "rpa.account.account_pool",
        "rpa.account.context_factory",
        "rpa.account.health_scorer",
        "rpa.auth.token_manager",
        "rpa.anti_detect.fingerprint",
        "rpa.anti_detect.stealth",
    ]
    ok_count = 0
    errors = []
    for mod in modules:
        try:
            __import__(mod)
            ok_count += 1
        except Exception as e:
            errors.append(f"{mod}: {e}")

    all_ok = ok_count == len(modules)
    return {
        "name": "modules_import",
        "status": "ok" if all_ok else "warning",
        "value": f"{ok_count}/{len(modules)}",
        "message": "所有模块可导入" if all_ok else f"导入失败: {'; '.join(errors[:3])}",
    }


def _check_dependencies() -> Dict[str, Any]:
    """检查第三方依赖"""
    deps = {
        "httpx": "httpx",
        "playwright": "playwright",
        "pydantic": "pydantic",
    }
    installed = {}
    missing = []
    for name, pkg in deps.items():
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "unknown")
            installed[name] = ver
        except ImportError:
            missing.append(name)

    return {
        "name": "dependencies",
        "status": "ok" if not missing else "warning",
        "value": installed,
        "message": "依赖完整" if not missing else f"缺失: {', '.join(missing)}",
    }


def _check_disk_space(min_gb: float = 1.0) -> Dict[str, Any]:
    """检查磁盘空间"""
    try:
        usage = shutil.disk_usage("/")
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        pct = (usage.free / usage.total) * 100
        ok = free_gb >= min_gb
        return {
            "name": "disk_space",
            "status": "ok" if ok else "warning",
            "value": {"free_gb": round(free_gb, 2), "total_gb": round(total_gb, 2), "free_pct": round(pct, 1)},
            "message": f"可用 {free_gb:.1f}GB ({pct:.1f}%)" if ok else f"磁盘空间不足: {free_gb:.1f}GB < {min_gb}GB",
        }
    except Exception as e:
        return {
            "name": "disk_space",
            "status": "unknown",
            "value": None,
            "message": f"无法检测: {e}",
        }


def _check_platform() -> Dict[str, Any]:
    """检查运行平台"""
    return {
        "name": "platform",
        "status": "ok",
        "value": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "message": f"{platform.system()} {platform.release()}",
    }


async def _check_browser() -> Dict[str, Any]:
    """检查 Playwright 浏览器是否可用"""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            version = await browser.version
            await browser.close()
        return {
            "name": "browser",
            "status": "ok",
            "value": f"Chromium {version}",
            "message": f"Chromium {version} 可用",
        }
    except Exception as e:
        return {
            "name": "browser",
            "status": "warning",
            "value": None,
            "message": f"浏览器不可用: {e}",
        }


def _check_config() -> Dict[str, Any]:
    """检查配置文件"""
    config_paths = [
        "config/defaults.yaml",
        "config/settings.yaml",
        "pyproject.toml",
    ]
    found = []
    for cp in config_paths:
        if os.path.exists(cp):
            found.append(cp)

    return {
        "name": "config",
        "status": "ok" if found else "warning",
        "value": found,
        "message": f"找到配置: {', '.join(found)}" if found else "未找到配置文件",
    }


# ============================================================
# 主入口
# ============================================================

async def health_check() -> Dict[str, Any]:
    """执行完整健康检查

    Returns:
        健康报告字典
    """
    start = time.time()
    checks = []

    # 同步检查
    checks.append(_check_python_version())
    checks.append(_check_platform())
    checks.append(_check_modules())
    checks.append(_check_dependencies())
    checks.append(_check_disk_space())
    checks.append(_check_config())

    # 异步检查
    checks.append(await _check_browser())

    elapsed = time.time() - start

    # 汇总
    statuses = [c["status"] for c in checks]
    if "error" in statuses:
        overall = "error"
    elif "warning" in statuses:
        overall = "warning"
    else:
        overall = "ok"

    report = {
        "overall": overall,
        "timestamp": time.time(),
        "elapsed_ms": round(elapsed * 1000, 1),
        "checks": checks,
        "summary": {
            "total": len(checks),
            "ok": statuses.count("ok"),
            "warning": statuses.count("warning"),
            "error": statuses.count("error"),
        },
    }

    return report


def print_report(report: Dict[str, Any]) -> None:
    """打印健康报告"""
    status_icons = {"ok": "✅", "warning": "⚠️", "error": "❌", "unknown": "❓"}

    print(f"\n{'='*60}")
    print(f"  SuperClaw Health Check — {report['overall'].upper()}")
    print(f"  {report['elapsed_ms']}ms | {report['timestamp']}")
    print(f"{'='*60}")

    for check in report["checks"]:
        icon = status_icons.get(check["status"], "?")
        print(f"  {icon} {check['name']}: {check['message']}")

    s = report["summary"]
    print(f"\n  Summary: {s['ok']} ok, {s['warning']} warning, {s['error']} error")
    print(f"{'='*60}\n")


async def main():
    report = await health_check()
    print_report(report)

    # 输出 JSON 到文件
    output = Path("health_report.json")
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"JSON report saved to {output}")


if __name__ == "__main__":
    asyncio.run(main())
