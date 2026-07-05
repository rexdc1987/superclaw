# ============================================================
# SuperClaw Multi-Stage Dockerfile
# Stage 1: Builder — 安装依赖
# Stage 2: Runtime — 精简运行环境
# ============================================================

# ---- Stage 1: Builder ----
FROM python:3.11-slim AS builder

WORKDIR /build

# 系统依赖（编译用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 缓存
COPY pyproject.toml README.md ./
COPY src/ src/

# 安装 Python 依赖
RUN pip install --no-cache-dir --prefix=/install \
    -e ".[dev]" 2>/dev/null || \
    pip install --no-cache-dir --prefix=/install \
    typer[all] rich pydantic PyYAML \
    fastapi uvicorn jinja2 httpx \
    apscheduler networkx \
    structlog prometheus-client \
    pytest pytest-asyncio

# ---- Stage 2: Runtime ----
FROM python:3.11-slim AS runtime

# 运行时系统依赖（Playwright Chromium）
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libwayland-client0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# 非 root 用户
RUN groupadd -r superclaw && useradd -r -g superclaw -d /app -s /sbin/nologin superclaw

# 复制安装好的 Python 包
COPY --from=builder /install /usr/local

# 复制应用代码
WORKDIR /app
COPY src/ src/
COPY config/ config/
COPY pyproject.toml README.md ./

# 创建数据目录
RUN mkdir -p /app/data /app/logs && \
    chown -R superclaw:superclaw /app

# 切换到非 root 用户
USER superclaw

# 环境变量默认值
ENV SUPERCLAW_ENV=production \
    SUPERCLAW_APP__DEBUG=false \
    SUPERCLAW_APP__LOG_LEVEL=INFO \
    SUPERCLAW_DATABASE__URL=sqlite:///app/data/superclaw.db \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# 暴露端口（Dashboard）
EXPOSE 8000

# 启动命令
CMD ["python", "-m", "uvicorn", "rpa.dashboard.app:app", "--host", "0.0.0.0", "--port", "8000"]
