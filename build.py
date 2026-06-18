"""SuperClaw PyInstaller build script"""
import os
import sys
import subprocess


def build():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(base_dir, "src")
    config_dir = os.path.join(base_dir, "config")
    assets_dir = os.path.join(base_dir, "assets")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "SuperClaw_v5",
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--add-data", config_dir + ";config",
        "--paths", src_dir,
    ]

    if os.path.isdir(assets_dir):
        cmd.extend(["--add-data", assets_dir + ";assets"])

    modules = [
        "models", "models.account", "models.task", "models.comment",
        "models.lead", "models.action", "models.risk", "models.audit",
        "models.keyword", "models.template", "models.database", "models.user",
        "services", "services.account_service", "services.task_service",
        "services.collector_service", "services.lead_service",
        "services.action_service", "services.risk_service",
        "services.export_service", "services.keyword_service",
        "services.review_service", "services.scheduler",
        "services.user_service", "services.task_executor",
        "gui", "gui.app", "gui.main_window", "gui.dashboard",
        "gui.account_view", "gui.task_view", "gui.lead_view",
        "gui.template_view", "gui.log_view", "gui.review_view",
        "gui.risk_view", "gui.login_dialog", "gui.user_view",
        "core", "core.config", "core.constants", "core.exceptions",
        "utils", "utils.logger", "utils.validators", "utils.helpers",
        "automation", "automation.browser", "automation.platform_base",
        "automation.douyin_adapter",
        "sqlalchemy.dialects.sqlite",
        "PySide6.QtCore", "PySide6.QtWidgets",
    ]
    for m in modules:
        cmd.extend(["--hidden-import", m])

    cmd.extend(["--exclude-module", "playwright"])
    cmd.append(os.path.join(src_dir, "main.py"))

    print("Building SuperClaw...")
    result = subprocess.run(cmd, cwd=base_dir)

    if result.returncode == 0:
        dist_dir = os.path.join(base_dir, "dist", "SuperClaw_v5")
        print("\nBuild successful!")
        print("Output: " + dist_dir)
    else:
        print("\nBuild failed!")
        sys.exit(1)


if __name__ == "__main__":
    build()
