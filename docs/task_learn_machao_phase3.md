# Ma Chao Phase 3 - Platform Adapters (Douyin + Xiaohongshu)

> Dispatched by Cao Cao | Date: 2026-06-20
> Build real platform adapters using the adapter framework from Phase 2
> Output: src/rpa/adapters/ + docs/learning_machao_phase3.md

---

## Goals

1. Build Douyin adapter (real implementation)
2. Build Xiaohongshu adapter (real implementation)
3. Build adapter integration tests with DAG engine

## Tasks

### Task 1: Douyin Adapter
**Output**: src/rpa/adapters/douyin.py + src/rpa/adapters/douyin_config.py

Real Douyin platform adapter:
- Extend BaseAdapter from Phase 2
- Operations: login, search_content, post_comment, like_content, follow_user
- Use DrissionPage for browser automation
- Anti-detection integration (fingerprint, stealth, behavior simulation)
- Error handling: captcha detection, rate limit detection, account ban detection
- Config: target URLs, operation intervals, comment templates

### Task 2: Xiaohongshu Adapter
**Output**: src/rpa/adapters/xiaohongshu.py + src/rpa/adapters/xiaohongshu_config.py

Real Xiaohongshu platform adapter:
- Same structure as Douyin adapter
- Operations: login, search_notes, post_comment, like_note, collect_note
- Platform-specific: note content parsing, image download
- Config: target topics, interaction rules

### Task 3: Adapter + DAG Integration
**Output**: tests/test_adapter_integration.py

Integration tests combining adapters with DAG engine:
- Define a workflow YAML that uses adapter actions
- Test: search -> filter -> comment -> report pipeline
- Test error handling: adapter failure -> retry -> fallback
- Test multi-adapter workflow (douyin + xiaohongshu in one pipeline)

### Task 4: Learning Notes
**Output**: docs/learning_machao_phase3.md

Document adapter implementation details, platform differences, integration patterns.

## Acceptance Criteria

1. Douyin adapter has all 5 operations implemented
2. Xiaohongshu adapter has all 5 operations implemented
3. Integration test defines a real workflow YAML and executes it
4. Adapters handle errors gracefully (captcha, rate limit, ban)
5. Write TASK_COMPLETE phase3_adapters at end of notes
