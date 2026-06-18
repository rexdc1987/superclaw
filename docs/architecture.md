# SuperClaw Architecture Design

## 1. Project Structure
SuperClaw/
  src/
    __init__.py
    main.py              # Application entry point
    core/
      __init__.py
      config.py          # YAML config loader
      constants.py       # Enums, constants
      exceptions.py      # Custom exceptions
    models/
      __init__.py
      database.py        # SQLAlchemy/SQLite setup
      account.py         # Account, AccountGroup
      keyword.py         # KeywordGroup
      task.py            # Task, TaskRule
      comment.py         # Comment
      lead.py            # Lead
      action.py          # Action, ExecutionLog
      template.py        # MessageTemplate, Material
      risk.py            # RiskRule, Blacklist
      audit.py           # AuditLog
    services/
      __init__.py
      account_service.py
      keyword_service.py
      collector_service.py   # Comment collection
      lead_service.py        # Lead scoring, management
      action_service.py      # Action execution
      risk_service.py        # Rate control, risk mgmt
      task_service.py        # Task lifecycle
      export_service.py      # CSV/XLSX export
    gui/
      __init__.py
      main_window.py     # Main window
      dashboard.py       # Work dashboard
      task_view.py       # Task creation/detail
      lead_view.py       # Lead library
      account_view.py    # Account management
      template_view.py   # Template management
      log_view.py        # Log viewer
      risk_view.py       # Risk control center
    automation/
      __init__.py
      browser.py         # Playwright browser manager
      platform_base.py   # Abstract platform adapter
      douyin_adapter.py  # Douyin platform adapter
      comment_ops.py     # Comment operations
      interaction_ops.py # Like/follow/DM operations
    utils/
      __init__.py
      logger.py          # Logging setup
      validators.py      # Input validation
      helpers.py         # Common helpers
  config/
    default.yaml         # Default configuration
    risk_rules.yaml      # Risk control rules
  tests/
  assets/
  requirements.txt

## 2. Database Schema (SQLAlchemy)

### Account
- id: int PK
- platform: str (douyin, kuaishou, etc.)
- username: str
- display_name: str
- status: enum(available, cooling, login_expired, error, restricted)
- group_id: FK -> AccountGroup
- daily_comment_count: int
- daily_dm_count: int
- daily_follow_count: int
- daily_fail_count: int
- last_error: str
- created_at, updated_at: datetime

### AccountGroup
- id: int PK
- name: str
- description: str

### KeywordGroup
- id: int PK
- name: str
- keywords: JSON (list of keyword configs)
- rotate_after_n_videos: int

### Task
- id: int PK
- name: str
- status: enum(draft, pending_review, queued, running, paused, completed, failed, cancelled)
- priority: int
- platform: str
- account_group_id: FK
- keyword_group_id: FK
- config: JSON (search params, filters, actions)
- progress: JSON (counts, stats)
- created_by: str
- started_at, completed_at: datetime
- created_at, updated_at: datetime

### Comment
- id: int PK
- task_id: FK -> Task
- platform: str
- video_id: str
- video_title: str
- comment_id: str
- comment_text: str
- user_id: str
- user_nickname: str
- user_region: str
- comment_time: datetime
- matched_keywords: JSON
- created_at: datetime

### Lead
- id: int PK
- task_id: FK -> Task
- platform: str
- user_id: str
- user_nickname: str
- source_comment_id: FK -> Comment
- score: int
- score_details: JSON
- status: enum(new, assigned, contacted, replied, converted, blacklisted)
- assigned_to: str
- last_contact_at: datetime
- contact_count: int
- created_at, updated_at: datetime

### Action
- id: int PK
- task_id: FK -> Task
- lead_id: FK -> Lead
- action_type: enum(comment_reply, first_comment, like, follow, favorite, dm, at_user, send_image)
- account_id: FK -> Account
- content: str
- status: enum(pending, approved, running, success, failed, skipped)
- error_message: str
- executed_at: datetime
- created_at: datetime

### MessageTemplate
- id: int PK
- name: str
- content: str (supports {nickname}, {keyword}, {platform}, {source_title})
- action_type: str
- is_active: bool
- sensitive_words_check: bool
- usage_count: int
- created_at: datetime

### Material
- id: int PK
- name: str
- type: enum(image, video)
- file_path: str
- category: str
- is_active: bool
- created_at: datetime

### RiskRule
- id: int PK
- name: str
- rule_type: enum(daily_limit, hourly_limit, per_video_limit, cooldown, circuit_breaker)
- platform: str
- action_type: str
- config: JSON (thresholds, durations)
- is_active: bool

### Blacklist
- id: int PK
- platform: str
- user_id: str
- reason: str
- created_at: datetime

### SensitiveWord
- id: int PK
- word: str
- category: str
- is_active: bool

### ExecutionLog
- id: int PK
- task_id: FK
- action_id: FK
- level: enum(info, warning, error, critical)
- message: str
- details: JSON
- created_at: datetime

### AuditLog
- id: int PK
- user: str
- action: str
- target_type: str
- target_id: str
- details: JSON
- created_at: datetime

## 3. Key Interfaces

### PlatformAdapter (Abstract)
- async search_videos(keyword, count) -> List[Video]
- async get_comments(video_id, count) -> List[Comment]
- async post_comment(video_id, content) -> Result
- async reply_comment(comment_id, content) -> Result
- async like_comment(comment_id) -> Result
- async follow_user(user_id) -> Result
- async send_dm(user_id, content) -> Result
- async send_image(user_id, image_path) -> Result
- async check_login() -> bool
- async handle_captcha() -> None

### TaskScheduler
- create_task(config) -> Task
- start_task(task_id)
- pause_task(task_id)
- resume_task(task_id)
- cancel_task(task_id)
- get_task_status(task_id) -> TaskStatus

### LeadEngine
- score_lead(comment, context) -> (score, details)
- filter_leads(task_id, criteria) -> List[Lead]
- assign_lead(lead_id, user)
- update_lead_status(lead_id, status)

### RiskController
- check_rate_limit(account_id, action_type) -> bool
- check_sensitive_words(content) -> List[str]
- check_blacklist(platform, user_id) -> bool
- check_duplicate_contact(platform, user_id, days) -> bool
- should_circuit_break(account_id) -> bool
