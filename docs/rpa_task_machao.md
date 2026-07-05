# 马超 RPA 学习任务 - 第一阶段

## 任务目标
设计 SuperClaw RPA 引擎架构，支持插件化 Action 和工作流编排。

## 学习内容

### 1. RPA 框架研究 (2天)
- 研究 RPAFramework 架构: https://github.com/robocorp/rpaframework
- 研究 TagUI 设计理念: https://github.com/aisingapore/TagUI
- 分析优缺点，提取可借鉴设计

### 2. 架构设计 (3天)
- 设计 Action 注册机制（插件化）
- 设计 Workflow 数据模型（DAG）
- 设计变量传递和上下文管理
- 设计异常处理和重试机制

### 3. 接口定义 (2天)
- 定义 Action 基类接口
- 定义 Workflow JSON Schema
- 定义引擎 API 接口

## 产出要求
1. 架构设计文档: E:\Projects\SuperClaw\docs\rpa_engine_design.md
2. 接口定义: E:\Projects\SuperClaw\src\rpa\interfaces.py
3. 数据模型: E:\Projects\SuperClaw\src\rpa\models.py

## 参考资源
- RPAFramework: https://robocorp.com/docs/libraries/rpa-framework
- DAG 调度: Airflow、Prefect 设计理念
