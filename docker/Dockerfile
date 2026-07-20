FROM node:22-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim AS runtime

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    SUPERCLAW_API_PORT=8980 \
    SUPERCLAW_EXECUTION_MODE=api \
    SUPERCLAW_FRONTEND_DIST=/app/frontend/dist \
    SUPERCLAW_SCREENSHOT_ROOT=/data/screenshots/hongguo

RUN groupadd -r superclaw && useradd -r -g superclaw -d /app -s /usr/sbin/nologin superclaw

WORKDIR /app
COPY pyproject.toml README.md requirements.txt ./
COPY src/ src/
COPY config/ config/
COPY run_api.py ./
COPY --from=frontend-builder /build/frontend/dist frontend/dist

RUN pip install --no-cache-dir \
      fastapi uvicorn jinja2 httpx pydantic PyYAML \
      SQLAlchemy PyMySQL cryptography uiautomator2 Pillow && \
    mkdir -p /data/screenshots/hongguo && \
    chown -R superclaw:superclaw /app /data

USER superclaw
EXPOSE 8980

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8980/health', timeout=3)"

CMD ["python", "run_api.py"]
