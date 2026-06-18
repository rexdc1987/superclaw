# 马超任务简报 - SuperClaw 代码开发

## 第一批任务：项目初始化 + 数据模型

### 任务 1: 项目结构初始化
- 在 C:/Users/Chaos/Documents/SuperClaw/ 创建完整项目结构
- 创建 requirements.txt (PySide6, playwright, sqlalchemy, pandas, openpyxl, pyyaml)
- 创建 src/__init__.py, src/main.py 入口
- 创建所有子包的 __init__.py

### 任务 2: 数据模型层
- 使用 SQLAlchemy + SQLite
- 实现所有数据模型：Account, AccountGroup, KeywordGroup, Task, Comment, Lead, Action, MessageTemplate, Material, RiskRule, Blacklist, SensitiveWord, ExecutionLog, AuditLog
- 创建 database.py 配置 SQLAlchemy engine 和 session
- 创建 alembic 迁移支持

### 任务 3: 核心服务接口
- 实现 AccountService: CRUD, 分组, 状态管理
- 实现 KeywordService: CRUD, 分组, 轮换逻辑
- 实现 TaskService: 创建, 状态机转换 (draft->queued->running->paused/completed/failed)

## 技术规范
- Python 3.11+
- SQLAlchemy 2.0 (async not required for MVP)
- SQLite 数据库文件: data/superclaw.db
- 日志: Python logging, 输出到 logs/ 目录

## 输出位置
C:/Users/Chaos/Documents/SuperClaw/src/
