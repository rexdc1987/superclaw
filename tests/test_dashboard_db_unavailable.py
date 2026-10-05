"""The dashboard must degrade cleanly when the shared MySQL link blips.

On 2026-09-18 a single ``2003 timed out`` turned ``GET /api/v1/hongguo/tasks``
into a 500 while the request issued right next to it returned 200.  A transient
blip is not a server bug, so the handler has to say "try again shortly" instead
of spilling a traceback, and it must not pay a fresh connect timeout per request
while the link is known to be down - ``list_tasks`` is one of the ``async``
handlers here, so that stall would freeze the event loop for every other client.

These tests pin three things:

* an open breaker short-circuits to 503 **without opening a socket**;
* a transient connect failure becomes 503, not 500;
* a *misconfigured* database still raises loudly (masking that would turn
  "wrong password" into a misleading "try again later").
"""

import sys
from pathlib import Path

from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pymysql
from fastapi import HTTPException

from rpa.dashboard import routes_hongguo
from rpa.hongguo import dbresilience

CANNOT_CONNECT = pymysql.err.OperationalError(
    2003, "Can't connect to MySQL server on '43.154.184.208' (timed out)"
)
ACCESS_DENIED = pymysql.err.OperationalError(1045, "Access denied for user 'superclaw'@'x'")


@pytest.fixture(autouse=True)
def schema_already_ready(monkeypatch):
    """Skip the one-time bootstrap so a mocked connection sees no DDL."""
    monkeypatch.setattr(routes_hongguo, "_schema_ready", True)
    monkeypatch.setattr(routes_hongguo, "_db_config", lambda: {})


def test_an_open_breaker_answers_503_without_opening_a_socket():
    dbresilience.DB_HEALTH.mark_down(CANNOT_CONNECT)

    with patch.object(dbresilience, "resilient_connect") as connect:
        with pytest.raises(HTTPException) as caught:
            with routes_hongguo._connection():
                pass

    assert caught.value.status_code == 503
    assert connect.call_count == 0
    assert caught.value.headers["Retry-After"] == str(
        int(dbresilience.DOWN_PROBE_INTERVAL_SECONDS)
    )


def test_a_transient_connect_failure_answers_503_instead_of_a_traceback():
    with patch.object(dbresilience, "resilient_connect", side_effect=CANNOT_CONNECT):
        with pytest.raises(HTTPException) as caught:
            with routes_hongguo._connection():
                pass

    assert caught.value.status_code == 503
    assert "OperationalError" in caught.value.detail


def test_a_misconfigured_database_is_still_loud():
    """Wrong credentials are not an outage - they must never read as 503."""
    with patch.object(dbresilience, "resilient_connect", side_effect=ACCESS_DENIED):
        with pytest.raises(pymysql.err.OperationalError) as caught:
            with routes_hongguo._connection():
                pass

    assert caught.value.args[0] == 1045


def test_the_dashboard_borrows_the_process_wide_breaker():
    """One breaker for the API and every task thread, not a private one."""
    connection = MagicMock()

    with patch.object(dbresilience, "resilient_connect", return_value=connection) as connect:
        with routes_hongguo._connection() as conn:
            assert conn is connection

    connect.assert_called_once()
    connection.commit.assert_called_once()
    connection.close.assert_called_once()


def test_the_caller_can_still_see_a_transient_error_from_inside_the_block():
    """A link that dies mid-query must surface as-is for the handler to map."""
    connection = MagicMock()
    connection.commit.side_effect = pymysql.err.OperationalError(2013, "lost")

    with patch.object(dbresilience, "resilient_connect", return_value=connection):
        with pytest.raises(pymysql.err.OperationalError):
            with routes_hongguo._connection():
                pass

    connection.rollback.assert_called_once()
