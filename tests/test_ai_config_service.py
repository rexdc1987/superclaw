"""Regression tests for AI secret precedence."""

from services import ai_config_service


def test_saved_api_key_takes_priority_over_environment(monkeypatch):
    monkeypatch.setenv("XIAOMI_API_KEY", "stale-environment-key")
    monkeypatch.setattr(
        ai_config_service,
        "app_config",
        lambda: {
            "ai": {
                "api_key_env": "XIAOMI_API_KEY",
                "api_key": "saved-settings-key",
            }
        },
    )

    assert ai_config_service.ai_config()["api_key"] == "saved-settings-key"


def test_environment_api_key_is_used_when_no_key_is_saved(monkeypatch):
    monkeypatch.setenv("XIAOMI_API_KEY", "environment-key")
    monkeypatch.setattr(
        ai_config_service,
        "app_config",
        lambda: {"ai": {"api_key_env": "XIAOMI_API_KEY"}},
    )

    assert ai_config_service.ai_config()["api_key"] == "environment-key"


def test_public_settings_reports_saved_key_as_configured(monkeypatch):
    monkeypatch.delenv("XIAOMI_API_KEY", raising=False)

    settings = ai_config_service.public_ai_settings(
        {"api_key_env": "XIAOMI_API_KEY", "api_key": "saved-settings-key"}
    )

    assert settings["api_key_configured"] is True
