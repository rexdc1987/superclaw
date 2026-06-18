# 海贼AI工作室 RPA 学习计划
> 2026-06-18 制定 | 负责人：曹操

---

## 原则
- ❌ 不使用 Playwright（反爬严重，平台封号风险高）
- ❌ 不使用 Selenium / Puppeteer（同类反爬检测）
- ✅ 优先使用 HTTP 直连、API 调用
- ✅ 浏览器操作用 DrissionPage（CDP 协议，反检测能力更强）
- ✅ 移动端用 ADB

---

## 一、赵云 — RPA 核心执行者

### 目标
掌握多种自动化技术，绕过平台反爬，稳定执行 RPA 任务。

### 学习路线

#### 第一阶段：HTTP 直连（1周）
- [ ] Python httpx / requests 库
- [ ] 逆向分析平台 API（抓包工具 mitmproxy / Charles）
- [ ] Cookie / Token 管理和复用
- [ ] 模拟登录（验证码处理方案）
- [ ] 实战：抖音/小红书 API 直连发评论

#### 第二阶段：DrissionPage 浏览器自动化（1周）
- [ ] DrissionPage 安装和基础用法
- [ ] 元素定位、点击、输入
- [ ] Session 管理和 Cookie 复用
- [ ] 反检测配置（指纹伪装、User-Agent）
- [ ] 实战：DrissionPage 自动化抖音操作

#### 第三阶段：ADB 移动端自动化（1周）
- [ ] ADB 基础命令（点击、滑动、截图）
- [ ] Python-adb 库（pure-python-adb）
- [ ] 安卓模拟器自动化（雷电/MuMu）
- [ ] 实战：抖音 APP 端自动化操作

#### 第四阶段：RPA 工作流引擎（2周）
- [ ] RPAFramework 基础
- [ ] 自定义 Action 开发
- [ ] 异常处理和重试机制
- [ ] 任务调度和并发控制
- [ ] 实战：端到端获客流程自动化

---

## 二、马超 — RPA 平台/工具开发

### 目标
开发 RPA 底层框架和可视化工具，支撑赵云的自动化任务。

### 学习路线

#### 第一阶段：RPA 框架设计（1周）
- [ ] 研究 RPAFramework 架构
- [ ] 研究 TagUI 设计理念
- [ ] 设计 SuperClaw RPA 引擎架构
- [ ] 定义 Action / Task / Workflow 数据模型

#### 第二阶段：RPA 引擎开发（2周）
- [ ] Action 注册机制（插件化）
- [ ] 工作流编排引擎（DAG 执行）
- [ ] 变量传递和上下文管理
- [ ] 日志和录制回放
- [ ] 实战：SuperClaw 内置 RPA 引擎

#### 第三阶段：可视化 RPA 编辑器（2周）
- [ ] 拖拽式流程编排 UI（Vue3 + vue-flow）
- [ ] Action 组件市场
- [ ] 流程导入导出（JSON/YAML）
- [ ] 调试模式（单步执行、断点）
- [ ] 实战：SuperClaw Web 端 RPA 编辑器

---

## 三、诸葛亮 — RPA 流程调度

### 目标
负责 RPA 任务的编排、调度和监控。

### 学习路线

#### 第一阶段：任务调度（1周）
- [ ] Cron 表达式和定时任务
- [ ] 任务队列（Redis / Celery）
- [ ] 并发控制和限流
- [ ] 失败重试策略

#### 第二阶段：流程编排（1周）
- [ ] DAG 有向无环图概念
- [ ] 条件分支、循环、并行
- [ ] 子流程和流程复用
- [ ] 实战：设计复杂获客流程模板

#### 第三阶段：监控告警（1周）
- [ ] RPA 执行监控看板
- [ ] 异常检测和自动告警
- [ ] 执行统计和报表
- [ ] 实战：SuperClaw RPA 监控模块

---

## 技术栈汇总

| 技术 | 用途 | 学习者 |
|------|------|--------|
| httpx / requests | HTTP 直连 | 赵云 |
| mitmproxy / Charles | 抓包分析 | 赵云 |
| DrissionPage | 浏览器自动化（非 Playwright） | 赵云 |
| ADB + pure-python-adb | 移动端自动化 | 赵云 |
| RPAFramework | RPA 框架参考 | 赵云、马超 |
| vue-flow | 可视化流程编辑器 | 马超 |
| Celery / Redis | 任务队列 | 诸葛亮 |
| DAG 引擎 | 工作流编排 | 马超、诸葛亮 |

---

## 排期

| 阶段 | 时间 | 负责人 | 产出 |
|------|------|--------|------|
| Phase 1 | 第1-2周 | 赵云、马超、诸葛亮 | HTTP 直连能力 + 框架设计 |
| Phase 2 | 第3-4周 | 赵云、马超 | DrissionPage + RPA 引擎 v1 |
| Phase 3 | 第5-6周 | 全员 | ADB 自动化 + 可视化编辑器 |
| Phase 4 | 第7-8周 | 全员 | 端到端 RPA 流程上线 |
