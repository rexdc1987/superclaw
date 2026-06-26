# 红果模块集成测试报告

**测试人:** 诸葛亮（军师）  
**测试时间:** 2026-06-23 15:39 ~ 15:55  
**测试依据:** task_zhuge_hongguo_test.md  
**关联BUG报告:** hongguo_bug_report.md（马超发现）

---

## 一、测试环境

| 项目 | 值 |
|------|-----|
| MySQL | 127.0.0.1:3308 (IPv6 ::1) |
| 数据库 | superclaw |
| Python | 3.8 (venv) |
| API端口 | 8002 |
| 前端 | frontend/src (Vue3 + Element Plus) + hongguo.html (内嵌模板) |

---

## 二、API端点测试结果

| # | 端点 | 方法 | 结果 | 说明 |
|---|------|------|------|------|
| 1 | /api/v1/hongguo/tasks | GET | ✅ PASS | 正常返回任务列表 |
| 2 | /api/v1/hongguo/tasks | POST | ❌ FAIL | 500 - `Unknown column 'task_name'` |
| 3 | /api/v1/hongguo/tasks/{id} | GET | ✅ PASS | 正常返回任务详情 |
| 4 | /api/v1/hongguo/tasks/{id} | PUT | ❌ FAIL | 500 - `_insert_log`中`episode_number`列不存在 |
| 5 | /api/v1/hongguo/tasks/{id}/start | GET | ⚠️ PASS* | 返回200但未实际改变DB状态（引擎未连接模拟器） |
| 6 | /api/v1/hongguo/tasks/{id}/pause | POST | ⚠️ PASS* | 返回200，error_message残留旧BUG信息 |
| 7 | /api/v1/hongguo/tasks/{id}/resume | POST | ⚠️ PASS* | 返回200，但需engine已pause才有效 |
| 8 | /api/v1/hongguo/tasks/{id}/stop | POST | ✅ PASS | 正常停止 |
| 9 | /api/v1/hongguo/tasks/{id}/records | GET | ✅ PASS | 正常返回空列表 |
| 10 | /api/v1/hongguo/tasks/{id}/logs | GET | ✅ PASS | 正常返回空列表 |

**通过率:** 6/10 (60%)，2个致命BUG导致核心功能不可用

---

## 三、ORM字段验证（BUG-001/002/003确认）

### 3.1 数据库实际Schema

**hongguo_comment_tasks:**
```
id, drama_name, comment_mode, start_episode, episode_interval, comment_interval_sec,
random_comment_count, random_min_interval, random_max_interval, content_source,
templates_json, status, current_episode, total_episodes, comments_sent, comments_verified,
error_message, started_at, completed_at, duration_seconds, created_at, updated_at
```

**hongguo_execution_logs:**
```
id, task_id, level, message, screenshot_path, created_at
```

### 3.2 字段不匹配清单

| BUG | 代码中使用 | 数据库实际 | 严重性 |
|-----|-----------|-----------|--------|
| BUG-001 | `comment_success_count` (engine.py L92, L317) | `comments_sent` | 🔴 致命 |
| BUG-001 | `comment_fail_count` (engine.py L93, L317) | `comments_verified` | 🔴 致命 |
| BUG-002 | `task_name` (routes_hongguo.py INSERT) | ❌ 不存在 | 🔴 致命 |
| BUG-002 | `comment_success_count` (routes_hongguo.py TaskUpdate) | ❌ 不存在 | 🔴 致命 |
| BUG-002 | `comment_fail_count` (routes_hongguo.py TaskUpdate) | ❌ 不存在 | 🔴 致命 |
| BUG-003 | `episode_number` (routes_hongguo.py `_insert_log`) | ❌ 不存在 | 🔴 致命 |

**结论:** BUG-001/002/003 **全部确认真实存在**，且影响范围比马超报告的更广。

---

## 四、前端代码验证

### 4.1 api/hongguo.js — BUG-004确认

```javascript
// 现有导出：
export const createTask, getTasks, getTask, updateTask, deleteTask
export const startTask, pauseTask, stopTask
export const getRecords, getLogs, getTemplates, createTemplate, deleteTemplate

// ❌ 缺失：resumeTask
```

**结论:** `resumeTask` 函数 **确实缺失**，BUG-004确认。

### 4.2 TaskExecute.vue — BUG-004/006确认

```html
<!-- 只有3个按钮：开启、暂停、停止 -->
<el-button @click="handleStart">开启</el-button>
<el-button @click="handlePause">暂停</el-button>
<el-button @click="handleStop">停止</el-button>
<!-- ❌ 缺失：恢复按钮 -->
```

```javascript
// statusText 缺少 waiting_login 和 paused
const statusText = (s) => ({ 
  pending: '待执行', running: '执行中', completed: '已完成', 
  failed: '失败', stopped: '已停止' 
}[s] || s)
// ❌ waiting_login 会显示为原始值 "waiting_login"
// ❌ paused 会显示为原始值 "paused"
```

**结论:** BUG-004（resume按钮缺失）和 BUG-006（waiting_login前端未映射）**均确认**。

### 4.3 hongguo.html（Dashboard内嵌模板）

```javascript
// ✅ 已有 waiting_login 映射
waiting_login: { label: "等待登录", type: "warning" },
// ✅ 已有恢复按钮
<el-button @click="runAction(row, 'resume')">恢复</el-button>
```

**注意:** Dashboard模板（hongguo.html）已修复，但 Vue组件（TaskExecute.vue）未同步修复。

---

## 五、状态流转校验（ISSUE-001确认）

| 操作 | 当前状态要求 | 实际校验 | 结果 |
|------|-------------|---------|------|
| start | pending/paused/stopped | ❌ 无校验，仅检查engine是否alive | 任何状态均可start |
| pause | running | ❌ 无校验 | 非running也可pause |
| resume | paused | ❌ 无校验 | 非paused也可resume |
| stop | running/paused | ❌ 无校验 | 任何状态均可stop |

**结论:** ISSUE-001 **确认**，状态机完全无保护。

---

## 六、测试覆盖（ISSUE-004确认）

- `tests/` 目录下无 hongguo 相关测试文件
- 无单元测试、无集成测试

**结论:** ISSUE-004 **确认**。

---

## 七、BUG汇总与优先级

| 编号 | 描述 | 状态 | 优先级 | 影响 |
|------|------|------|--------|------|
| BUG-001 | ORM字段名`comment_success_count`/`comment_fail_count`与DB不匹配 | ✅ 确认 | P0 | 任务执行时更新失败 |
| BUG-002 | API routes INSERT/UPDATE使用不存在字段`task_name`等 | ✅ 确认 | P0 | 创建任务、更新任务均500 |
| BUG-003 | `_insert_log`使用不存在字段`episode_number` | ✅ 确认 | P0 | 所有写日志操作失败 |
| BUG-004 | 前端api/hongguo.js缺少resumeTask，TaskExecute.vue缺恢复按钮 | ✅ 确认 | P1 | 无法从前端恢复暂停任务 |
| BUG-006 | TaskExecute.vue的statusText缺少waiting_login和paused | ✅ 确认 | P2 | 状态显示为原始值 |
| ISSUE-001 | 状态流转无校验 | ✅ 确认 | P1 | 可能导致数据不一致 |
| ISSUE-004 | 测试覆盖不足 | ✅ 确认 | P2 | 回归风险高 |

---

## 八、修复建议

### P0 立即修复
1. **统一字段名:** 将engine.py中的`comment_success_count`/`comment_fail_count`改为`comments_sent`/`comments_verified`
2. **移除`task_name`:** 从INSERT语句中移除，或在DB中添加该列
3. **移除`episode_number`:** 从`_insert_log`的INSERT中移除，或在DB中添加该列
4. **清理TaskUpdate:** 移除`comment_success_count`/`comment_fail_count`字段

### P1 尽快修复
5. **添加resumeTask:** 在`api/hongguo.js`中添加`export const resumeTask = (id) => api.post('/tasks/' + id + '/resume')`
6. **添加恢复按钮:** 在`TaskExecute.vue`中添加resume按钮和handleResume函数
7. **状态校验:** 在engine的start/pause/resume/stop方法中添加前置状态检查

### P2 后续优化
8. **同步状态映射:** 确保TaskExecute.vue的statusText包含所有状态
9. **补充测试:** 为hongguo模块编写单元测试和集成测试

---

## 九、结论

马超发现的BUG **全部确认真实存在**，且问题范围更广：
- **3个P0致命BUG** 导致创建任务、更新任务、任务执行日志写入全部失败
- **2个P1功能缺失** 导致前端无法恢复暂停任务
- **1个P1设计缺陷** 状态机无保护
- **1个P2显示问题** 状态文本不完整

**建议:** 立即修复P0问题，否则红果评论模块的核心功能完全不可用。
