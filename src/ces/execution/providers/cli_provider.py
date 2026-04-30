"""CLI-based LLM provider using installed claude/codex CLI tools.

Implements LLMProviderProtocol by calling ``claude -p`` or ``codex exec``
via subprocess. This lets governance features (manifest generation,
evidence synthesis, adversarial review) work through CLI subscriptions
without requiring API keys.

T-04-01 mitigation: No API keys are stored or logged.
T-04-03 mitigation: max_tokens is respected in token estimation.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import AsyncIterator
from contextlib import suppress

from ces.execution._subprocess_env import build_subprocess_env
from ces.execution.providers.protocol import LLMError, LLMResponse

# Per-tool env-var needs. Matches the runtime adapters' ``runtime_env_keys``
# so the inline provider path gets the same allowlist behaviour.
_CLI_TOOL_EXTRA_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "claude": (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "CLAUDECODE",
        "CLAUDE_CODE",
    ),
    "codex": (
        "CODEX_HOME",
        "CODEX_SANDBOX",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "OPENAI_ORG_ID",
        "OPENAI_ORGANIZATION",
        "OPENAI_PROJECT",
    ),
}


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~3 characters per token."""
    return max(1, len(text) // 3)


class CLILLMProvider:
    """LLM provider that delegates to installed CLI tools.

    Supports ``claude`` (Claude Code CLI) and ``codex`` (Codex CLI).
    """

    def __init__(self, cli_tool: str, timeout: int = 300) -> None:
        # Resolve the CLI path once so Windows .cmd/.bat shims (npm-installed
        # `codex`, etc.) work with `asyncio.create_subprocess_exec`, which
        # uses CreateProcess and does NOT append extensions like the shell
        # does. On Unix this is equivalent to invoking by name.
        resolved = shutil.which(cli_tool)
        if resolved is None:
            msg = f"CLI tool not found on PATH: {cli_tool}"
            raise FileNotFoundError(msg)
        self._cli_tool = cli_tool
        self._cli_path = resolved
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return f"{self._cli_tool}-cli"

    def _format_prompt(self, messages: list[dict[str, str]]) -> str:
        """Serialize message list to a single prompt string."""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append(f"[System]\n{content}")
            elif role == "assistant":
                parts.append(f"[Assistant]\n{content}")
            else:
                parts.append(content)
        return "\n\n".join(parts)

    def _build_command(self) -> list[str]:
        """Build the subprocess command for the configured CLI tool.

        Prompt is passed via stdin to avoid OS command-line length limits.
        The command omits the prompt argument so the CLI reads from stdin.
        """
        if self._cli_tool == "claude":
            return [
                self._cli_path,
                "-p",
                "--allowedTools",
                "Read Grep Glob",
                "--add-dir",
                ".",
                "--output-format",
                "json",
            ]
        # codex
        return [
            self._cli_path,
            "exec",
        ]

    def _parse_output(self, stdout: str) -> tuple[str, str]:
        """Parse CLI output. Returns (content, model_version).

        Claude CLI emits a JSON envelope (``{"result": ..., "modelUsage": ...}``).
        Codex CLI emits free-form text framed with metadata headers. Anything
        that isn't a JSON dict with the expected shape falls through to raw text.
        """
        try:
            parsed = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            return stdout.strip(), "unknown"

        if not isinstance(parsed, dict):
            # JSON list, string, or number — not the Claude-CLI envelope.
            return stdout.strip(), "unknown"

        content = parsed.get("result", stdout)
        # Claude CLI puts model info in modelUsage dict, not "model" key
        model_version = parsed.get("model", "")
        if not model_version:
            model_usage = parsed.get("modelUsage", {})
            if model_usage:
                model_version = next(iter(model_usage))
        return content, model_version or "unknown"

    async def generate(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate a response by calling the CLI tool.

        Uses asyncio subprocess for true concurrency when multiple
        reviewers are dispatched in parallel via asyncio.gather.
        """
        import asyncio

        prompt = self._format_prompt(messages)
        command = self._build_command()
        # Apply the same env allowlist as the runtime adapters so this spawn
        # path can't leak AWS_*, DATABASE_URL, or other non-CLI secrets into
        # the subprocess (T-04-06 extended).
        extra_keys = _CLI_TOOL_EXTRA_ENV_KEYS.get(self._cli_tool, ())
        subprocess_env = build_subprocess_env(extra_keys)
        proc = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=prompt.encode()),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            if proc is not None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.communicate(), timeout=5)
                except TimeoutError:
                    proc.kill()
                    with suppress(TimeoutError, ProcessLookupError):
                        await proc.communicate()
            raise LLMError(
                f"CLI command timed out after {self._timeout}s",
                provider_name=self.provider_name,
                model_id=model_id,
                original_error=exc,
            ) from exc

        stdout_text = stdout_bytes.decode()
        stderr_text = stderr_bytes.decode()

        if proc.returncode != 0:
            raise LLMError(
                f"CLI command failed (exit {proc.returncode}): {stderr_text[:500]}",
                provider_name=self.provider_name,
                model_id=model_id,
            )

        content, model_version = self._parse_output(stdout_text)
        input_tokens = _estimate_tokens(prompt)
        output_tokens = min(_estimate_tokens(content), max_tokens)

        return LLMResponse(
            content=content,
            model_id=model_id,
            model_version=model_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider_name=self.provider_name,
        )

    async def stream(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        """Yield the CLI response in chunks."""
        response = await self.generate(
            model_id=model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        chunk_size = 80
        text = response.content
        for i in range(0, len(text), chunk_size):
            yield text[i : i + chunk_size]
