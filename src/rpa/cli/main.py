"""
SuperClaw CLI 入口

用法：
    superclaw run task.yaml           # 运行任务
    superclaw config show             # 查看配置
    superclaw config set app.debug true
    superclaw account list            # 列出账号
    superclaw health                  # 健康检查
    superclaw --version               # 版本号
    superclaw --help                  # 帮助信息
"""

import typer

from rpa.cli.commands.run import run as run_cmd
from rpa.cli.commands.config_cmd import app as config_app
from rpa.cli.commands.account import app as account_app
from rpa.cli.commands.health import health as health_cmd

app = typer.Typer(
    name="superclaw",
    help="SuperClaw RPA 平台命令行工具",
    no_args_is_help=True,
    add_completion=False,
)

# 注册子命令
app.add_typer(config_app, name="config", help="配置管理")
app.add_typer(account_app, name="account", help="账号管理")

# 直接命令（非子命令组）
app.command()(run_cmd)
app.command()(health_cmd)


@app.command()
def version():
    """显示版本信息"""
    typer.echo("SuperClaw v0.1.0")


if __name__ == "__main__":
    app()
