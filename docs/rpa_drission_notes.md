# RPA 第二阶段学习笔记 - DrissionPage 浏览器自动化

## 一、DrissionPage 概述

### 1.1 为什么选 DrissionPage？

| 特性 | DrissionPage | Playwright | Selenium |
|------|-------------|-----------|----------|
| 反检测能力 | ⭐⭐⭐⭐⭐ 原生强 | ⭐⭐⭐ 需插件 | ⭐⭐ 较弱 |
| 安装难度 | 极简 (pip install) | 中等 | 较复杂 |
| 浏览器控制 | 直接控制 Chromium | 自带浏览器 | 需 WebDriver |
| API 风格 | 简洁链式 | 现代 async | 传统 |
| 维护成本 | 低 | 中 | 高 |

**核心优势：DrissionPage 直接控制用户浏览器进程，不注入 WebDriver 标记，天然绕过大部分反爬检测。**

### 1.2 三种页面模式

```
ChromiumPage  → 控制浏览器（类似 Selenium，但更强）
SessionPage   → 纯 HTTP 请求（类似 httpx/requests）
WebPage       → 混合模式（自动切换浏览器和 HTTP）
```

| 模式 | 适用场景 | 特点 |
|------|---------|------|
| `ChromiumPage` | 需要 JS 渲染、复杂交互 | 控制真实浏览器 |
| `SessionPage` | 纯 API/HTML 抓取 | 轻量、快速 |
| `WebPage` | 混合场景 | 灵活切换 |

---

## 二、安装与基础用法

### 2.1 安装

```bash
pip install DrissionPage
```

DrissionPage 自带 Chromium 内核，无需额外安装浏览器。

### 2.2 ChromiumPage 基础

```python
from DrissionPage import ChromiumPage

# 启动浏览器（有头模式）
page = ChromiumPage()

# 访问网页
page.get("https://www.douyin.com")

# 获取标题
print(page.title)

# 获取页面 HTML
html = page.html

# 关闭
page.quit()
```

### 2.3 元素定位

```python
# CSS Selector（推荐）
elem = page.ele("css:.search-input")
elem = page.ele("css:#login-btn")

# XPath
elem = page.ele("xpath://div[@class='content']//a")

# 文本定位
elem = page.ele("text:登录")
elem = page.ele("text:包含关键字@@")  # 模糊匹配

# 属性定位
elem = page.ele("@name=username")
elem = page.ele("@data-testid=submit")

# 组合定位
elem = page.ele("css:button@@text()=提交")
```

### 2.4 元素操作

```python
# 点击
elem.click()

# 输入文字
elem.input("Hello World")

# 清空输入框
elem.clear()

# 获取文本
text = elem.text

# 获取属性
href = elem.attr("href")

# 判断元素是否存在
if page.ele("css:.error-msg"):
    print("出现错误")

# 等待元素出现
elem = page.ele("css:.loading", timeout=10)
```

### 2.5 链式操作

```python
# DrissionPage 支持链式调用
page.ele("css:.search-btn").click()
page.ele("css:.search-input").input("关键词")
page.ele("css:button@@type=submit").click()
```

---

## 三、Session 管理

### 3.1 Cookie 导入导出

```python
from DrissionPage import ChromiumPage

page = ChromiumPage()

# 导入 Cookie（字典格式）
cookies = [
    {"name": "sessionid", "value": "abc123", "domain": ".douyin.com"},
    {"name": "ttwid", "value": "xyz789", "domain": ".douyin.com"},
]
page.set.cookies(cookies)

# 导出所有 Cookie
all_cookies = page.cookies()
print(all_cookies)

# 清除 Cookie
page.cookies.clear()
```

### 3.2 复用浏览器登录状态

```python
# 方法1：指定用户数据目录（推荐）
page = ChromiumPage(user_data_path="C:/Users/user/AppData/Local/Google/Chrome/User Data")

# 方法2：先登录再保存 Cookie
page = ChromiumPage()
page.get("https://www.douyin.com")
# ... 手动或自动登录 ...
cookies = page.cookies()
# 保存到文件，下次导入
```

### 3.3 无头/有头模式

```python
# 有头模式（默认，可看到浏览器）
page = ChromiumPage()

# 无头模式（后台运行）
page = ChromiumPage(headless=True)
```

---

## 四、反检测配置

### 4.1 启动参数配置

```python
from DrissionPage import ChromiumPage, ChromiumOptions

co = ChromiumOptions()

# 基础反检测设置
co.set_argument("--disable-blink-features=AutomationControlled")
co.set_argument("--disable-infobars")
co.set_argument("--disable-gpu")

# 设置窗口大小（避免小窗口特征）
co.set_argument("--window-size=1920,1080")

# 无头模式
# co.headless(True)

# 设置代理
# co.set_proxy("http://127.0.0.1:7890")

page = ChromiumPage(co)
```

### 4.2 User-Agent 随机化

```python
import random

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

co = ChromiumOptions()
co.set_user_agent(random.choice(USER_AGENTS))
```

### 4.3 JS 注入绕过检测

```python
# 在页面加载前注入 JS 覆盖 navigator.webdriver
page.run_js("""
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
""")
```

### 4.4 随机延迟（模拟人类行为）

```python
import time
import random

def human_delay(min_s=0.5, max_s=2.0):
    """随机延迟，模拟人类操作"""
    time.sleep(random.uniform(min_s, max_s))

# 使用
elem.click()
human_delay(1.0, 3.0)
page.ele("css:.next-btn").click()
```

---

## 五、实战要点

### 5.1 DrissionPage vs Playwright 反检测对比

| 检测项 | DrissionPage | Playwright |
|--------|-------------|-----------|
| `navigator.webdriver` | 默认隐藏 | 需手动覆盖 |
| WebDriver 标记 | 无 | 有（需插件） |
| Chrome DevTools Protocol | 直接控制 | CDP 代理 |
| 用户数据目录 | 直接读取 | 需配置 |
| 被识别为自动化概率 | 低 | 中 |

### 5.2 抖音网页操作要点

1. **登录状态复用**：通过 Cookie 导入，避免每次重新登录
2. **评论操作流程**：
   - 打开视频页面
   - 等待评论区加载
   - 定位评论输入框
   - 输入文字并提交
3. **频率控制**：每次操作间加随机延迟
4. **异常处理**：元素未找到、页面超时、反爬触发

### 5.3 常见问题

| 问题 | 解决方案 |
|------|---------|
| 元素找不到 | 增加等待时间 / 检查选择器 |
| 页面加载慢 | 设置更长超时 / 等待特定元素 |
| 被检测为自动化 | 检查反检测配置 / 更新 JS 注入 |
| Cookie 失效 | 重新获取 / 检查域名匹配 |

---

## 六、核心经验总结

1. **DrissionPage 适合 RPA 场景**：安装简单、反检测强、API 简洁
2. **优先用 ChromiumPage**：需要页面交互时，比 httpx 更可靠
3. **Session 管理是关键**：Cookie 导入导出决定了能否复用登录态
4. **反检测不是万能的**：配合频率控制、代理 IP 效果更好
5. **混合使用最优**：API 能做的用 httpx，页面交互用 DrissionPage

---

_学习日期: 2026-06-18_
