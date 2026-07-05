# 马超任务简报 -- 红果模块BUG检查

## 任务目标
检查 SuperClaw 红果评论模块的完整代码，找出所有BUG和潜在问题。

## 检查范围

### 1. 后端API (src/rpa/dashboard/routes_hongguo.py)
- 所有API端点是否正常工作
- 错误处理是否完善
- 数据库连接是否稳定
- 状态流转逻辑是否正确

### 2. 数据库模型 (src/models/hongguo_*.py)
- hongguo_task.py, hongguo_record.py, hongguo_log.py, hongguo_template.py
- 字段定义是否合理，是否有遗漏

### 3. 前端代码 (frontend/src/)
- views/TaskList.vue, TaskCreate.vue, TaskExecute.vue, TemplateManager.vue
- api/hongguo.js, router/index.js
- 检查API调用是否与后端接口匹配

### 4. 测试文件
- tests/test_hongguo_api.py, tests/test_hongguo_models.py
- 运行测试确认通过率

## 检查方法
1. 运行测试: cd /mnt/e/Projects/SuperClaw && PYTHONPATH=src ./venv/bin/python -m pytest tests/test_hongguo*.py -v
2. 逐文件代码审查
3. 检查前后端接口一致性

## 输出
写入: /mnt/e/Projects/SuperClaw/docs/hongguo_bug_report.md
格式: 严重问题(BUG-001) + 一般问题(ISSUE-001) + 测试结果 + 总结
