# RPA 主流框架调研报告

> 作者：马超 | 日期：2026-06-20  
> 阶段：Phase 1 模块1

---

## 1. 调研目标

研究三个主流 RPA 框架的架构设计、核心概念和技术选型，为 SuperClaw RPA 引擎设计提供参考。

调研框架：
- **RPAFramework** — Python 开源 RPA 框架
- **TagUI** — 低代码 RPA 工具
- **Robot Framework** — 关键字驱动测试/RPA 框架

---

## 2. RPAFramework

### 2.1 概述

RPAFramework 是一个 Python 原生的开源 RPA 框架，基于 UiPath 的 RPAFramework 概念，专注于 Web 和桌面自动化。项目地址：`https://github.com/robotcorp/rpaframework`（已被 Robocorp 收购并更名为 Robocorp Actions）。

### 2.2 核心架构

```
┌─────────────────────────────────────────┐
│            Robot (YAML/Python)           │
├─────────────────────────────────────────┤
│         Task Runner (执行引擎)           │
├──────┬──────┬──────┬──────┬─────────────┤
│ Browser│Desktop│ HTTP │ PDF  │ Excel     │
│ Library│Library│Client│      │           │
├──────┴──────┴──────┴──────┴─────────────┤
│     基础设施层 (日志/配置/安全)           │
└─────────────────────────────────────────┘
```

### 2.3 核心概念

| 概念 | 说明 |
|------|------|
| **Robot** | 一个完整的自动化单元，用 YAML 或 Python 定义 |
| **Task** | Robot 内的单个执行步骤 |
| **Library** | 功能库（如 Browser、Desktop、HTTP），每个 Library 封装一类操作 |
| **Variable** | 跨 Task 的变量传递 |
| **Credential** | 安全存储的凭据（通过 Robocorp Vault） |

### 2.4 设计特点

**优点**：
- **Python 原生**：用 Python 编写 Robot，IDE 支持好
- **Library 模式**：每个功能模块是独立的 Library，可组合
- **丰富的内置库**：Browser（Selenium/Playwright）、Desktop（Win32）、HTTP、PDF、Excel 等
- **YAML 配置**：Robot 可以用 YAML 定义，非开发人员也能编写
- **Conda 环境管理**：依赖隔离好

**缺点**：
- **架构偏重**：完整框架较重，轻量场景不适用
- **依赖多**：需要 Conda、Robocorp Lab 等工具链
- **学习曲线**：对纯 Python 开发者不直观

### 2.5 对 SuperClaw 的启示

1. **Library 模式可借鉴**：将功能按领域拆分为独立 Library（Action），通过注册机制接入引擎
2. **YAML 配置**：Workflow 用 YAML/JSON 声明，引擎解释执行——这与 SuperClaw 的设计一致
3. **Python 原生优先**：SuperClaw 也是 Python 项目，可以参考其 API 设计风格

---

## 3. TagUI

### 3.1 概述

TagUI 是一个低代码 RPA 工具，由 AI Singapore 开发。核心理念是**用自然语言（或伪代码）编写自动化脚本**，降低 RPA 门槛。

项目地址：`https://github.com/aiminglabs/tagui`

### 3.2 核心架构

```
┌─────────────────────────────────────────┐
│         TagUI Script (.tag)             │
│    (自然语言 / 伪代码 / JavaScript)      │
├─────────────────────────────────────────┤
│         Parser (解析器)                  │
│    将伪代码转换为 JavaScript             │
├─────────────────────────────────────────┤
│         Chrome DevTools Protocol        │
│    (通过 Chrome 控制浏览器)              │
├─────────────────────────────────────────┤
│         Visual Flow (可视化流程)         │
│    (可选的流程图编辑器)                   │
└─────────────────────────────────────────┘
```

### 3.3 核心概念

| 概念 | 说明 |
|------|------|
| **Step** | 单个操作步骤，如 `click button`、`type input as text` |
| **Flow** | 多个 Step 组成的流程 |
| **Selector** | 元素定位器（CSS / XPath / 文本） |
| **Variable** | 变量赋值和引用 |
| **Function** | 自定义函数/子流程 |

### 3.4 语法示例

```
// TagUI 伪代码示例
click login_button
type username as admin
type password as {{password}}
click submit
wait for dashboard
snap dashboard to dashboard.png
```

### 3.5 设计特点

**优点**：
- **极低门槛**：伪代码接近自然语言，非技术人员可编写
- **单文件部署**：一个 `.tag` 文件包含完整流程
- **内置反检测**：自动注入反检测脚本
- **可视化**：可选的流程图编辑器
- **跨平台**：支持 Windows/macOS/Linux

**缺点**：
- **功能有限**：伪代码表达能力有限，复杂逻辑难以实现
- **调试困难**：伪代码层的调试工具有限
- **性能一般**：每次操作都通过 Chrome DevTools，性能不如原生 API
- **扩展性差**：自定义功能需要写 JavaScript 插件

### 3.6 对 SuperClaw 的启示

1. **低门槛入口**：可以考虑支持简单的声明式 Workflow 语法，降低使用门槛
2. **反检测集成**：TagUI 的反检测策略值得参考
3. **可视化流程**：Phase 4 的管控面板可以考虑加入流程可视化

---

## 4. Robot Framework

### 4.1 概述

Robot Framework 是最成熟的开源 RPA/测试框架之一，由 Nokia Siemens Networks 开发，现由 Robot Framework Foundation 维护。核心理念是**关键字驱动**（Keyword-Driven）。

项目地址：`https://github.com/robotframework/robotframework`

### 4.2 核心架构

```
┌─────────────────────────────────────────┐
│          Robot File (.robot)            │
│    (关键字 + 数据表)                     │
├─────────────────────────────────────────┤
│          Test Runner (执行引擎)          │
│    解析 .robot → 执行关键字 → 生成报告   │
├─────────────────────────────────────────┤
│          Library Layer (库层)            │
├──────┬──────┬──────┬──────┬─────────────┤
│BuiltIn│Selenium│String │ Collections│  ...
│      │Library│      │           │
├──────┴──────┴──────┴──────┴─────────────┤
│     Python / Java / .NET 扩展层          │
└─────────────────────────────────────────┘
```

### 4.3 核心概念

| 概念 | 说明 |
|------|------|
| **Keyword** | 最小执行单元，类似函数。如 `Click Element`、`Input Text` |
| **Library** | 关键字的集合。每个 Library 是一个 Python/Java 模块 |
| **Test Case** | 测试用例，由多个关键字组成 |
| **Suite** | 测试套件，包含多个 Test Case |
| **Variable** | 变量，支持标量 `${var}`、列表 `@{list}`、字典 `&{dict}` |
| **Tag** | 标签，用于筛选和分组 |
| **Setup / Teardown** | 前置/后置操作 |

### 4.4 语法示例

```robot
*** Settings ***
Library    SeleniumLibrary

*** Variables ***
${URL}      https://example.com
${BROWSER}  chrome

*** Test Cases ***
Login Test
    Open Browser    ${URL}    ${BROWSER}
    Input Text      id=username    admin
    Input Text      id=password    secret
    Click Button    id=login
    Page Should Contain    Welcome
    Close Browser
```

### 4.5 设计特点

**优点**：
- **关键字驱动**：非技术人员也能理解和编写
- **丰富的生态**：SeleniumLibrary、Browser Library、Database Library 等
- **可扩展性强**：用 Python/Java 编写自定义 Library
- **成熟的报告**：内置 HTML 报告和日志
- **数据驱动**：支持数据表驱动测试
- **跨语言**：支持 Python、Java、.NET

**缺点**：
- **语法特殊**：`.robot` 文件语法独特，学习成本高
- **性能一般**：关键字层的抽象有性能开销
- **调试体验**：IDE 支持不如纯 Python
- **Web 依赖**：Browser Library 依赖 Selenium/Playwright

### 4.6 对 SuperClaw 的启示

1. **关键字驱动模式**：SuperClaw 的 Action 本质上就是"关键字"，可以参考其命名规范（如 `web.click`、`http.get`）
2. **Library 生态**：参考其 Library 组织方式，将 Action 按领域分组（web、http、file、data）
3. **报告系统**：内置的 HTML 报告生成值得参考
4. **数据驱动**：支持参数化执行，类似 SuperClaw 的 Workflow inputs

---

## 5. 框架对比

### 5.1 核心维度对比

| 维度 | RPAFramework | TagUI | Robot Framework |
|------|-------------|-------|-----------------|
| **语言** | Python 原生 | 伪代码/JS | 关键字（.robot） |
| **学习曲线** | 中等 | 低 | 中等 |
| **扩展性** | 高（Python Library） | 低（JS 插件） | 高（Python/Java Library） |
| **反检测** | 内置 | 内置 | 需自定义 |
| **Web 自动化** | Selenium/Playwright | Chrome DevTools | Selenium/Browser Library |
| **桌面自动化** | 支持（Win32） | 有限 | 支持（Win32） |
| **社区活跃度** | 中等 | 低 | 高 |
| **生产就绪** | 是 | 有限 | 是 |

### 5.2 架构模式对比

| 模式 | RPAFramework | TagUI | Robot Framework |
|------|-------------|-------|-----------------|
| **执行模式** | Python 直接执行 | 伪代码→JS→执行 | 关键字→Python→执行 |
| **数据传递** | Python 变量 | 变量（`{{var}}`） | 标量/列表/字典变量 |
| **流程编排** | Python 代码 | 顺序步骤 | 顺序 + Setup/Teardown |
| **错误处理** | Python try/except | 有限 | Run Keyword And Ignore Error |
| **并行执行** | 需自己实现 | 不支持 | 需自己实现 |
| **报告** | 自定义 | 截图 | 内置 HTML 报告 |

---

## 6. 对 SuperClaw 的综合建议

### 6.1 架构设计借鉴

1. **Action = Library 模式**（借鉴 RPAFramework）
   - 每个 Action 是独立的"库"，实现特定功能
   - 通过注册机制接入引擎，支持热插拔
   - SuperClaw 已实现 `ActionRegistry`，方向正确

2. **声明式 Workflow**（借鉴 RPAFramework + Robot Framework）
   - Workflow 用 JSON/YAML 声明，引擎解释执行
   - 支持数据驱动和参数化
   - SuperClaw 已实现 `WorkflowDefinition`，方向正确

3. **关键字命名规范**（借鉴 Robot Framework）
   - 采用 `domain.action` 格式：`web.click`、`http.get`、`file.copy`
   - 清晰的层级结构，便于查找和文档生成

### 6.2 SuperClaw 独特优势

SuperClaw 相比这些框架的独特价值：

| 特性 | 说明 |
|------|------|
| **社媒适配** | 专注抖音/小红书/B站等国内社媒平台，内置反检测 |
| **多账号管理** | 账号池轮换、健康度评分、凭据加密——这是 RPA 框架普遍缺失的 |
| **DAG 编排** | 支持并行、条件分支、循环——比 TagUI 的顺序步骤更强大 |
| **监控告警** | Prometheus 指标 + 告警引擎——生产级可观测性 |
| **异步执行** | 基于 asyncio——比 Robot Framework 的同步模型更高效 |

### 6.3 架构决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 语言 | Python 3.10+ | 与现有代码一致，生态丰富 |
| Workflow 定义 | JSON（优先）+ YAML | JSON 更通用，YAML 更易读 |
| Action 注册 | 装饰器 + 自动发现 | 参考 RPAFramework 的 Library 模式 |
| 浏览器引擎 | Playwright（优先） | 异步支持好，反检测能力强 |
| 数据模型 | Pydantic v2 | 类型安全，序列化好 |
| 并发模型 | asyncio | I/O 密集型任务，异步效率高 |

---

## 7. 参考资料

1. RPAFramework GitHub: https://github.com/robotcorp/rpaframework
2. TagUI GitHub: https://github.com/aiminglabs/tagui
3. Robot Framework GitHub: https://github.com/robotframework/robotframework
4. Robot Framework User Guide: https://robotframework.org/robotframework/latest/RobotFrameworkUserGuide.html
5. Playwright Python: https://playwright.dev/python/

---

<!-- TASK_COMPLETE: phase1_rpa_design -->
