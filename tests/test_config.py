"""
配置系统单元测试

测试 YAML 加载、环境变量覆盖、配置校验、运行时 override。
"""

import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from rpa.config.settings import SettingsManager, get_settings, reset_settings, _deep_merge, _apply_env_overrides
from rpa.config.models import SuperClawConfig, AppConfig, RetryConfig


class TestDeepMerge:
    """深度合并测试"""
    
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}
    
    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 1}
        override = {"a": {"y": 3, "z": 4}}
        result = _deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 3, "z": 4}, "b": 1}
    
    def test_deep_nested_merge(self):
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"d": 3, "e": 4}}}
        result = _deep_merge(base, override)
        assert result == {"a": {"b": {"c": 1, "d": 3, "e": 4}}}
    
    def test_override_replaces_non_dict(self):
        base = {"a": [1, 2]}
        override = {"a": [3, 4]}
        result = _deep_merge(base, override)
        assert result == {"a": [3, 4]}


class TestEnvOverrides:
    """环境变量覆盖测试"""
    
    def test_boolean_override(self):
        data = {"app": {"debug": False}}
        with patch.dict(os.environ, {"SUPERCLAW_APP__DEBUG": "true"}):
            result = _apply_env_overrides(data)
            assert result["app"]["debug"] is True
    
    def test_int_override(self):
        data = {"queue": {"max_workers": 5}}
        with patch.dict(os.environ, {"SUPERCLAW_QUEUE__MAX_WORKERS": "10"}):
            result = _apply_env_overrides(data)
            assert result["queue"]["max_workers"] == 10
    
    def test_float_override(self):
        data = {"retry": {"base_delay": 5.0}}
        with patch.dict(os.environ, {"SUPERCLAW_RETRY__BASE_DELAY": "10.5"}):
            result = _apply_env_overrides(data)
            assert result["retry"]["base_delay"] == 10.5
    
    def test_string_override(self):
        data = {"app": {"env": "production"}}
        with patch.dict(os.environ, {"SUPERCLAW_APP__ENV": "development"}):
            result = _apply_env_overrides(data)
            assert result["app"]["env"] == "development"
    
    def test_non_superclaw_env_ignored(self):
        data = {"app": {"debug": False}}
        with patch.dict(os.environ, {"OTHER_VAR": "true"}):
            result = _apply_env_overrides(data)
            assert result["app"]["debug"] is False
    
    def test_new_key_created(self):
        data = {}
        with patch.dict(os.environ, {"SUPERCLAW_NEWSECTION__KEY": "value"}):
            result = _apply_env_overrides(data)
            assert result["newsection"]["key"] == "value"


class TestSettingsManager:
    """配置管理器测试"""
    
    def setup_method(self):
        reset_settings()
    
    def test_load_defaults(self):
        settings = SettingsManager()
        assert settings.config.app.name == "SuperClaw"
        assert settings.config.app.version == "0.1.0"
        assert settings.config.scheduler.max_instances == 1
    
    def test_get_dotpath(self):
        settings = SettingsManager()
        assert settings.get("app.name") == "SuperClaw"
        assert settings.get("app.debug") is False
        assert settings.get("nonexistent", "default") == "default"
    
    def test_override(self):
        settings = SettingsManager()
        settings.override("app.debug", True)
        assert settings.config.app.debug is True
        assert settings.get("app.debug") is True
    
    def test_override_nested(self):
        settings = SettingsManager()
        settings.override("retry.max_retries", 5)
        assert settings.config.retry.max_retries == 5
    
    def test_override_invalid_value_rejects(self):
        settings = SettingsManager()
        with pytest.raises(Exception):
            settings.override("scheduler.max_instances", -1)  # ge=1
    
    def test_to_dict(self):
        settings = SettingsManager()
        d = settings.to_dict()
        assert isinstance(d, dict)
        assert "app" in d
        assert "scheduler" in d
    
    def test_to_yaml(self):
        settings = SettingsManager()
        yaml_str = settings.to_yaml()
        assert "SuperClaw" in yaml_str
        assert "app:" in yaml_str
    
    def test_reload(self):
        settings = SettingsManager()
        settings.override("app.debug", True)
        settings.reload()
        # 重载后应恢复默认值
        assert settings.config.app.debug is False


class TestConfigModels:
    """配置模型校验测试"""
    
    def test_app_config_valid(self):
        config = AppConfig(name="Test", env="development", debug=True)
        assert config.name == "Test"
        assert config.env == "development"
    
    def test_app_config_invalid_env(self):
        with pytest.raises(Exception):
            AppConfig(env="invalid_env")
    
    def test_retry_config(self):
        config = RetryConfig(max_retries=5, base_delay=10.0, max_delay=600.0)
        assert config.max_retries == 5
    
    def test_retry_config_zero_retries(self):
        config = RetryConfig(max_retries=0)
        assert config.max_retries == 0
    
    def test_full_config_loads(self):
        """验证完整配置可以从 defaults.yaml 加载"""
        settings = SettingsManager()
        config = settings.config
        assert config.app.name == "SuperClaw"
        assert config.scheduler.max_instances >= 1
        assert config.queue.max_workers >= 1
        assert config.retry.max_retries >= 0


class TestConfigWithCustomFile:
    """自定义配置文件测试"""
    
    def test_custom_yaml_override(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write("app:\n  debug: true\n  version: '9.9.9'\n")
            tmp_path = f.name
        
        try:
            settings = SettingsManager(config_path=tmp_path)
            assert settings.config.app.debug is True
            assert settings.config.app.version == "9.9.9"
            # 默认值应保留
            assert settings.config.app.name == "SuperClaw"
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    
    def test_missing_config_file_ignored(self):
        settings = SettingsManager(config_path="/nonexistent/path.yaml")
        assert settings.config.app.name == "SuperClaw"
