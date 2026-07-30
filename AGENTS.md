# SuperClaw Agent Rules

This file is the operating contract for coding agents working in this repository.

## Supported target

- Primary tested host: Windows 10/11 x64.
- Python: 3.11 or newer for a fresh installation.
- Node.js: 22 LTS.
- Database: MySQL 8.x. Hongguo task data must not use SQLite.
- Device automation: MuMu multi-instance plus its bundled ADB.
- Local ports: API `8987`, Vue dev server `3000`, development MySQL `3308`.
- Main test page: `http://127.0.0.1:3000/hongguo/multi`.

## Bootstrap and verification

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap_windows.ps1 -DatabaseMode Auto -Start
.\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py
```

Use `-DatabaseMode Existing` only when a dedicated MySQL database and user already exist.

## Before editing

1. Read `docs/AGENT_INSTALL_AND_TEST.md` and the files around the requested behavior.
2. Run `git status --short`. Never discard user/runtime changes.
3. Check `GET http://127.0.0.1:8987/health` before restarting services.
4. Never restart the API while `running_tasks` is greater than zero unless the user explicitly asks.
5. Treat `config/local.yaml`, API keys, database exports, logs and screenshots as secrets/runtime data.

## Hongguo invariants

- MySQL is the source of truth for tasks, logs, records, templates and leases.
- Never mark an episode complete without confirming the actual current episode.
- A recovery path must verify target title/total episode count and reject `current_episode=0`.
- Comment success requires post-send verification and evidence screenshots.
- Completed comments must not be sent again when a stopped/failed task resumes.
- LiveLite, reward-rain/Polaris pages and in-player ads are different states; do not merge their handlers.
- AI failures must respect local fallback. Template mode must contain at least one non-empty template.
- A saved multi-line template represents multiple independent comment candidates, one per line.
- Keep default playback speed at `1.0x`, random likes at `5`, and favorite count at `1` unless requested.

## Required checks

For backend/RPA changes:

```powershell
.\.venv\Scripts\python.exe -m py_compile src\rpa\dashboard\routes_hongguo.py
.\.venv\Scripts\python.exe -m pytest tests\test_rpa_engine.py tests\test_server_security.py -q
```

For template workflow changes, add `tests\test_hongguo_templates.py`.

For frontend changes:

```powershell
Set-Location frontend
npm.cmd run build
```

After service startup:

```powershell
.\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py
```

Run a real device task only after automated checks pass. Start with one MuMu instance and a short episode range.

## Git hygiene

- Commit source, tests, maintained docs and maintained scripts only.
- Do not commit `config/local.yaml`, `.env`, `config/hongguo_ai_usage.json`, `data/`, `logs/`, `screenshots/`, `tmp/`, `backups/`, ADB dumps or database exports.
- Scan staged changes for keys/passwords before committing.
- Use the current feature branch unless the user asks for another branch.
- Record exact tests run and any unrelated pre-existing failures in the final response.
