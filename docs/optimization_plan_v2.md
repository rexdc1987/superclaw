# SuperClaw V2 优化方案 - 基于公域获客5套打法

## 一、现状差距分析

| 文档要求 | SuperClaw现状 | 差距等级 |
|----------|-------------|---------|
| 自动曝光（同行评论区截流） | 已有关键词搜索+评论采集+私信 | 低 |
| 定向曝光（同行粉丝列表抓取） | 无粉丝列表抓取 | 高 |
| 链接曝光（付费投流视频截流） | 无广告/投流视频识别 | 高 |
| 搜索账号曝光（ToB） | 无用户搜索功能 | 高 |
| 留痕曝光（高风险行业） | 有点赞/关注/收藏，无留痕模式 | 中 |
| 地域筛选 | 无IP/地区过滤 | 高 |
| 时效筛选 | 有time_range_days，但无1天内最新 | 低 |
| 分层私信策略 | 无私信策略引擎 | 中 |
| 风控分级（行业风险等级） | 有频控+敏感词，无行业风险分级 | 中 |

## 二、V2优化方案（6个模块）

### 模块1：打法模板系统（Playbook）
让5套打法变成可选模板，用户选打法自动配置参数。

新增文件：
- models/playbook.py - Playbook模型
- services/playbook_service.py - 打法模板管理
- gui/playbook_view.py - 打法选择页面（卡片式）

5套预设打法：
- 自动曝光：关键词搜索同行视频 + 评论+私信
- 定向曝光：同行账号+粉丝列表 + 评论+私信
- 链接曝光：付费投流视频URL + 评论+私信
- 搜索账号：用户名/行业关键词搜人 + 私信
- 留痕曝光：关键词搜索视频 + 仅点赞+关注+收藏

### 模块2：高级筛选引擎
解决地域、时效、账号质量筛选。

增强文件：
- models/lead.py - 新增user_region/user_ip_location/account_type/follower_count字段
- services/filter_service.py - 筛选服务
- gui/filter_panel.py - 筛选面板组件

筛选维度：
- 地域：同城/同省/指定城市（从评论者主页抓取IP属地）
- 时效：1天/3天/7天/30天内（评论时间过滤）
- 账号类型：个人/企业/蓝V（从主页抓取认证标识）
- 粉丝量：指定范围（从主页抓取粉丝数）
- 活跃度：最近N天有发布（从主页抓取最后发布时间）

### 模块3：用户搜索与抓取（ToB获客核心）
支持按关键词搜索用户账号，抓取用户信息。

新增文件：
- automation/user_ops.py - 用户搜索/信息抓取操作
- 扩展platform_base.py - 新增search_users()接口
- 扩展douyin_adapter.py - 实现用户搜索

接口设计：
- search_users(keyword, filters) -> List[UserInfo]
- get_user_profile(user_url) -> UserProfile
- get_user_followers(user_url, count) -> List[UserInfo]
- get_user_videos(user_url, count) -> List[VideoInfo]

### 模块4：留痕曝光模式
高风险行业专用：只点赞+关注+收藏，不发评论不发私信。

新增文件：
- services/stealth_service.py - 留痕模式服务
- Task类型新增STEALTH_EXPOSURE
- 打法模板中自动配置

逻辑：
1. 搜索目标视频
2. 对评论区高意向用户：点赞其评论 -> 关注 -> 收藏视频
3. 靠账号名称（如"XX装修顾问"）吸引用户主动回访
4. 无任何主动触达，零封号风险

### 模块5：分层私信策略引擎
支持按关键词匹配度分层发送不同私信内容。

新增文件：
- models/strategy.py - 策略规则模型
- services/strategy_service.py - 策略执行引擎
- gui/strategy_view.py - 策略配置页面

两层策略：
- 精准层：评论含强意图词（怎么买/多少钱/求链接） -> 个性化话术
- 广泛层：评论在目标视频下但无强意图词 -> 通用话术（免费福利钩子）

### 模块6：风控分级体系
按行业风险等级匹配获客功能。

增强文件：
- models/risk.py - 新增IndustryRiskLevel
- services/risk_service.py - 行业风险校验

分级规则：
- 低风险（装修/教育/餐饮）：全部动作可发私信
- 中风险（电商/本地生活）：评论+点赞+关注+收藏，私信需内容审核
- 高风险（医美/金融/保险）：仅点赞+关注+收藏，禁止私信

## 三、开发优先级排序

| 优先级 | 模块 | 理由 | 预估工时 |
|--------|------|------|---------|
| P0 | 模块1：打法模板 | 核心差异化，用户直接选打法 | 3天 |
| P0 | 模块2：高级筛选 | 地域筛选是刚需，影响转化率 | 2天 |
| P1 | 模块4：留痕曝光 | 高风险行业刚需，实现简单 | 1天 |
| P1 | 模块5：分层私信 | 提升私信转化率 | 2天 |
| P2 | 模块3：用户搜索 | ToB获客核心，开发量大 | 3天 |
| P2 | 模块6：风控分级 | 合规保障，防止封号 | 1天 |

总预估：12天（约2周）

## 四、数据模型变更

### 新增表
- playbooks - 打法模板表
- strategies - 私信策略规则表
- user_profiles - 抓取的用户信息表

### 现有表扩展
- leads新增：user_region, user_ip_location, account_type, follower_count, is_business_account
- tasks新增：playbook_id, risk_level, filter_config_json
- risk_rules新增：industry_risk_level

### 新增枚举
- PlaybookType: AUTO_EXPOSURE, TARGETED_EXPOSURE, LINK_EXPOSURE, ACCOUNT_SEARCH, STEALTH_EXPOSURE
- RiskLevel: LOW, MEDIUM, HIGH
- AccountType: PERSONAL, BUSINESS, VERIFIED
