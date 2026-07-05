# 赵云 RPA 学习任务 - 第一阶段

## 任务目标
学习 HTTP 直连技术，掌握不通过浏览器直接调用平台 API 的能力。

## 学习内容

### 1. Python httpx 库 (2天)
- 安装: pip install httpx
- 学习异步请求、Session 管理、Cookie 处理
- 实践: 模拟登录、带 Cookie 请求

### 2. 抓包分析 (2天)
- 安装 mitmproxy: pip install mitmproxy
- 学习 HTTPS 抓包、请求/响应分析
- 实践: 抓取抖音/小红书 API 请求

### 3. API 逆向 (3天)
- 分析平台 API 接口（登录、发评论、获取列表）
- 提取必要参数（Cookie、Token、签名）
- 实践: 用 httpx 调用平台 API 发评论

## 产出要求
1. 学习笔记: E:\Projects\SuperClaw\docs\rpa_http_notes.md
2. 示例代码: E:\Projects\SuperClaw\src\automation\http_client.py
3. 抓包记录: E:\Projects\SuperClaw\docs\api_analysis.md

## 参考资源
- httpx 文档: https://www.python-httpx.org/
- mitmproxy 文档: https://docs.mitmproxy.org/
