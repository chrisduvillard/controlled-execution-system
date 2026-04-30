"""Tests that CES_DEMO_MODE is surfaced to new users on build and no-provider errors."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


class TestBuildHelpMentionsDemoMode:
    """`ces build --help` should advertise CES_DEMO_MODE for offline trial."""

    def test_build_help_mentions_demo_mode(self, tmp_path: Path, monkeypatch: object) -> None:
        """Running `ces build --help` includes a reference to CES_DEMO_MODE."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["build", "--help"], env={"COLUMNS": "200"})
        assert result.exit_code == 0
        assert "CES_DEMO_MODE" in result.stdout


class TestNullProviderErrorMentionsDemoMode:
    """The `_NullLLMProvider.generate` RuntimeError should mention CES_DEMO_MODE."""

    def test_null_provider_error_mentions_demo_mode(self) -> None:
        """When no provider is configured, the error message hints at demo mode."""
        import asyncio

        import pytest

        from ces.cli._factory import _NullLLMProvider

        provider = _NullLLMProvider()

        async def _trigger() -> None:
            await provider.generate("any-model", [{"role": "user", "content": "hi"}])

        with pytest.raises(RuntimeError, match="CES_DEMO_MODE"):
            asyncio.run(_trigger())
