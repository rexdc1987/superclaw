# SuperClaw Web Frontend v2 Development Plan

## Overview
将 Web 前端从基础 MVP 升级到与 PySide6 客户端对齐的完整版本。

## Current State
- 6 个 Vue 页面: Login, Dashboard, Accounts, Tasks, Leads, Playbooks
- 技术栈: Vue3 + Element Plus + Vite
- API base: /api/v1/

## Backend API (已就绪)
- /api/v1/accounts - 账号 CRUD + groups + health report
- /api/v1/tasks - 任务 CRUD + start/pause/resume/cancel/complete
- /api/v1/leads - 线索 CRUD + score/assign/status
- /api/v1/actions - 动作 CRUD + batch/execute/review
- /api/v1/playbooks - 打法模板 CRUD + presets
- /api/v1/risk - 风控 rules + sensitive-words + blacklist
- /api/v1/users - 用户 CRUD + login
- /api/v1/keywords - 关键词 groups + import/next

## Phase 1: 新增缺失页面 (4个新页面)

### 1. 运行日志 (/logs)
- 实时日志表格: 类型、时间、内容、浏览器名、账号
- 日志级别筛选、时间范围筛选、自动滚动、导出

### 2. 审核队列 (/review)
- 待审核列表 + 通过/拒绝/批量操作
- API: POST /api/v1/actions/review/{submit|approve|reject}

### 3. 风控中心 (/risk)
- 3个Tab: 风控规则、敏感词、黑名单
- 每个Tab支持 CRUD + 检测

### 4. 用户管理 (/users)
- 用户列表 + 新增/编辑/删除

## Phase 2: 增强现有页面
- Dashboard: 刷新按钮、4个统计卡片
- Tasks: 参数配置、控制按钮
- Accounts: 分组管理、健康报告

## Phase 3: 关键词管理 (/keywords)
- 关键词组 CRUD + 导入

## UI/UX: 深色主题、Element Plus、表格分页
