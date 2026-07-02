"""Run SuperClaw API server."""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path = [p for p in sys.path if 'hermes' not in p.lower()]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
import uvicorn


def configure_logging() -> None:
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"api-{datetime.now().strftime('%Y%m%d')}.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


if __name__ == "__main__":
    configure_logging()
    logging.getLogger(__name__).info("Starting SuperClaw API on 0.0.0.0:8890")
    uvicorn.run("api.main:app", host="0.0.0.0", port=8890, reload=False, log_config=None, access_log=True)
