"""Tests for the CLI-based LLM provider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from ces.execution.processes import ProcessResult, ProcessTimeoutError
from ces.execution.providers.cli_provider import CLILLMProvider
from ces.execution.providers.protocol import LLMError, LLMProviderProtocol, LLMResponse


@pytest.fixture(autouse=True)
def _resolve_cli_paths():
    """Make CLILLMProvider construction succeed without claude/codex on PATH.

    The provider's __init__ calls shutil.which() and raises FileNotFoundError
    when the tool isn't installed (necessary for Windows .cmd shim resolution).
    Tests in this file mock the subprocess separately, so the path resolution
    just needs to return something truthy.
    """
    with patch("shutil.which", side_effect=lambda tool: f"/usr/bin/{tool}"):
        yield


def _process_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> ProcessResult:
    """Create a managed process result for provider tests."""
    return ProcessResult(
        command=("/usr/bin/claude",),
        exit_code=returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=False,
    )


class TestCLILLMProvider:
    def test_implements_protocol(self) -> None:
        provider = CLILLMProvider(cli_tool="claude")
        assert isinstance(provider, LLMProviderProtocol)

    def test_provider_name_claude(self) -> None:
        provider = CLILLMProvider(cli_tool="claude")
        assert provider.provider_name == "claude-cli"

    def test_provider_name_codex(self) -> None:
        provider = CLILLMProvider(cli_tool="codex")
        assert provider.provider_name == "codex-cli"

    @pytest.mark.asyncio
    async def test_generate_calls_claude_subprocess(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/claude"):
            provider = CLILLMProvider(cli_tool="claude")

        stdout_data = json.dumps(
            {
                "model": "claude-sonnet-4-20250514",
                "result": "The answer is 42.",
            }
        )

        mock_run = AsyncMock(return_value=_process_result(stdout=stdout_data))

        with patch("ces.execution.providers.cli_provider.run_async_command", mock_run):
            response = await provider.generate(
                model_id="claude-cli",
                messages=[{"role": "user", "content": "What is the answer?"}],
            )

        assert isinstance(response, LLMResponse)
        assert response.content == "The answer is 42."
        assert response.model_version == "claude-sonnet-4-20250514"
        assert response.provider_name == "claude-cli"
        assert response.input_tokens > 0
        assert response.output_tokens > 0

        # Verify helper was called with the resolved claude path + -p
        call_kwargs = mock_run.call_args.kwargs
        call_args = mock_run.call_args.args[0]
        assert call_args[0] == "/usr/bin/claude"
        assert "-p" in call_args
        assert call_kwargs["stdin_text"] == "What is the answer?"

    @pytest.mark.asyncio
    async def test_generate_calls_codex_subprocess(self) -> None:
        provider = CLILLMProvider(cli_tool="codex")

        mock_run = AsyncMock(return_value=_process_result(stdout="The answer is 42."))

        with patch("ces.execution.providers.cli_provider.run_async_command", mock_run):
            response = await provider.generate(
                model_id="codex-cli",
                messages=[{"role": "user", "content": "What is the answer?"}],
            )

        assert isinstance(response, LLMResponse)
        assert response.content == "The answer is 42."
        assert response.provider_name == "codex-cli"

    @pytest.mark.asyncio
    async def test_generate_handles_non_json_claude_output(self) -> None:
        """When claude returns plain text instead of JSON, use it as-is."""
        provider = CLILLMProvider(cli_tool="claude")

        mock_run = AsyncMock(return_value=_process_result(stdout="Plain text response"))

        with patch("ces.execution.providers.cli_provider.run_async_command", mock_run):
            response = await provider.generate(
                model_id="claude-cli",
                messages=[{"role": "user", "content": "Hello"}],
            )

        assert response.content == "Plain text response"

    @pytest.mark.asyncio
    async def test_generate_raises_on_nonzero_exit(self) -> None:
        provider = CLILLMProvider(cli_tool="claude")

        mock_run = AsyncMock(return_value=_process_result(returncode=1, stderr="Authentication failed"))

        with (
            patch("ces.execution.providers.cli_provider.run_async_command", mock_run),
            pytest.raises(LLMError, match="CLI command failed"),
        ):
            await provider.generate(
                model_id="claude-cli",
                messages=[{"role": "user", "content": "Hello"}],
            )

    @pytest.mark.asyncio
    async def test_generate_redacts_secret_like_stderr_on_nonzero_exit(self) -> None:
        provider = CLILLMProvider(cli_tool="claude")
        token = "ghp" + "_" + "syntheticexamplevalue123"
        api_key = "sk" + "-" + "syntheticexamplevalue123"

        mock_run = AsyncMock(
            return_value=_process_result(
                returncode=1,
                stderr=f"failed with GITHUB_TOKEN={token} OPENAI_API_KEY={api_key}",
            )
        )

        with (
            patch("ces.execution.providers.cli_provider.run_async_command", mock_run),
            pytest.raises(LLMError) as exc_info,
        ):
            await provider.generate(
                model_id="claude-cli",
                messages=[{"role": "user", "content": "Hello"}],
            )

        message = str(exc_info.value)
        assert token not in message
        assert api_key not in message
        assert "GITHUB_TOKEN=<REDACTED>" in message
        assert "OPENAI_API_KEY=<REDACTED>" in message

    @pytest.mark.asyncio
    async def test_generate_raises_on_timeout(self) -> None:
        provider = CLILLMProvider(cli_tool="claude", timeout=1)

        timeout = ProcessTimeoutError(
            "timeout",
            ProcessResult(("/usr/bin/claude",), 124, "", "", timed_out=True),
        )
        mock_run = AsyncMock(side_effect=timeout)

        with (
            patch("ces.execution.providers.cli_provider.run_async_command", mock_run),
            pytest.raises(LLMError, match="timed out"),
        ):
            await provider.generate(
                model_id="claude-cli",
                messages=[{"role": "user", "content": "Hello"}],
            )

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
    @pytest.mark.asyncio
    async def test_generate_formats_assistant_role(self) -> None:
        # filterwarnings above: on CPython 3.12 (CI runner), AsyncMock's
        # interaction with asyncio.wait_for can leave a stray AsyncMock
        # internal coroutine that Python flags at GC time. The behavior
        # is test-scaffolding-specific (not a production bug) and does
        # not reproduce on 3.13. Silence to keep `pytest -W error` green.
        provider = CLILLMProvider(cli_tool="claude")

        stdout_data = json.dumps({"result": "OK"})
        mock_run = AsyncMock(return_value=_process_result(stdout=stdout_data))

        with patch("ces.execution.providers.cli_provider.run_async_command", mock_run):
            await provider.generate(
                model_id="claude-cli",
                messages=[
                    {"role": "system", "content": "Be helpful"},
                    {"role": "assistant", "content": "Previous response"},
                    {"role": "user", "content": "Follow up"},
                ],
            )

        # Check the prompt includes the assistant role (passed via stdin)
        prompt_text = mock_run.call_args.kwargs["stdin_text"]
        assert "[Assistant]" in prompt_text

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self) -> None:
        provider = CLILLMProvider(cli_tool="claude")

        stdout_data = json.dumps({"result": "Streamed response text"})
        mock_run = AsyncMock(return_value=_process_result(stdout=stdout_data))

        with patch("ces.execution.providers.cli_provider.run_async_command", mock_run):
            chunks: list[str] = []
            async for chunk in provider.stream(
                model_id="claude-cli",
                messages=[{"role": "user", "content": "Hello"}],
            ):
                chunks.append(chunk)

        full_text = "".join(chunks)
        assert "Streamed response text" in full_text

    def test_format_prompt_combines_messages(self) -> None:
        provider = CLILLMProvider(cli_tool="claude")
        messages = [
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": "Do the thing."},
        ]
        prompt = provider._format_prompt(messages)
        assert "You are a helper." in prompt
        assert "Do the thing." in prompt


class TestCLIBuildCommand:
    def test_claude_command_includes_allowed_tools(self) -> None:
        provider = CLILLMProvider(cli_tool="claude")
        cmd = provider._build_command()
        assert "--allowedTools" in cmd

    def test_claude_command_includes_add_dir(self) -> None:
        provider = CLILLMProvider(cli_tool="claude")
        cmd = provider._build_command()
        assert "--add-dir" in cmd

    def test_codex_command_minimal(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/codex"):
            provider = CLILLMProvider(cli_tool="codex")
        cmd = provider._build_command()
        assert cmd == ["/usr/bin/codex", "exec"]
