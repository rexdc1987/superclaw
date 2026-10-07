"""Shared test fixtures — in-memory SQLite database"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models.database as db_module
from models.database import Base

# Import all models to register with Base
import models.account, models.task, models.comment, models.lead
import models.action, models.risk, models.audit, models.keyword, models.template, models.playbook, models.strategy
import models.user

# Import all service modules so we can patch their get_session references
import services.account_service as acct_mod
import services.task_service as task_mod
import services.lead_service as lead_mod
import services.action_service as action_mod
import services.collector_service as collector_mod
import services.risk_service as risk_mod
import services.playbook_service as pb_mod
import services.filter_service as filter_mod
import services.stealth_service as stealth_mod
import services.strategy_service as strategy_mod
import services.user_service as user_mod


@pytest.fixture(autouse=True)
def in_memory_db(monkeypatch):
    """Patch get_session to use in-memory SQLite for ALL modules"""
    monkeypatch.setenv("SUPERCLAW_AUTH_REQUIRED", "false")
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    new_get_session = lambda: TestSession()

    # Patch in database module
    monkeypatch.setattr(db_module, "get_session", new_get_session)
    # Patch in every service module that imports get_session directly
    monkeypatch.setattr(acct_mod, "get_session", new_get_session)
    monkeypatch.setattr(task_mod, "get_session", new_get_session)
    monkeypatch.setattr(lead_mod, "get_session", new_get_session)
    monkeypatch.setattr(action_mod, "get_session", new_get_session)
    monkeypatch.setattr(collector_mod, "get_session", new_get_session)
    monkeypatch.setattr(risk_mod, "get_session", new_get_session)
    monkeypatch.setattr(pb_mod, "get_session", new_get_session)
    monkeypatch.setattr(filter_mod, "get_session", new_get_session)
    monkeypatch.setattr(stealth_mod, "get_session", new_get_session)
    monkeypatch.setattr(strategy_mod, "get_session", new_get_session)
    monkeypatch.setattr(user_mod, "get_session", new_get_session)

    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def isolated_embedded_lock(tmp_path, monkeypatch):
    """Keep the embedded-API singleton guard away from the real .run lock file.

    Without this, any test building ``TestClient(api.main.app)`` would take the
    process-lifetime lock and occupy it for the rest of the test session.

    Bypassing the lock is only half the job: with it out of the way the startup
    lifespan would also run ``reconcile_runtime_state()``, which stops every
    ``running`` task owned by this machine's worker id and deletes its device
    leases. Because the test process reports the same hostname as the live API,
    running the suite while a batch is in flight silently kills it - it did, on
    2026-09-14 (tasks 362-365). Neutralise reconcile for the whole session.
    """
    import api.main as main_module

    monkeypatch.setattr(
        main_module, "_embedded_lock_path", lambda: tmp_path / "embedded-api.lock"
    )
    monkeypatch.setattr(main_module, "_EMBEDDED_LOCK_HANDLE", None)
    monkeypatch.setattr(
        main_module,
        "reconcile_runtime_state",
        lambda: {"stopped_tasks": 0, "released_leases": 0},
    )
    yield


@pytest.fixture(autouse=True)
def no_queue_dispatcher(monkeypatch):
    """Keep the queue dispatcher thread out of the test process.

    ``TestClient(api.main.app)`` runs the real startup lifespan, which now
    starts a background dispatcher. That thread talks to whatever database
    ``config/local.yaml`` points at - the shared production one - and would
    cheerfully create and start a real emulator batch from inside a test run.
    Same class of accident as the reconcile sweep on 2026-09-14, so it is off
    for the whole suite.

    Deliberately not unit-tested: a test asserting "the guard holds" fails by
    doing exactly the thing the guard exists to prevent, and a broken patch
    would then be indistinguishable from a working one.
    """
    monkeypatch.setenv("SUPERCLAW_QUEUE_DISPATCHER", "0")
    yield


@pytest.fixture(autouse=True)
def isolated_db_spool(tmp_path, monkeypatch):
    """Keep engine log spooling out of the real repository and out of each other.

    Most engine tests build ``TaskEngine(..., db_config={})``.  Whenever such a
    test drives a code path that logs, the row cannot reach MySQL and is spooled
    instead - by default into ``logs/db_spool`` in the working tree, where the
    next test would then try to flush it.  Point the spool at ``tmp_path`` and
    forget anything learned about the link so one test's simulated outage cannot
    leak into the next.
    """
    import rpa.hongguo.dbresilience as dbresilience

    monkeypatch.setenv("SUPERCLAW_DB_SPOOL_DIR", str(tmp_path / "db_spool"))
    dbresilience.DB_HEALTH.reset()
    yield
    dbresilience.DB_HEALTH.reset()


@pytest.fixture(autouse=True)
def isolated_device_call_guards():
    """Undo the process-wide device call guards after every test.

    ``connect_exact()`` installs wall-clock deadlines inside uiautomator2 itself
    - it replaces ``AdbHTTPConnection.connect`` and lowers ``HTTP_TIMEOUT`` from
    its 300s default.  That is a deliberate process-global patch, so a test that
    reaches the real ``connect_exact`` would otherwise hand a patched
    uiautomator2 to every test that runs after it.  Put the originals back.
    """
    import rpa.hongguo.device as device_module

    try:
        import uiautomator2.base as u2_base
        import uiautomator2.core as u2_core
    except Exception:  # uiautomator2 is not part of every deployment
        yield
        return

    original_connect = u2_core.AdbHTTPConnection.connect
    original_http_timeout = u2_base.HTTP_TIMEOUT
    original_flag = device_module._device_call_guards_applied
    try:
        yield
    finally:
        u2_core.AdbHTTPConnection.connect = original_connect
        u2_base.HTTP_TIMEOUT = original_http_timeout
        device_module._device_call_guards_applied = original_flag
