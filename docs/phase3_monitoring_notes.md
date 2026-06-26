# SuperClaw 第三阶段 — 监控与告警系统学习笔记

> 作者：诸葛亮（agent）| 日期：2026-06-18

---

## 一、监控系统概述

### 1.1 为什么 RPA 需要监控？

RPA 系统在无人值守环境下运行，面临以下挑战：
- **任务失败**：目标网站改版、网络超时、验证码触发
- **账号异常**：被封禁、被限制、健康度下降
- **性能退化**：响应变慢、队列积压、资源耗尽
- **代理失效**：IP 被封、延迟飙升

监控系统的作用是：**实时感知 → 及时告警 → 快速定位 → 恢复服务**。

### 1.2 监控指标体系

| 指标类别 | 指标名 | 类型 | 说明 |
|----------|--------|------|------|
| 任务指标 | task_success_total | Counter | 成功任务数 |
| | task_failure_total | Counter | 失败任务数 |
| | task_duration_seconds | Histogram | 任务耗时分布 |
| | captcha_triggered_total | Counter | 验证码触发次数 |
| 资源指标 | active_accounts | Gauge | 活跃账号数 |
| | queue_depth | Gauge | 任务队列深度 |
| 业务指标 | success_rate | Gauge | 成功率 |

---

## 二、Prometheus 指标采集

### 2.1 Prometheus 四种指标类型

**Counter（计数器）**
- 只增不减，适合累计值
- 如：任务成功次数、失败次数
- 查询用 `rate()` 获取速率

**Gauge（仪表盘）**
- 可增可减，适合当前值
- 如：活跃账号数、队列深度
- 直接查询当前值

**Histogram（直方图）**
- 按区间统计分布
- 如：任务耗时分布（0-0.5s、0.5-1s、1-2s...）
- 自动生成 `_bucket`、`_sum`、`_count`

**Summary（摘要）**
- 客户端计算分位数
- 如：P50、P95、P99 延迟
- 不太适合聚合，Histogram 更灵活

### 2.2 Python prometheus_client 使用

```python
from prometheus_client import Counter, Gauge, Histogram, start_http_server

# 定义指标
TASK_SUCCESS = Counter('task_success_total', '成功任务数', ['task_type'])
TASK_DURATION = Histogram('task_duration_seconds', '任务耗时', ['task_type'])
ACTIVE_ACCOUNTS = Gauge('active_accounts', '活跃账号数')

# 使用
TASK_SUCCESS.labels(task_type='search').inc()
TASK_DURATION.labels(task_type='search').observe(2.5)
ACTIVE_ACCOUNTS.set(5)

# 暴露 /metrics 端口
start_http_server(8000)
```

### 2.3 PromQL 常用查询

```promql
# 成功率（5分钟窗口）
rate(task_success_total[5m]) / (rate(task_success_total[5m]) + rate(task_failure_total[5m]))

# P95 延迟
histogram_quantile(0.95, rate(task_duration_seconds_bucket[5m]))

# 每秒任务数
rate(task_success_total[1m])

# 验证码触发率
rate(captcha_triggered_total[5m])
```

---

## 三、告警系统设计

### 3.1 告警规则设计

| 规则名 | 条件 | 阈值 | 级别 | 说明 |
|--------|------|------|------|------|
| 成功率下降 | success_rate < 0.8 | 80% | WARNING | 5分钟窗口成功率低于80% |
| 任务积压 | queue_depth > 100 | 100 | WARNING | 队列积压超过100 |
| 严重积压 | queue_depth > 500 | 500 | CRITICAL | 队列积压超过500 |
| 账号异常 | active_accounts < 2 | 2 | CRITICAL | 可用账号不足 |
| 验证码风暴 | captcha rate > 0.5/s | 0.5 | WARNING | 验证码触发过于频繁 |

### 3.2 告警去重（冷却机制）

问题：同一个告警每分钟触发一次，会导致消息轰炸。

解决方案：**冷却时间**
- 每条规则有独立的冷却计时器
- 告警触发后，在冷却期内不再重复发送
- 默认冷却时间：5 分钟
- CRITICAL 级别可以设置更短的冷却时间

### 3.3 告警通道

| 通道 | 适用场景 | 优点 | 缺点 |
|------|----------|------|------|
| 飞书 Webhook | 团队协作 | 即时通知、富文本 | 需要飞书机器人 |
| 邮件 | 正式记录 | 持久化、可搜索 | 延迟高 |
| HTTP Webhook | 自动化处理 | 灵活、可集成 | 需要自建接收端 |

---

## 四、Grafana Dashboard 设计

### 4.1 核心面板

1. **任务成功率仪表盘** — Gauge 类型，红色 < 60%，橙色 60-80%，绿色 > 80%
2. **任务执行时长热力图** — Heatmap 类型，观察耗时分布变化
3. **成功/失败趋势** — TimeSeries 类型，两条曲线对比
4. **活跃账号数** — Stat 类型，实时数字
5. **队列深度** — Stat 类型，带阈值告警
6. **验证码触发计数** — Stat 类型
7. **告警历史** — Table 类型，展示最近告警

### 4.2 Dashboard JSON 结构

```json
{
  "panels": [
    {
      "title": "面板标题",
      "type": "gauge|timeseries|heatmap|stat|table",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "targets": [
        {"expr": "PromQL 表达式", "legendFormat": "图例"}
      ],
      "fieldConfig": {
        "defaults": {
          "thresholds": {
            "steps": [
              {"color": "red", "value": null},
              {"color": "green", "value": 0.8}
            ]
          }
        }
      }
    }
  ],
  "refresh": "10s",
  "time": {"from": "now-1h", "to": "now"}
}
```

### 4.3 导入方式

1. 打开 Grafana → Dashboards → Import
2. 上传 `grafana/dashboard.json`
3. 配置 Prometheus 数据源

---

## 五、日志系统

### 5.1 结构化日志

推荐使用 `structlog` 替代标准 `logging`：

```python
import structlog

logger = structlog.get_logger()
logger.info("task_completed", task_type="search", duration=2.5, account="user_001")
```

输出格式（JSON）：
```json
{"event": "task_completed", "task_type": "search", "duration": 2.5, "account": "user_001", "timestamp": "2026-06-18T20:00:00Z"}
```

### 5.2 日志级别使用规范

| 级别 | 场景 | 示例 |
|------|------|------|
| DEBUG | 开发调试 | 鼠标坐标、代理选择过程 |
| INFO | 正常运行 | 任务完成、代理切换 |
| WARNING | 需要关注 | 代理延迟高、账号健康度下降 |
| ERROR | 出现问题 | 任务失败、API 调用异常 |
| CRITICAL | 严重故障 | 所有代理不可用、数据库连接断开 |

---

## 六、集成架构

```
SuperClaw RPA 引擎
├── 任务执行层
│   ├── engine.py → 记录 task_success/failure
│   ├── anti_detect/ → 记录 captcha_triggered
│   └── account/ → 更新 active_accounts
├── 监控层
│   ├── MetricsCollector (metrics.py)
│   │   ├── prometheus_client 指标
│   │   └── /metrics HTTP 端点
│   └── AlertEngine (alert_engine.py)
│       ├── 规则评估
│       ├── 冷却去重
│       └── 多通道推送
│           ├── FeishuChannel
│           └── WebhookChannel
└── 可视化层
    └── Grafana Dashboard
        ├── 实时指标面板
        └── 告警历史
```

---

## 七、最佳实践

1. **指标命名规范**：`superclaw_` 前缀 + 小写下划线
2. **标签控制**：标签值不要有高基数（如 user_id），会导致内存爆炸
3. **告警分级**：WARNING 通知即可，CRITICAL 需要立即处理
4. **Dashboard 刷新**：10s 间隔，不要过于频繁
5. **日志与指标互补**：指标看趋势，日志查细节

---

*学习完成，产出 5 个代码文件 + 1 个 Grafana 模板 + 本文档。*
