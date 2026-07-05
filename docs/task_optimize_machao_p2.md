# 马超补完任务 — SuperClaw 优化续

> DAG合并已完成，以下为剩余任务

## 项目路径
E:/Projects/SuperClaw
source venv/bin/activate

## 当前状态
495 passed / 1 failed / 4 skipped / 228 warnings

## 剩余任务

### Task 1: Dashboard模板修复（当前唯一失败）
tests/test_monitoring.py::TestDashboard::test_overview_page 报 TypeError
- 错误：cannot use tuple as dict key (unhashable type: dict)
- 位置：jinja2/utils.py — 模板渲染问题
- 检查 src/rpa/dashboard/templates/overview.html 模板语法
- 检查 src/rpa/dashboard/app.py 传给模板的数据结构
- 修复后移除 tests/test_monitoring.py 中 test_overview_page 的 @pytest.mark.skip

### Task 2: 修复5个TODO
- src/rpa/cli/commands/account.py:29,81,98 — 账号持久化（可用JSON文件）
- src/rpa/dag_engine.py:345 — 子流程集成
- src/rpa/orchestrator.py:366 — 搜索逻辑占位

### Task 3: 检查__init__.py导出
确保所有子模块的公共API都正确导出

## 验收标准
pytest tests/ -q — 0 failed, warnings不超过228
