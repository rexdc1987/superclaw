# 马超任务 — SuperClaw RPA 代码全面优化

> 派发人：曹操 | 执行人：马超 | 日期：2026-06-20

## 项目路径
E:/Projects/SuperClaw
激活虚拟环境：source venv/bin/activate

## 当前状态
- 495 passed / 0 failed / 5 skipped / 228 warnings
- 66个Python文件，13470行代码

## 优化任务清单

### Task 1: DAG模块合并（最高优先级）
项目有两套DAG实现：
- src/rpa/dag.py (DAGExecutor, 484行) — 被engine.py引用
- src/rpa/dag_engine.py (DagEngine, 523行) — 被orchestrator.py引用

要求：
1. 分析两个模块的功能差异
2. 保留dag_engine.py（功能更完整：并行、条件、子流程）
3. 将dag.py中独有的功能迁移到dag_engine.py
4. 修改engine.py的import指向dag_engine.py
5. 删除dag.py
6. 确保所有测试通过

### Task 2: 修复剩余5个TODO
- src/rpa/cli/commands/account.py:29 — 从持久化存储加载账号列表
- src/rpa/cli/commands/account.py:81 — 实际写入持久化存储
- src/rpa/cli/commands/account.py:98 — 实际删除
- src/rpa/dag_engine.py:345 — 子流程集成
- src/rpa/orchestrator.py:366 — 接入实际搜索逻辑

### Task 3: Dashboard Jinja2模板修复
- src/rpa/dashboard/app.py 的 overview 页面报 TypeError
- 修复模板渲染问题，确保 test_overview_page 能通过
- 修复后移除 tests/test_monitoring.py 中的 @pytest.mark.skip

### Task 4: 代码质量提升
- 检查所有模块是否有未使用的import
- 检查是否有可以提取为公共方法的重复代码
- 检查异常处理是否完善（是否有裸 except）

### Task 5: 补充缺失的__init__.py导出
- 检查所有子模块的__init__.py是否正确导出公共API
- 确保 from rpa.xxx import YYY 的导入路径都可用

## 验收标准
1. pytest tests/ -q — 0 failed
2. warnings 数量不超过当前（228）
3. DAG模块只剩一个（dag_engine.py）
4. TODO 数量从 5 降到 0
5. Dashboard test_overview_page 通过

## 完成后
运行 pytest tests/ -q 确认全部通过，输出最终测试结果。
