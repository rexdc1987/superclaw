# 马超 Phase 4 学习笔记 — Workflow YAML 引擎 + CLI 集成

> 作者：马超 | 日期：2026-06-20  
> 状态：学习完成

---

## 1. 任务完成情况

| 任务 | 产出文件 | 状态 |
|------|----------|------|
| Task 1: YAML Schema + Parser | `src/rpa/workflow/schema.py` + `parser.py` | ✅ |
| Task 2: Workflow Runner | `src/rpa/workflow/runner.py` | ✅ |
| Task 3: CLI 集成 | `src/rpa/cli/commands/run.py` (已更新) | ✅ |
| Task 4: 学习笔记 | 本文档 | ✅ |

测试结果：**123 passed** (Phase 2: 49 + Phase 3: 38 + Phase 4: 36)

---

## 2. Workflow YAML Schema 设计

### 2.1 YAML 格式定义

```yaml
name: douyin_engagement
description: "抖音互动流程"
version: "1.0.0"

variables:
  keyword: "Python"
  max_count: 10

steps:
  - adapter: douyin
    operation: login
    params:
      account: "{{account}}"

  - adapter: douyin
    operation: search
    params:
      keyword: "{{keyword}}"
      count: "{{max_count}}"
    depends_on: [douyin.login]

  - adapter: douyin
    operation: comment
    params:
      content: "好内容！"
    depends_on: [douyin.search]
    condition: "{{item.likes}} > 100"

  - adapter: douyin
    operation: like
    depends_on: [douyin.search]

  - action: log.info
    params:
      message: "流程完成"
    depends_on: [douyin.comment, douyin.like]
```

### 2.2 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | 工作流名称（必填） |
| `description` | str | 描述 |
| `version` | str | 版本号 |
| `variables` | dict | 全局变量 |
| `steps` | list | 步骤列表（必填） |
| `on_failure` | str | 全局失败策略: fail/skip |
| `max_retries` | int | 全局最大重试次数 |
| `timeout_seconds` | float | 全局超时 |

### 2.3 Step 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | str | 步骤 ID（可选，自动生成） |
| `adapter` | str | 适配器平台名 |
| `operation` | str | 适配器操作名 |
| `action` | str | DAG Action 名称（兼容模式） |
| `params` | dict | 操作参数 |
| `depends_on` | list | 依赖的步骤 ID |
| `condition` | str | 条件表达式 |
| `on_failure` | str | 失败策略 |
| `retry` | int/dict | 重试配置 |
| `timeout_seconds` | float | 超时 |
| `loop_over` | str | 循环变量引用 |
| `loop_var` | str | 循环变量名 |

### 2.4 自动生成 ID 规则

- `adapter` + `operation` → `{adapter}.{operation}`（如 `douyin.search`）
- `action` → 直接用 action 名（如 `log.info`）
- 都没有 → `step_{hash}`

---

## 3. Parser 设计

### 3.1 解析流程

```
YAML 文件/字符串
    ↓ yaml.safe_load
原始字典
    ↓ WorkflowParser.parse_dict
WorkflowDefinition
    ↓ validate_dag()
验证（环检测、依赖校验、字段校验）
    ↓
可用的工作流对象
```

### 3.2 模板变量解析

支持两种语法：
- `{{variable_name}}` — 双花括号
- `${variable_name}` — 美元符号

解析规则：
- **纯模板引用**（整个字符串就是一个模板）→ 返回原始类型（不转为字符串）
- **混合模板**（模板嵌在文本中）→ 替换为字符串值

```python
# 纯引用 → 保留类型
resolve_template("{{count}}", {"count": 42})  # → 42 (int)

# 混合 → 转字符串
resolve_template("Count: {{count}}", {"count": 42})  # → "Count: 42"
```

### 3.3 验证规则

1. 必须有 `name` 字段
2. 必须有 `steps` 且非空
3. 每个步骤必须指定 `adapter` 或 `action`
4. `adapter` 必须配合 `operation`
5. `depends_on` 引用的步骤必须存在
6. 不能有循环依赖（DFS 检测）
7. 不能有重复步骤 ID
8. `loop_over` 必须配合 `loop_var`

---

## 4. Runner 设计

### 4.1 执行流程

```
run(workflow_source, variables, dry_run)
    ↓
解析 YAML → WorkflowDefinition
    ↓
Dry-run? → 返回验证结果
    ↓
合并变量 → 全局变量 + 运行时变量
    ↓
拓扑排序 → 并行分组
    ↓
逐组执行:
  ├── 单步骤 → 直接执行
  └── 多步骤 → asyncio.gather 并行
    ↓
每个步骤:
  ├── 检查条件
  ├── 解析模板参数
  ├── 处理循环（如有）
  ├── 执行操作（adapter 或 action）
  ├── 写入上下文
  └── 回调通知
    ↓
汇总结果 → WorkflowResult
```

### 4.2 适配器操作映射

| YAML 操作 | 适配器方法 |
|-----------|-----------|
| `login` | `adapter.login()` |
| `search` | `adapter.search_content()` |
| `comment` / `post_comment` | `adapter.post_comment()` |
| `like` | `adapter.like_content()` |
| `follow` | `adapter.follow_user()` |
| `collect` | `adapter.collect_note()` |
| `get_comments` | `adapter.get_comments()` |
| `get_user_info` | `adapter.get_user_info()` |

### 4.3 循环支持

```yaml
steps:
  - adapter: douyin
    operation: comment
    loop_over: "{{search.results}}"
    loop_var: item
    params:
      target_url: "{{item.url}}"
      content: "好内容！"
```

执行时自动遍历 `search.results` 列表，每次迭代将当前元素赋值给 `item`。

### 4.4 上下文传递

步骤执行后，结果自动写入上下文：
- `context.set(step_id, result.data)` — 整个结果字典
- `context.set(f"{step_id}.{key}", value)` — 每个字段单独存储

后续步骤通过 `{{step_id.key}}` 引用前序步骤的输出。

---

## 5. CLI 集成

### 5.1 命令行用法

```bash
# 基本执行
superclaw run workflow.yaml

# Dry-run 验证
superclaw run workflow.yaml --dry-run

# 指定账号
superclaw run workflow.yaml --account default

# 传递变量
superclaw run workflow.yaml --var keyword=AI --var count=10

# 超时控制
superclaw run workflow.yaml --timeout 300

# 详细输出
superclaw run workflow.yaml --verbose
```

### 5.2 执行输出

```
工作流: workflow.yaml
变量: {'keyword': 'AI', 'account': 'default'}
执行中...

        执行结果
┏━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ 指标     ┃ 值         ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━┩
│ 工作流   │ test       │
│ 状态     │ completed  │
│ 总步骤   │ 3          │
│ 成功     │ 3          │
│ 失败     │ 0          │
│ 耗时     │ 1234ms     │
│ Dry Run  │ 否         │
└──────────┴────────────┘

✓ 工作流执行成功
```

---

## 6. 端到端示例

### 6.1 抖音互动工作流

```yaml
name: douyin_engagement
description: "搜索关键词 → 评论高赞视频"
variables:
  keyword: "Python教程"
  min_likes: 100

steps:
  - adapter: douyin
    operation: login
    params: {}

  - adapter: douyin
    operation: search
    params:
      keyword: "{{keyword}}"
      count: 20

  - adapter: douyin
    operation: comment
    loop_over: "{{douyin.search.results}}"
    loop_var: video
    params:
      target_url: "{{video.url}}"
      content: "太棒了！学到了很多🔥"
    condition: "{{video.metrics.likes}} > {{min_likes}}"
```

### 6.2 多平台工作流

```yaml
name: multi_platform_research
description: "双平台内容调研"
variables:
  keyword: "AI绘画"

steps:
  - adapter: douyin
    operation: search
    params: {keyword: "{{keyword}}", count: 10}

  - adapter: xiaohongshu
    operation: search
    params: {keyword: "{{keyword}}", count: 10}

  - action: log.info
    params:
      message: "抖音: {{douyin.search.count}} 条, 小红书: {{xiaohongshu.search.count}} 条"
    depends_on: [douyin.search, xiaohongshu.search]
```

---

## 7. 架构图

```
┌──────────────────────────────────────────────┐
│              CLI (superclaw run)              │
│    typer + rich (进度条/表格/颜色)            │
├──────────────────────────────────────────────┤
│           WorkflowRunner                      │
│  ├── YAML 解析 (WorkflowParser)              │
│  ├── 变量解析 ({{var}} / ${var})             │
│  ├── DAG 调度 (拓扑排序 + 并行)              │
│  ├── 循环展开                                 │
│  └── 条件评估                                 │
├──────────┬───────────────────────────────────┤
│ Adapter  │         DAG Engine                │
│ Registry │  (兼容 Action 操作)               │
├──────────┼───────────────────────────────────┤
│ Douyin   │  LogAction                       │
│ XHS      │  DelayAction                     │
│ (更多...) │  ConditionAction                 │
│          │  SetVarAction / GetVarAction      │
│          │  HttpGet / HttpPost               │
│          │  TransformAction                  │
├──────────┴───────────────────────────────────┤
│            ContextManager                    │
│  (变量存储 + 模板解析 + 节点输出)             │
├──────────────────────────────────────────────┤
│        Anti-Detect Layer                     │
│  StealthMiddleware + BehaviorSimulator       │
│  FingerprintManager + ProxyPool             │
└──────────────────────────────────────────────┘
```

---

## 8. 测试覆盖

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|----------|
| TestWorkflowSchema | 13 | Definition/Step/ID生成/DAG验证/拓扑排序/并行分组 |
| TestWorkflowParser | 14 | 字符串解析/文件解析/变量/重试/条件/错误处理 |
| TestWorkflowRunner | 9 | 初始化/Dry-run/无效工作流/变量/条件评估 |
| **合计** | **36** | |

---

## 9. 四个阶段总结

| 阶段 | 产出 | 核心内容 |
|------|------|----------|
| Phase 1 | 框架调研 + 代码分析 | RPAFramework/TagUI/Robot Framework 对比 |
| Phase 2 | RPA 引擎核心 | Action 注册/DAG 执行/上下文管理/异常处理 |
| Phase 3 | 平台适配器 | 抖音/小红书适配器 + 反检测集成 |
| Phase 4 | Workflow 引擎 + CLI | YAML 解析/工作流执行器/CLI 集成 |

### 完整模块清单

```
src/rpa/
  ├── interfaces.py          # Action 基类 + 接口定义
  ├── models.py              # 数据模型 (Pydantic)
  ├── engine.py              # WorkflowEngine 核心引擎
  ├── dag.py                 # DAG 执行器
  ├── context.py             # 上下文管理器
  ├── actions/               # 内置 Actions
  │   ├── __init__.py        # ActionRegistry
  │   └── builtin.py         # 8 个内置 Action
  ├── adapters/              # 平台适配器
  │   ├── __init__.py
  │   ├── base.py            # BaseAdapter + 数据模型
  │   ├── registry.py        # AdapterRegistry
  │   ├── douyin.py          # 抖音适配器
  │   ├── douyin_config.py
  │   ├── xiaohongshu.py     # 小红书适配器
  │   └── xiaohongshu_config.py
  ├── workflow/              # YAML 工作流
  │   ├── __init__.py
  │   ├── schema.py          # WorkflowStep/WorkflowDefinition
  │   ├── parser.py          # YAML 解析器
  │   └── runner.py          # 工作流执行器
  ├── anti_detect/           # 反检测层
  │   ├── stealth.py
  │   ├── behavior.py
  │   ├── fingerprint.py
  │   ├── proxy_manager.py
  │   └── captcha_adapter.py
  ├── account/               # 账号管理
  ├── monitoring/            # 监控告警
  └── cli/                   # 命令行
      └── commands/run.py    # 已集成 WorkflowRunner
```

---

## 10. 后续优化方向

1. **并行执行真异步**: 当前用 `asyncio.gather`，可加入 `Semaphore` 控制并发度
2. **条件分支隔离**: 条件为 false 时跳过后续依赖节点
3. **子流程支持**: `action: subprocess` 调用另一个 YAML 工作流
4. **可视化编辑器**: 基于 DAG 的流程图编辑器
5. **工作流版本管理**: Git 集成 + 回滚能力
6. **执行历史持久化**: SQLite/PostgreSQL 存储运行记录
7. **Web Dashboard**: 实时监控工作流执行状态

---

<!-- TASK_COMPLETE: phase4_workflow -->
