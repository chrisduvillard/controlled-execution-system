"""Tests for CES local-first configuration management."""

from __future__ import annotations

import pytest

from ces.shared.config import CESSettings


@pytest.fixture(autouse=True)
def _isolate_dotenv_cwd(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep default-setting tests independent of a developer's repo-root .env."""
    monkeypatch.chdir(tmp_path)


class TestCESSettingsDefaults:
    """CESSettings should provide sensible defaults for local use."""

    def test_default_log_level(self) -> None:
        settings = CESSettings()
        assert settings.log_level == "INFO"

    def test_default_log_format(self) -> None:
        settings = CESSettings()
        assert settings.log_format == "json"

    def test_default_runtime(self) -> None:
        settings = CESSettings()
        assert settings.default_runtime == "codex"

    def test_default_model_roster_has_multiple_entries(self) -> None:
        settings = CESSettings()
        assert len(settings.model_roster) >= 3


class TestCESSettingsEnvOverride:
    """CESSettings fields can be overridden via CES_-prefixed environment variables."""

    def test_log_level_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CES_LOG_LEVEL", "DEBUG")
        settings = CESSettings()
        assert settings.log_level == "DEBUG"

    def test_log_format_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CES_LOG_FORMAT", "console")
        settings = CESSettings()
        assert settings.log_format == "console"

    def test_default_runtime_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CES_DEFAULT_RUNTIME", "claude")
        settings = CESSettings()
        assert settings.default_runtime == "claude"


class TestCESSettingsDotenv:
    """CESSettings should load repo-local .env files when present."""

    def test_dotenv_values_are_loaded(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "CES_DEMO_MODE=1\nCES_DEFAULT_RUNTIME=claude\n",
            encoding="utf-8",
        )

        settings = CESSettings()

        assert settings.demo_mode is True
        assert settings.default_runtime == "claude"

    def test_real_environment_overrides_dotenv(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "CES_DEFAULT_RUNTIME=claude\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("CES_DEFAULT_RUNTIME", "codex")

        settings = CESSettings()

        assert settings.default_runtime == "codex"

    def test_non_ces_dotenv_keys_are_ignored(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "OPENAI_API_KEY=sk-test\nCES_DEFAULT_RUNTIME=claude\n",
            encoding="utf-8",
        )

        settings = CESSettings()

        assert settings.default_runtime == "claude"


class TestDemoModeSettings:
    """Demo mode setting tests."""

    def test_demo_mode_defaults_to_false(self) -> None:
        settings = CESSettings()
        assert settings.demo_mode is False

    def test_demo_mode_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CES_DEMO_MODE", "1")
        settings = CESSettings()
        assert settings.demo_mode is True


class TestCESSettingsEnvPrefix:
    """The CES_ prefix must be required -- unprefixed vars should not apply."""

    def test_unprefixed_env_var_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEFAULT_RUNTIME", "claude")
        settings = CESSettings()
        assert settings.default_runtime == "codex"


class TestValidateProductionSecrets:
    """validate_production_secrets() must flag dev defaults and pass through custom secrets."""

    def test_default_hmac_secret_emits_warning(self) -> None:
        settings = CESSettings()
        warnings = settings.validate_production_secrets()
        assert len(warnings) == 1
        assert "CES_AUDIT_HMAC_SECRET" in warnings[0]
        assert "T-07-01" in warnings[0]

    def test_custom_hmac_secret_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CES_AUDIT_HMAC_SECRET", "production-grade-secret-value")
        settings = CESSettings()
        assert settings.validate_production_secrets() == []


class TestEnforceResolvedSecrets:
    """enforce_resolved_secrets() inspects the bytes that will actually be used."""

    def test_real_resolved_secret_passes(self) -> None:
        CESSettings().enforce_resolved_secrets(b"\x00" * 32)

    def test_resolved_secret_with_marker_raises(self) -> None:
        settings = CESSettings()
        bad = b"ces-dev-hmac-secret-do-not-use-in-production"
        with pytest.raises(RuntimeError, match="T-07-01"):
            settings.enforce_resolved_secrets(bad)

    def test_demo_mode_bypasses_enforcement(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CES_DEMO_MODE", "1")
        settings = CESSettings()
        bad = b"ces-dev-hmac-secret-do-not-use-in-production"
        settings.enforce_resolved_secrets(bad)
