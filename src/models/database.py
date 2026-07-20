"""SQLAlchemy Database Setup - MySQL/SQLite dual support"""
import os
import sys
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

def _get_base_dir():
    """Get base directory for both source and PyInstaller bundle"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    # Source mode: go up from src/models/ to project root
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _load_config():
    config_path = os.path.join(_get_base_dir(), "config", "default.yaml")
    local_path = os.path.join(_get_base_dir(), "config", "local.yaml")
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    if os.path.exists(local_path):
        with open(local_path, "r", encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        for key, value in local.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
    return config

def _build_url(cfg):
    db = cfg.get("database", {})
    engine_type = db.get("engine", "sqlite")
    if engine_type == "mysql":
        host = os.environ.get("SUPERCLAW_DB_HOST") or db.get("host", "127.0.0.1")
        port = int(os.environ.get("SUPERCLAW_DB_PORT") or db.get("port", 3306))
        name = os.environ.get("SUPERCLAW_DB_NAME") or db.get("name", "superclaw")
        user = os.environ.get("SUPERCLAW_DB_USER") or db.get("user", "superclaw")
        pwd = os.environ.get("SUPERCLAW_DB_PASSWORD") or db.get("password", "")
        return f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{name}?charset=utf8mb4"
    db_path = os.path.join(_get_base_dir(), "data", "superclaw.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return "sqlite:///{}".format(db_path)

cfg = _load_config()
engine = create_engine(_build_url(cfg), echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    Base.metadata.create_all(engine)

def get_session():
    return SessionLocal()
