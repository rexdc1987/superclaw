# SuperClaw V2 开发任务 - P0批次

## 项目路径
E:\Projects\SuperClaw

## 技术栈
Python 3.11 + PySide6 + SQLAlchemy + SQLite

## 参考文档
E:\Projects\SuperClaw\docs\optimization_plan_v2.md

## 本轮任务：开发2个P0模块

### 模块1：打法模板系统（Playbook）

新建文件：
- src/models/playbook.py
- src/services/playbook_service.py
- src/gui/playbook_view.py

Playbook模型字段：
- id (int PK)
- name (str) - 打法名称
- description (str) - 描述
- playbook_type (str enum) - AUTO_EXPOSURE/TARGETED_EXPOSURE/LINK_EXPOSURE/ACCOUNT_SEARCH/STEALTH_EXPOSURE
- search_config_json (text) - 搜索配置
- action_config_json (text) - 动作配置
- filter_config_json (text) - 筛选配置
- risk_level (str enum) - low/medium/high
- is_active (bool)
- created_at (datetime)

5套预设打法：
1. AUTO_EXPOSURE（自动曝光）：关键词搜同行视频，动作=评论+私信
2. TARGETED_EXPOSURE（定向曝光）：同行账号粉丝列表，动作=评论+私信
3. LINK_EXPOSURE（链接曝光）：付费投流视频URL，动作=评论+私信
4. ACCOUNT_SEARCH（搜索账号）：按行业关键词搜人，动作=私信
5. STEALTH_EXPOSURE（留痕曝光）：关键词搜视频，动作=仅点赞+关注+收藏

PlaybookService需要的方法：
- create_playbook(data) -> Playbook
- get_playbooks(active_only=True) -> List
- delete_playbook(id) -> bool
- get_preset_playbooks() -> List[dict] - 返回5套预设打法配置
- apply_playbook(task_id, playbook_id) -> Task - 将打法配置应用到任务

GUI要求：
- 卡片式展示5套打法，每个卡片显示打法名称、图标、描述、适用场景
- 点击卡片选择打法后，自动创建任务并应用配置
- 已有自定义打法列表，支持增删

在src/core/constants.py中新增枚举：
class PlaybookType(str, Enum):
    AUTO_EXPOSURE = "auto_exposure"
    TARGETED_EXPOSURE = "targeted_exposure"
    LINK_EXPOSURE = "link_exposure"
    ACCOUNT_SEARCH = "account_search"
    STEALTH_EXPOSURE = "stealth_exposure"

在src/gui/main_window.py的sidebar中添加"打法模板"导航项（index 7，风控中心移到index 8）。

### 模块2：高级筛选引擎

新建文件：
- src/services/filter_service.py
- src/gui/filter_panel.py

增强src/models/lead.py，Lead表新增字段：
- user_region (str, default="") - 用户地区
- user_ip_location (str, default="") - IP属地
- account_type (str, default="personal") - 账号类型(personal/business/verified)
- follower_count (int, default=0) - 粉丝数
- is_following (bool, default=False) - 是否已关注
- last_active_at (datetime, nullable) - 最后活跃时间

FilterService需要的方法：
- filter_by_region(leads_query, region) -> query - 按地区过滤
- filter_by_time(leads_query, days) -> query - 按时效过滤（N天内）
- filter_by_account_type(leads_query, account_type) -> query - 按账号类型
- filter_by_follower_count(leads_query, min_count=0, max_count=999999999) -> query - 按粉丝量范围
- apply_filters(task_id, filter_config) -> List[Lead] - 应用组合筛选，返回结果

FilterPanel组件（可复用QWidget）：
- 地域下拉框：全部/同城/同省 + 城市输入框
- 时效下拉框：全部/1天/3天/7天/30天
- 账号类型下拉框：全部/个人/企业/蓝V
- 粉丝量范围：最小值+最大值输入框
- apply_filters按钮 -> 发射filter_changed信号
- 集成到lead_view.py的顶部

### 完成标准
1. 所有新文件语法正确
2. 运行 pytest tests/ -v 确保现有113个测试全部通过
3. 新增模块的单元测试（至少覆盖核心方法）
4. GUI页面可正常显示

### 工作顺序
1. 先在constants.py添加新枚举
2. 写models（playbook.py + 修改lead.py）
3. 写services（playbook_service.py + filter_service.py）
4. 写GUI（playbook_view.py + filter_panel.py + 修改main_window.py + lead_view.py）
5. 写测试
6. 运行全部测试验证
