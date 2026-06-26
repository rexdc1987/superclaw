# 诸葛亮任务简报 -- 红果模块集成测试

## 任务目标
对红果评论模块进行集成测试，验证马超发现的BUG是否真实存在。

## 马超发现的问题摘要
- BUG-001/002/003: ORM字段名与API/Engine不匹配
- BUG-004: resume功能前端缺失
- BUG-006: waiting_login状态前端未映射
- ISSUE-001: 状态流转无校验
- ISSUE-004: 测试覆盖不足

## 测试任务

### 1. 启动Dashboard API
cd /mnt/e/Projects/SuperClaw && PYTHONPATH=src ./venv/bin/python -c "from rpa.dashboard.app import app; import uvicorn; uvicorn.run(app, host='0.0.0.0', port=8002)"

### 2. API端点测试 (用curl)
- GET /api/v1/hongguo/tasks
- POST /api/v1/hongguo/tasks (创建任务)
- GET /api/v1/hongguo/tasks/{id}
- POST /api/v1/hongguo/tasks/{id}/start
- POST /api/v1/hongguo/tasks/{id}/pause
- POST /api/v1/hongguo/tasks/{id}/resume
- POST /api/v1/hongguo/tasks/{id}/stop
- GET /api/v1/hongguo/tasks/{id}/records
- GET /api/v1/hongguo/tasks/{id}/logs

### 3. ORM字段验证
- 读取数据库实际schema: mysql -u root -pf62f2d10192807cb -h 127.0.0.1 -P 3308 superclaw -e "DESCRIBE hongguo_comment_tasks"
- 对比ORM模型定义
- 确认BUG-001/002/003是否真实

### 4. 前端代码验证
- 检查api/hongguo.js是否有resumeTask
- 检查TaskExecute.vue是否有恢复按钮
- 检查statusText是否包含waiting_login

## 输出
写入: /mnt/e/Projects/SuperClaw/docs/hongguo_test_report.md
格式: 测试项 + 结果(PASS/FAIL) + BUG确认状态 + 建议
