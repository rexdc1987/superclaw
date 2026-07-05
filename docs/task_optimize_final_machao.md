# 马超任务 — SuperClaw 代码全面审查与优化

> 派发人：曹操 | 执行人：马超

## 项目路径
E:/Projects/SuperClaw
source venv/bin/activate

## 当前状态
- 496 passed / 0 failed / 4 skipped / 272 warnings
- GUI可正常启动和登录

## 核心要求
代码审查+优化，改完必须通过以下验证：
1. pytest tests/ -q — 0 failed
2. python run.py --gui — 能启动、登录、点击侧边栏各页面

## 优化任务

### Task 1: DAG模块检查
dag.py已被删除，dag_engine.py已更新。确认：
- engine.py和orchestrator.py的import都指向dag_engine.py
- 没有残留的dag.py引用

### Task 2: 消除剩余 warnings
当前272个warnings，主要是：
- SQLAlchemy LegacyAPIWarning（session.query.get）
- DeprecationWarning（datetime.utcnow）
- PydanticDeprecatedSince20（class-based config）
目标：降到100以下

### Task 3: 代码质量扫描
- 未使用的import
- 裸except
- 重复代码
- 缺失的类型注解

### Task 4: GUI冒烟测试
修改任何代码后，必须验证：
- pytest通过
- GUI能启动登录
- 侧边栏可点击

## 禁止事项
- 不要改datetime.utcnow()为datetime.now(timezone.utc)——数据库存的是naive datetime，会崩
- 不要改PySide6的lambda签名——checked参数必须保留默认值
- 每改一个文件就跑一次pytest，不要批量改完再测

## 完成标准
pytest 0 failed + GUI可正常操作所有页面
