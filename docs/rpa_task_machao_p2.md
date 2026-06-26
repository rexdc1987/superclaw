# 马超 RPA 学习任务 - 第二阶段

## 任务目标
开发 SuperClaw RPA 引擎 v1，实现 Action 插件化和 DAG 工作流执行。

## 开发内容

### 1. Action 注册机制 (3天)
- 实现 Action 基类和装饰器注册
- 内置 Action 开发：HTTP请求、等待、条件判断、循环
- Action 参数校验和类型系统

### 2. DAG 工作流引擎 (4天)
- DAG 图构建和验证（检测环）
- 拓扑排序和执行调度
- 并行节点执行
- 条件分支和跳转

### 3. 变量和上下文 (2天)
- 全局变量和局部变量
- 变量引用解析（${var} 语法）
- Action 间数据传递

### 4. 异常处理 (1天)
- 重试机制（指数退避）
- 超时控制
- 错误恢复和回滚

## 产出要求
1. RPA 引擎核心: E:\Projects\SuperClaw\src\rpa\engine.py
2. Action 注册器: E:\Projects\SuperClaw\src\rpa\actions\__init__.py
3. 内置 Actions: E:\Projects\SuperClaw\src\rpa\actions\builtin.py
4. DAG 执行器: E:\Projects\SuperClaw\src\rpa\dag.py
5. 单元测试: E:\Projects\SuperClaw\tests\test_rpa_engine.py

## 技术要求
- 基于第一阶段的 interfaces.py 和 models.py 开发
- 所有 Action 必须有 type hints 和 docstring
- DAG 引擎必须有环检测
- 测试覆盖率 > 80%
