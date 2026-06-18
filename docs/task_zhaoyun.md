# 赵云任务简报 - SuperClaw 浏览器自动化

## 任务目标
搭建 Playwright 执行节点框架，验证抖音平台元素定位。

## 任务内容
1. 创建平台适配器抽象基类 (PlatformAdapter)
2. 实现抖音适配器 (DouyinAdapter):
   - 搜索视频
   - 读取评论区
   - 发布评论/回复
   - 点赞/关注/收藏
   - 发送私信
3. 异常检测:
   - 登录状态检查
   - 验证码检测
   - 页面元素变化检测
4. 元素定位配置化（YAML）

## 技术规范
- Playwright (Python)
- 异步 async/await
- 遇到验证码/登录失效时抛出异常，不尝试绕过
- 元素定位使用 CSS selector + XPath 备选

## 输出位置
C:/Users/Chaos/Documents/SuperClaw/src/automation/
