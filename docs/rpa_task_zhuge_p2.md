# 诸葛亮 RPA 学习任务 - 第二阶段

## 任务目标
学习 DAG 流程编排，掌握条件分支、循环、并行执行和子流程复用。

## 学习内容

### 1. DAG 理论 (2天)
- 有向无环图概念和性质
- 拓扑排序算法
- 关键路径分析
- 实践：Python networkx 库构建 DAG

### 2. 流程编排模式 (3天)
- 条件分支（if/else）
- 循环（for/while）
- 并行执行（parallel split/join）
- 子流程调用（subprocess）

### 3. 流程模板设计 (2天)
- 获客流程模板（搜索→筛选→评论→私信）
- 批量操作模板（批量关注、批量点赞）
- 流程导入导出（JSON/YAML）

## 产出要求
1. 学习笔记: E:\Projects\SuperClaw\docs\rpa_dag_notes.md
2. DAG 引擎: E:\Projects\SuperClaw\src\rpa\dag_engine.py
3. 流程模板: E:\Projects\SuperClaw\src\rpa\templates\lead_gen.yaml
4. 流程编排器: E:\Projects\SuperClaw\src\rpa\orchestrator.py

## 参考资源
- networkx: https://networkx.org/
- Airflow DAG 设计理念
- Prefect workflow patterns
