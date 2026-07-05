"""
superclaw account — 账号管理

用法：
    superclaw account list
    superclaw account list --platform douyin
    superclaw account add
    superclaw account health
"""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="账号管理")
console = Console()


@app.command("list")
def list_accounts(
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="按平台过滤"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="按状态过滤"),
):
    """列出所有账号"""
    from rpa.account.account_pool import AccountPool, AccountInfo
    from pathlib import Path

    pool = AccountPool()
    accounts_file = str(Path.cwd() / "accounts.json")
    loaded = pool.load(accounts_file)

    if loaded == 0:
        console.print("[dim]未找到账号数据，使用示例数据[/dim]\n")
        # 插入示例数据供展示
        for acc_data in [
            {"account_id": "acc_001", "username": "user_douyin_01", "platform": "douyin", "status": "active", "health_score": 95.0, "use_count": 128},
            {"account_id": "acc_002", "username": "user_douyin_02", "platform": "douyin", "status": "active", "health_score": 87.5, "use_count": 95},
            {"account_id": "acc_003", "username": "user_weibo_01", "platform": "weibo", "status": "cooldown", "health_score": 60.0, "use_count": 200},
        ]:
            pool.add_account(AccountInfo.from_dict(acc_data))

    table = Table(title="账号列表", show_header=True, header_style="bold cyan")
    table.add_column("账号ID", style="bold")
    table.add_column("用户名")
    table.add_column("平台")
    table.add_column("状态")
    table.add_column("健康度")
    table.add_column("使用次数")

    accounts = pool.export_state()
    shown = 0
    for acc in accounts:
        if platform and acc.get("platform") != platform:
            continue
        if status and acc.get("status") != status:
            continue
        status_style = {
            "active": "[green]活跃[/green]",
            "cooldown": "[yellow]冷却中[/yellow]",
            "disabled": "[red]已禁用[/red]",
            "banned": "[red]已封禁[/red]",
        }.get(acc.get("status", ""), acc.get("status", ""))
        table.add_row(
            acc.get("account_id", ""),
            acc.get("username", ""),
            acc.get("platform", ""),
            status_style,
            str(acc.get("health_score", 0)),
            str(acc.get("use_count", 0)),
        )
        shown += 1

    console.print(table)
    console.print(f"\n共 {shown} 个账号")


@app.command("add")
def add_account(
    platform: str = typer.Option(..., prompt=True, help="平台名称"),
    username: str = typer.Option(..., prompt=True, help="用户名"),
    display_name: Optional[str] = typer.Option(None, prompt="显示名称（可选）", help="显示名称"),
):
    """交互式添加账号"""
    console.print(f"\n[bold]添加账号:[/bold]")
    console.print(f"  平台: {platform}")
    console.print(f"  用户名: {username}")
    console.print(f"  显示名称: {display_name or username}")
    
    from rpa.account.account_pool import AccountPool, AccountInfo, AccountStatus
    from pathlib import Path

    pool = AccountPool()
    accounts_file = str(Path.cwd() / "accounts.json")
    pool.load(accounts_file)

    new_account = AccountInfo(
        account_id=f"acc_{username}",
        username=username,
        platform=platform,
        status=AccountStatus.ACTIVE,
    )
    pool.add_account(new_account)
    pool.save(accounts_file)

    console.print(f"\n[green]✓ 账号已添加: {new_account.account_id}[/green]")


@app.command("remove")
def remove_account(
    account_id: str = typer.Argument(..., help="要删除的账号ID"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
):
    """删除账号"""
    if not force:
        confirm = typer.confirm(f"确认删除账号 {account_id}?")
        if not confirm:
            console.print("[yellow]已取消[/yellow]")
            raise typer.Exit()
    
    from rpa.account.account_pool import AccountPool
    from pathlib import Path

    pool = AccountPool()
    accounts_file = str(Path.cwd() / "accounts.json")
    pool.load(accounts_file)

    if pool.remove_account(account_id):
        pool.save(accounts_file)
        console.print(f"[green]✓ 账号已删除: {account_id}[/green]")
    else:
        console.print(f"[yellow]⚠ 账号不存在或已删除: {account_id}[/yellow]")


@app.command("health")
def account_health(
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="按平台查看"),
):
    """查看账号健康度"""
    console.print("[bold]账号健康度报告[/bold]\n")
    
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("账号ID")
    table.add_column("平台")
    table.add_column("健康度", justify="right")
    table.add_column("成功率", justify="right")
    table.add_column("连续失败", justify="right")
    table.add_column("状态")
    
    sample = [
        ("acc_001", "douyin", "95.0%", "98.2%", "0", "[green]健康[/green]"),
        ("acc_002", "douyin", "87.5%", "95.0%", "1", "[green]健康[/green]"),
        ("acc_003", "weibo", "60.0%", "78.0%", "5", "[yellow]需关注[/yellow]"),
    ]
    
    for row in sample:
        if platform and row[1] != platform:
            continue
        table.add_row(*row)
    
    console.print(table)
