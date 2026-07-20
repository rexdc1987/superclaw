# Hongguo Server Deployment

## Supported topologies

### Integrated Windows host

Use this mode for the current test environment. The API, Vue frontend, MySQL client,
MuMu and ADB all run on one Windows host.

- `SUPERCLAW_EXECUTION_MODE=embedded`
- Start with `scripts/start_hongguo_server.ps1`
- Existing search, playback, advertisement and comment logic is unchanged.

### Control plane plus Windows workers

Use this mode when the browser/API server is separate from MuMu hosts.

- Control plane: `SUPERCLAW_EXECUTION_MODE=api`
- Windows nodes: `run_worker.py`
- All components connect to the same MySQL database.
- Each worker must have a stable and unique `SUPERCLAW_WORKER_ID`.
- The control plane and workers must see the same screenshot storage. Use an SMB share
  mounted at the path configured by `SUPERCLAW_SCREENSHOT_ROOT`.

## Production requirements

1. Copy `.env.example` to the deployment secret store and replace every placeholder.
2. Generate `SUPERCLAW_AUTH_SECRET` with at least 32 random characters.
3. Rotate the database password that existed in older Git history.
4. Build and start the control plane with `docker compose --env-file .env up -d --build`.
5. Create the first administrator:

   ```powershell
   $env:SUPERCLAW_ADMIN_USERNAME = 'admin'
   $env:SUPERCLAW_ADMIN_PASSWORD = '<strong-password>'
   python scripts/create_admin.py
   ```

6. On each Windows MuMu host, configure the central database and run:

   ```powershell
   $env:SUPERCLAW_DB_HOST = '<mysql-host>'
   $env:SUPERCLAW_DB_PORT = '3306'
   $env:SUPERCLAW_DB_NAME = 'superclaw'
   $env:SUPERCLAW_DB_USER = 'superclaw'
   $env:SUPERCLAW_DB_PASSWORD = '<database-password>'
   $env:SUPERCLAW_SCREENSHOT_ROOT = '\\fileserver\superclaw\screenshots\hongguo'
   .\scripts\start_hongguo_worker.ps1 -WorkerId 'mumu-host-01' -WorkerName 'MuMu Host 01'
   ```

7. Put an HTTPS reverse proxy in front of port 8980. Do not expose MySQL or ADB ports
   to the public network.

## Health checks

`GET /health` reports two different conditions:

- `status`: API and database availability.
- `task_execution_ready`: at least one worker is online in control-plane mode.

A worker is considered offline after 90 seconds without a heartbeat.

## Data ownership and device locking

- Regular users only see their own tasks, batches, logs, records and templates.
- Administrators can inspect all tenants.
- Device leases are stored in MySQL and include the worker ID, so identical localhost
  ADB ports on different MuMu hosts do not conflict.
- Mutating API calls are recorded in `superclaw_api_audit_logs` without request bodies.

## Backup and rollback

Back up MySQL and screenshot storage together. Database records contain screenshot paths,
so restoring only one side produces incomplete evidence.

The last verified pre-server baseline is:

- Commit: `0c97fa5`
- Tag: `hongguo-tasks117-119-complete-20260720`

Rollback changes the application commit only. Do not drop the added ownership, worker or
lease columns; older code ignores them.
