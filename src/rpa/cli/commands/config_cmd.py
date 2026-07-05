"""
superclaw config — 配置管理

用法：
    superclaw config show
    superclaw config show --format json
    superclaw config get app.debug
    superclaw config set app.debug true
"""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="配置管理")
console = Console()


def _get_settings():
    from rpa.config.settings import get_settings
    return get_settings()


@app.command("show")
def show_config(
    format: str = typer.Option("table", "--format", "-f", help="输出格式: table/json/yaml"),
    section: Optional[str] = typer.Option(None, "--section", "-s", help="只显示指定配置段"),
):
    """显示当前配置"""
    settings = _get_settings()
    
    if section:
        data = settings.get(section)
        if data is None:
            console.print(f"[red]配置段不存在: {section}[/red]")
            raise typer.Exit(code=1)
        if isinstance(data, dict):
            data = {f"{section}.{k}": v for k, v in data.items()}
        else:
            data = {section: data}
    else:
        data = settings.to_dict()
    
    if format == "json":
        import json
        console.print_json(json.dumps(data, ensure_ascii=False, indent=2))
    elif format == "yaml":
        import yaml
        console.print(yaml.dump(data, allow_unicode=True, default_flow_style=False))
    else:
        # 表格格式
        table = Table(title="SuperClaw 配置", show_header=True, header_style="bold cyan")
        table.add_column("配置项", style="bold")
        table.add_column("值")
        table.add_column("类型", style="dim")
        
        _add_dict_rows(table, data)
        console.print(table)


def _add_dict_rows(table: Table, data: dict, prefix: str = ""):
    """递归添加字典行到表格"""
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            _add_dict_rows(table, value, full_key)
        else:
            table.add_row(full_key, str(value), type(value).__name__)


@app.command("get")
def get_config(
    key: str = typer.Argument(..., help="配置项路径，如 app.debug"),
):
    """获取指定配置值"""
    settings = _get_settings()
    value = settings.get(key)
    
    if value is None:
        console.print(f"[red]配置项不存在: {key}[/red]")
        raise typer.Exit(code=1)
    
    console.print(f"[bold]{key}[/bold] = {value}")


@app.command("set")
def set_config(
    key: str = typer.Argument(..., help="配置项路径，如 app.debug"),
    value: str = typer.Argument(..., help="新值"),
):
    """修改配置项（仅运行时生效）"""
    settings = _get_settings()
    
    # 类型转换
    if value.lower() in ("true", "yes"):
        parsed = True
    elif value.lower() in ("false", "no"):
        parsed = False
    else:
        try:
            parsed = int(value)
        except ValueError:
            try:
                parsed = float(value)
            except ValueError:
                parsed = value
    
    try:
        settings.override(key, parsed)
        console.print(f"[green]✓ 已设置 {key} = {parsed}[/green]")
    except Exception as e:
        console.print(f"[red]错误：{e}[/red]")
        raise typer.Exit(code=1)


@app.command("reload")
def reload_config():
    """重新加载配置文件"""
    settings = _get_settings()
    try:
        settings.reload()
        console.print("[green]✓ 配置已重载[/green]")
    except Exception as e:
        console.print(f"[red]错误：{e}[/red]")
        raise typer.Exit(code=1)
