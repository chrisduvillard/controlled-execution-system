"""Tests for local runtime adapters."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from ces.execution.runtimes.adapters import ClaudeRuntimeAdapter, CodexRuntimeAdapter


class TestRuntimeAdapterEnvScrubbing:
    """Runtime adapters should not inherit the whole host environment."""

    @patch.dict(
        "os.environ",
        {
            "PATH": "/usr/bin",
            "HOME": "/home/tester",
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
            "OPENAI_API_KEY": "sk-openai",
            "CODEX_HOME": "/home/tester/.codex",
            "AWS_SECRET_ACCESS_KEY": "aws-secret",
            "GITHUB_TOKEN": "ghp-secret",
        },
        clear=True,
    )
    def test_codex_runtime_passes_allowlisted_env(self, tmp_path: Path) -> None:
        adapter = CodexRuntimeAdapter()
        adapter.version = MagicMock(return_value="1.0.0")

        def _run(*args, **kwargs):
            kwargs["stdout"].write(b"ok")
            return SimpleNamespace(returncode=0)

        with (
            patch(
                "ces.execution.runtimes.adapters.subprocess.run",
                side_effect=_run,
            ) as mock_run,
            patch(
                "ces.execution.runtimes.adapters.uuid.uuid4",
                return_value=UUID("12345678-1234-5678-1234-567812345678"),
            ),
        ):
            result = adapter.run_task(
                manifest_description="Implement feature",
                prompt_pack="Prompt pack",
                working_dir=tmp_path,
            )

        assert result.runtime_version == "1.0.0"
        env = mock_run.call_args.kwargs["env"]
        assert env == {
            "PATH": "/usr/bin",
            "HOME": "/home/tester",
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
            "OPENAI_API_KEY": "sk-openai",
            "CODEX_HOME": "/home/tester/.codex",
        }
        command = mock_run.call_args.args[0]
        assert command[0] == "codex"
        assert "-C" in command
        assert str(tmp_path) in command
        assert result.transcript_path is not None
        transcript_path = Path(result.transcript_path)
        assert transcript_path.parent == tmp_path / ".ces" / "runtime-transcripts"
        if os.name != "nt":
            assert stat.S_IMODE(transcript_path.stat().st_mode) == 0o600
            assert stat.S_IMODE(transcript_path.parent.stat().st_mode) == 0o700

    @patch.dict(
        "os.environ",
        {
            "PATH": "/usr/bin",
            "HOME": "/home/tester",
            "LANG": "en_US.UTF-8",
            "ANTHROPIC_API_KEY": "sk-ant-123",
            "CLAUDE_CODE": "1",
            "HTTPS_PROXY": "http://proxy.internal:8080",
            "AWS_SECRET_ACCESS_KEY": "aws-secret",
            "SLACK_BOT_TOKEN": "xoxb-secret",
        },
        clear=True,
    )
    def test_claude_runtime_passes_allowlisted_env(self, tmp_path: Path) -> None:
        adapter = ClaudeRuntimeAdapter()
        adapter.version = MagicMock(return_value="1.0.0")

        def _run(*args, **kwargs):
            kwargs["stdout"].write(b'{"model":"claude-sonnet","result":"done"}')
            return SimpleNamespace(returncode=0)

        with (
            patch(
                "ces.execution.runtimes.adapters.subprocess.run",
                side_effect=_run,
            ) as mock_run,
            patch(
                "ces.execution.runtimes.adapters.uuid.uuid4",
                return_value=UUID("87654321-4321-8765-4321-876543218765"),
            ),
        ):
            result = adapter.run_task(
                manifest_description="Implement feature",
                prompt_pack="Prompt pack",
                working_dir=tmp_path,
            )

        assert result.runtime_version == "1.0.0"
        assert result.reported_model == "claude-sonnet"
        assert result.stdout == "done"
        env = mock_run.call_args.kwargs["env"]
        assert env == {
            "PATH": "/usr/bin",
            "HOME": "/home/tester",
            "LANG": "en_US.UTF-8",
            "ANTHROPIC_API_KEY": "sk-ant-123",
            "CLAUDE_CODE": "1",
            "HTTPS_PROXY": "http://proxy.internal:8080",
        }
        assert mock_run.call_args.kwargs["cwd"] == tmp_path

    @patch.dict(
        "os.environ",
        {
            "PATH": "/usr/bin",
            "HOME": "/home/tester",
        },
        clear=True,
    )
    def test_codex_runtime_caps_message_file_and_stderr(self, tmp_path: Path) -> None:
        adapter = CodexRuntimeAdapter()
        adapter.version = MagicMock(return_value="1.0.0")
        oversized_stdout = "x" * 32
        oversized_stderr = "e" * 32

        def _run(*args, **kwargs):
            kwargs["stderr"].write(oversized_stderr.encode("utf-8"))
            message_path = Path(args[0][-1])
            message_path.write_text(oversized_stdout, encoding="utf-8")
            return SimpleNamespace(returncode=0)

        with (
            patch(
                "ces.execution.runtimes.adapters.subprocess.run",
                side_effect=_run,
            ),
            patch(
                "ces.execution.runtimes.adapters.uuid.uuid4",
                return_value=UUID("12345678-1234-5678-1234-567812345678"),
            ),
            patch("ces.execution.runtimes.adapters._MAX_RUNTIME_OUTPUT_BYTES", 8),
        ):
            result = adapter.run_task(
                manifest_description="Implement feature",
                prompt_pack="Prompt pack",
                working_dir=tmp_path,
            )

        assert result.stdout == "xxxxxxxx\n...[truncated]"
        assert result.stderr == "eeeeeeee\n...[truncated]"
        assert result.transcript_path is not None
        assert Path(result.transcript_path).parent == tmp_path / ".ces" / "runtime-transcripts"

    @patch.dict(
        "os.environ",
        {
            "PATH": "/usr/bin",
            "HOME": "/home/tester",
        },
        clear=True,
    )
    def test_codex_runtime_scrubs_persisted_message_file(self, tmp_path: Path) -> None:
        adapter = CodexRuntimeAdapter()
        adapter.version = MagicMock(return_value="1.0.0")

        def _run(*args, **kwargs):
            message_path = Path(args[0][-1])
            message_path.write_text(
                "done\nOPENAI_API_KEY=sk-openai-secret-value\n",
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0)

        with patch(
            "ces.execution.runtimes.adapters.subprocess.run",
            side_effect=_run,
        ):
            result = adapter.run_task(
                manifest_description="Implement feature",
                prompt_pack="Prompt pack",
                working_dir=tmp_path,
            )

        assert result.transcript_path is not None
        transcript = Path(result.transcript_path).read_text(encoding="utf-8")
        assert "sk-openai-secret-value" not in result.stdout
        assert "sk-openai-secret-value" not in transcript
        assert "OPENAI_API_KEY=<REDACTED>" in result.stdout
        assert transcript == result.stdout
