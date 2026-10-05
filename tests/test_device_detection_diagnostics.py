"""Regression tests: a failed device detection must never look like a
successful empty one.

Background. The 红果多开 page used to read only ``online_count`` from
``GET /api/v1/hongguo/multi/devices`` and then always toast a green
"检测完成：在线 0 台". Two independent faults made that misleading:

1. the endpoint reports internal failures as HTTP 200 + ``success: false``, and
   the view ignored the flag entirely;
2. ``device._discover_addrs()`` swallowed every exception with a bare
   ``except Exception: return []``, so "the ADB server is wedged" produced the
   exact same result - and the same log line - as "this machine has no
   emulator".

These tests pin the contract that lets the UI tell the difference:
``success`` for hard failures, and ``reason``/``reason_text`` plus
``diagnostics`` for a legitimate zero.
"""
import contextlib
from unittest.mock import MagicMock, patch

import pytest

from rpa.hongguo import device as device_module


@pytest.fixture(autouse=True)
def _reset_discovery_errors():
    """The last-error globals are process-wide, so isolation is on us."""
    device_module._LAST_ADB_ERROR = None
    device_module._LAST_MANAGER_ERROR = None
    yield
    device_module._LAST_ADB_ERROR = None
    device_module._LAST_MANAGER_ERROR = None


# --------------------------------------------------------------------------
# device.py: discovery failures must be observable
# --------------------------------------------------------------------------
def test_discover_addrs_keeps_contract_but_records_the_reason():
    with patch.object(
        device_module, "call_with_timeout", side_effect=RuntimeError("adb server is wedged")
    ):
        addrs = device_module._discover_addrs()

    # Existing callers still get a plain empty list (behaviour unchanged).
    assert addrs == []
    error = device_module.discovery_diagnostics()["adb_error"]
    assert "adb server is wedged" in (error or "")


def test_discover_addrs_clears_the_reason_once_adb_recovers():
    with patch.object(device_module, "call_with_timeout", side_effect=RuntimeError("boom")):
        device_module._discover_addrs()
    assert device_module.discovery_diagnostics()["adb_error"] is not None

    with patch.object(device_module, "call_with_timeout", return_value=["127.0.0.1:16416"]):
        assert device_module._discover_addrs() == ["127.0.0.1:16416"]
    assert device_module.discovery_diagnostics()["adb_error"] is None


def test_missing_mumu_manager_records_an_actionable_hint():
    with patch.object(device_module, "_mumu_manager_path", return_value=None):
        result = device_module._run_mumu_manager(["info", "--vmindex", "all"])

    assert result["success"] is False
    error = device_module.discovery_diagnostics()["mumu_manager_error"] or ""
    assert "MuMuManager" in error
    # The hint must name the env var, otherwise the operator cannot act on it.
    assert "SUPERCLAW_MUMU_ROOT" in error


def test_mumu_manager_nonzero_exit_is_recorded():
    fake_proc = MagicMock(returncode=1, stdout="", stderr="vm not ready")
    with patch.object(device_module, "_mumu_manager_path", return_value=MagicMock()):
        with patch.object(device_module, "call_with_timeout", return_value=fake_proc):
            result = device_module._run_mumu_manager(["info", "--vmindex", "all"])

    assert result["success"] is False
    assert "vm not ready" in (device_module.discovery_diagnostics()["mumu_manager_error"] or "")


def test_diagnostics_expose_environment_without_secrets():
    diagnostics = device_module.discovery_diagnostics()
    assert set(diagnostics) == {
        "adb_error",
        "mumu_manager_error",
        "mumu_root",
        "mumu_root_exists",
        "mumu_manager_path",
        "adb_path",
    }


# --------------------------------------------------------------------------
# routes_hongguo.py: a zero result must explain itself
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload,instances,expected",
    [
        (
            {"online_count": 0, "remote_workers": True, "diagnostics": {}},
            None,
            "no_online_worker",
        ),
        (
            {"online_count": 0, "diagnostics": {"adb_error": "RuntimeError: wedged"}},
            [{"index": "1"}],
            "adb_unavailable",
        ),
        (
            {"online_count": 0, "diagnostics": {"mumu_manager_error": "退出码 1"}},
            [{"index": "1"}],
            "mumu_manager_unavailable",
        ),
        ({"online_count": 0, "diagnostics": {}}, [], "mumu_not_found"),
        (
            {"online_count": 0, "devices": [{"status": "adb_not_ready"}], "diagnostics": {}},
            [{"index": "1"}],
            "adb_not_ready",
        ),
        (
            {"online_count": 0, "devices": [{"status": "online"}], "diagnostics": {}},
            [{"index": "1"}],
            "no_online_device",
        ),
    ],
)
def test_zero_device_result_carries_a_reason(payload, instances, expected):
    from rpa.dashboard import routes_hongguo

    result = routes_hongguo._annotate_detection_reason(dict(payload), instances)
    assert result["reason"] == expected
    assert result["reason_text"]


def test_healthy_result_gains_no_reason():
    from rpa.dashboard import routes_hongguo

    result = routes_hongguo._annotate_detection_reason({"online_count": 2}, [{"index": "1"}])
    assert "reason" not in result
    assert "reason_text" not in result


def test_uncached_detection_reports_its_source():
    from rpa.dashboard import routes_hongguo

    instances = [{"index": "1", "name": "Xiaomi14", "addr": "127.0.0.1:16416"}]

    def fake_check(addr, mumu=None, timeout=0):
        return {"addr": addr, "online": True, "logged_in": True, "status": "logged_in"}

    with patch.object(routes_hongguo, "discover_mumu_instances", return_value=instances):
        with patch.object(routes_hongguo, "discover_online_addrs", return_value=[]):
            with patch.object(routes_hongguo, "_safe_check_login_for_device", side_effect=fake_check):
                result = routes_hongguo._detect_multi_devices_uncached()

    assert result["device_source"] == "local_mumu"
    assert result["online_count"] == 1
    assert not result.get("reason")
    assert isinstance(result["diagnostics"], dict)


def test_control_plane_zero_devices_explains_the_mode(monkeypatch):
    from rpa.dashboard import routes_hongguo

    monkeypatch.setenv("SUPERCLAW_EXECUTION_MODE", "api")
    conn_ctx = MagicMock()
    conn_ctx.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchall.return_value = []

    with patch.object(routes_hongguo, "_connection", return_value=conn_ctx):
        with patch.object(
            routes_hongguo, "_apply_device_lease_visibility", side_effect=lambda value: dict(value)
        ):
            result = routes_hongguo._list_registered_worker_devices()

    # Not a failure - the request worked, this instance just never looks at
    # local MuMu. But it must not be silent either.
    assert result["success"] is True
    assert result["device_source"] == "remote_workers"
    assert result["online_count"] == 0
    assert result["reason"] == "no_online_worker"
    assert "embedded" in result["reason_text"]


def test_endpoint_error_is_not_reported_as_success(monkeypatch):
    from rpa.dashboard import routes_hongguo

    monkeypatch.setenv("SUPERCLAW_EXECUTION_MODE", "api")

    @contextlib.contextmanager
    def failing_connection():
        raise RuntimeError("MySQL server has gone away")

    with patch.object(routes_hongguo, "_connection", failing_connection):
        result = routes_hongguo.list_multi_devices()

    assert result["success"] is False
    assert result["reason"] == "backend_error"
    assert result["online_count"] == 0
    assert "MySQL" in result["database_error"]
    # The UI reads this to render the failure instead of a green toast.
    assert result["reason_text"]
