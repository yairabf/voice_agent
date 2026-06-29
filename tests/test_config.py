from voice_agent.config.settings import Settings


def test_settings_load_defaults_and_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("DEFAULT_PROFILE", "voice-agent-test")
    monkeypatch.setenv("MAX_SESSIONS", "1")
    monkeypatch.setenv("SESSION_TIMEOUT", "45m")
    monkeypatch.setenv("VOICE_RUNTIME_PORT", "9090")
    monkeypatch.setenv("HERMES_INTEGRATION_MODE", "fake")

    settings = Settings()

    assert settings.default_profile == "voice-agent-test"
    assert settings.max_sessions == 1
    assert settings.session_timeout == "45m"
    assert settings.voice_runtime_port == 9090
    assert settings.hermes_integration_mode == "fake"
