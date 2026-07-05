# ZhuGe Phase 4 - Docker Deployment + Project Packaging

> Dispatched by Cao Cao | Date: 2026-06-20
> Final phase: containerize SuperClaw for production deployment
> Output: docker/ + pyproject.toml + docs/learning_zhuge_phase4.md

---

## Goals

1. Create Dockerfile with multi-stage build
2. Create docker-compose.yml for full stack
3. Create pyproject.toml for proper Python packaging
4. Write deployment guide

## Tasks

### Task 1: Dockerfile (multi-stage)
**Output**: docker/Dockerfile

Production-ready Dockerfile:
- Stage 1 (builder): install dependencies with pip
- Stage 2 (runtime): copy only needed files, non-root user
- Health check built in
- Support for Playwright browser deps (chromium)
- Environment variable configuration

### Task 2: Docker Compose
**Output**: docker/docker-compose.yml

Full stack orchestration:
- superclaw service (main app)
- Environment variables for config override
- Volume mounts for data persistence
- Network configuration
- Restart policy

### Task 3: Python Packaging
**Output**: pyproject.toml

Modern Python project config:
- Project metadata (name, version, description)
- Dependencies list (httpx, typer, pydantic, playwright, etc.)
- Entry point: superclaw = rpa.cli.main:app
- Dev dependencies (pytest, ruff)
- Python version requirement (>=3.8)

### Task 4: Deployment Guide + Learning Notes
**Output**: docs/deployment_guide.md + docs/learning_zhuge_phase4.md

Document:
- Quick start guide (docker-compose up)
- Configuration reference
- Environment variables
- Troubleshooting common issues

## Acceptance Criteria

1. Dockerfile builds successfully
2. docker-compose.yml is valid
3. pyproject.toml has all dependencies
4. Deployment guide is complete
5. Write TASK_COMPLETE phase4_deploy at end of notes
