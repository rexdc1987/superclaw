"""The queue / 剧单 endpoints must say "try again" when the link blips mid-query.

``routes_hongguo._connection`` hands a mid-block failure straight to the caller on
purpose, so each handler can decide what it means.  These screens are pure
button-clicking, so ``routes_hongguo_queue._request_connection`` maps a transient
one to 503 - and must leave everything else exactly as it found it:

* a handler-raised ``HTTPException`` (409 "already a queue running", 404 ...) is a
  real answer, not an outage, and has to reach the client unchanged;
* a misconfiguration such as 1045 must stay loud instead of masquerading as 503.

Note the wrapper deliberately does **not** open the process-wide breaker: a single
mid-query 2013 can happen on an otherwise healthy server, and tripping the breaker
there would blanket-503 every other dashboard screen.
"""

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pymysql
from fastapi import HTTPException

from rpa.dashboard import routes_hongguo_queue as routes
from rpa.hongguo import dbresilience

LOST_CONNECTION = pymysql.err.OperationalError(
    2013, "Lost connection to MySQL server during query ([WinError 10054] ...)"
)
ACCESS_DENIED = pymysql.err.OperationalError(1045, "Access denied for user 'superclaw'@'x'")


def _blowing_up(exc: BaseException):
    """A stand-in ``_connection`` that yields once and then raises."""

    @contextmanager
    def _cm():
        yield MagicMock()
        raise exc

    return _cm


def test_a_mid_query_blip_becomes_503_with_a_retry_after(monkeypatch):
    monkeypatch.setattr(routes, "_connection", _blowing_up(LOST_CONNECTION))

    with pytest.raises(HTTPException) as caught:
        with routes._request_connection():
            pass

    assert caught.value.status_code == 503
    assert "OperationalError" in caught.value.detail
    assert caught.value.headers["Retry-After"] == str(
        int(dbresilience.DOWN_PROBE_INTERVAL_SECONDS)
    )


def test_a_handler_raised_http_error_passes_through_untouched(monkeypatch):
    """409/404 from the queue logic is an answer, not an outage."""
    busy = HTTPException(status_code=409, detail="已有一个队列没跑完，请等它结束或先取消")
    monkeypatch.setattr(routes, "_connection", _blowing_up(busy))

    with pytest.raises(HTTPException) as caught:
        with routes._request_connection():
            pass

    assert caught.value.status_code == 409
    assert "队列" in caught.value.detail


def test_a_misconfigured_database_stays_loud(monkeypatch):
    monkeypatch.setattr(routes, "_connection", _blowing_up(ACCESS_DENIED))

    with pytest.raises(pymysql.err.OperationalError) as caught:
        with routes._request_connection():
            pass

    assert caught.value.args[0] == 1045


def test_the_blip_does_not_trip_the_process_wide_breaker(monkeypatch):
    """One mid-query 2013 on a healthy server must not blanket-503 everything."""
    dbresilience.DB_HEALTH.reset()
    monkeypatch.setattr(routes, "_connection", _blowing_up(LOST_CONNECTION))

    with pytest.raises(HTTPException):
        with routes._request_connection():
            pass

    assert dbresilience.DB_HEALTH.is_down() is False


def test_a_healthy_connection_is_handed_straight_through(monkeypatch):
    connection = MagicMock()

    @contextmanager
    def _fine():
        yield connection

    monkeypatch.setattr(routes, "_connection", _fine)

    with routes._request_connection() as conn:
        assert conn is connection


def test_every_queue_endpoint_goes_through_the_wrapper():
    """A new endpoint that keeps the bare ``_connection`` would silently 500."""
    source = Path(routes.__file__).read_text(encoding="utf-8")
    # The wrapper's own body is the only place allowed to call the raw helper.
    # That single assertion is the real invariant: any handler that reached for
    # ``_connection`` directly would push this count past 1.
    assert source.count("with _connection() as conn:") == 1
    # Do not pin this to an exact endpoint count - adding a route is normal work,
    # and pinning it turned a new (correct) endpoint into a false alarm.
    assert source.count("with _request_connection() as conn:") >= 9
    assert "def _request_connection" in source
    _assert_every_connection_handler_uses_the_wrapper(source)


def _assert_every_connection_handler_uses_the_wrapper(source: str) -> None:
    """Walk each route handler and require the wrapper wherever it touches a conn.

    A bare ``_connection()`` in a handler does not crash in tests - it only
    degrades to an unhandled 500 the first time the remote DB blips - so the
    only reliable guard is to read the source and check every handler.
    """
    # Handler bodies start after a raw decorator line and run to the next
    # top-level ``@``/``def``; splitting on route decorators is enough here.
    # Only ``*_router.<verb>(...)`` counts - ``@contextmanager`` decorates the
    # wrapper itself, which is the one legitimate user of the raw helper.
    parts = source.split("\n@")
    checked = 0
    for part in parts[1:]:
        header = part.split("\n", 1)[0]
        if "router." not in header:
            continue
        if not any(m in header for m in (".get(", ".post(", ".put(", ".patch(", ".delete(")):
            continue
        body = part.split("\n@", 1)[0]
        if "conn" not in body:
            continue
        checked += 1
        assert "with _request_connection() as conn:" in body, (
            "route handler opens a connection without the 503 wrapper: " + header
        )
    assert checked >= 9, "expected at least 9 connection-using handlers, saw %d" % checked


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
