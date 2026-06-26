# 诸葛亮 Phase 3 学习笔记 — 监控 + 告警 + Dashboard

> 学习人：诸葛亮 | 日期：2026-06-20
> 任务来源：曹操派发

---

## 1. 产出清单

| 产出 | 文件 | 说明 |
|------|------|------|
| 增强指标采集器 | `src/rpa/monitoring/metrics.py` | 新增平台维度、账号健康度、系统指标 |
| 简易通道 | `src/rpa/monitoring/simple_channels.py` | Console + File 通道 |
| Dashboard 应用 | `src/rpa/dashboard/app.py` | FastAPI，4 个路由 |
| Dashboard 模板 | `src/rpa/dashboard/templates/overview.html` | 概览页面（纯 HTML/CSS） |
| 测试 | `tests/test_monitoring.py` | 22 个用例 |
| **测试结果** | **22/22 passed** | **0.95s** |

---

## 2. 指标采集系统设计

### 指标分层

```
任务级指标（每次执行记录）
  ↓ 聚合
平台级指标（按 douyin/weibo 等分组统计）
  ↓ 聚合
账号级指标（每个账号的健康度评分）
  ↓ 聚合
系统级指标（CPU/内存/运行时间/浏览器实例数）
```

### 数据结构

- **TaskMetric**：单次任务记录（task_type, success, duration, platform, account_id, error_type）
- **PlatformStats**：平台维度聚合（total, success, failure, avg_duration）
- **deque 时间序列**：保留最近 1000 条记录，自动淘汰旧数据

### 降级策略

- 有 `prometheus_client`：使用 Counter/Gauge/Histogram
- 无 `prometheus_client`：自动切换 `_StubMetric`（内存计数器），API 兼容

---

## 3. 告警引擎设计

### 告警规则

```python
AlertRule(
    name="成功率下降",
    condition="success_rate",    # 指标名
    threshold=0.8,               # 阈值
    operator="lt",               # 比较运算符：lt/le/gt/ge/eq
    channels=[console, file],    # 推送通道
    cooldown=300,                # 冷却时间（防风暴）
)
```

### 告警状态机

```
规则评估 → 阈值触发 → 冷却检查 → 生成 Alert → 推送通道 → 记录历史
```

### 防风暴机制

- **冷却期**：同一规则在 cooldown 秒内不重复触发
- **评估频率**：由调用方控制（如每 30 秒评估一次）

### 通道扩展

已实现：ConsoleChannel（控制台）、FileChannel（文件）
已预留：WebhookChannel（飞书/钉钉/Slack，channels/ 包中已有 feishu_channel.py）

---

## 4. Dashboard 架构

### 路由设计

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 概览 HTML 页面 |
| `/api/metrics` | GET | JSON 指标 |
| `/api/alerts` | GET | 告警历史 |
| `/api/platforms` | GET | 平台统计 |
| `/api/health` | GET | 健康检查 |

### 技术选型

- **FastAPI**：异步、自动 OpenAPI 文档、类型安全
- **Jinja2**：服务端渲染，无需前端框架
- **纯 CSS**：无外部依赖，grid 布局，响应式

### 依赖注入

Dashboard 通过 `init_dashboard(collector, alert_engine)` 接收外部实例，解耦监控模块。

---

## 5. 踩坑记录

1. **channels 包冲突**：项目已有 `monitoring/channels/` 包（含 feishu_channel.py），不能再创建同名 `channels.py`。解决方案：新建 `simple_channels.py` 放 Console/File 通道。
2. **structlog 依赖**：已有 channels/__init__.py 使用 structlog，需安装。
3. **Python 3.8 类型提示**：已有代码中 `list[str]` 等写法会报错，需用 `List[str]`。
4. **f-string 多行**：已有 channels/__init__.py 的 `to_text()` 方法中 f-string 换行写法有语法错误，已修复。

---

<!-- TASK_COMPLETE: phase3_monitoring -->
