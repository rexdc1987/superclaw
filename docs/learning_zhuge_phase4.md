# 诸葛亮 Phase 4 学习笔记 — Docker 部署 + 项目打包

> 学习人：诸葛亮 | 日期：2026-06-20
> 任务来源：曹操派发 | 最终阶段

---

## 1. 产出清单

| 产出 | 文件 | 说明 |
|------|------|------|
| Dockerfile | `docker/Dockerfile` | 多阶段构建，非 root 用户，Playwright 依赖 |
| Docker Compose | `docker/docker-compose.yml` | 单服务编排，数据卷持久化 |
| pyproject.toml | `pyproject.toml` | 现代 Python 打包，完整依赖列表 |
| 部署指南 | `docs/deployment_guide.md` | 快速开始 + 配置参考 + 故障排除 |
| 学习笔记 | `docs/learning_zhuge_phase4.md` | 本文件 |

---

## 2. Dockerfile 多阶段构建设计

### 两阶段架构

```
Stage 1: builder (python:3.11-slim)
  → 安装编译工具
  → pip install 依赖到 /install
  → 不包含应用代码的编译产物

Stage 2: runtime (python:3.11-slim)
  → 仅复制 /install 中的 Python 包
  → 安装 Playwright 运行时依赖（libnss3 等）
  → 创建非 root 用户 superclaw
  → 复制应用代码
  → 暴露 8000 端口
```

### 关键设计决策

1. **非 root 用户**：`useradd -r -r superclaw`，容器内以 superclaw 用户运行，避免 root 权限泄露。
2. **依赖缓存**：先复制 `pyproject.toml` 再复制代码，利用 Docker 层缓存——只有依赖变化时才重新安装。
3. **Playwright 依赖**：Chromium 需要大量系统库（libnss3、libatk 等），全部在 runtime 阶段安装。
4. **健康检查**：`HEALTHCHECK` 指令每 30 秒检查一次。
5. **环境变量**：通过 `ENV` 设置默认值，运行时可用 `docker-compose environment` 覆盖。

### 镜像大小优化

- builder 阶段的编译工具不进入 runtime 阶段
- `--no-cache-dir` 禁用 pip 缓存
- `--no-install-recommends` 最小化 apt 安装
- 预估 runtime 镜像约 400-600MB（含 Chromium 依赖）

---

## 3. Docker Compose 编排设计

### 服务定义

```yaml
services:
  superclaw:
    build: ..           # 从项目根目录构建
    ports: 8000:8000    # Dashboard 端口
    volumes:            # 数据持久化
      - superclaw_data:/app/data
      - superclaw_logs:/app/logs
    environment:        # 配置覆盖
      - SUPERCLAW_ENV=production
    restart: unless-stopped
```

### 数据持久化

- `superclaw_data`：SQLite 数据库、导出文件
- `superclaw_logs`：告警日志、应用日志

### 扩展预留

当前是单服务部署。后续可扩展：
- Redis 服务（消息队列）
- Prometheus + Grafana（监控）
- Nginx 反向代理

---

## 4. Python 打包设计（pyproject.toml）

### 依赖分层

| 类别 | 包 | 说明 |
|------|-----|------|
| 核心 | typer, rich, pydantic, PyYAML | CLI + 配置 |
| Web | fastapi, uvicorn, jinja2, httpx | Dashboard |
| 调度 | apscheduler, networkx | 任务调度 + DAG |
| 监控 | structlog | 日志结构化 |
| 自动化 | playwright | 浏览器 RPA |
| 数据 | SQLAlchemy | ORM |
| 可选 | prometheus-client | Prometheus 指标 |

### Entry Point

```toml
[project.scripts]
superclaw = "rpa.cli.main:app"
```

安装后可直接在终端运行 `superclaw` 命令。

### 开发依赖

```toml
[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "ruff"]
```

`pip install -e ".[dev]"` 安装开发环境。

---

## 5. 四个阶段总结

| 阶段 | 产出 | 核心能力 |
|------|------|----------|
| Phase 1 | scheduler.py + 学习笔记 | 任务调度、状态机、限流、重试 |
| Phase 2 | CLI + 配置系统 + 测试 | typer CLI、Pydantic 配置、42 个测试 |
| Phase 3 | 监控 + 告警 + Dashboard | 指标采集、告警引擎、FastAPI 面板 |
| Phase 4 | Docker + 打包 + 部署指南 | 容器化、pip 打包、生产部署 |

### 技术栈全景

```
CLI:        typer + rich
配置:       PyYAML + Pydantic
调度:       APScheduler
DAG:        networkx
队列:       asyncio.Queue
限流:       自建 TokenBucket
监控:       prometheus-client（可选）+ 内存计数器
告警:       自建 AlertEngine + 多通道
Dashboard:  FastAPI + Jinja2
数据库:     SQLAlchemy + SQLite
浏览器:     Playwright
容器:       Docker multi-stage
打包:       pyproject.toml + setuptools
```

---

<!-- TASK_COMPLETE: phase4_deploy -->
