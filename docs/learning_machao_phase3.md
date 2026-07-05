# 马超 Phase 3 学习笔记 — 平台适配器实现

> 作者：马超 | 日期：2026-06-20  
> 状态：学习完成

---

## 1. 任务完成情况

| 任务 | 产出文件 | 状态 |
|------|----------|------|
| Task 1: 抖音适配器 | `src/rpa/adapters/douyin.py` + `douyin_config.py` | ✅ |
| Task 2: 小红书适配器 | `src/rpa/adapters/xiaohongshu.py` + `xiaohongshu_config.py` | ✅ |
| Task 3: 集成测试 | `tests/test_adapter_integration.py` (38 tests, all pass) | ✅ |
| Task 4: 学习笔记 | 本文档 | ✅ |

---

## 2. 适配器架构设计

### 2.1 整体架构

```
src/rpa/adapters/
  ├── __init__.py              # 模块导出
  ├── base.py                  # BaseAdapter 抽象基类 + 数据模型 + 错误类型
  ├── registry.py              # AdapterRegistry 适配器注册中心
  ├── douyin.py                # 抖音适配器实现
  ├── douyin_config.py         # 抖音配置（Pydantic）
  ├── xiaohongshu.py           # 小红书适配器实现
  └── xiaohongshu_config.py    # 小红书配置（Pydantic）
```

### 2.2 核心设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 浏览器引擎 | Playwright | 与反检测模块一致，async 原生支持 |
| 配置管理 | Pydantic BaseModel | 类型安全，支持默认值和验证 |
| 数据模型 | Pydantic BaseModel | ContentItem/UserInfo/CommentItem 统一格式 |
| 错误体系 | 分级异常类 | CaptchaDetected/RateLimited/AccountBanned 便于上层处理 |
| 注册机制 | 平台名 -> 类映射 | 简单高效，支持动态发现 |

### 2.3 BaseAdapter 接口

```python
class BaseAdapter(ABC):
    platform: str = ""
    
    # 生命周期
    async def setup(context=None)    # 初始化
    async def teardown()             # 清理
    
    # 核心操作（必须实现）
    async def login(credentials) -> AdapterResult
    async def check_login() -> bool
    async def search_content(keyword, count) -> AdapterResult
    async def post_comment(target_url, content) -> AdapterResult
    async def like_content(target_url) -> AdapterResult
    async def follow_user(user_url) -> AdapterResult
    
    # 可选操作
    async def get_comments(...) -> AdapterResult
    async def get_user_info(...) -> AdapterResult
    async def send_dm(...) -> AdapterResult
```

---

## 3. 抖音适配器实现细节

### 3.1 5个核心操作

| 操作 | 实现要点 |
|------|----------|
| **login** | Cookie 优先 → 手动登录兜底（等待120秒） |
| **search_content** | URL 搜索 → 滚动加载 → CSS 选择器提取卡片 |
| **post_comment** | 定位输入框 → 行为模拟打字 → 鼠标轨迹移动 → 点击提交 |
| **like_content** | 定位点赞按钮 → 点击 |
| **follow_user** | 定位关注按钮 → 检查"已关注"状态 → 点击 |

### 3.2 反检测集成

- **StealthMiddleware**: 注入 CDP 脚本隐藏 webdriver 标志
- **BehaviorSimulator**: 贝塞尔鼠标轨迹 + 变速打字 + 随机延迟
- **页面状态检测**: 每次操作后检查验证码/频率限制/封禁

### 3.3 CSS 选择器配置化

所有选择器集中在 `DouyinConfig.selectors` 字典中，平台改版时只需修改配置，不需要改代码：

```python
selectors = {
    "search_input": '[class*="search"] input',
    "video_card": '[class*="video-card"]',
    "comment_input": '[class*="comment-input"], textarea',
    ...
}
```

---

## 4. 小红书适配器实现细节

### 4.1 与抖音的差异

| 方面 | 抖音 | 小红书 |
|------|------|--------|
| 搜索 URL | `/search/{keyword}?type=video` | `/search_result?keyword={keyword}` |
| 内容类型 | 视频 | 笔记（图文+视频） |
| 特有操作 | - | **收藏笔记** (collect_note) |
| 选择器 | video-card | note-item |
| 评论长度限制 | 100字 | 200字 |
| 评论模板风格 | 简短有力 | 种草风格（📌表情） |

### 4.2 小红书特有功能

- **收藏笔记**: `collect_note()` 操作，点击收藏按钮
- **图片提取**: 搜索结果中提取封面图 URL
- **种草风格评论**: 模板更贴近小红书社区氛围

---

## 5. 错误处理机制

### 5.1 三级检测

每次页面操作后，`_check_page_status()` 按优先级检测：

1. **验证码** (CAPTCHA) — 最高优先级
2. **账号封禁** (ACCOUNT_BANNED) — 次高优先级
3. **频率限制** (RATE_LIMITED) — 最低优先级

### 5.2 错误类型体系

```
AdapterError (基类)
  ├── CaptchaDetected     # 验证码
  ├── RateLimited         # 频率限制
  └── AccountBanned       # 账号封禁
```

上层调用方可以通过 `try/except` 精确捕获不同类型的错误：

```python
try:
    result = await adapter.post_comment(url, content)
except CaptchaDetected:
    # 等待手动解决或调用验证码服务
except AccountBanned:
    # 切换账号
except RateLimited:
    # 等待后重试
```

---

## 6. DAG 集成模式

### 6.1 适配器作为 Action

适配器操作可以通过 Action 封装接入 DAG 引擎：

```yaml
nodes:
  - id: search
    action: adapter.search
    params:
      platform: douyin
      keyword: "Python教程"
      count: 10
  
  - id: comment
    action: adapter.comment
    params:
      platform: douyin
      target_url: "{{search.url}}"
      content: "好内容！"
    depends_on: [search]
```

### 6.2 多平台工作流

```yaml
nodes:
  - id: search_dy
    action: adapter.search
    params: { platform: douyin, keyword: "AI" }
  
  - id: search_xhs
    action: adapter.search
    params: { platform: xiaohongshu, keyword: "AI" }
    depends_on: [search_dy]
  
  - id: report
    action: log.info
    params: { message: "搜索完成" }
    depends_on: [search_dy, search_xhs]
```

### 6.3 错误恢复工作流

```yaml
nodes:
  - id: risky_action
    action: adapter.comment
    retry:
      max_attempts: 3
      delay_seconds: 5
      backoff_multiplier: 2.0
    fallback_action: log.info
```

---

## 7. 测试覆盖

### 7.1 测试矩阵

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|----------|
| TestDataModels | 6 | ContentItem/UserInfo/CommentItem/AdapterResult |
| TestAdapterErrors | 3 | CaptchaDetected/RateLimited/AccountBanned |
| TestAdapterRegistry | 6 | 注册/创建/列表/发现/全局实例 |
| TestConfigs | 4 | 默认值/自定义配置 |
| TestDouyinAdapterMocked | 8 | 平台名/配置/检测方法/Mock浏览器操作 |
| TestXiaohongshuAdapterMocked | 5 | 平台名/配置/评论模板/Setup |
| TestAdapterDAGIntegration | 5 | DAG工作流/多平台/错误处理/注册中心/上下文传递 |
| **合计** | **38** | |

### 7.2 Mock 策略

由于 Playwright 浏览器在测试环境中不可用，采用 Mock 策略：
- `AsyncMock` 模拟 page 和 context
- 直接测试适配器的配置加载、错误检测、工具方法
- DAG 集成测试验证工作流定义的正确性

---

## 8. 平台差异对比

| 特性 | 抖音 | 小红书 |
|------|------|--------|
| 基础 URL | douyin.com | xiaohongshu.com |
| 搜索参数 | `/search/{kw}?type=video` | `/search_result?keyword={kw}` |
| 视口尺寸 | 1920x1080 | 1440x900 |
| 操作间隔 | [2-5s] | [2-5s] |
| 评论间隔 | [10-30s] | [15-45s] |
| 评论上限 | 100字 | 200字 |
| 收藏功能 | ❌ | ✅ |
| 评论模板风格 | 简洁 | 种草风+emoji |

---

## 9. 后续优化方向

1. **Cookie 持久化**: 将登录态保存到文件，避免每次手动登录
2. **验证码自动处理**: 集成 CaptchaAdapter（已有 TwoCaptchaSolver）
3. **代理轮换**: 集成 ProxyPool 实现代理切换
4. **操作录制**: 录制人类操作序列，回放时更自然
5. **更多平台**: B站、快手、微博等适配器
6. **DrissionPage 后端**: 作为 Playwright 的备选方案

---

<!-- TASK_COMPLETE: phase3_adapters -->
