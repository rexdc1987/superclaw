"""
superclaw health — 系统健康检查

用法：
    superclaw health
    superclaw health --quick
"""

import os
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="系统健康检查")
console = Console()


@app.command()
def health(
    quick: bool = typer.Option(False, "--quick", "-q", help="仅检查关键项"),
):
    """系统健康检查"""
    console.print("[bold]SuperClaw 系统健康检查[/bold]\n")
    
    checks = []
    
    # 1. Python 环境
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("Python 版本", py_version, sys.version_info >= (3, 10)))
    
    # 2. 关键依赖检查
    deps = {
        "typer": "typer",
        "rich": "rich",
        "pydantic": "pydantic",
        "yaml": "PyYAML",
        "apscheduler": "APScheduler",
        "networkx": "networkx",
    }
    
    for module_name, package_name in deps.items():
        try:
            mod = __import__(module_name)
            version = getattr(mod, '__version__', 'installed')
            checks.append((f"依赖 {package_name}", version, True))
        except ImportError:
            checks.append((f"依赖 {package_name}", "未安装", False))
    
    # 3. 配置文件检查
    config_paths = [
        ("默认配置", Path(__file__).parent.parent.parent / "config" / "defaults.yaml"),
        ("数据目录", Path("data")),
    ]
    
    for name, path in config_paths:
        exists = path.exists()
        checks.append((name, "存在" if exists else "不存在", exists))
    
    if not quick:
        # 4. 磁盘空间
        try:
            stat = os.statvfs(".")
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
            checks.append(("磁盘空间", f"{free_gb:.1f} GB", free_gb > 1.0))
        except (OSError, AttributeError):
            checks.append(("磁盘空间", "无法检测", False))
        
        # 5. 调度器状态
        try:
            from rpa.scheduler import SuperClawScheduler
            checks.append(("调度器模块", "可用", True))
        except ImportError:
            checks.append(("调度器模块", "不可用", False))
        
        # 6. 配置系统
        try:
            from rpa.config.settings import get_settings
            settings = get_settings()
            checks.append(("配置系统", f"env={settings.config.app.env}", True))
        except Exception as e:
            checks.append(("配置系统", str(e), False))
    
    # 输出结果
    table = Table(title="健康检查结果", show_header=True, header_style="bold")
    table.add_column("检查项", style="bold")
    table.add_column("状态")
    table.add_column("结果")
    
    all_ok = True
    for name, result, ok in checks:
        status = "[green]✓[/green]" if ok else "[red]✗[/red]"
        if not ok:
            all_ok = False
        table.add_row(name, status, result)
    
    console.print(table)
    
    if all_ok:
        console.print("\n[bold green]✓ 所有检查通过[/bold green]")
    else:
        console.print("\n[bold red]✗ 部分检查未通过[/bold red]")
        raise typer.Exit(code=1)
