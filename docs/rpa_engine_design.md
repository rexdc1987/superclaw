# SuperClaw RPA 引擎架构设计

> 版本: v1.0 | 日期: 2026-06-18 | 作者: 马超

## 1. 概述

### 1.1 目标
设计一个插件化、可扩展的 RPA 引擎，支持：
- **插件化 Action**：按领域拆分，独立注册，热插拔
- **DAG 工作流编排**：支持并行、串行、条件分支
- **变量与上下文管理**：跨 Action 传递数据
- **异常处理与重试**：自动恢复、降级策略

### 1.2 设计原则
| 原则 | 说明 |
|------|------|
| 插件化 | Action 通过注册机制接入，引擎核心不感知具体实现 |
| 声明式 | Workflow 用 JSON/YAML 声明，引擎解释执行 |
| 可观测 | 每个节点有状态追踪、日志、指标 |
| 容错性 | 节点失败可重试、跳过、降级 |

### 1.3 技术选型
- **语言**: Python 3.10+
- **调度**: APScheduler（已有 scheduler.py）+ DAG 拓扑排序
- **数据模型**: Pydantic v2
- **序列化**: JSON（Workflow 定义）、SQLite（运行时状态）

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────┐
│                  SuperClaw RPA Engine            │
├─────────────┬──────────────┬────────────────────┤
│  Workflow   │   Action     │    Context         │
│  Engine     │   Registry   │    Manager         │
│  (DAG)      │   (Plugins)  │    (Variables)     │
├─────────────┴──────────────┴────────────────────┤
│                  Core Layer                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ Scheduler│ │ Executor │ │ ErrorHandler     │ │
│  │ (Timing) │ │ (Runner) │ │ (Retry/Fallback) │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
├─────────────────────────────────────────────────┤
│              Action Modules (Plugins)            │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
│  │Web   │ │Desktop│ │File  │ │API   │ │Custom│ │
│  │Action│ │Action │ │Action│ │Action│ │Action│ │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ │
└─────────────────────────────────────────────────┘
```

### 2.1 核心模块职责

| 模块 | 职责 |
|------|------|
| **WorkflowEngine** | 解析 Workflow DAG，按拓扑序调度 Action 执行 |
| **ActionRegistry** | 管理 Action 的注册、发现、实例化 |
| **ContextManager** | 管理 Workflow 级和 Action 级变量的读写与传递 |
| **Scheduler** | 定时/周期触发 Workflow（复用现有 scheduler.py） |
| **Executor** | 实际执行 Action，管理生命周期（pending→running→done/error） |
| **ErrorHandler** | 处理异常：重试、跳过、降级、告警 |

---

## 3. Action 注册机制（插件化）

### 3.1 设计思路
借鉴 RPAFramework 的 Library 独立包结构：
- 每个 Action 是一个独立 Python 类，继承 `BaseAction`
- 通过 `@register_action` 装饰器自动注册
- Action 按领域拆分为独立模块（web、desktop、file、api 等）

### 3.2 注册流程
```
Action 类定义
    ↓
@register_action(name="web.click", category="web")
    ↓
ActionRegistry.register(action_class)
    ↓
引擎通过 name 查找并实例化
```

### 3.3 Action 发现
- **显式注册**: 代码中调用 `registry.register(MyAction)`
- **自动发现**: 扫描 `actions/` 目录下所有 `*_action.py` 文件
- **入口点**: 支持 Python entry_points（`superclaw.rpa.actions`）

### 3.4 Action 生命周期
```
init() → validate_params() → execute(context) → on_success() / on_error() → cleanup()
```

---

## 4. Workflow 数据模型（DAG）

### 4.1 核心概念

| 概念 | 说明 |
|------|------|
| **Workflow** | 一个完整的自动化流程，包含多个 Action 节点 |
| **Node** | DAG 中的一个节点，对应一个 Action 调用 |
| **Edge** | 节点间的依赖关系（A → B 表示 A 完成后才执行 B） |
| **Variable** | 节点间传递的数据，通过 Context 管理 |

### 4.2 DAG 示例
```json
{
  "id": "user_onboarding",
  "name": "用户入职流程",
  "nodes": [
    {
      "id": "fetch_user",
      "action": "api.get",
      "params": {"url": "{{env.API_BASE}}/users/{{input.user_id}}"},
      "outputs": {"user_data": "$.result"}
    },
    {
      "id": "send_email",
      "action": "email.send",
      "params": {
        "to": "{{fetch_user.user_data.email}}",
        "template": "welcome"
      },
      "depends_on": ["fetch_user"]
    },
    {
      "id": "create_record",
      "action": "db.insert",
      "params": {"table": "onboarding", "data": "{{fetch_user.user_data}}"},
      "depends_on": ["fetch_user"]
    }
  ]
}
```

### 4.3 并行执行
- 无依赖关系的节点自动并行
- `fetch_user` 完成后，`send_email` 和 `create_record` 并行执行

### 4.4 条件分支
```json
{
  "id": "check_approval",
  "action": "condition.check",
  "params": {"expression": "{{fetch_user.user_data.role} == 'admin'}"},
  "branches": {
    "true": ["admin_setup"],
    "false": ["standard_setup"]
  }
}
```

---

## 5. 变量传递与上下文管理

### 5.1 作用域层次

```
WorkflowContext (全局)
  ├── env.*          环境变量
  ├── input.*        Workflow 输入参数
  ├── global.*       Workflow 级自定义变量
  │
  └── NodeContext (节点级)
       ├── params.*   节点输入参数
       ├── outputs.*  节点输出结果
       └── local.*    节点局部变量
```

### 5.2 变量引用语法
- `{{variable_name}}` — 引用变量
- `{{node_id.output_field}}` — 引用其他节点的输出
- `{{env.API_KEY}}` — 引用环境变量
- `$.json_path` — JSONPath 提取

### 5.3 数据流
```
Workflow 输入 → WorkflowContext
    ↓
Node A 执行 → outputs 写入 NodeContext A
    ↓
Node B 读取 NodeContext A 的 outputs → 执行 → 写入 NodeContext B
    ↓
Workflow 结果 ← 最后一个节点的 outputs
```

---

## 6. 异常处理与重试机制

### 6.1 错误分类

| 类型 | 说明 | 默认策略 |
|------|------|----------|
| **可恢复错误** | 网络超时、页面未加载 | 重试 |
| **不可恢复错误** | 参数错误、权限不足 | 立即失败 |
| **降级错误** | 第三方服务不可用 | 执行备用 Action |

### 6.2 重试策略
```json
{
  "id": "fetch_data",
  "action": "http.get",
  "retry": {
    "max_attempts": 3,
    "delay_seconds": 5,
    "backoff_multiplier": 2,
    "retry_on": ["TimeoutError", "ConnectionError"]
  }
}
```

### 6.3 错误处理流程
```
Action 执行
  ├── 成功 → 写入 outputs，继续下一节点
  └── 失败
        ├── 重试次数 < max → 等待 delay 后重试
        ├── 重试次数 >= max
        │     ├── 有 fallback_action → 执行降级
        │     ├── on_failure: "skip" → 跳过，标记为 skipped
        │     └── on_failure: "fail" → 终止 Workflow
        └── 记录错误日志，触发告警
```

### 6.4 Workflow 级错误处理
```json
{
  "id": "my_workflow",
  "on_failure": "continue",
  "error_handler": {
    "alert_channel": "feishu",
    "notify_on": ["failed", "timeout"]
  }
}
```

---

## 7. 引擎执行流程

```
1. 加载 Workflow JSON → 解析为 DAG
2. 拓扑排序 → 确定执行顺序
3. 创建 WorkflowContext（初始化 env/input/global）
4. 调度器触发 → Executor 开始执行
5. 遍历 DAG：
   a. 检查节点依赖是否全部完成
   b. 通过 ActionRegistry 实例化 Action
   c. 注入 Context，调用 execute()
   d. 成功 → 写入 outputs，标记 done
   e. 失败 → 重试/跳过/降级
   f. 所有节点完成 → Workflow 完成
6. 返回 Workflow 结果
```

---

## 8. 扩展点

| 扩展点 | 说明 |
|--------|------|
| **自定义 Action** | 继承 BaseAction，实现 execute() |
| **自定义调度器** | 实现 SchedulerInterface |
| **自定义存储** | 替换默认的 SQLite 存储 |
| **Webhook 触发** | 外部系统通过 API 触发 Workflow |
| **监控集成** | 通过 EventHandler 接入监控系统 |

---

## 9. 目录结构

```
src/rpa/
├── __init__.py
├── interfaces.py          # Action 基类、Registry 接口
├── models.py              # Workflow、Node、Edge 数据模型
├── engine.py              # WorkflowEngine 核心引擎
├── context.py             # ContextManager 上下文管理
├── executor.py            # Action 执行器
├── registry.py            # Action 注册中心
├── error_handler.py       # 异常处理与重试
├── scheduler.py           # 调度器（已有）
└── actions/               # 内置 Action 模块
    ├── __init__.py
    ├── web_action.py      # Web 自动化
    ├── desktop_action.py  # 桌面自动化
    ├── file_action.py     # 文件操作
    └── api_action.py      # HTTP API 调用
```

---

## 10. 后续计划

- **第二阶段**: 实现 Engine 核心 + 3 个内置 Action（web/file/api）
- **第三阶段**: 可视化 Workflow 编辑器
- **第四阶段**: 监控仪表盘 + 告警系统

---

<!-- TASK_COMPLETE: phase1_rpa_design -->
