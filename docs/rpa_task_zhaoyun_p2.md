# 赵云 RPA 学习任务 - 第二阶段

## 任务目标
学习 DrissionPage 浏览器自动化，掌握不依赖 Playwright 的浏览器操作能力。

## 学习内容

### 1. DrissionPage 基础 (2天)
- 安装: pip install DrissionPage
- 学习 ChromiumPage、SessionPage、WebPage 三种模式
- 元素定位：css selector、xpath、text
- 实践：打开网页、点击、输入、截图

### 2. Session 管理 (2天)
- Cookie 导入导出
- 复用浏览器登录状态
- 无头模式和有头模式切换

### 3. 反检测配置 (2天)
- User-Agent 随机化
- 指纹伪装配置
- 绕过常见检测（Cloudflare、reCAPTCHA）

### 4. 实战 (1天)
- 用 DrissionPage 自动化抖音网页操作
- 对比 DrissionPage 和 Playwright 的反检测能力差异

## 产出要求
1. 学习笔记: E:\Projects\SuperClaw\docs\rpa_drission_notes.md
2. 示例代码: E:\Projects\SuperClaw\src\automation\drission_client.py
3. 反检测测试报告: E:\Projects\SuperClaw\docs\antidetect_report.md

## 参考资源
- DrissionPage 文档: https://www.drissionpage.cn/
- GitHub: https://github.com/g1879/DrissionPage
