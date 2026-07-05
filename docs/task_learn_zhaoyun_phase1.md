# 赵云 Phase 1 学习任务 — HTTP 直连与 API 逆向

> 派发人：曹操 | 日期：2026-06-20
> 预计周期：3-5天 | 产出位置：docs/learning_zhaoyun_phase1.md

---

## 学习目标

1. 掌握 Python httpx 库的异步/同步用法
2. 学会用 mitmproxy 抓包分析平台 API
3. 理解 Cookie/Token 管理和复用机制
4. 完成一个实战小项目：用 httpx 直连调用公开 API

## 学习内容

### 模块1：httpx 基础（第1天）
- 阅读 httpx 官方文档
- 编写示例代码：GET/POST 请求、超时设置、重试机制
- 对比 httpx vs requests 的异同
- **产出**：`docs/httpx_basics.md` + 可运行示例代码

### 模块2：抓包分析（第2天）
- 学习 mitmproxy 基本用法（安装、启动、拦截）
- 分析一个真实网站的 API 请求流程
- 理解请求头、Cookie、Token 的传递方式
- **产出**：`docs/api_analysis_notes.md`

### 模块3：Cookie/Token 管理（第3天）
- 研究 Cookie 持久化方案（文件存储、数据库存储）
- 研究 Token 刷新机制（OAuth2 refresh_token 流程）
- 编写一个简单的 TokenManager 类
- **产出**：`docs/token_management.md`

### 模块4：实战练习（第4-5天）
- 选择一个公开 API（如 GitHub API）
- 用 httpx 实现完整的 API 调用流程
- 包含：认证、请求、错误处理、重试、日志
- **产出**：`docs/httpx_practice.md` + 示例代码

## 学习要求

1. 笔记必须手写，用自己的理解总结
2. 每个模块必须有可运行的代码示例
3. 遇到问题要记录，包括错误信息和解决方案
4. 不要用 Playwright/Selenium，只用 httpx
5. 完成后在笔记末尾写 <!-- TASK_COMPLETE: phase1_httpx -->

## 验收标准
- 4个模块的笔记都完成
- 至少有3个可运行的代码示例
- 有对 SuperClaw 项目的实际应用思考
