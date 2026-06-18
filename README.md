# SuperClaw - Social Media Comment Lead Operations System

Automated comment collection, intelligent filtering, lead scoring, and batch outreach.

## Features

- **Keyword Search** - Search videos on Douyin/Kuaishou/Bilibili/Xiaohongshu
- **Comment Collection** - Auto-collect video comments with keyword matching
- **Lead Scoring** - Intent keywords, activity, interaction history auto-scoring
- **Batch Actions** - Comment reply, like, follow, DM, favorite
- **Risk Control** - Rate limits, sensitive word filter, blacklist, circuit breaker
- **Dashboard** - Task progress, lead stats, account health
- **GUI** - PySide6 desktop app with 8 functional pages

## Tech Stack

- GUI: PySide6 (Qt6)
- Browser Automation: Playwright (Chromium)
- Database: SQLite / MySQL (SQLAlchemy ORM)
- Runtime: Python 3.11+

## Quick Start

### Install dependencies
    pip install -r requirements.txt
    playwright install chromium

### Initialize database
    python -c "from src.models.database import init_db; init_db()"

### Launch GUI
    python src/main.py

### Run tests
    pip install -r requirements-dev.txt
    pytest tests/ -v

## Project Structure

    SuperClaw/
    +-- src/
    |   +-- main.py              # Entry point
    |   +-- core/                # Config, constants, exceptions
    |   +-- models/              # Database models (14 tables)
    |   +-- services/            # Business services (8)
    |   +-- gui/                 # GUI pages (8)
    |   +-- automation/          # Browser automation
    |   +-- utils/               # Utility functions
    +-- config/                  # YAML config
    +-- tests/                   # 113 tests
    +-- data/                    # SQLite database
    +-- logs/                    # Runtime logs
    +-- requirements.txt         # Production deps
    +-- requirements-dev.txt     # Dev deps
    +-- pyproject.toml           # Project metadata

## Supported Platforms

- Douyin: search, comments, reply, like, follow, DM
- Kuaishou: adapter ready, pending testing
- Bilibili: adapter ready, pending testing
- Xiaohongshu: adapter ready, pending testing

## Build Executable

    pip install pyinstaller
    python build.py
    # Output: dist/SuperClaw.exe

## License

MIT
