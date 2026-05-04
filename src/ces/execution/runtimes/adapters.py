"""Runtime adapters for Codex CLI and Claude Code."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from ces.execution._subprocess_env import build_subprocess_env
from ces.execution.runtimes.protocol import AgentRuntimeResult
from ces.execution.secrets import scrub_secrets_from_text

_MAX_RUNTIME_OUTPUT_BYTES = 1_048_576
_TRUNCATION_MARKER = "\n...[truncated]"
_DEFAULT_RUNTIME_TIMEOUT_SECONDS = 1800
_TIMEOUT_EXIT_CODE = 124

# Default tool allowlist for the Claude builder runtime when the manifest
# doesn't name one explicitly. Deliberately excludes Bash and WebFetch so
# prompt-injected repo content cannot exec arbitrary shell or exfiltrate
# to the network. Manifests that legitimately need broader tools can opt
# in via ``TaskManifest.allowed_tools``.
_DEFAULT_CLAUDE_ALLOWED_TOOLS: tuple[str, ...] = ("Read", "Grep", "Glob", "Edit", "Write")


class _BaseRuntimeAdapter:
    runtime_name = "runtime"
    binary_name = ""
    version_args: tuple[str, ...] = ("--version",)
    runtime_env_keys: tuple[str, ...] = ()

    def _resolved_binary(self) -> str:
        """Return the full path to the binary via shutil.which().

        On Windows, npm installs .CMD shims that subprocess.run() cannot
        execute by name alone.  Using the resolved path works everywhere.
        """
        return shutil.which(self.binary_name) or self.binary_name

    def detect(self) -> bool:
        return shutil.which(self.binary_name) is not None

    def _build_env(self) -> dict[str, str]:
        """Pass only the env vars required for CLI auth and stable execution."""
        return build_subprocess_env(self.runtime_env_keys)

    def _runtime_timeout_seconds(self) -> int:
        raw = os.environ.get("CES_RUNTIME_TIMEOUT_SECONDS")
        if raw is None:
            return _DEFAULT_RUNTIME_TIMEOUT_SECONDS
        try:
            timeout = int(raw)
        except ValueError:
            return _DEFAULT_RUNTIME_TIMEOUT_SECONDS
        return timeout if timeout > 0 else _DEFAULT_RUNTIME_TIMEOUT_SECONDS

    def _timeout_message(self, timeout_seconds: int) -> str:
        return (
            f"{self.runtime_name} runtime timed out after {timeout_seconds} seconds. "
            "The run was stopped so CES can recover instead of hanging indefinitely; "
            "inspect the runtime transcript, then retry with `ces continue` or set "
            "CES_RUNTIME_TIMEOUT_SECONDS to a larger positive value if this task legitimately needs more time."
        )

    @staticmethod
    def _prepare_project_transcript_path(working_dir: Path, invocation_ref: str) -> Path:
        """Create a private project-local transcript file path.

        Using a predictable filename in the shared temp directory exposes runtime
        output to cross-user reads and symlink clobbering. Keep transcripts
        inside `.ces/runtime-transcripts` with restrictive permissions instead.
        """
        transcript_dir = working_dir / ".ces" / "runtime-transcripts"
        transcript_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(transcript_dir, 0o700)
        except OSError:
            pass
        fd, transcript_path = tempfile.mkstemp(
            prefix=f"{invocation_ref}-",
            suffix=".txt",
            dir=transcript_dir,
        )
        os.close(fd)
        try:
            os.chmod(transcript_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return Path(transcript_path)

    @staticmethod
    def _decode_limited_output(data: bytes) -> str:
        truncated = len(data) > _MAX_RUNTIME_OUTPUT_BYTES
        payload = data[:_MAX_RUNTIME_OUTPUT_BYTES]
        text = payload.decode("utf-8", errors="replace")
        if truncated:
            return text + _TRUNCATION_MARKER
        return text

    @classmethod
    def _read_limited_file(cls, handle: object) -> str:
        stream = handle
        if not hasattr(stream, "seek") or not hasattr(stream, "read"):
            return ""
        stream.seek(0)
        data = stream.read(_MAX_RUNTIME_OUTPUT_BYTES + 1)
        return cls._decode_limited_output(data)

    @classmethod
    def _read_limited_path(cls, path: Path) -> str:
        with path.open("rb") as handle:
            data = handle.read(_MAX_RUNTIME_OUTPUT_BYTES + 1)
        return cls._decode_limited_output(data)

    @classmethod
    def _read_scrubbed_limited_path(cls, path: Path) -> str:
        text = scrub_secrets_from_text(cls._read_limited_path(path))
        path.write_text(text, encoding="utf-8")
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return text

    def version(self) -> str:
        if not self.detect():
            return "not-installed"
        result = subprocess.run(
            [self._resolved_binary(), *self.version_args],
            capture_output=True,
            text=True,
            check=False,
            env=self._build_env(),
        )
        return (result.stdout or result.stderr).strip() or "unknown"

    def summarize_evidence(self, evidence_context: dict) -> tuple[str, str]:
        summary = [
            f"Runtime: {evidence_context.get('runtime_name', self.runtime_name)}",
            f"Task: {evidence_context.get('description', 'unknown task')}",
            f"Exit code: {evidence_context.get('exit_code', 'n/a')}",
            f"Output lines: {evidence_context.get('output_lines', 0)}",
            f"Recommendation: {'approve' if evidence_context.get('exit_code', 1) == 0 else 'review carefully'}",
        ]
        challenge = [
            "Did the runtime actually modify the intended files?",
            "Was the output successful or only plausible?",
            "Are there missing tests or follow-up checks?",
        ]
        return ("\n".join(summary[:10]), "\n".join(challenge[:3]))

    def generate_manifest_assist(self, truth_artifacts: dict, description: str) -> dict:
        del truth_artifacts
        return {
            "description": description,
            "risk_tier": "B",
            "behavior_confidence": "BC2",
            "change_class": "Class 2",
            "affected_files": [],
            "token_budget": 75000,
            "reasoning": f"{self.runtime_name} local assist inferred a moderate default classification.",
        }


class CodexRuntimeAdapter(_BaseRuntimeAdapter):
    """Adapter for the local `codex` CLI."""

    runtime_name = "codex"
    binary_name = "codex"
    runtime_env_keys = (
        "CODEX_HOME",
        "CODEX_SANDBOX",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "OPENAI_ORG_ID",
        "OPENAI_ORGANIZATION",
        "OPENAI_PROJECT",
    )

    def run_task(
        self,
        manifest_description: str,
        prompt_pack: str,
        working_dir: Path,
        allowed_tools: tuple[str, ...] = (),
    ) -> AgentRuntimeResult:
        # Codex receives full host access instead of an explicit tool allowlist;
        # side-effect risk is disclosed and gated by the builder flow.
        del allowed_tools
        started = time.monotonic()
        invocation_ref = f"codex-{uuid.uuid4().hex[:12]}"
        message_file = self._prepare_project_transcript_path(working_dir, invocation_ref)
        # Chris's CES/Codex deployment always runs Codex with full host access.
        # Codex workspace-write uses bubblewrap, which cannot execute shell tools
        # on the target Ubuntu host (`bwrap: loopback: Failed RTM_NEWADDR`).
        # Runtime side-effect risk is disclosed and gated by the builder flow.
        command = [
            self._resolved_binary(),
            "exec",
            prompt_pack or manifest_description,
            "-C",
            str(working_dir),
            "--sandbox",
            "danger-full-access",
            "--skip-git-repo-check",
            "--output-last-message",
            str(message_file),
        ]
        timeout_seconds = self._runtime_timeout_seconds()
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                result = subprocess.run(
                    command,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    check=False,
                    env=self._build_env(),
                    timeout=timeout_seconds,
                )
                exit_code = result.returncode
            except subprocess.TimeoutExpired:
                exit_code = _TIMEOUT_EXIT_CODE
                stderr_file.write(("\n" + self._timeout_message(timeout_seconds)).encode("utf-8"))
            stdout = self._read_limited_file(stdout_file)
            stderr = self._read_limited_file(stderr_file)
        if message_file.exists():
            stdout = self._read_scrubbed_limited_path(message_file)
        return AgentRuntimeResult(
            runtime_name=self.runtime_name,
            runtime_version=self.version(),
            reported_model=None,
            invocation_ref=invocation_ref,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=time.monotonic() - started,
            transcript_path=str(message_file) if message_file.exists() else None,
        )


class ClaudeRuntimeAdapter(_BaseRuntimeAdapter):
    """Adapter for the local `claude` CLI."""

    runtime_name = "claude"
    binary_name = "claude"
    runtime_env_keys = (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "CLAUDECODE",
        "CLAUDE_CODE",
    )

    def run_task(
        self,
        manifest_description: str,
        prompt_pack: str,
        working_dir: Path,
        allowed_tools: tuple[str, ...] = (),
    ) -> AgentRuntimeResult:
        started = time.monotonic()
        invocation_ref = f"claude-{uuid.uuid4().hex[:12]}"
        effective_tools = allowed_tools or _DEFAULT_CLAUDE_ALLOWED_TOOLS
        command = [
            self._resolved_binary(),
            "-p",
            prompt_pack or manifest_description,
            "--output-format",
            "json",
            # ``default`` (not ``acceptEdits``) so the model must request tool
            # use explicitly instead of auto-approving Edit/Bash calls. Combined
            # with ``--allowedTools`` this blocks prompt-injection-driven host
            # command execution — see tests/unit/test_execution/test_claude_adapter_hardening.py.
            "--permission-mode",
            "default",
            "--allowedTools",
            " ".join(effective_tools),
            "--add-dir",
            str(working_dir),
        ]
        timeout_seconds = self._runtime_timeout_seconds()
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                result = subprocess.run(
                    command,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    check=False,
                    cwd=working_dir,
                    env=self._build_env(),
                    timeout=timeout_seconds,
                )
                exit_code = result.returncode
            except subprocess.TimeoutExpired:
                exit_code = _TIMEOUT_EXIT_CODE
                stderr_file.write(("\n" + self._timeout_message(timeout_seconds)).encode("utf-8"))
            stdout = self._read_limited_file(stdout_file)
            stderr = self._read_limited_file(stderr_file)
        reported_model = None
        try:
            parsed = json.loads(stdout) if stdout else {}
            if isinstance(parsed, dict):
                reported_model = parsed.get("model")
                stdout = parsed.get("result", stdout)
        except json.JSONDecodeError:
            pass
        return AgentRuntimeResult(
            runtime_name=self.runtime_name,
            runtime_version=self.version(),
            reported_model=reported_model,
            invocation_ref=invocation_ref,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=time.monotonic() - started,
        )
