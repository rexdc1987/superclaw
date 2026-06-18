# SuperClaw V2 开发任务 - P1批次

## 项目路径
E:\Projects\SuperClaw

## 本轮任务：开发2个P1模块

### 模块4：留痕曝光模式（Stealth Exposure）

高风险行业专用：只点赞+关注+收藏，不发评论不发私信。

新建文件：
- src/services/stealth_service.py

StealthService需要的方法：
- execute_stealth_task(task_id) - 执行留痕曝光任务
- stealth_interact(adapter, user_url) - 对单个用户执行留痕操作（点赞评论+关注+收藏）
- get_stealth_stats(task_id) - 获取留痕曝光统计

逻辑流程：
1. 搜索目标视频
2. 采集评论区用户
3. 对每个高意向用户执行：点赞其评论 -> 关注该用户 -> 收藏视频
4. 不发任何评论/私信，靠账号名称吸引回访
5. 记录每个操作到Action表（action_type=like/follow/favorite）

在Task模型中，playbook_id关联到STEALTH_EXPOSURE打法时自动进入留痕模式。

### 模块5：分层私信策略引擎（Strategy）

新建文件：
- src/models/strategy.py
- src/services/strategy_service.py

Strategy模型字段：
- id (int PK)
- name (str) - 策略名称
- description (str)
- platform (str) - 适用平台
- rules_json (text) - 规则JSON [{keywords: [...], template_id: N, priority: N}]
- is_active (bool)
- created_at (datetime)

StrategyService需要的方法：
- create_strategy(data) -> Strategy
- get_strategies(platform=None) -> List
- delete_strategy(id) -> bool
- match_strategy(comment_content, strategy_id) -> dict - 匹配评论内容到对应规则
- execute_strategy(task_id, strategy_id, leads) - 按策略分层发送私信

两层策略逻辑：
1. 精准层：评论含强意图词（怎么买/多少钱/求链接/想要/购买） -> 使用精准话术模板
2. 广泛层：评论无强意图词 -> 使用通用话术模板（免费福利钩子）

匹配规则存在rules_json中，格式：
[
  {"name": "精准层", "keywords": ["买","购买","多少钱","求链接","想要"], "template_id": 1, "priority": 1},
  {"name": "广泛层", "keywords": ["*"], "template_id": 2, "priority": 2}
]

### 完成标准
1. 所有新文件语法正确
2. 运行 pytest tests/ -v 确保全部测试通过
3. 新增模块的单元测试
