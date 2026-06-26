# 【红果短剧自动评论】开发指导说明书 v2.0

## 1. 需求概述

本功能基于MuMu模拟器+uiautomator2，实现红果免费短剧APP全自动评论。支持随机评论和指定评论两种模式，评论内容支持AI生成和用户模版。所有评论记录入库附截图。

**运行环境：** MuMu模拟器(127.0.0.1:7555) + MySQL(localhost:3308) + Vue3前端

---

## 2. 系统架构

| 模块 | 职责 |
|------|------|
| 前端配置模块 | 任务表单、模版管理、登录弹窗 |
| 前端监控模块 | 实时截图(5s刷新)、日志、评论记录、进度条 |
| 任务调度模块 | 状态机(pending/running/paused/completed/failed/stopped) |
| 模拟器控制模块 | ADB连接、APP启动、UI定位、搜索/播放/评论/截图 |
| 评论生成模块 | AI生成、模版抽取、混合模式 |
| 登录管理模块 | 登录检测、验证码辅助 |
| 数据持久层 | MySQL存储 |

---

## 3. 核心业务逻辑

### 3.1 任务启动流程

1. 创建任务 -> ADB连接检测(127.0.0.1:7555) -> 启动APP(com.phoenix.read)
2. 登录检测：点击我的tab，检测我的钱包，未登录则弹窗辅助(status=waiting_login)，5分钟超时
3. 搜索剧名：搜索图标(858,65)，输入关键词，选择结果
4. 获取总集数，按模式执行评论
5. 完成 status=completed

### 3.2 随机评论模式 (random)

配置：random_comment_count(默认10)、random_min_interval(默认20s)、random_max_interval(默认60s)
逻辑：随机抽取N个不重复集数，逐集播放，命中则评论，集间随机等待

### 3.3 指定评论模式 (specified)

配置：start_episode(默认1)、episode_interval(默认1)、comment_interval_sec(默认30s)
逻辑：从第1集播放，到达start_episode开始评论，每隔N集评论一次

### 3.4 单次评论流程

1. 检测全屏：d(resourceId=com.phoenix.read:id/cdi).exists，不存在则press back退出
2. 点击评论按钮：d(resourceId=com.phoenix.read:id/cdi).click() - 禁止坐标点击
3. 等待评论面板(2s)
4. 点击输入框：d(textContains=有趣评论千千万).click()
5. 输入评论内容
6. 发送：d(text=发表).click()
7. 关闭面板：d.press(back)
8. 截图验证：重新打开评论，搜索评论前8字，截图保存
9. 等待间隔时间

### 3.5 评论内容生成

- ai：根据标题关键词匹配风格(重生/逆袭/甜宠/复仇/赘婿/战神/总裁/通用)，口语化15-30字
- template：从用户模版列表随机抽取，空则回退ai
- mixed：50%概率AI + 50%概率模版

### 3.6 异常处理

| 场景 | 策略 |
|------|------|
| ADB连接失败 | 立即终止 status=failed |
| APP未安装/启动超时 | 立即终止 status=failed |
| 未登录 | 暂停+前端弹窗辅助，5分钟超时 |
| 搜索无结果 | 立即终止 status=failed |
| 全屏未退出 | press back重试2次，跳过该集 |
| 评论按钮找不到 | 重试2次，跳过 |
| 发送失败 | 重试1次，记录failed |
| 用户暂停 | 保存进度 status=paused |
| 用户停止 | 立即停止 status=stopped |

---

## 4. 数据结构

### 4.1 数据库表 (MySQL localhost:3308)

hongguo_comment_tasks: id, task_name, drama_name, comment_mode(random/specified), content_source(ai/template/mixed), start_episode, episode_interval, comment_interval_sec, random_comment_count, random_min_interval, random_max_interval, templates(JSON), status(7态: pending/waiting_login/running/paused/completed/failed/stopped), total_episodes, current_episode, comment_success_count, comment_fail_count, error_message, created_at, updated_at, started_at, completed_at

hongguo_comment_records: id, task_id(FK), episode_number, comment_content, content_source, status(success/failed/skipped), screenshot_input_path, screenshot_verify_path, error_message, created_at

hongguo_execution_logs: id, task_id(FK), level(info/warn/error), message, episode_number, created_at

hongguo_comment_templates: id, content, category, is_default, created_at

### 4.2 API接口 (16个)

POST/GET/GET:id/PUT/DELETE /api/v1/hongguo/tasks
POST /api/v1/hongguo/tasks/:id/start|pause|resume|stop
GET /api/v1/hongguo/tasks/:id/records|logs|screenshot
POST /api/v1/hongguo/check-login
GET/POST/DELETE /api/v1/hongguo/templates

### 4.3 前端路由 (5个)

| 路由 | 页面 | 说明 |
|------|------|------|
| /hongguo | TaskList.vue | 任务列表 |
| /hongguo/create | TaskCreate.vue | 新建任务 |
| /hongguo/:id/edit | TaskCreate.vue | 编辑 |
| /hongguo/:id | TaskExecute.vue | 执行监控 |
| /hongguo/templates | TemplateManager.vue | 模版管理 |

---

## 5. 开发计划

### Phase 1：后端基础
1. 建表SQL(4张表, MySQL localhost:3308)
2. 任务CRUD接口
3. 模版CRUD接口 + 5条默认模版

### Phase 2：前端配置页面
4. TaskList.vue
5. TaskCreate.vue(含模式切换参数组)
6. TemplateManager.vue

### Phase 3：模拟器控制核心
7. ADB连接模块(127.0.0.1:7555)
8. 登录检测接口
9. 模拟器原子操作
10. 任务执行引擎

### Phase 4：执行监控页面
11. TaskExecute.vue(截图+进度+日志+记录)
12. LoginCheck.vue

### Phase 5：联调
13. 全流程联调
14. 异常场景测试
15. 截图路径：E:/Projects/SuperClaw/screenshots/hongguo/{task_id}/

---

**文档归属：** 诸葛亮(PM)
**技术底座：** hongguo-zidong-pinglun 技能
**数据库：** MySQL localhost:3308，禁止SQLite
