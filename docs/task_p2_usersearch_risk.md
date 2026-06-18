# SuperClaw V2 开发任务 - P2批次

## 项目路径
E:\Projects\SuperClaw

## 本轮任务：开发2个P2模块

### 模块3：用户搜索与抓取（ToB获客核心）

新建文件：
- src/automation/user_ops.py

增强文件：
- src/automation/platform_base.py - 新增抽象方法
- src/automation/douyin_adapter.py - 实现用户搜索

platform_base.py新增抽象方法：
- async search_users(keyword, count=20) -> List[Dict]
- async get_user_profile(user_url) -> Dict
- async get_user_videos(user_url, count=10) -> List[Dict]

douyin_adapter.py实现：
- search_users: 访问 douyin.com/search/{keyword}?type=user，抓取用户卡片
- get_user_profile: 访问用户主页，抓取昵称/简介/粉丝数/关注数/获赞数/IP属地/是否企业号
- get_user_videos: 访问用户主页视频tab，抓取最近视频列表

返回数据结构：
search_users返回: [{user_id, nickname, avatar_url, signature, follower_count, is_verified}]
get_user_profile返回: {user_id, nickname, signature, follower_count, following_count, like_count, ip_location, is_business, is_verified, video_count}
get_user_videos返回: [{video_id, title, url, like_count, comment_count, publish_time}]

### 模块6：风控分级体系

增强文件：
- src/models/risk.py - 新增IndustryRiskLevel枚举
- src/core/constants.py - 新增RiskLevel枚举
- src/services/risk_service.py - 新增行业风险校验

constants.py新增枚举：
class IndustryRiskLevel(str, Enum):
    LOW = "low"        # 装修/教育/餐饮 - 全部动作可用
    MEDIUM = "medium"  # 电商/本地生活 - 可私信但需内容审核
    HIGH = "high"      # 医美/金融/保险 - 仅点赞+关注+收藏，禁止私信

risk_service.py新增方法：
- get_industry_risk_level(platform, action_type) -> RiskLevel - 获取当前行业风险等级
- validate_action_by_risk_level(action_type, risk_level) -> Tuple[bool, str] - 按风险等级校验动作是否允许
- set_industry_risk_level(task_id, risk_level) - 设置任务的行业风险等级

风险规则存储在risk_rules表中，rule_type新增"industry_risk"类型。

### 完成标准
1. 所有新文件语法正确
2. 运行 pytest tests/ -v 确保全部测试通过
3. 新增模块的单元测试
4. user_ops.py的测试用mock，不依赖真实网络
