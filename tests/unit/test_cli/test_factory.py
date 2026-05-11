"""Tests for the CLI service factory."""

from __future__ import annotations

import pytest


class TestGetSettings:
    def test_get_settings_returns_ces_settings(self) -> None:
        from ces.cli._factory import get_settings
        from ces.shared.config import CESSettings

        settings = get_settings()
        assert isinstance(settings, CESSettings)

    def test_get_settings_has_core_local_fields(self) -> None:
        from ces.cli._factory import get_settings

        settings = get_settings()
        assert hasattr(settings, "audit_hmac_secret")
        assert hasattr(settings, "default_model_id")
        assert hasattr(settings, "default_runtime")
        assert len(settings.model_roster) >= 3

    def test_get_settings_loads_project_root_dotenv_from_subdirectory(self, tmp_path, monkeypatch) -> None:
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "config.yaml").write_text(
            "project_name: test\nproject_id: proj-test\n",
            encoding="utf-8",
        )
        (tmp_path / ".env").write_text(
            "CES_DEMO_MODE=1\nCES_DEFAULT_RUNTIME=claude\n",
            encoding="utf-8",
        )
        nested = tmp_path / "src" / "pkg"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        from ces.cli._factory import get_settings

        settings = get_settings()

        assert settings.default_runtime == "claude"
        assert settings.demo_mode is True


class TestNullLLMProvider:
    def test_provider_name_is_null(self) -> None:
        from ces.cli._factory import _NullLLMProvider

        provider = _NullLLMProvider()
        assert provider.provider_name == "null"

    @pytest.mark.asyncio
    async def test_generate_raises_runtime_error(self) -> None:
        from ces.cli._factory import _NullLLMProvider

        provider = _NullLLMProvider()
        with pytest.raises(RuntimeError, match="No LLM provider configured"):
            await provider.generate(model_id="test", messages=[])

    @pytest.mark.asyncio
    async def test_stream_raises_runtime_error(self) -> None:
        from ces.cli._factory import _NullLLMProvider

        provider = _NullLLMProvider()
        with pytest.raises(RuntimeError, match="No LLM provider configured"):
            async for _chunk in provider.stream(model_id="test", messages=[]):
                pass


class TestGetServices:
    @pytest.mark.asyncio
    async def test_local_services_dict_has_expected_keys(self, tmp_path, monkeypatch) -> None:
        import yaml

        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "keys").mkdir()
        (ces_dir / "artifacts").mkdir()
        (ces_dir / "state.db").touch()
        with open(ces_dir / "config.yaml", "w") as f:
            yaml.safe_dump(
                {
                    "project_name": "test",
                    "project_id": "proj-test",
                    "preferred_runtime": None,
                },
                f,
            )

        monkeypatch.chdir(tmp_path)

        from ces.cli._factory import get_services

        async with get_services() as services:
            expected_keys = {
                "settings",
                "manifest_manager",
                "audit_ledger",
                "classification_engine",
                "classification_oracle",
                "trust_manager",
                "review_router",
                "evidence_synthesizer",
                "gate_evaluator",
                "kill_switch",
                "intake_engine",
                "vault_service",
                "emergency_service",
                "hidden_check_engine",
                "sensor_orchestrator",
                "merge_controller",
                "guide_pack_builder",
                "note_ranker",
                "legacy_behavior_service",
                "provider_registry",
                "runtime_registry",
                "agent_runner",
                "completion_verifier",
                "self_correction_manager",
                "framework_reminder_builder",
                "local_store",
                "project_config",
            }
            assert set(services.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_services_use_project_root_when_called_from_subdirectory(self, tmp_path, monkeypatch) -> None:
        import yaml

        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "keys").mkdir()
        (ces_dir / "artifacts").mkdir()
        (ces_dir / "state.db").touch()
        with open(ces_dir / "config.yaml", "w") as f:
            yaml.safe_dump(
                {
                    "project_name": "test",
                    "project_id": "proj-test",
                    "preferred_runtime": None,
                },
                f,
            )
        nested = tmp_path / "src" / "pkg"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        from ces.cli._factory import get_services

        async with get_services() as services:
            store = services["local_store"]
            assert store._db_path == ces_dir / "state.db"

        assert not (nested / ".ces").exists()

    @pytest.mark.asyncio
    async def test_get_services_closes_local_store_on_exit(self, tmp_path, monkeypatch) -> None:
        import sqlite3

        import yaml

        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "keys").mkdir()
        (ces_dir / "artifacts").mkdir()
        (ces_dir / "state.db").touch()
        with open(ces_dir / "config.yaml", "w") as f:
            yaml.safe_dump(
                {
                    "project_name": "test",
                    "project_id": "proj-test",
                    "preferred_runtime": None,
                },
                f,
            )
        monkeypatch.chdir(tmp_path)

        from ces.cli._factory import get_services

        async with get_services() as services:
            store = services["local_store"]

        with pytest.raises(sqlite3.ProgrammingError):
            store.get_project_settings()

    @pytest.mark.asyncio
    async def test_server_mode_config_raises_explicit_error(self, tmp_path, monkeypatch) -> None:
        import yaml

        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "keys").mkdir()
        (ces_dir / "artifacts").mkdir()
        (ces_dir / "state.db").touch()
        with open(ces_dir / "config.yaml", "w") as f:
            yaml.safe_dump(
                {
                    "project_name": "test",
                    "project_id": "proj-test",
                    "execution_mode": "server",
                },
                f,
            )

        monkeypatch.chdir(tmp_path)

        from ces.cli._factory import get_services

        with pytest.raises(RuntimeError, match="server mode is no longer supported"):
            async with get_services():
                pass


class TestDemoModeFactory:
    @pytest.mark.asyncio
    async def test_demo_mode_registers_demo_provider(self, tmp_path, monkeypatch) -> None:
        import yaml

        from ces.execution.providers.demo_provider import DemoLLMProvider

        monkeypatch.setenv("CES_DEMO_MODE", "1")
        monkeypatch.setattr("ces.execution.providers.cli_provider.shutil.which", lambda _name: None)

        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "keys").mkdir()
        (ces_dir / "artifacts").mkdir()
        (ces_dir / "state.db").touch()
        with open(ces_dir / "config.yaml", "w") as f:
            yaml.safe_dump(
                {
                    "project_name": "test",
                    "project_id": "proj-test",
                    "preferred_runtime": None,
                },
                f,
            )

        monkeypatch.chdir(tmp_path)

        from ces.cli._factory import get_services

        async with get_services() as services:
            registry = services["provider_registry"]
            provider = registry.get_provider("demo")
            assert isinstance(provider, DemoLLMProvider)

    @pytest.mark.asyncio
    async def test_no_demo_mode_uses_null_provider(self, tmp_path, monkeypatch) -> None:
        import yaml

        from ces.cli._factory import get_services

        monkeypatch.delenv("CES_DEMO_MODE", raising=False)
        monkeypatch.setattr("ces.execution.providers.cli_provider.shutil.which", lambda _name: None)

        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "keys").mkdir()
        (ces_dir / "artifacts").mkdir()
        (ces_dir / "state.db").touch()
        with open(ces_dir / "config.yaml", "w") as f:
            yaml.safe_dump(
                {
                    "project_name": "test",
                    "project_id": "proj-test",
                    "preferred_runtime": None,
                },
                f,
            )

        monkeypatch.chdir(tmp_path)

        async with get_services() as services:
            assert services["provider_registry"].list_models() == []


class TestLocalStoreWiring:
    @pytest.mark.asyncio
    async def test_local_services_include_merge_controller_and_note_ranker(self, tmp_path, monkeypatch) -> None:
        import yaml

        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "keys").mkdir()
        (ces_dir / "artifacts").mkdir()
        (ces_dir / "state.db").touch()
        with open(ces_dir / "config.yaml", "w") as f:
            yaml.safe_dump(
                {
                    "project_name": "test",
                    "project_id": "proj-test",
                    "preferred_runtime": None,
                },
                f,
            )

        monkeypatch.chdir(tmp_path)

        from ces.cli._factory import get_services
        from ces.knowledge.services.note_ranker import NoteRanker

        async with get_services() as services:
            assert services["merge_controller"] is not None
            assert services["guide_pack_builder"] is not None
            assert services["note_ranker"] is NoteRanker
