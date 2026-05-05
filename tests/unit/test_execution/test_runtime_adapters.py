"""Tests for local runtime adapters."""

from __future__ import annotations

import os
import signal
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from ces.execution.runtimes.adapters import ClaudeRuntimeAdapter, CodexRuntimeAdapter


def _completed_process(returncode: int = 0) -> MagicMock:
    process = MagicMock()
    process.pid = 12345
    process.communicate.return_value = (None, None)
    process.returncode = returncode
    process.poll.return_value = returncode
    return process


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

        def _popen(*args, **kwargs):
            kwargs["stdout"].write(b"ok")
            return _completed_process()

        with (
            patch(
                "ces.execution.runtimes.adapters.subprocess.Popen",
                side_effect=_popen,
            ) as mock_popen,
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
        env = mock_popen.call_args.kwargs["env"]
        assert env == {
            "PATH": "/usr/bin",
            "HOME": "/home/tester",
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
            "OPENAI_API_KEY": "sk-openai",
            "CODEX_HOME": "/home/tester/.codex",
        }
        command = mock_popen.call_args.args[0]
        assert command[0] == "codex"
        assert "-C" in command
        assert str(tmp_path) in command
        sandbox_index = command.index("--sandbox")
        assert command[sandbox_index + 1] == "danger-full-access"
        assert "workspace-write" not in command
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

        def _popen(*args, **kwargs):
            kwargs["stdout"].write(b'{"model":"claude-sonnet","result":"done"}')
            return _completed_process()

        with (
            patch(
                "ces.execution.runtimes.adapters.subprocess.Popen",
                side_effect=_popen,
            ) as mock_popen,
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
        env = mock_popen.call_args.kwargs["env"]
        assert env == {
            "PATH": "/usr/bin",
            "HOME": "/home/tester",
            "LANG": "en_US.UTF-8",
            "ANTHROPIC_API_KEY": "sk-ant-123",
            "CLAUDE_CODE": "1",
            "HTTPS_PROXY": "http://proxy.internal:8080",
        }
        assert mock_popen.call_args.kwargs["cwd"] == tmp_path

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

        def _popen(*args, **kwargs):
            kwargs["stderr"].write(oversized_stderr.encode("utf-8"))
            message_path = Path(args[0][-1])
            message_path.write_text(oversized_stdout, encoding="utf-8")
            return _completed_process()

        with (
            patch(
                "ces.execution.runtimes.adapters.subprocess.Popen",
                side_effect=_popen,
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
            "CES_RUNTIME_TIMEOUT_SECONDS": "7",
        },
        clear=True,
    )
    def test_runtime_adapters_pass_configured_timeout_to_subprocess(self, tmp_path: Path) -> None:
        adapter = CodexRuntimeAdapter()
        adapter.version = MagicMock(return_value="1.0.0")
        process = _completed_process()

        def _popen(*args, **kwargs):
            kwargs["stdout"].write(b"ok")
            return process

        with patch(
            "ces.execution.runtimes.adapters.subprocess.Popen",
            side_effect=_popen,
        ) as mock_popen:
            adapter.run_task(
                manifest_description="Implement feature",
                prompt_pack="Prompt pack",
                working_dir=tmp_path,
            )

        process.communicate.assert_called_once_with(timeout=7)
        assert mock_popen.call_args.kwargs["start_new_session"] is True
        assert mock_popen.call_args.kwargs["stdin"] == subprocess.DEVNULL

    @patch.dict(
        "os.environ",
        {
            "PATH": "/usr/bin",
            "HOME": "/home/tester",
        },
        clear=True,
    )
    def test_runtime_adapters_do_not_inherit_stdin(self, tmp_path: Path) -> None:
        adapter = CodexRuntimeAdapter()
        adapter.version = MagicMock(return_value="1.0.0")

        def _popen(*args, **kwargs):
            kwargs["stdout"].write(b"ok")
            return _completed_process()

        with patch(
            "ces.execution.runtimes.adapters.subprocess.Popen",
            side_effect=_popen,
        ) as mock_popen:
            adapter.run_task(
                manifest_description="Implement feature",
                prompt_pack="Prompt pack",
                working_dir=tmp_path,
            )

        assert mock_popen.call_args.kwargs["stdin"] == subprocess.DEVNULL

    @patch.dict(
        "os.environ",
        {
            "PATH": "/usr/bin",
            "HOME": "/home/tester",
            "CES_RUNTIME_TIMEOUT_SECONDS": "3",
        },
        clear=True,
    )
    def test_codex_runtime_timeout_returns_actionable_failure(self, tmp_path: Path) -> None:
        adapter = CodexRuntimeAdapter()
        adapter.version = MagicMock(return_value="1.0.0")

        process = MagicMock()
        process.pid = 4242
        process.communicate.side_effect = subprocess.TimeoutExpired(cmd=["codex"], timeout=3)
        process.poll.return_value = None
        process.wait.return_value = None

        def _popen(*args, **kwargs):
            kwargs["stderr"].write(b"partial stderr before hang")
            return process

        with (
            patch("ces.execution.runtimes.adapters.subprocess.Popen", side_effect=_popen),
            patch("ces.execution.runtimes.adapters.os.getpgid", return_value=9001) as mock_getpgid,
            patch("ces.execution.runtimes.adapters.os.killpg") as mock_killpg,
        ):
            result = adapter.run_task(
                manifest_description="Implement feature",
                prompt_pack="Prompt pack",
                working_dir=tmp_path,
            )

        assert result.exit_code == 124
        assert "timed out after 3 seconds" in result.stderr
        assert "partial stderr before hang" in result.stderr
        assert result.transcript_path is not None
        mock_getpgid.assert_called_once_with(4242)
        assert mock_killpg.call_args_list[0].args == (9001, signal.SIGTERM)

    @patch.dict(
        "os.environ",
        {
            "PATH": "/usr/bin",
            "HOME": "/home/tester",
        },
        clear=True,
    )
    def test_codex_runtime_sigterm_cleans_process_group_before_exiting(self, tmp_path: Path) -> None:
        adapter = CodexRuntimeAdapter()
        adapter.version = MagicMock(return_value="1.0.0")
        installed_handlers: dict[int, object] = {}

        process = MagicMock()
        process.pid = 5151
        process.poll.return_value = None
        process.wait.return_value = None

        def _communicate(*, timeout: int):
            del timeout
            handler = installed_handlers[signal.SIGTERM]
            assert callable(handler)
            handler(signal.SIGTERM, None)
            raise AssertionError("SIGTERM handler should exit before communicate returns")

        process.communicate.side_effect = _communicate

        def _signal(signum: int, handler: object) -> object:
            previous = installed_handlers.get(signum, signal.SIG_DFL)
            installed_handlers[signum] = handler
            return previous

        with (
            patch("ces.execution.runtimes.adapters.subprocess.Popen", return_value=process),
            patch("ces.execution.runtimes.adapters.signal.signal", side_effect=_signal),
            patch("ces.execution.runtimes.adapters.os.getpgid", return_value=9002) as mock_getpgid,
            patch("ces.execution.runtimes.adapters.os.killpg") as mock_killpg,
            pytest.raises(SystemExit) as raised,
        ):
            adapter.run_task(
                manifest_description="Implement feature",
                prompt_pack="Prompt pack",
                working_dir=tmp_path,
            )

        assert raised.value.code == 128 + signal.SIGTERM
        mock_getpgid.assert_called_once_with(5151)
        assert mock_killpg.call_args_list[0].args == (9002, signal.SIGTERM)

    def test_process_group_cleanup_kills_surviving_descendants_after_leader_exits(self) -> None:
        process = MagicMock()
        process.pid = 6262
        process.poll.return_value = 0
        process.wait.return_value = None

        clock = iter([0.0, 0.1, 5.1, 5.2, 10.3])

        with (
            patch("ces.execution.runtimes.adapters.os.killpg") as mock_killpg,
            patch("ces.execution.runtimes.adapters.time.monotonic", side_effect=lambda: next(clock)),
            patch("ces.execution.runtimes.adapters.time.sleep"),
        ):
            CodexRuntimeAdapter._terminate_process_tree(process, 9003)

        assert mock_killpg.call_args_list[0].args == (9003, signal.SIGTERM)
        assert (9003, signal.SIGKILL) in [call.args for call in mock_killpg.call_args_list]

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
        secret_key = "OPENAI" + "_API_KEY"
        secret_value = "sk-" + "openai-secret-value"

        def _popen(*args, **kwargs):
            message_path = Path(args[0][-1])
            message_path.write_text(f"done\n{secret_key}={secret_value}", encoding="utf-8")
            return _completed_process()

        with patch(
            "ces.execution.runtimes.adapters.subprocess.Popen",
            side_effect=_popen,
        ):
            result = adapter.run_task(
                manifest_description="Implement feature",
                prompt_pack="Prompt pack",
                working_dir=tmp_path,
            )

        assert result.transcript_path is not None
        transcript = Path(result.transcript_path).read_text(encoding="utf-8")
        assert secret_value not in result.stdout
        assert secret_value not in transcript
        assert secret_key in result.stdout
        assert transcript == result.stdout
