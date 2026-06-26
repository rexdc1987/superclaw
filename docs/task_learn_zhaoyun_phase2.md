# Zhao Yun Phase 2 - HTTP Client + Anti-Detection + Token Management

> Dispatched by Cao Cao | Date: 2026-06-20
> Based on Phase 1 httpx research, build production-grade HTTP client
> Output: src/rpa/http/ + src/rpa/anti_detect/ + src/rpa/auth/ + docs/learning_zhaoyun_phase2.md

---

## Goals

1. Wrap httpx as production HTTP client for SuperClaw
2. Implement anti-detection strategies
3. Implement Token management and Cookie persistence

## Tasks

### Task 1: HTTP Client Wrapper
**Output**: src/rpa/http/client.py + src/rpa/http/retry.py

Wrap httpx for SuperClaw:
- Unified get/post methods with auto headers
- Auto retry with exponential backoff
- Separate timeout config (connect/read/write)
- Connection pool management (httpx.AsyncClient reuse)
- Request/response logging with structlog

### Task 2: Anti-Detection Module
**Output**: src/rpa/anti_detect/fingerprint.py + src/rpa/anti_detect/stealth.py

Browser anti-detection:
- Browser fingerprint randomization (User-Agent, WebGL, Canvas, timezone)
- WebDriver detection evasion (navigator.webdriver = false)
- Behavior simulation (random delays, mouse trajectories)
- Each strategy independently toggleable

### Task 3: Token Manager
**Output**: src/rpa/auth/token_manager.py

Token lifecycle management:
- Token storage (encrypted file storage)
- Token refresh (OAuth2 refresh_token flow)
- Multi-account Token isolation
- Token expiry detection and auto-renewal

### Task 4: Learning Notes
**Output**: docs/learning_zhaoyun_phase2.md

Document:
- httpx advanced usage (connection pools, HTTP/2, streaming)
- Anti-detection implementation details and verification methods
- Problems encountered and solutions

## Acceptance Criteria

1. HTTP client can send requests and auto-retry correctly
2. Anti-detection module passes basic bot detection tests
3. Token manager can store, read, refresh tokens correctly
4. All modules have unit tests
5. Write TASK_COMPLETE phase2_http at end of notes
