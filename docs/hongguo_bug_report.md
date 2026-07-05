# 红果评论模块 BUG 检查报告

**检查人**: 马超  
**检查时间**: 2026-06-23 15:35  
**检查范围**: 后端API、数据库模型、前端代码、测试文件  

---

## 测试结果

```
✅ test_hongguo_api.py — FastAPI 路由注册正常（13个路由）
✅ test_hongguo_models.py — 模型导入正常，字段可读写
⚠️ 注意：测试仅验证导入，未覆盖实际 API 调用和数据库操作
```

---

## 严重问题 (BUG)

### BUG-001: ORM 模型字段名与实际数据库列名严重不匹配
**文件**: `src/models/hongguo_task.py` vs `src/rpa/dashboard/routes_hongguo.py`  
**影响**: 后端 API 写入的列名在数据库中可能不存在，导致运行时 SQL 报错  

| API 使用列名 | ORM 模型字段名 | 说明 |
|---|---|---|
| `templates` (TEXT) | `templates_json` | 名称不一致 |
| `comment_success_count` | `comments_sent` | 名称不一致 |
| `comment_fail_count` | `comments_verified` | 名称不一致 |

**结论**: API 和 ORM 模型描述的是同一张表但用了不同列名。如果数据库 schema 以 ORM 为准，则 API 的 UPDATE/INSERT 语句会写入不存在的列；反之亦然。**必须统一。**

---

### BUG-002: ORM 模型字段名与数据库列名不匹配（记录表）
**文件**: `src/models/hongguo_record.py` vs `engine.py`  

| API/Engine 使用列名 | ORM 模型字段名 |
|---|---|
| `comment_content` | `comment_text` |
| `content_source` | `generated_by` |

Engine 的 `_save_record` 方法 INSERT `comment_content` 和 `content_source`，但 ORM 定义的是 `comment_text` 和 `generated_by`。如果数据库 schema 与 ORM 一致，Engine 的 INSERT 会失败。

---

### BUG-003: ORM 模型缺少 `episode_number` 字段（日志表）
**文件**: `src/models/hongguo_log.py` vs `engine.py` / `routes_hongguo.py`  
**影响**: API 和 Engine 都 INSERT `episode_number` 列，但 ORM 模型未定义此字段  

```python
# routes_hongguo.py 和 engine.py 都执行：
INSERT INTO hongguo_execution_logs (task_id, level, message, episode_number) ...
# 但 ORM 模型只有 id, task_id, level, message, screenshot_path, created_at
```

如果数据库表没有 `episode_number` 列，所有带集数的日志写入都会失败。

---

### BUG-004: `resume` 功能后端可用但前端未暴露
**文件**: `frontend/src/api/hongguo.js` / `frontend/src/views/TaskExecute.vue`  
**影响**: 任务暂停后无法通过 UI 恢复执行  

后端有 `POST /tasks/{task_id}/resume`，但：
- `api/hongguo.js` 未导出 `resumeTask` 函数
- `TaskExecute.vue` 只有「开启」按钮（disabled when running），没有「恢复」按钮
- 暂停后的任务只能通过 API 手动调用 resume

---

### BUG-005: `stop_task` 端点存在死代码 / 无返回值路径
**文件**: `src/rpa/dashboard/routes_hongguo.py`  

```python
@router.post("/tasks/{task_id}/stop")
async def stop_task(task_id: int):
    with _connection() as conn:
        _fetch_one_or_404(conn, task_id)
    if not _engine_manager().stop_task(task_id):
        return _set_task_status(task_id, "stopped", "任务已停止")
    with _connection() as conn:          # <-- 如果 stop_task 返回 True，这里会打开新连接
        return _serialize_task(_fetch_one_or_404(conn, task_id))
```

当 engine 的 `stop()` 返回 `True`（正常停止），会再开一个连接查询并返回。但 `_set_task_status` 已经设置了 status 并写日志。两条路径都 work，但逻辑冗余且每次 stop 都打开 2 个连接。

---

### BUG-006: `waiting_login` 状态前端未处理
**文件**: `frontend/src/views/TaskList.vue` / `TaskExecute.vue`  
**影响**: 等待登录状态下状态标签显示为原始文本  

后端 `TASK_STATUSES` 包含 `waiting_login`，Engine 在等待登录时会设置此状态。但前端 `statusType` 和 `statusText` 映射中没有 `waiting_login`，会 fallback 到默认样式和原始字符串。

---

### BUG-007: 截图路径跨平台兼容问题
**文件**: `src/rpa/dashboard/routes_hongguo.py` → `_latest_screenshot_file`  
**影响**: Windows 环境下截图可能无法正常显示  

```python
def _latest_screenshot_file(task_id: int) -> Optional[str]:
    # ... 
    return str(max(files, key=lambda path: path.stat().st_mtime).as_posix())
    # 返回 POSIX 格式路径，如 E:/Projects/...
```

`screenshot_image` 端点中：
```python
if not latest or not Path(latest).exists():
```
`Path` 在 Windows 上接受 POSIX 路径，但 `FileResponse` 可能会有问题。此外，Engine 的 `_latest_screenshot_file` 和 routes 的是同一个函数，但截图目录硬编码为 `E:/Projects/SuperClaw/screenshots/hongguo`，如果路径不存在会静默返回 None。

---

## 一般问题 (ISSUE)

### ISSUE-001: API `update_task` 端点允许任意状态流转
**文件**: `routes_hongguo.py` → `update_task`  
**风险**: 中  

`TaskUpdate` 模型允许直接设置 `status` 为任意合法值。恶意请求可以：
- 将 `completed` 的任务直接设为 `running`（绕过 Engine）
- 将 `failed` 的任务设为 `completed`

建议：只允许特定状态转换（如 pending→running, running→paused 等）。

---

### ISSUE-002: `start_task` 不验证任务当前状态
**文件**: `routes_hongguo.py` → `start_task`  
**风险**: 低  

直接调用 `engine.start_task()` 而不先检查任务是否在 `pending` 状态。已完成或失败的任务可以被重新启动。

---

### ISSUE-003: Engine 未验证任务当前状态即开始执行
**文件**: `src/rpa/hongguo/engine.py` → `TaskEngine._run`  
**风险**: 低  

Engine 启动后直接更新 status 为 `running`，不管之前是什么状态。如果任务已经是 `completed`，会覆盖状态。

---

### ISSUE-004: 测试覆盖严重不足
**文件**: `tests/test_hongguo_api.py`, `tests/test_hongguo_models.py`  
**风险**: 高（维护性）  

当前测试仅验证导入和基本实例化，未覆盖：
- API 端点的 HTTP 请求测试
- 数据库 CRUD 操作
- 状态流转逻辑
- Engine 的线程行为
- 前后端接口一致性

---

### ISSUE-005: `comment_interval_sec` 允许为 0
**文件**: `routes_hongguo.py` → `TaskBase`  
**风险**: 低  

`comment_interval_sec: int = Field(default=30, ge=0)` 允许设置为 0，可能导致评论发送过于频繁被风控。

---

### ISSUE-006: Engine `_log` 和 `_update_task` 异常被静默吞掉
**文件**: `src/rpa/hongguo/engine.py`  
**风险**: 低  

```python
def _log(self, level, message, episode=None):
    try:
        # ... INSERT ...
    except Exception:
        pass  # 完全吞掉异常
```

日志写入失败不会有任何提示，可能导致问题难以排查。

---

### ISSUE-007: `check_login` 端点硬编码设备地址
**文件**: `routes_hongguo.py` → `check_login`  
**风险**: 低  

```python
device = connect("127.0.0.1:7555")  # 硬编码
```

而 Engine 的 `TaskEngine` 接受 `device_addr` 参数。多设备场景下此端点无法适配。

---

### ISSUE-008: 模板 API 缺少 `getTemplate` 和 `updateTemplate` 的前端调用
**文件**: `frontend/src/api/hongguo.js`  
**风险**: 低  

API 层有 `GET /templates/{id}` 和 `PUT /templates/{id}`，但前端只用了 list/create/delete，缺少单个查询和更新功能。

---

### ISSUE-009: `_set_task_status` 每次调用打开 2 个数据库连接
**文件**: `routes_hongguo.py`  
**风险**: 低（性能）  

`_set_task_status` 内部调用 `_connection()` 一次做 UPDATE + log，然后外层又调用 `_connection()` 做 SELECT。同一个操作用了 2 个连接，可以合并。

---

### ISSUE-010: `task_name` 默认值可能为空字符串
**文件**: `routes_hongguo.py` → `create_task`  

```python
task_name = payload.task_name or f"{payload.drama_name}评论任务"
```

如果前端传 `task_name: ""`，`or` 会触发默认值。但如果传 `task_name: " "`（空格），strip 后为空但 `or` 不触发，导致 `task_name` 为空格字符串。Pydantic validator 虽然做了 strip 但没检查空。

---

## 总结

| 类别 | 数量 |
|---|---|
| 严重 BUG | 7 |
| 一般问题 | 10 |
| 测试通过 | 2/2（仅导入测试） |

### 最高优先级修复建议

1. **BUG-001/002/003** — 统一 ORM 模型与数据库 schema 的字段名，建议以实际数据库表为准修正 ORM
2. **BUG-004** — 前端补充 resume 功能（API 函数 + UI 按钮）
3. **BUG-006** — 前端补充 `waiting_login` 状态映射
4. **ISSUE-001** — 添加状态流转校验，防止非法状态跳转
5. **ISSUE-004** — 补充 API 集成测试和状态机单元测试
