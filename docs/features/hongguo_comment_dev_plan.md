# 红果评论功能 - 开发计划

> 负责人：马超（全栈开发）
> 审核人：曹操（任务派发+验收）
> 日期：2026-06-22

---

## 阶段1：数据库模型（优先）

创建SQLAlchemy模型文件，遵循现有task.py的代码风格。

### 文件列表
- src/models/hongguo_task.py — 红果任务主表
- src/models/hongguo_record.py — 评论记录表
- src/models/hongguo_log.py — 执行日志表
- src/models/hongguo_template.py — 评论模板表

### 要求
- 继承 models.database.Base
- 字段类型参照 task.py 的 Column 定义
- JSON字段用 Text 存储
- 时间字段用 datetime.utcnow
- 添加 __repr__ 和常用 property

---

## 阶段2：FastAPI后端

### 目录结构
src/api/
  __init__.py
  main.py              # FastAPI app入口
  deps.py              # 依赖注入（DB session）
  hongguo/
    __init__.py
    router.py          # 路由定义
    schemas.py         # Pydantic模型
    service.py         # 业务逻辑

### API接口（参照PRD第7章）
- POST /api/v1/hongguo/tasks — 创建任务
- GET /api/v1/hongguo/tasks — 任务列表
- GET /api/v1/hongguo/tasks/:id — 任务详情
- POST /api/v1/hongguo/tasks/:id/start — 开启任务
- POST /api/v1/hongguo/tasks/:id/pause — 暂停任务
- POST /api/v1/hongguo/tasks/:id/stop — 停止任务
- GET /api/v1/hongguo/tasks/:id/records — 评论记录
- GET /api/v1/hongguo/tasks/:id/logs — 执行日志

---

## 阶段3：Vue3前端

### 目录结构
frontend/
  package.json
  vite.config.js
  src/
    main.js
    App.vue
    router/index.js
    api/hongguo.js       # API调用
    views/
      TaskList.vue       # 任务列表
      TaskCreate.vue     # 新建任务
      TaskExecute.vue    # 执行监控
    components/
      LiveScreenshot.vue
      ExecutionLog.vue
      ProgressBar.vue
      CommentTable.vue

### 页面功能
1. 任务列表 — 表格展示，状态标签，操作按钮
2. 新建任务 — 表单（剧名/模式/间隔/评论来源/模板）
3. 执行监控 — 实时截图+日志+进度条+评论记录

---

## 阶段4：登录检测模块

- 红果APP登录状态检测
- 手机验证码登录辅助
- 前端登录引导弹窗

---

## 验收标准

1. 数据库模型能正确创建表
2. API接口能正常CRUD
3. 前端页面能正常显示和操作
4. 任务状态流转正确（pending->running->completed）
5. 评论记录能正确保存和查询
