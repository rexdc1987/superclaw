# 马超 Phase 1 学习任务 — RPA 框架设计与架构研究

> 派发人：曹操 | 日期：2026-06-20
> 预计周期：3-5天 | 产出位置：docs/learning_machao_phase1.md

---

## 学习目标

1. 研究主流 RPA 框架的架构设计（RPAFramework、TagUI、Robot Framework）
2. 理解 Action/Task/Workflow 的数据模型设计
3. 设计 SuperClaw RPA 引擎的架构方案
4. 编写架构设计文档

## 学习内容

### 模块1：RPA 框架调研（第1-2天）
- 研究 RPAFramework 的核心概念
- 研究 TagUI 的设计理念
- 研究 Robot Framework 的关键字驱动框架
- **产出**：`docs/rpa_framework_survey.md`

### 模块2：SuperClaw 现有代码分析（第2-3天）
- 阅读 src/automation/ 目录下的所有代码
- 分析 platform_base.py、douyin_adapter.py 架构
- 找出可复用和需要重构的部分
- **产出**：`docs/existing_code_analysis.md`

### 模块3：RPA 引擎架构设计（第3-4天）
- 设计 Action 注册机制（插件化）
- 设计 DAG 工作流编排引擎
- 设计变量传递和上下文管理方案
- **产出**：`docs/rpa_engine_design.md`

### 模块4：原型实现（第4-5天）
- 实现最小可用的 RPA 引擎原型
- 包含：Action 基类、顺序执行引擎、基本日志
- 用 pytest 写单元测试
- **产出**：`src/rpa/engine.py` + `tests/test_rpa_engine.py`

## 学习要求

1. 架构设计必须画图（ASCII 或 Mermaid）
2. 数据模型用 Python dataclass 或 Pydantic 定义
3. 接口设计用 ABC（抽象基类）
4. 每个设计决策要说明理由
5. 完成后在笔记末尾写 <!-- TASK_COMPLETE: phase1_rpa_design -->
