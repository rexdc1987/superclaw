"""
CLI 命令单元测试

使用 pytest + typer.testing.CliRunner 测试所有 CLI 命令。
"""

import pytest
from typer.testing import CliRunner
from rpa.cli.main import app

runner = CliRunner()


class TestVersionCommand:
    """版本命令测试"""
    
    def test_version_output(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "SuperClaw" in result.output
        assert "0.1.0" in result.output


class TestHealthCommand:
    """健康检查命令测试"""
    
    def test_health_quick(self):
        result = runner.invoke(app, ["health", "--quick"])
        # 快速模式应通过（至少 Python 和基础依赖存在）
        assert "健康检查" in result.output or "health" in result.output.lower()
    
    def test_health_full(self):
        result = runner.invoke(app, ["health"])
        assert "检查项" in result.output or "检查" in result.output


class TestConfigCommand:
    """配置命令测试"""
    
    def test_config_show_table(self):
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "配置" in result.output
    
    def test_config_show_json(self):
        result = runner.invoke(app, ["config", "show", "--format", "json"])
        assert result.exit_code == 0
        assert "app" in result.output
    
    def test_config_show_yaml(self):
        result = runner.invoke(app, ["config", "show", "--format", "yaml"])
        assert result.exit_code == 0
    
    def test_config_get(self):
        result = runner.invoke(app, ["config", "get", "app.name"])
        assert result.exit_code == 0
        assert "SuperClaw" in result.output
    
    def test_config_get_nonexistent(self):
        result = runner.invoke(app, ["config", "get", "nonexistent.key"])
        assert result.exit_code == 1
    
    def test_config_set(self):
        result = runner.invoke(app, ["config", "set", "app.debug", "true"])
        assert result.exit_code == 0
        assert "已设置" in result.output
    
    def test_config_reload(self):
        result = runner.invoke(app, ["config", "reload"])
        assert result.exit_code == 0
        assert "重载" in result.output


class TestAccountCommand:
    """账号命令测试"""
    
    def test_account_list(self):
        result = runner.invoke(app, ["account", "list"])
        assert result.exit_code == 0
        assert "账号" in result.output
    
    def test_account_list_filter_platform(self):
        result = runner.invoke(app, ["account", "list", "--platform", "douyin"])
        assert result.exit_code == 0
    
    def test_account_health(self):
        result = runner.invoke(app, ["account", "health"])
        assert result.exit_code == 0
        assert "健康度" in result.output
    
    def test_account_remove_with_force(self):
        result = runner.invoke(app, ["account", "remove", "acc_001", "--force"])
        assert result.exit_code == 0


class TestRunCommand:
    """运行命令测试"""
    
    def test_run_missing_file(self):
        result = runner.invoke(app, ["run", "nonexistent.yaml"])
        assert result.exit_code == 1
        assert "不存在" in result.output
    
    def test_run_invalid_extension(self):
        # 创建临时文件
        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w') as f:
            f.write("test")
            tmp_path = f.name
        
        try:
            result = runner.invoke(app, ["run", tmp_path])
            # 应有警告但不一定是错误
            assert "警告" in result.output or result.exit_code == 0
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    
    def test_run_dry_run(self):
        import tempfile
        import yaml
        from pathlib import Path
        
        task_config = {
            'workflow': {'id': 'test', 'name': '测试任务'},
            'nodes': [{'id': 'n1', 'type': 'action', 'name': '测试节点'}],
            'edges': [],
        }
        
        with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False, mode='w', encoding='utf-8') as f:
            yaml.dump(task_config, f, allow_unicode=True)
            tmp_path = f.name
        
        try:
            result = runner.invoke(app, ["run", tmp_path, "--dry-run"])
            assert result.exit_code == 0
            assert "DRY RUN" in result.output or "校验通过" in result.output
        finally:
            Path(tmp_path).unlink(missing_ok=True)
