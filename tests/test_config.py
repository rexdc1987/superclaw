"""config 单元测试"""
import sys, os, tempfile, yaml
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from core.config import Config, DEFAULT_CONFIG


class TestConfig:
    def test_default_values(self):
        cfg = Config()
        assert cfg.get("database.path") == "data/superclaw.db"
        assert cfg.get("risk.daily_comment_limit") == 50
        assert cfg.get("browser.headless") is False

    def test_missing_key(self):
        cfg = Config()
        assert cfg.get("nonexistent.key") is None
        assert cfg.get("nonexistent.key", "fallback") == "fallback"

    def test_load_yaml(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            yaml.dump({"risk": {"daily_comment_limit": 99}}, f)
            path = f.name
        try:
            cfg = Config(path)
            assert cfg.get("risk.daily_comment_limit") == 99
            assert cfg.get("risk.daily_dm_limit") == 20  # default preserved
        finally:
            os.unlink(path)

    def test_dot_notation(self):
        cfg = Config()
        assert cfg.get("logging.level") == "INFO"
