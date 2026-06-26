# SuperClaw 反检测模块使用指南

> 路径: 
> 日期: 2026-06-19

---

## 一、模块总览

| 文件 | 功能 |
|------|------|
|  | WebDriver 隐藏 + CDP 注入 |
|  | 浏览器指纹伪装（5种设备模板） |
|  | 人类行为模拟（鼠标/键盘/滚动） |
|  | 代理池管理（健康检查 + 轮换） |
|  | 验证码处理适配器（2Captcha） |

---

## 二、快速开始

### 2.1 基础反检测启动



### 2.2 带代理的启动



---

## 三、各模块详解

### 3.1 stealth.py — StealthMiddleware

核心功能：
-  → 返回 Chromium 启动参数列表
-  → 注入反检测 JS（navigator.webdriver=false、plugins 伪造等）
-  → 随机 User-Agent 生成

检测点覆盖：
-  → false
-  → 伪造插件列表
-  → 根据指纹配置
-  → 伪造 chrome 对象
-  CDP 检测规避

### 3.2 fingerprint.py — FingerprintManager

5种内置设备模板：

| 模板 | User-Agent | 分辨率 | DPR |
|------|-----------|--------|-----|
| Windows Chrome | Chrome/Win10 | 1920x1080 | 1.0 |
| macOS Safari | Safari/Mac | 1440x900 | 2.0 |
| Linux Firefox | Firefox/Linux | 1366x768 | 1.0 |
| Android Chrome | Chrome/Android | 412x915 | 2.625 |
| iOS Safari | Safari/iOS | 390x844 | 3.0 |

使用方式：


### 3.3 behavior.py — BehaviorSimulator

| 方法 | 功能 | 关键参数 |
|------|------|----------|
|  | 贝塞尔曲线鼠标移动 | steps, overshoot |
|  | 变速打字 | wpm（字/分钟） |
|  | 自然滚动 | direction, distance |
|  | 随机等待 | min_ms, max_ms |



### 3.4 proxy_manager.py — ProxyPool



### 3.5 captcha_adapter.py — CaptchaAdapter



---

## 四、最佳实践

1. **组合使用**：stealth + fingerprint + behavior 三件套缺一不可
2. **代理隔离**：每个账号绑定固定代理，避免 IP 频繁切换
3. **行为随机化**：不要用固定参数，每次操作加随机抖动
4. **频率控制**：单账号操作间隔 > 30秒，避免触发频率检测
5. **指纹一致性**：同一账号始终使用同一指纹，不要中途切换

---

## 五、检测测试网站

- https://bot.sannysoft.com — 基础自动化检测
- https://pixelscan.net — 浏览器指纹一致性
- https://abrahamjuliot.github.io/creepjs/ — 高级指纹检测

目标：bot.sannysoft.com 全绿，pixelscan 无异常标记。
