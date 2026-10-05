# -*- coding: utf-8 -*-
"""「机器归属」页面的接线契约（静态）。

`App.vue::allMenuItems` 是**硬编码数组**，加上 `router/index.js` 和 API 封装，
新增页面一共要动四处；少任何一处页面就不通（菜单有、路由没有 → 点了白屏；
路由有、菜单没有 → 只能手敲地址）。这类"漏一处"的错编译期查不出来，
所以用一组静态断言钉住。

背景：`src/api/attribution/` 的 4 个 admin 端点 2026-09-16 就绪，但一直没有页面；
2026-09-17 补齐，同时把接线固定下来。
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"
VIEW = FRONTEND / "views" / "MachineAttribution.vue"
ROUTER = FRONTEND / "router" / "index.js"
APP = FRONTEND / "App.vue"
API_MODULE = FRONTEND / "api" / "attribution.js"
BACKEND_ROUTER = ROOT / "src" / "api" / "attribution" / "router.py"
BACKEND_MAIN = ROOT / "src" / "api" / "main.py"


def read(path: Path) -> str:
    assert path.exists(), "找不到 {0}".format(path)
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def view() -> str:
    return read(VIEW)


@pytest.fixture(scope="module")
def view_script(view: str) -> str:
    match = re.search(r"<script setup>(.*?)</script>", view, re.S)
    assert match, "MachineAttribution.vue 里找不到 <script setup> 段"
    return match.group(1)


def test_the_page_exists_and_calls_every_attribution_endpoint(view_script: str):
    assert "@/api/attribution" in view_script
    for fn in ("getAttributionMachines", "getAttributionGaps",
               "getAttributionInference", "bindMachine"):
        assert fn in view_script, "页面没有调用 {0}".format(fn)


def test_the_page_renders_the_three_sections(view: str):
    for label in ("机器档案与产出", "归属建议", "归属缺口"):
        assert label in view, "页面缺少「{0}」区块".format(label)


def test_router_registers_the_page_as_admin_only():
    source = read(ROUTER)
    at = source.find("'/machines'")
    assert at != -1, "router/index.js 里没有 /machines 路由"
    block = source[at: at + 260]
    assert "MachineAttribution.vue" in block, "路由没指向 MachineAttribution.vue"
    assert "requiresAdmin: true" in block, "机器归属跨租户，必须是 requiresAdmin"


def test_sidebar_menu_lists_the_page_as_admin_only():
    source = read(APP)
    at = source.find("allMenuItems")
    assert at != -1, "App.vue 里找不到 allMenuItems"
    menu = source[at:]
    menu = menu[: menu.index("]")] if "]" in menu else menu
    line = [l for l in menu.splitlines() if "'/machines'" in l]
    assert line, "侧边菜单没有 机器归属（菜单是硬编码数组，漏了就点不到）"
    assert "adminOnly: true" in line[0], "菜单项必须是 adminOnly"


def test_api_module_points_at_the_attribution_prefix_and_covers_bind():
    source = read(API_MODULE)
    assert "baseURL: '/api/v1/attribution'" in source
    for path in ("'/machines'", "'/gaps'", "'/inference'"):
        assert "api.get(" + path + ")" in source, "缺少只读端点 {0}".format(path)
    # 绑定是写操作：路径、force，以及 backfill 查询参数都要在
    assert "/bind" in source
    assert "backfill" in source


def test_backend_router_is_mounted_and_every_route_requires_admin():
    main = read(BACKEND_MAIN)
    assert "attribution_router" in main, "main.py 没有挂载 attribution 路由"

    router = read(BACKEND_ROUTER)
    assert "require_admin" in router
    # 3 个只读 + 1 个绑定：一个都不能漏，跨租户数据只给管理员
    assert router.count("dependencies=_ADMIN") == 4, (
        "归属接口共有 4 个，每个都必须挂 admin 依赖，实际 %d 个"
        % router.count("dependencies=_ADMIN")
    )
    assert "_ADMIN = [Depends(require_admin)]" in router
