# SuperClaw 代码优化任务分配

> 执行人：马超、诸葛亮 | 验收：曹操 | 日期：2026-06-20

## 当前状态
- 482 passed / 18 failed / 330 warnings
- 65个Python文件，13460行源码

## 马超任务（代码修复）

### Task 1: 修复 Pydantic v2 废弃警告
- 文件：src/rpa/interfaces.py 第46行
- 把 class Config 改为 model_config = ConfigDict
- 验证：运行测试无 PydanticDeprecated 警告

### Task 2: 修复 SQLAlchemy 废弃 API
- 多个文件中 session.query(Model).get(id) 改为 session.get(Model, id)
- 多个文件中 datetime.utcnow() 改为 datetime.now(datetime.UTC)
- 验证：运行测试无 LegacyAPI/Deprecation 警告

### Task 3: DAG 模块合并分析
- 分析 dag.py (DAGExecutor 484行) vs dag_engine.py (DagEngine 523行) 差异
- 确定保留哪个、删除哪个、需要迁移哪些import
- 输出分析报告到 docs/dag_merge_analysis.md

## 诸葛亮任务（依赖和测试）

### Task 4: 修复缺失依赖
- 安装 jinja2（dashboard测试需要）
- 更新 pyproject.toml 的 dependencies 列表

### Task 5: 修复 18 个失败测试
- 集成测试 import 问题（test_e2e.py 11个失败）
- 浏览器测试 playwright 问题（test_browser.py 3个失败）
- Dashboard jinja2 问题（test_monitoring.py 4个失败）
- 目标：全部通过或合理标记 skip

## 验收标准
1. pytest tests/ -q 结果：0 failed，warnings 小于 50
2. 无 PydanticDeprecated 警告
3. 无 LegacyAPIWarning
4. DAG分析报告完成
