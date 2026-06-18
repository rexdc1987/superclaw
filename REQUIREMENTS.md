# SuperClaw 项目需求文档 v2.0
> 更新时间：2026-06-18

---

## 1. 项目概述

**SuperClaw** 是一套社交媒体评论引流运营系统，支持抖音、小红书、快手、B站等平台的自动化评论、私信、关注等操作，实现精准获客和引流。

### 1.1 核心功能
- 🎯 **任务管理** — 创建、调度、执行自动化任务（评论/私信/关注/点赞/浏览）
- 📦 **账号管理** — 多平台账号分组管理，健康度监控
- 🔑 **关键词管理** — 关键词组配置，轮换策略
- 👥 **线索管理** — 自动采集潜在客户，评分筛选
- 📋 **剧本管理** — 预设运营策略模板
- ⚠️ **风控管理** — 敏感词过滤、频率限制、异常检测
- 👤 **用户管理** — 多角色权限控制
- 📊 **数据看板** — 运营数据可视化

---

## 2. 系统架构

### 2.1 前后端分离架构

```
┌─────────────────────────────────────────────────────────┐
│                      客户端 (PySide6 GUI)                │
│         Windows 桌面应用，直接连接 MySQL                   │
└─────────────────────────────────────────────────────────┘

┌─────────────────┐    HTTP/JSON    ┌─────────────────────┐
│   Web 前端       │ ◄────────────► │   Web 后端            │
│  Vue3 + Element  │    /api/v1/*   │   FastAPI + SQLAlch  │
│  Nginx 静态托管   │                │   uvicorn 运行        │
└─────────────────┘                └─────────────────────┘
                                           │
                                           ▼
                                   ┌──────────────┐
                                   │   MySQL 8.0   │
                                   │   端口: 3308   │
                                   │   库: superclaw│
                                   └──────────────┘
```

### 2.2 三端共用同一数据库
- **客户端** (PySide6 GUI) — 直连 MySQL
- **Web 前端** (Vue3) — 通过 FastAPI 后端访问 MySQL
- **Web 后端** (FastAPI) — SQLAlchemy ORM 访问 MySQL

---

## 3. 技术栈

### 3.1 客户端（桌面应用）
| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 运行环境 |
| PySide6 | 6.5+ | GUI 框架 |
| SQLAlchemy | 2.0+ | ORM |
| PyMySQL | 1.1+ | MySQL 驱动 |
| Playwright | 1.40+ | 浏览器自动化 |
| PyYAML | 6.0+ | 配置文件解析 |

### 3.2 Web 前端
| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 3.5+ | 前端框架 |
| Vue Router | 4.6+ | 路由管理 |
| Element Plus | 2.14+ | UI 组件库 |
| Axios | 1.18+ | HTTP 请求 |
| Pinia | 3.0+ | 状态管理 |
| Vite | 8.0+ | 构建工具 |

### 3.3 Web 后端
| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.14 | 运行环境 |
| FastAPI | - | Web 框架 |
| SQLAlchemy | 2.0+ | ORM |
| PyMySQL | 1.1+ | MySQL 驱动 |
| uvicorn | - | ASGI 服务器 |

### 3.4 数据库
| 技术 | 版本 | 配置 |
|------|------|------|
| MySQL | 8.0 | 端口 3308，库名 superclaw |

---

## 4. 运行环境

### 4.1 客户端
```
路径: E:\Projects\SuperClaw
启动: 双击 start.bat 或 venv\Scripts\python.exe run.py --gui
Python: 3.11 (venv)
```

### 4.2 Web 后端
```
路径: /www/wwwroot/superclaw-api/
启动: cd /www/wwwroot/superclaw-api && source venv/bin/activate && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
端口: 8000
API文档: http://127.0.0.1:8000/docs
```

### 4.3 Web 前端
```
路径: /www/wwwroot/superclaw/frontend/
开发: npm run dev
构建: npm run build
部署: Nginx 托管 dist/ 目录
域名: test.superclaw.com (hosts 127.0.0.1)
```

### 4.4 数据库
```
类型: MySQL 8.0
端口: 3308 (WSL MySQL，避开 ServBay 3306)
库名: superclaw
连接: localhost:3308
```

---

## 5. API 路由

| 模块 | 路由前缀 | 功能 |
|------|----------|------|
| 账号管理 | /api/v1/accounts/ | CRUD、分组、健康度报告 |
| 任务管理 | /api/v1/tasks/ | CRUD、启动/暂停/继续/取消 |
| 线索管理 | /api/v1/leads/ | CRUD、导出 |
| 动作记录 | /api/v1/actions/ | 审核队列 |
| 剧本管理 | /api/v1/playbooks/ | CRUD |
| 风控规则 | /api/v1/risk/ | 规则管理 |
| 用户管理 | /api/v1/users/ | CRUD、登录 |
| 关键词 | /api/v1/keywords/ | 关键词组、导入/轮换 |
| 导出 | /api/v1/export/ | CSV 导出 |

---

## 6. 数据模型

### 6.1 核心表
| 表名 | 说明 | 关键字段 |
|------|------|----------|
| users | 用户 | username, role, status, expire_at |
| accounts | 账号 | platform, account_name, status, group_id |
| account_groups | 账号分组 | name, platform |
| tasks | 任务 | name, platform, status, priority, progress |
| leads | 线索 | platform, username, score, status |
| keywords | 关键词 | group_id, keyword, used_count |
| keyword_groups | 关键词组 | name, platform |
| playbooks | 剧本 | name, type, config_json |
| actions | 动作记录 | task_id, action_type, status |
| risk_rules | 风控规则 | rule_type, pattern, action |

### 6.2 任务状态机
```
draft → pending → running ⇄ paused → completed
                  ↓           ↓
                failed      cancelled
```

---

## 7. 前端页面

| 页面 | 路由 | 功能 |
|------|------|------|
| 登录 | /login | 用户认证 |
| 看板 | / | 运营数据概览 |
| 账号管理 | /accounts | 账号 CRUD、分组、健康度 |
| 任务中心 | /tasks | 任务创建、调度、监控 |
| 关键词 | /keywords | 关键词组管理 |
| 线索管理 | /leads | 线索查看、导出 |
| 剧本管理 | /playbooks | 策略模板 |
| 审核中心 | /review | 动作审核队列 |
| 风控管理 | /risk | 风控规则配置 |
| 用户管理 | /users | 用户 CRUD |
| 日志 | /logs | 操作日志 |

---

## 8. Nginx 配置

```nginx
server {
    listen 80;
    server_name test.superclaw.com;

    # 前端静态文件
    root /www/wwwroot/superclaw/frontend/dist;
    index index.html;

    # Vue Router history 模式
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 反向代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 9. 注意事项

1. **venv 路径**: start.bat 启动前需清除 PYTHONPATH，避免与其他 venv 冲突
2. **MySQL 端口**: 使用 3308 而非 3306，避开 ServBay 冲突
3. **任务状态**: draft 状态可直接启动到 running（已修复状态机）
4. **字段同步**: Web 端和客户端显示字段需保持一致
