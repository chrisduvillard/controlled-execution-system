"""Shared helpers for CES scratch-project E2E harnesses."""

from __future__ import annotations

import json
import os
import pty
import re
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

PROMPT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"What do you want to build\??:?"),
    re.compile(r"Any stack or constraint I should respect\??:?"),
    re.compile(r"What should be true when this is done\??:?"),
    re.compile(r"What should definitely stay working\??:?"),
    re.compile(r"What best reflects today's behavior\??:?"),
    re.compile(r"Which workflows matter most to keep working\??:?"),
    re.compile(r"Proceed with execution\?.*"),
    re.compile(r"Ship this change\?.*"),
    re.compile(r"Save this manifest\?.*"),
    re.compile(r"Approve this evidence\?.*"),
)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
MANIFEST_RE = re.compile(r"\bM-[A-Za-z0-9_-]+\b")


@dataclass(frozen=True)
class HarnessContext:
    project_root: Path
    request: str
    pytest_command: str
    runtime: str


@dataclass(frozen=True)
class PromptAnswer:
    prompt: str
    text: str
    source: str


@dataclass(frozen=True)
class CommandResult:
    label: str
    command: list[str]
    cwd: str
    returncode: int
    output: str
    answers: list[PromptAnswer]
    started_at: str
    duration_seconds: float


class AnswerProvider(Protocol):
    def answer(self, prompt: str, context: HarnessContext) -> PromptAnswer:
        """Return the next non-interactive answer for a CES prompt."""


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def create_scratch_project(project_root: Path) -> Path:
    """Create a tiny committed Python project with one intentionally failing test."""
    if project_root.exists():
        shutil.rmtree(project_root)
    (project_root / "src").mkdir(parents=True)
    (project_root / "tests").mkdir()
    (project_root / ".gitignore").write_text(
        ".ces/\n.codex\n.pytest_cache/\n__pycache__/\n*.py[cod]\n",
        encoding="utf-8",
    )
    (project_root / "README.md").write_text("# CES scratch testing project\n", encoding="utf-8")
    (project_root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "ces-scratch-testing-project"\n'
        'version = "0.0.0"\n'
        'requires-python = ">=3.12"\n'
        "\n"
        "[tool.pytest.ini_options]\n"
        'pythonpath = ["src"]\n',
        encoding="utf-8",
    )
    (project_root / "src" / "calculator.py").write_text(
        '"""Tiny module for the CES scratch smoke test."""\n\n'
        "def add(left: int, right: int) -> int:\n"
        "    return left - right\n",
        encoding="utf-8",
    )
    (project_root / "tests" / "test_calculator.py").write_text(
        "from calculator import add\n\n\ndef test_add_returns_sum() -> None:\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    run_simple(["git", "init"], cwd=project_root)
    run_simple(["git", "add", "."], cwd=project_root)
    run_simple(
        [
            "git",
            "-c",
            "user.name=CES Scratch",
            "-c",
            "user.email=ces-scratch@example.invalid",
            "commit",
            "-m",
            "Initial failing scratch app",
        ],
        cwd=project_root,
    )
    return project_root


def run_simple(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def commit_all(project_root: Path, message: str) -> None:
    run_simple(["git", "add", "."], cwd=project_root)
    run_simple(
        [
            "git",
            "-c",
            "user.name=CES Scratch",
            "-c",
            "user.email=ces-scratch@example.invalid",
            "commit",
            "-m",
            message,
        ],
        cwd=project_root,
    )


class FallbackAnswerProvider:
    """Deterministic CI-safe answers for CES prompts."""

    def answer(self, prompt: str, context: HarnessContext) -> PromptAnswer:
        prompt_lower = strip_ansi(prompt).lower()
        brownfield_extension = _is_brownfield_extension_request(context.request)
        if (
            "proceed with execution" in prompt_lower
            or "ship this change" in prompt_lower
            or "approve this evidence" in prompt_lower
            or "save this manifest" in prompt_lower
        ):
            text = "y"
        elif "stack or constraint" in prompt_lower:
            text = "Keep the tiny Python app local-first; do not add Postgres, Redis, or new services."
        elif "true when this is done" in prompt_lower and brownfield_extension:
            text = f"add, subtract, multiply, and divide work; divide by zero raises; {context.pytest_command} passes."
        elif "true when this is done" in prompt_lower:
            text = f"calculator.add returns sums and {context.pytest_command} passes."
        elif "definitely stay working" in prompt_lower:
            text = "Keep the calculator.add(left, right) API and the existing pytest workflow."
        elif "today's behavior" in prompt_lower and brownfield_extension:
            text = "calculator.add already returns sums; subtract, multiply, and divide are not implemented yet."
        elif "today's behavior" in prompt_lower:
            text = "tests/test_calculator.py and src/calculator.py are the source of truth."
        elif "workflows matter most" in prompt_lower:
            text = f"Running {context.pytest_command}."
        elif "what do you want to build" in prompt_lower:
            text = context.request
        else:
            text = "Preserve current behavior and make the requested tests pass."
        return PromptAnswer(prompt=strip_ansi(prompt).strip(), text=text, source="fallback")


class CodexAnswerProvider:
    """Use Codex CLI to answer CES's follow-up prompts non-interactively."""

    def __init__(self, *, codex_binary: str = "codex", timeout_seconds: int = 120) -> None:
        self._codex_binary = codex_binary
        self._timeout_seconds = timeout_seconds

    def answer(self, prompt: str, context: HarnessContext) -> PromptAnswer:
        clean_prompt = strip_ansi(prompt).strip()
        with tempfile.TemporaryDirectory(prefix="ces-codex-answer-") as tmp:
            output_path = Path(tmp) / "answer.txt"
            instruction = self._build_instruction(clean_prompt, context)
            command = [
                self._codex_binary,
                "exec",
                instruction,
                "-C",
                str(context.project_root),
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--output-last-message",
                str(output_path),
            ]
            result = subprocess.run(  # noqa: S603
                command,
                cwd=context.project_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._timeout_seconds,
            )
            answer_text = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
            if result.returncode != 0 or not answer_text:
                details = (result.stderr or result.stdout or "Codex produced no answer").strip()
                raise RuntimeError(f"Codex failed to answer CES prompt: {details}")
            answer_text = answer_text.splitlines()[0].strip().strip('"')
            return PromptAnswer(prompt=clean_prompt, text=answer_text, source="codex")

    @staticmethod
    def _build_instruction(prompt: str, context: HarnessContext) -> str:
        files = summarize_project(context.project_root)
        return "\n".join(
            [
                "You are answering a CES CLI follow-up prompt for an automated local smoke test.",
                "Return only the exact answer text to type into the CLI. No markdown, no explanation.",
                "For yes/no confirmation prompts, return only y or n.",
                "",
                f"CES prompt: {prompt}",
                f"User request: {context.request}",
                f"Runtime under test: {context.runtime}",
                f"Verification command: {context.pytest_command}",
                "",
                "Project context:",
                files,
                "",
                "Constraints: keep this local-first; do not suggest Postgres, Redis, or hosted services.",
            ]
        )


def summarize_project(project_root: Path) -> str:
    snippets: list[str] = []
    for relative in ("README.md", "pyproject.toml", "src/calculator.py", "tests/test_calculator.py"):
        path = project_root / relative
        if path.exists():
            text = path.read_text(encoding="utf-8")
            snippets.append(f"--- {relative} ---\n{text[:1200].rstrip()}")
    return "\n\n".join(snippets)


class EvidenceRecorder:
    def __init__(self, evidence_dir: Path) -> None:
        self.evidence_dir = evidence_dir
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_path = self.evidence_dir / "command-transcript.txt"
        self.answers_path = self.evidence_dir / "codex-prompt-answers.jsonl"
        self.results: list[CommandResult] = []

    def record(self, result: CommandResult) -> None:
        self.results.append(result)
        with self.transcript_path.open("a", encoding="utf-8") as transcript:
            transcript.write(f"\n\n## {result.label}\n")
            transcript.write(f"$ {' '.join(result.command)}\n")
            transcript.write(f"cwd: {result.cwd}\n")
            transcript.write(f"exit: {result.returncode}; duration: {result.duration_seconds:.2f}s\n\n")
            transcript.write(result.output)
            if not result.output.endswith("\n"):
                transcript.write("\n")
        with self.answers_path.open("a", encoding="utf-8") as answers:
            for answer in result.answers:
                answers.write(json.dumps(asdict(answer)) + "\n")

    def write_text(self, name: str, text: str) -> Path:
        path = self.evidence_dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def write_summary(self, summary: dict[str, object]) -> Path:
        return self.write_text("summary.json", json.dumps(summary, indent=2, default=str) + "\n")


class InteractiveCommandDriver:
    """Run a command through a PTY and answer recognized CES prompts."""

    def __init__(self, *, timeout_seconds: int = 900) -> None:
        self._timeout_seconds = timeout_seconds

    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None,
        answer_provider: AnswerProvider,
        context: HarnessContext,
        label: str,
    ) -> CommandResult:
        started = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        master_fd, slave_fd = pty.openpty()
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=cwd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            text=False,
            close_fds=True,
        )
        os.close(slave_fd)
        output_parts: list[str] = []
        answers: list[PromptAnswer] = []
        answered_positions: dict[str, int] = {}
        deadline = time.monotonic() + self._timeout_seconds

        try:
            while process.poll() is None:
                if time.monotonic() > deadline:
                    process.kill()
                    raise TimeoutError(f"{label} timed out after {self._timeout_seconds}s")
                readable, _, _ = select.select([master_fd], [], [], 0.25)
                if not readable:
                    continue
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                chunk = data.decode("utf-8", errors="replace")
                output_parts.append(chunk)
                clean_output = strip_ansi("".join(output_parts))
                for pattern in PROMPT_PATTERNS:
                    for match in pattern.finditer(clean_output):
                        key = pattern.pattern
                        if match.end() <= answered_positions.get(key, 0):
                            continue
                        answer = answer_provider.answer(match.group(0), context)
                        answers.append(answer)
                        os.write(master_fd, f"{answer.text}\n".encode())
                        output_parts.append(f"\n[ces-scratch-e2e answered via {answer.source}: {answer.text}]\n")
                        answered_positions[key] = match.end()
                        break
            while True:
                readable, _, _ = select.select([master_fd], [], [], 0)
                if not readable:
                    break
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                output_parts.append(data.decode("utf-8", errors="replace"))
        finally:
            os.close(master_fd)
        return CommandResult(
            label=label,
            command=command,
            cwd=str(cwd),
            returncode=process.wait(),
            output="".join(output_parts),
            answers=answers,
            started_at=started_at,
            duration_seconds=time.monotonic() - started,
        )


def run_command(command: list[str], *, cwd: Path, env: dict[str, str] | None, label: str) -> CommandResult:
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    result = subprocess.run(  # noqa: S603
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        label=label,
        command=command,
        cwd=str(cwd),
        returncode=result.returncode,
        output=(result.stdout or "") + (result.stderr or ""),
        answers=[],
        started_at=started_at,
        duration_seconds=time.monotonic() - started,
    )


def install_fake_codex_runtime(bin_dir: Path) -> Path:
    """Install a tiny `codex` shim for fallback mode."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    codex_path = bin_dir / "codex"
    codex_path.write_text(
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        "def write_baseline(cwd: Path) -> str:\n"
        "    target = cwd / 'src' / 'calculator.py'\n"
        "    if target.exists():\n"
        "        text = target.read_text(encoding='utf-8')\n"
        "        text = text.replace('return left - right', 'return left + right')\n"
        "        text = text.replace('return a - b', 'return a + b')\n"
        "        target.write_text(text, encoding='utf-8')\n"
        "    return 'Implemented by fake Codex runtime: calculator.add now returns the sum.'\n"
        "\n"
        "def write_brownfield(cwd: Path) -> str:\n"
        "    (cwd / 'src' / 'calculator.py').write_text(\n"
        '        \'\\"\\"\\"Tiny module for the CES scratch smoke test.\\"\\"\\"\\n\\n\'\n'
        "        'def add(left: int, right: int) -> int:\\n'\n"
        "        '    return left + right\\n\\n\\n'\n"
        "        'def subtract(left: int, right: int) -> int:\\n'\n"
        "        '    return left - right\\n\\n\\n'\n"
        "        'def multiply(left: int, right: int) -> int:\\n'\n"
        "        '    return left * right\\n\\n\\n'\n"
        "        'def divide(left: int, right: int) -> float:\\n'\n"
        "        '    return left / right\\n',\n"
        "        encoding='utf-8',\n"
        "    )\n"
        "    (cwd / 'tests' / 'test_calculator.py').write_text(\n"
        "        'import pytest\\n\\n'\n"
        "        'import calculator\\n\\n\\n'\n"
        "        'def test_add_returns_sum() -> None:\\n'\n"
        "        '    assert calculator.add(2, 3) == 5\\n\\n\\n'\n"
        "        'def test_subtract_returns_difference() -> None:\\n'\n"
        "        '    assert calculator.subtract(7, 3) == 4\\n\\n\\n'\n"
        "        'def test_multiply_returns_product() -> None:\\n'\n"
        "        '    assert calculator.multiply(6, 4) == 24\\n\\n\\n'\n"
        "        'def test_divide_returns_quotient() -> None:\\n'\n"
        "        '    assert calculator.divide(8, 2) == 4\\n\\n\\n'\n"
        "        'def test_divide_by_zero_raises_zero_division_error() -> None:\\n'\n"
        "        '    with pytest.raises(ZeroDivisionError):\\n'\n"
        "        '        calculator.divide(8, 0)\\n',\n"
        "        encoding='utf-8',\n"
        "    )\n"
        "    return 'Implemented by fake Codex runtime: calculator operations were extended.'\n"
        "\n"
        "def main() -> int:\n"
        "    args = sys.argv[1:]\n"
        "    if '--version' in args or '-V' in args:\n"
        "        print('codex-fake 0.0')\n"
        "        return 0\n"
        "    if not args or args[0] != 'exec':\n"
        "        print('fake codex only supports exec', file=sys.stderr)\n"
        "        return 2\n"
        "    cwd = Path.cwd()\n"
        "    if '-C' in args:\n"
        "        cwd = Path(args[args.index('-C') + 1])\n"
        "    output = None\n"
        "    if '--output-last-message' in args:\n"
        "        output = Path(args[args.index('--output-last-message') + 1])\n"
        "    request = ' '.join(args).lower()\n"
        "    if all(word in request for word in ('subtract', 'multiply', 'divide')):\n"
        "        message = write_brownfield(cwd)\n"
        "    else:\n"
        "        message = write_baseline(cwd)\n"
        "    if output is not None:\n"
        "        output.parent.mkdir(parents=True, exist_ok=True)\n"
        "        output.write_text(message + '\\n', encoding='utf-8')\n"
        "    print(message)\n"
        "    return 0\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    codex_path.chmod(codex_path.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def ces_command(ces_repo: Path) -> list[str]:
    return ["uv", "run", "--project", str(ces_repo), "ces"]


def ensure_success(recorder: EvidenceRecorder, result: CommandResult) -> None:
    recorder.record(result)
    if result.returncode != 0:
        raise RuntimeError(f"{result.label} failed with exit {result.returncode}")


def parse_manifest_id(*texts: str) -> str | None:
    for text in texts:
        match = MANIFEST_RE.search(text)
        if match:
            return match.group(0)
    return None


def build_env(*, mode: str, fake_bin: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("UV_CACHE_DIR", str(Path(tempfile.gettempdir()) / "uv-cache"))
    env.setdefault("NO_COLOR", "1")
    if mode == "fallback" and fake_bin is not None:
        env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    return env


def direct_smoke_env(base_env: dict[str, str]) -> dict[str, str]:
    env = base_env.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = "src" if not existing else f"src{os.pathsep}{existing}"
    return env


def direct_calculator_smoke_command() -> list[str]:
    return [
        sys.executable,
        "-c",
        "from calculator import add, subtract, multiply, divide; import pytest; "
        "assert add(2, 3) == 5; assert subtract(10, 4) == 6; "
        "assert multiply(-3, 5) == -15; assert divide(9, 3) == 3; "
        "pytest.raises(ZeroDivisionError, divide, 1, 0); print('calculator-ok')",
    ]


def _is_brownfield_extension_request(request: str) -> bool:
    lowered = request.lower()
    return all(word in lowered for word in ("subtract", "multiply", "divide"))
