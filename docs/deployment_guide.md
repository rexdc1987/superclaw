# SuperClaw 部署指南

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 1. 克隆项目
git clone <repo-url> superclaw
cd superclaw

# 2. 启动服务
docker-compose -f docker/docker-compose.yml up -d

# 3. 访问 Dashboard
# 浏览器打开 http://localhost:8000

# 4. 查看日志
docker-compose -f docker/docker-compose.yml logs -f superclaw
```

### 方式二：本地安装

```bash
# 1. 安装依赖
pip install -e ".[dev]"

# 2. 安装 Playwright 浏览器
playwright install chromium

# 3. 启动 Dashboard
superclaw dashboard

# 4. 运行任务
superclaw run task.yaml
```

---

## 配置参考

### 配置文件层次

```
优先级从低到高：
1. src/rpa/config/defaults.yaml    — 内置默认值
2. config/{env}.yaml               — 环境配置
3. 环境变量 SUPERCLAW_*             — 运行时覆盖
4. settings.override()             — 代码级覆盖
```

### 环境变量

双下划线 `__` 作为层级分隔符：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SUPERCLAW_ENV` | 运行环境 | production |
| `SUPERCLAW_APP__DEBUG` | 调试模式 | false |
| `SUPERCLAW_APP__LOG_LEVEL` | 日志级别 | INFO |
| `SUPERCLAW_DATABASE__URL` | 数据库连接 | sqlite:///data/superclaw.db |
| `SUPERCLAW_QUEUE__MAX_WORKERS` | 最大工作线程 | 5 |
| `SUPERCLAW_RATE_LIMIT__GLOBAL_CAPACITY` | 全局限流容量 | 100 |
| `SUPERCLAW_RETRY__MAX_RETRIES` | 最大重试次数 | 3 |

### 配置示例

```bash
# 开发环境
export SUPERCLAW_ENV=development
export SUPERCLAW_APP__DEBUG=true
export SUPERCLAW_APP__LOG_LEVEL=DEBUG

# 生产环境（使用 PostgreSQL）
export SUPERCLAW_DATABASE__URL=postgresql://user:pass@db:5432/superclaw
```

---

## CLI 命令

```bash
superclaw run task.yaml              # 运行任务
superclaw run task.yaml --dry-run    # 仅验证
superclaw config show                # 查看配置
superclaw config show --format json  # JSON 格式
superclaw config get app.debug       # 获取配置值
superclaw config set app.debug true  # 设置配置值
superclaw account list               # 列出账号
superclaw account health             # 账号健康度
superclaw health                     # 系统健康检查
superclaw version                    # 版本号
```

---

## 故障排除

### Playwright 浏览器未安装

```bash
# 本地安装
playwright install chromium

# Docker 中已内置，无需额外操作
```

### 数据库初始化失败

```bash
# 检查数据目录权限
ls -la data/

# 确保目录可写
mkdir -p data && chmod 755 data
```

### 端口被占用

```bash
# 修改 docker-compose.yml 中的端口映射
ports:
  - "8001:8000"  # 改为 8001
```

### 配置不生效

```bash
# 检查环境变量是否正确（注意双下划线）
echo $SUPERCLAW_APP__DEBUG

# 检查配置加载顺序
superclaw config show --format yaml
```

---

## 架构概览

```
┌─────────────────────────────────────────┐
│            SuperClaw Platform            │
├──────────┬──────────┬───────────────────┤
│   CLI    │ Dashboard│    Scheduler      │
│ (typer)  │(FastAPI) │ (APScheduler)     │
├──────────┴──────────┴───────────────────┤
│              Core Engine                 │
│  DAG Engine │ Orchestrator │ Task Queue  │
├──────────────────────────────────────────┤
│          Automation Layer                │
│  Playwright │ Platform Adapter │ Anti-Det│
├──────────────────────────────────────────┤
│         Monitoring & Alerting            │
│  Metrics │ Alert Engine │ Channels       │
├──────────────────────────────────────────┤
│           Data Layer                     │
│  SQLAlchemy │ SQLite/PostgreSQL          │
└──────────────────────────────────────────┘
```
