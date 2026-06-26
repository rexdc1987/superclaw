# Zhao Yun Phase 3 - Multi-Account Manager + DrissionPage Integration

> Dispatched by Cao Cao | Date: 2026-06-20
> Build multi-account management and browser automation integration
> Output: src/rpa/account/ + docs/learning_zhaoyun_phase3.md

---

## Goals

1. Build multi-account pool manager
2. Build browser context factory with anti-detection
3. Integrate HTTP client with anti-detection middleware

## Tasks

### Task 1: Account Pool Manager
**Output**: src/rpa/account/pool.py + src/rpa/account/models.py

Multi-account lifecycle management:
- Account model: platform, credentials, health_score, status, last_used
- AccountPool: load from config, round-robin selection, health-based selection
- Account states: active, cooldown, banned, disabled
- Cooldown mechanism: after error, account enters cooldown for N minutes
- Health scoring: success rate, response time, captcha frequency

### Task 2: Browser Context Factory
**Output**: src/rpa/account/context_factory.py

Create isolated browser contexts per account:
- Each account gets its own browser context with persistent storage
- Auto-apply anti-detection (fingerprint + stealth from Phase 2)
- Context lifecycle: create -> use -> recycle
- Resource limits: max concurrent contexts, idle timeout

### Task 3: HTTP + Anti-Detection Integration
**Output**: src/rpa/http/middleware.py

Middleware chain for HTTP client:
- Auto-rotate User-Agent per request
- Inject platform-specific headers
- Rate limiting per account
- Request/response logging with account context

### Task 4: Learning Notes
**Output**: docs/learning_zhaoyun_phase3.md

Document account pool design, context isolation, middleware architecture.

## Acceptance Criteria

1. AccountPool can load, select, cooldown accounts correctly
2. Browser context factory creates isolated contexts with anti-detection
3. HTTP middleware chain works end-to-end
4. All modules have unit tests
5. Write TASK_COMPLETE phase3_accounts at end of notes
