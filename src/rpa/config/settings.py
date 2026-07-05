"""
SuperClaw 配置管理器

支持 YAML 分层加载、环境变量覆盖、配置校验、热重载。

优先级：defaults.yaml < 环境配置 < 环境变量(SUPERCLAW_*) < 运行时覆盖

用法：
    from rpa.config.settings import get_settings
    
    settings = get_settings()
    print(settings.app.name)        # "SuperClaw"
    print(settings.app.debug)       # False
    
    # 运行时覆盖
    settings.override("app.debug", True)
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Any, Optional


from rpa.config.models import SuperClawConfig

logger = logging.getLogger(__name__)

# 项目根目录（src/rpa/config/ 的上三级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_CONFIG_PATH = Path(__file__).parent / "defaults.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典，override 覆盖 base"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_env_overrides(data: dict, prefix: str = "SUPERCLAW_") -> dict:
    """
    从环境变量覆盖配置。
    
    规则：
    - 双下划线 __ 表示嵌套层级分隔
    - SUPERCLAW_APP__DEBUG=true → data['app']['debug'] = True
    - SUPERCLAW_QUEUE__MAX_WORKERS=10 → data['queue']['max_workers'] = 10
    - 值会自动转换类型（int/float/bool/str）
    """
    import copy
    result = copy.deepcopy(data)
    
    for env_key, env_value in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        
        # 去掉前缀，用双下划线分割层级
        config_path = env_key[len(prefix):]
        keys = config_path.split("__")
        
        # 转为小写（仅 key 部分，值保持原样）
        keys = [k.lower() for k in keys]
        
        # 导航到嵌套位置
        current = result
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        
        # 类型转换
        final_key = keys[-1]
        if env_value.lower() in ("true", "yes", "1"):
            current[final_key] = True
        elif env_value.lower() in ("false", "no", "0"):
            current[final_key] = False
        else:
            try:
                current[final_key] = int(env_value)
            except ValueError:
                try:
                    current[final_key] = float(env_value)
                except ValueError:
                    current[final_key] = env_value
        
        logger.debug(f"环境变量覆盖: {env_key} → {'.'.join(keys)}")
    
    return result


class SettingsManager:
    """
    配置管理器
    
    支持：
    - YAML 分层加载
    - 环境变量覆盖（SUPERCLAW_ 前缀）
    - Pydantic 校验
    - 运行时 override
    - 配置热重载（watchdog）
    """
    
    def __init__(self, config_path: Optional[str] = None, env: Optional[str] = None):
        """
        Args:
            config_path: 自定义配置文件路径（可选）
            env: 环境名，如 development/staging/production（可选，默认从环境变量读取）
        """
        self._config_path = config_path
        self._env = env or os.environ.get("SUPERCLAW_ENV", "production")
        self._config: Optional[SuperClawConfig] = None
        self._raw_data: dict = {}
        self._watchers: list = []
        
        self._load()
    
    def _load(self):
        """加载配置"""
        # 1. 加载默认配置
        base_data = self._load_yaml(_DEFAULT_CONFIG_PATH)
        
        # 2. 加载环境配置（如果存在）
        env_config_path = self._get_env_config_path()
        if env_config_path and env_config_path.exists():
            env_data = self._load_yaml(env_config_path)
            base_data = _deep_merge(base_data, env_data)
            logger.info(f"加载环境配置: {env_config_path}")
        
        # 3. 加载用户自定义配置（如果指定）
        if self._config_path:
            custom_path = Path(self._config_path)
            if custom_path.exists():
                custom_data = self._load_yaml(custom_path)
                base_data = _deep_merge(base_data, custom_data)
                logger.info(f"加载自定义配置: {custom_path}")
        
        # 4. 环境变量覆盖
        base_data = _apply_env_overrides(base_data)
        
        self._raw_data = base_data
        
        # 5. Pydantic 校验
        try:
            self._config = SuperClawConfig(**base_data)
            logger.info(f"配置加载完成 (env={self._env})")
        except Exception as e:
            logger.error(f"配置校验失败: {e}")
            raise
    
    def _load_yaml(self, path: Path) -> dict:
        """加载 YAML 文件"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning(f"配置文件不存在: {path}")
            return {}
        except yaml.YAMLError as e:
            logger.error(f"YAML 解析失败: {path} - {e}")
            return {}
    
    def _get_env_config_path(self) -> Optional[Path]:
        """获取环境配置文件路径"""
        # 优先检查项目根目录
        env_path = _PROJECT_ROOT / "config" / f"{self._env}.yaml"
        if env_path.exists():
            return env_path
        
        # 检查 src/rpa/config/ 目录
        env_path = _DEFAULT_CONFIG_PATH.parent / f"{self._env}.yaml"
        if env_path.exists():
            return env_path
        
        return None
    
    @property
    def config(self) -> SuperClawConfig:
        """获取校验后的配置对象"""
        if self._config is None:
            raise RuntimeError("配置未加载")
        return self._config
    
    @property
    def raw(self) -> dict:
        """获取原始配置字典"""
        return self._raw_data
    
    def get(self, dotpath: str, default: Any = None) -> Any:
        """
        用点号路径获取配置值
        
        示例：settings.get("app.debug") → False
        """
        keys = dotpath.split(".")
        value = self._raw_data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value
    
    def override(self, dotpath: str, value: Any) -> None:
        """
        运行时覆盖配置（仅影响内存，不写入文件）
        
        示例：settings.override("app.debug", True)
        """
        keys = dotpath.split(".")
        data = self._raw_data
        for key in keys[:-1]:
            if key not in data:
                data[key] = {}
            data = data[key]
        data[keys[-1]] = value
        
        # 重新校验
        try:
            self._config = SuperClawConfig(**self._raw_data)
        except Exception as e:
            logger.error(f"覆盖后校验失败: {dotpath}={value} - {e}")
            raise
    
    def reload(self) -> None:
        """重新加载配置"""
        self._load()
        logger.info("配置已重载")
    
    def to_dict(self) -> dict:
        """导出为字典"""
        return self._raw_data.copy()
    
    def to_yaml(self) -> str:
        """导出为 YAML 字符串"""
        return yaml.dump(self._raw_data, allow_unicode=True, default_flow_style=False)


# 全局实例
_settings: Optional[SettingsManager] = None


def get_settings(config_path: Optional[str] = None, env: Optional[str] = None) -> SettingsManager:
    """获取全局配置管理器"""
    global _settings
    if _settings is None:
        _settings = SettingsManager(config_path=config_path, env=env)
    return _settings


def reset_settings():
    """重置全局配置（用于测试）"""
    global _settings
    _settings = None
