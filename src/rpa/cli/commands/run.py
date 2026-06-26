"""
superclaw run — 运行指定工作流

用法：
    superclaw run workflow.yaml
    superclaw run workflow.yaml --dry-run
    superclaw run workflow.yaml --account default
    superclaw run workflow.yaml --var keyword=AI --var count=10
"""



from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

app = typer.Typer(help="运行指定工作流")
console = Console()


def _parse_variables(var_list: Optional[List[str]]) -> Dict[str, Any]:
    """解析 --var key=value 参数"""
    variables = {}
    if not var_list:
        return variables
    for item in var_list:
        if "=" in item:
            key, value = item.split("=", 1)
            # 尝试解析为数字/布尔/JSON
            try:
                import json
                value = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass
            variables[key.strip()] = value
    return variables


@app.command()
def run(
    workflow_file: Path = typer.Argument(..., help="工作流 YAML 文件路径"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="仅验证配置，不实际执行"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="使用的账号名称"),
    var: Optional[List[str]] = typer.Option(None, "--var", "-V", help="运行时变量 key=value"),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t", help="超时秒数"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示详细输出"),
):
    """运行指定的 RPA 工作流"""
    # 校验文件
    if not workflow_file.exists():
        console.print(f"[red]错误：文件不存在: {workflow_file}[/red]")
        raise typer.Exit(code=1)

    if workflow_file.suffix not in ('.yaml', '.yml'):
        console.print(f"[yellow]警告：文件扩展名不是 .yaml/.yml: {workflow_file}[/yellow]")

    # 解析变量
    variables = _parse_variables(var)
    if account:
        variables["account"] = account

    # 先做 dry-run 验证
    console.print(f"\n[bold blue]工作流:[/bold blue] {workflow_file.name}")
    if variables:
        console.print(f"[bold blue]变量:[/bold blue] {variables}")

    if dry_run:
        console.print("\n[yellow]DRY RUN 模式 — 仅验证，不执行[/yellow]")

    # 执行
    import asyncio
    from rich.table import Table

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("解析工作流...", total=None)

        try:
            from rpa.workflow.runner import WorkflowRunner

            runner = WorkflowRunner()

            def on_step_done(step_id, record):
                icon = "✓" if record.status.value == "success" else "✗"
                progress.update(task, description=f"{icon} {step_id}")

            runner._on_step_complete = on_step_done

            progress.update(task, description="执行中...")

            result = asyncio.run(
                runner.run(
                    str(workflow_file),
                    variables=variables,
                    dry_run=dry_run,
                    timeout_seconds=timeout,
                )
            )

            progress.update(task, description="完成")

        except ImportError as e:
            progress.update(task, description="失败")
            console.print(f"[red]缺少依赖: {e}[/red]")
            console.print("[yellow]请安装: pip install pyyaml[/yellow]")
            raise typer.Exit(code=1)
        except Exception as e:
            progress.update(task, description="失败")
            console.print(f"[red]错误：{e}[/red]")
            raise typer.Exit(code=1)

    # 输出结果表格
    summary = result.summary()
    table = Table(title="执行结果")
    table.add_column("指标", style="cyan")
    table.add_column("值", style="green")
    table.add_row("工作流", summary["workflow"])
    table.add_row("状态", summary["status"])
    table.add_row("总步骤", str(summary["total_steps"]))
    table.add_row("成功", str(summary["successful"]))
    table.add_row("失败", str(summary["failed"]))
    table.add_row("耗时", f"{summary['duration_ms']:.0f}ms")
    table.add_row("Dry Run", "是" if summary["dry_run"] else "否")
    console.print(table)

    if summary["failed"] > 0:
        console.print("\n[red]✗ 部分步骤失败[/red]")
        raise typer.Exit(code=1)
    elif dry_run:
        console.print("\n[green]✓ 验证通过[/green]")
    else:
        console.print("\n[bold green]✓ 工作流执行成功[/bold green]")
