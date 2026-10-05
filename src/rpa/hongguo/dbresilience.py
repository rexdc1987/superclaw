"""Resilient MySQL access for the Hongguo task engine.

Background
----------
On 2026-09-16 the link between this machine and the shared cloud database
(43.154.184.208:3306) disappeared for about twenty minutes.  Task 411 died on
the spot with ``(2003, "Can't connect to MySQL server on '43.154.184.208'
(timed out)")``; tasks 409/410/412 simply went quiet.  Three separate design
gaps turned one network blip into a lost four-device batch:

1. ``TaskEngine._connection`` opened a brand new ``pymysql.connect`` per call
   with no socket timeouts, so a dead link blocked and then raised.  The first
   ``OperationalError`` travelled out of ``_run_verified_flow`` into its own
   ``except Exception`` handler - which then tried to write ``status='failed'``
   across the same broken link.
2. ``TaskEngine._log`` swallowed every exception, so the outage left no trace at
   all: the only reason we know what happened is that an external reaper wrote
   its own message into ``error_message``.
3. Nothing retried.  A link that came back at 20:51 was never given the chance
   to let a task resume where it stopped.

The three rules implemented here
--------------------------------
* **Fail fast, then back off.** Socket timeouts are set so an unreachable host
  raises in seconds; transient failures are retried with exponential backoff and
  jitter instead of killing the calling thread.
* **Pay for what you cannot lose.** A critical write (task status, counters,
  comment records) waits out an outage up to a budget comfortably longer than
  the observed blip.  Best-effort work (a log line) gives up quickly rather than
  stalling the device flow.
* **Never lose a log line silently.** When the database is unreachable, log rows
  go to an append-only local spool and are replayed with their original
  timestamps once the link returns.

Deliberately *not* implemented: a task-level heartbeat that keeps refreshing
``updated_at``.  ``updated_at`` is a state-transition timestamp and the log table
is the activity signal (see ``.workbuddy/memory/MEMORY.md``).  Teaching
``updated_at`` to lie would make "is this thread actually alive?" unanswerable -
the exact question that had to be answered by hand on 2026-09-16.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pymysql


def _env_float(name: str, default: float) -> float:
    """Read a float from the environment, falling back on anything unusable."""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


#: A dead link must raise in seconds, not after the OS default TCP timeout.
CONNECT_TIMEOUT_SECONDS = _env_float("SUPERCLAW_DB_CONNECT_TIMEOUT", 5.0)
READ_TIMEOUT_SECONDS = _env_float("SUPERCLAW_DB_READ_TIMEOUT", 20.0)
WRITE_TIMEOUT_SECONDS = _env_float("SUPERCLAW_DB_WRITE_TIMEOUT", 20.0)

#: How long a *critical* write keeps retrying before it gives up.  Riding an
#: outage out is far cheaper than losing a batch, so this has to sit
#: comfortably above the longest outage we actually see.  The 2026-09-16 blip
#: lasted ~20 minutes and was covered by the old 1800s default; the one on
#: 2026-09-17 ran 113 minutes, blew through it, and killed tasks 420-423 at
#: episode 47/48 after 90 minutes of real work.  Three hours clears that with
#: headroom.  Override with SUPERCLAW_DB_OUTAGE_BUDGET_SECONDS.
OUTAGE_BUDGET_SECONDS = _env_float("SUPERCLAW_DB_OUTAGE_BUDGET_SECONDS", 10800.0)
#: How long a *best effort* write keeps retrying before it spools.
BEST_EFFORT_BUDGET_SECONDS = _env_float(
    "SUPERCLAW_DB_BEST_EFFORT_BUDGET_SECONDS", 4.0
)

RETRY_BASE_DELAY_SECONDS = 0.5
RETRY_MAX_DELAY_SECONDS = 15.0

#: While the database is known to be down, cheap writes short-circuit to the
#: spool instead of each paying a full connect timeout.  Once this window
#: expires one real call is let through to re-check the link.
DOWN_PROBE_INTERVAL_SECONDS = _env_float("SUPERCLAW_DB_DOWN_PROBE_INTERVAL", 15.0)

DEFAULT_SPOOL_DIR_NAME = "db_spool"

#: ``errno -> retry?``.  Everything in here means "the same call could plausibly
#: succeed in a moment".  Anything else (bad SQL, wrong credentials, missing
#: table) must surface immediately - hiding it behind a retry loop only makes
#: the failure slower and harder to read.
TRANSIENT_MYSQL_ERRNOS = frozenset(
    {
        1040,  # too many connections
        1042,  # bad / unresolvable host
        1047,  # unknown command (half-open connection)
        1053,  # server shutdown in progress
        1205,  # lock wait timeout exceeded
        1317,  # query execution was interrupted
        2003,  # can't connect to MySQL server
        2006,  # MySQL server has gone away
        2013,  # lost connection during query
        2055,  # lost connection to MySQL server
    }
)

#: pymysql 在 ``_read_packet`` 里发现包序号错乱时抛出的文案。它抛之前已经调用
#: ``_force_close()`` 关掉了 socket，所以「换一条新连接重试」正是唯一正确的处理
#: —— 但 ``InternalError`` 继承自 ``DatabaseError`` 而不是 ``OperationalError``，
#: 上面按 errno 的判定压根看不到它。2026-09-30 00:00~00:30 远程库抖动期间，6 个
#: 任务就是被这条原文写进 ``error_message`` 直接判死的（一次都没重试）。
#: 注：``connections.py`` 里 ``InternalError`` 只有这一处抛出点，所以按文案匹配
#: 既够精确，也不会误吞将来可能新增的其它 ``InternalError``。
PACKET_DESYNC_MARKER = "Packet sequence number wrong"


def default_spool_dir() -> Path:
    """Where spooled log rows live when the database cannot be reached."""
    configured = os.environ.get("SUPERCLAW_DB_SPOOL_DIR")
    if configured and str(configured).strip():
        return Path(configured)
    # src/rpa/hongguo/dbresilience.py -> parents[3] is the project root.
    return Path(__file__).resolve().parents[3] / "logs" / DEFAULT_SPOOL_DIR_NAME


def is_transient_error(exc: BaseException) -> bool:
    """True when retrying the exact same call could plausibly succeed."""
    if isinstance(exc, pymysql.err.OperationalError):
        code = exc.args[0] if exc.args else None
        if isinstance(code, int):
            return code in TRANSIENT_MYSQL_ERRNOS
        # OperationalError without a numeric errno is a socket-level failure.
        return True
    if isinstance(exc, pymysql.err.InterfaceError):
        return True
    if isinstance(exc, pymysql.err.InternalError) and PACKET_DESYNC_MARKER in str(exc):
        # See PACKET_DESYNC_MARKER: the socket is already closed, retry is the fix.
        return True
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, OSError):
        # socket.timeout, ConnectionResetError, socket.gaierror and friends all
        # arrive as OSError subclasses.  A plain file error never reaches a
        # database call site, so this cannot shadow a programming mistake.
        return True
    return False


def apply_timeouts(db_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Copy ``db_config``, filling in socket timeouts unless already set."""
    cfg: Dict[str, Any] = dict(db_config or {})
    cfg.setdefault("connect_timeout", CONNECT_TIMEOUT_SECONDS)
    cfg.setdefault("read_timeout", READ_TIMEOUT_SECONDS)
    cfg.setdefault("write_timeout", WRITE_TIMEOUT_SECONDS)
    return cfg


class DbUnavailable(RuntimeError):
    """Raised when a retry budget was genuinely spent without reaching MySQL."""

    def __init__(
        self,
        label: str,
        attempts: int,
        budget: float,
        last_error: Optional[BaseException],
    ) -> None:
        super().__init__(
            "{label} 在 {budget:.0f} 秒重试预算内始终无法访问数据库"
            "（已尝试 {attempts} 次）：{error}".format(
                label=label, budget=budget, attempts=attempts, error=last_error
            )
        )
        self.label = label
        self.attempts = attempts
        self.budget = budget
        self.last_error = last_error


class DbHealth:
    """Process-wide view of "can we reach the shared database right now?".

    A best-effort write pays a full connect timeout every time it tries while
    the link is down.  With the engine logging several lines per episode that
    adds up to minutes of pointless stalling, so the first failure flips this
    flag and cheap writes short-circuit to the spool until the probe window
    expires and one real call is allowed through again.
    """

    def __init__(self, probe_interval: float = DOWN_PROBE_INTERVAL_SECONDS) -> None:
        self._lock = threading.Lock()
        self._down = False
        self._down_until = 0.0
        self._probe_interval = max(0.0, float(probe_interval))
        self._last_error = ""
        self._ever_connected = False
        self.failure_count = 0
        self.recovery_count = 0

    @property
    def ever_connected(self) -> bool:
        """Whether this process has *ever* reached the database.

        A process that never connected is misconfigured, not suffering an
        outage, so it must fail fast instead of waiting out a budget.  This is
        also what keeps a broken ``db_config`` in a test from blocking for
        thirty minutes.
        """
        with self._lock:
            return self._ever_connected

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def mark_down(self, exc: Optional[BaseException] = None) -> None:
        with self._lock:
            if not self._down:
                # A fresh outage.  Repeated failures inside one outage must not
                # inflate the count, otherwise a twenty minute blip reads as
                # hundreds of separate incidents.
                self.failure_count += 1
            self._down = True
            self._down_until = time.monotonic() + self._probe_interval
            if exc is not None:
                self._last_error = str(exc)

    def mark_up(self) -> None:
        with self._lock:
            if self._down:
                self.recovery_count += 1
            self._down = False
            self._down_until = 0.0
            self._last_error = ""
            self._ever_connected = True

    def is_down(self) -> bool:
        """True while the breaker is open.

        Expiry is expressed purely as time passing, never as a state change:
        once the probe window is over the next real call is let through.  If it
        succeeds it calls :meth:`mark_up` and the outage is counted as recovered;
        if it fails :meth:`mark_down` simply extends the window and the outage
        stays a single incident.
        """
        with self._lock:
            return self._down and time.monotonic() < self._down_until

    def reset(self) -> None:
        """Test hook - forget everything learned about the link."""
        with self._lock:
            self._down = False
            self._down_until = 0.0
            self._last_error = ""
            self._ever_connected = False
            self.failure_count = 0
            self.recovery_count = 0

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "down": self._down,
                "ever_connected": self._ever_connected,
                "failure_count": self.failure_count,
                "recovery_count": self.recovery_count,
                "last_error": self._last_error,
            }


#: One breaker for the whole process: the API and every task thread talk to the
#: same MySQL instance, so they should agree about whether it is reachable.
DB_HEALTH = DbHealth()


def resilient_connect(db_config: Optional[Dict[str, Any]]):
    """Open one connection with sane socket timeouts, updating shared health."""
    try:
        conn = pymysql.connect(**apply_timeouts(db_config))
    except BaseException as exc:
        if is_transient_error(exc):
            DB_HEALTH.mark_down(exc)
        raise
    DB_HEALTH.mark_up()
    return conn


def probe(db_config: Optional[Dict[str, Any]]) -> bool:
    """Cheap ``SELECT 1``.  Returns False instead of raising."""
    try:
        conn = resilient_connect(db_config)
    except BaseException:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchall()
    except BaseException as exc:
        if is_transient_error(exc):
            DB_HEALTH.mark_down(exc)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return True


def call_with_retry(
    work: Callable[[], Any],
    *,
    label: str,
    budget: float = OUTAGE_BUDGET_SECONDS,
    max_attempts: int = 0,
    base_delay: float = RETRY_BASE_DELAY_SECONDS,
    max_delay: float = RETRY_MAX_DELAY_SECONDS,
    should_abort: Optional[Callable[[], bool]] = None,
    on_retry: Optional[Callable[[int, float, BaseException], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Any:
    """Run ``work``, retrying transient database failures with backoff.

    ``max_attempts=0`` means "retry until ``budget`` is spent".  A non-transient
    exception is re-raised untouched, and if no retry actually happened (budget
    zero on the first failure) the original exception propagates as well - the
    caller only ever sees :class:`DbUnavailable` when a real budget was spent,
    which keeps misconfiguration reading exactly as loudly as it used to.
    """
    deadline = monotonic() + max(0.0, float(budget))
    attempt = 0
    delay = max(0.0, float(base_delay))
    last_error: Optional[BaseException] = None

    while True:
        attempt += 1
        try:
            return work()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            if not is_transient_error(exc):
                raise
            last_error = exc
            if should_abort is not None and should_abort():
                raise
            if max_attempts and attempt >= max_attempts:
                if attempt <= 1:
                    raise
                break
            remaining = deadline - monotonic()
            if remaining <= 0:
                if attempt <= 1:
                    raise
                break
            wait = min(delay, remaining)
            wait += random.uniform(0.0, wait * 0.25)  # jitter
            if on_retry is not None:
                try:
                    on_retry(attempt, wait, exc)
                except Exception:
                    pass
            sleep(wait)
            delay = min(max(delay * 2, RETRY_BASE_DELAY_SECONDS), max_delay)

    raise DbUnavailable(label, attempt, float(budget), last_error)


def wait_for_database(
    db_config: Optional[Dict[str, Any]],
    *,
    budget: float = OUTAGE_BUDGET_SECONDS,
    should_abort: Optional[Callable[[], bool]] = None,
    sleep: Callable[[float], None] = time.sleep,
    probe_fn: Optional[Callable[[Optional[Dict[str, Any]]], bool]] = None,
) -> bool:
    """Block until a probe succeeds, giving up after ``budget`` seconds."""
    check = probe_fn or probe
    deadline = time.monotonic() + max(0.0, float(budget))
    delay = RETRY_BASE_DELAY_SECONDS
    while True:
        if should_abort is not None and should_abort():
            return False
        if check(db_config):
            return True
        if time.monotonic() >= deadline:
            return False
        sleep(min(delay, RETRY_MAX_DELAY_SECONDS))
        delay = min(max(delay * 2, RETRY_BASE_DELAY_SECONDS), RETRY_MAX_DELAY_SECONDS)


def _encode_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"__type__": "datetime", "value": value.isoformat()}
    return value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict) and value.get("__type__") == "datetime":
        try:
            return datetime.fromisoformat(str(value.get("value")))
        except (TypeError, ValueError):
            return None
    return value


class LogSpool:
    """Append-only local fallback for ``hongguo_execution_logs`` rows.

    Rows are replayed with their *original* ``created_at``, so a gap caused by an
    outage is filled in retroactively instead of the timeline jumping.  Every
    method is best effort and never raises: this is the last line of defence and
    it must not be able to take the engine down with it.
    """

    def __init__(self, directory: Optional[Any] = None, name: str = "hongguo_execution_logs"):
        self.directory = Path(directory) if directory is not None else default_spool_dir()
        self.name = name
        self.path = self.directory / "{0}.jsonl".format(self.name)
        self._lock = threading.Lock()
        self.dropped_count = 0
        self.spooled_count = 0

    def append(self, row: Dict[str, Any]) -> bool:
        try:
            payload = json.dumps(
                {k: _encode_value(v) for k, v in row.items()},
                ensure_ascii=False,
            )
        except (TypeError, ValueError):
            self.dropped_count += 1
            return False
        with self._lock:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(payload + "\n")
            except Exception:
                # This class is the last line of defence and must never be able
                # to take the engine down with it, so the net is deliberately
                # wider than OSError (an unusable path raises ValueError).
                self.dropped_count += 1
                return False
        self.spooled_count += 1
        return True

    def pending(self) -> List[Dict[str, Any]]:
        with self._lock:
            if not self.path.exists():
                return []
            try:
                raw = self.path.read_text(encoding="utf-8")
            except Exception:
                return []
        rows: List[Dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                decoded = json.loads(line)
            except ValueError:
                continue
            if isinstance(decoded, dict):
                rows.append({k: _decode_value(v) for k, v in decoded.items()})
        return rows

    def rewrite(self, rows: List[Dict[str, Any]]) -> None:
        """Replace the spool file with whatever was *not* delivered."""
        with self._lock:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                if not rows:
                    # Truncate in place rather than unlink.  A refused unlink
                    # (antivirus, a sandbox, an open handle) leaves the delivered
                    # rows on disk, and the next probe replays them all over
                    # again - which is how the three rows from 2026-09-17 17:37
                    # ended up in hongguo_execution_logs three times over.
                    self.path.write_text("", encoding="utf-8")
                    return
                body = "".join(
                    json.dumps({k: _encode_value(v) for k, v in row.items()}, ensure_ascii=False)
                    + "\n"
                    for row in rows
                )
                self.path.write_text(body, encoding="utf-8")
            except Exception:
                pass

    def pending_count(self) -> int:
        return len(self.pending())

    def clear(self) -> None:
        self.rewrite([])

    def snapshot(self) -> Dict[str, Any]:
        try:
            pending = self.pending_count()
        except Exception:
            pending = -1
        return {
            "path": str(self.path),
            "pending": pending,
            "spooled": self.spooled_count,
            "dropped": self.dropped_count,
        }


def flush_spooled_logs(
    insert_row: Callable[[Any, Dict[str, Any]], None],
    spool: LogSpool,
    db_config: Optional[Dict[str, Any]],
    *,
    max_rows: int = 500,
) -> int:
    """Replay spooled log rows into the database.  Returns how many landed.

    ``insert_row(cur, row)`` performs the INSERT.  The whole batch commits as one
    transaction, so a failure part-way through rolls back cleanly and the spool
    keeps every row for the next attempt.
    """
    try:
        rows = spool.pending()
    except Exception:
        return 0
    if not rows:
        return 0
    batch = rows[: max(1, int(max_rows))]
    try:
        conn = resilient_connect(db_config)
    except BaseException:
        return 0
    delivered = 0
    try:
        with conn.cursor() as cur:
            for row in batch:
                insert_row(cur, row)
                delivered += 1
        conn.commit()
    except BaseException as exc:
        if is_transient_error(exc):
            DB_HEALTH.mark_down(exc)
        try:
            conn.rollback()
        except Exception:
            pass
        delivered = 0  # rolled back: nothing landed
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if delivered:
        try:
            spool.rewrite(rows[delivered:])
        except Exception:
            pass
    return delivered


EXECUTION_LOG_INSERT_SQL = """
                        INSERT INTO hongguo_execution_logs (
                            task_id, level, message, episode_number, screenshot_path, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """


def execution_log_row(cur: Any, row: Dict[str, Any]) -> None:
    """INSERT one spooled execution-log row using the shared statement."""
    cur.execute(
        EXECUTION_LOG_INSERT_SQL,
        (
            row.get("task_id"),
            row.get("level") or "info",
            row.get("message") or "",
            row.get("episode_number"),
            row.get("screenshot_path"),
            row.get("created_at") or datetime.now(),
        ),
    )
