"""Unit coverage for the Codex scratch-project E2E harness."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _load_harness() -> Any:
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "run_codex_scratch_e2e.py"
    spec = importlib.util.spec_from_file_location("run_codex_scratch_e2e", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_shared_harness() -> Any:
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "codex_scratch_harness.py"
    spec = importlib.util.spec_from_file_location("codex_scratch_harness", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_brownfield_harness() -> Any:
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "run_codex_brownfield_e2e.py"
    spec = importlib.util.spec_from_file_location("run_codex_brownfield_e2e", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fallback_provider_answers_known_ces_prompts(tmp_path: Path) -> None:
    harness = _load_harness()
    provider = harness.FallbackAnswerProvider()
    context = harness.HarnessContext(
        project_root=tmp_path,
        request="Fix calculator.add so pytest passes",
        pytest_command=f"{sys.executable} -m pytest -q",
        runtime="codex",
    )

    assert "local-first" in provider.answer("Any stack or constraint I should respect?", context).text
    assert "pytest" in provider.answer("What should be true when this is done?", context).text
    assert provider.answer("Proceed with execution? [Y/n]:", context).text == "y"


def test_codex_provider_invokes_codex_non_interactively(monkeypatch: Any, tmp_path: Path) -> None:
    harness = _load_shared_harness()
    provider = harness.CodexAnswerProvider(codex_binary="codex")
    context = harness.HarnessContext(
        project_root=tmp_path,
        request="Fix calculator.add so pytest passes",
        pytest_command=f"{sys.executable} -m pytest -q",
        runtime="codex",
    )
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(command)
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text("Keep the tiny Python app local-first.", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(harness.subprocess, "run", fake_run)

    answer = provider.answer("Any stack or constraint I should respect?", context)

    assert answer.source == "codex"
    assert answer.text == "Keep the tiny Python app local-first."
    assert calls
    assert calls[0][:2] == ["codex", "exec"]
    assert "-C" in calls[0]
    assert str(tmp_path) in calls[0]
    assert "--output-last-message" in calls[0]


def test_fake_codex_runtime_modifies_scratch_project(tmp_path: Path) -> None:
    harness = _load_harness()
    project_root = harness.create_scratch_project(tmp_path / "target")
    fake_bin = harness.install_fake_codex_runtime(tmp_path / "fake-bin")
    message_path = tmp_path / "message.txt"

    result = subprocess.run(  # noqa: S603
        [
            str(fake_bin / "codex"),
            "exec",
            "Fix calculator.add",
            "-C",
            str(project_root),
            "--output-last-message",
            str(message_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "return left + right" in (project_root / "src" / "calculator.py").read_text(encoding="utf-8")
    assert "fake Codex runtime" in message_path.read_text(encoding="utf-8")


def test_interactive_driver_answers_detected_prompt(tmp_path: Path) -> None:
    harness = _load_harness()
    prompt_script = tmp_path / "prompt_script.py"
    prompt_script.write_text(
        "import sys\n"
        "sys.stdout.write('Any stack or constraint I should respect?: ')\n"
        "sys.stdout.flush()\n"
        "answer = sys.stdin.readline().strip()\n"
        "print(f'got:{answer}')\n",
        encoding="utf-8",
    )
    provider = harness.FallbackAnswerProvider()
    context = harness.HarnessContext(
        project_root=tmp_path,
        request="Fix calculator.add so pytest passes",
        pytest_command=f"{sys.executable} -m pytest -q",
        runtime="codex",
    )
    driver = harness.InteractiveCommandDriver(timeout_seconds=5)

    result = driver.run(
        [sys.executable, str(prompt_script)],
        cwd=tmp_path,
        env=None,
        answer_provider=provider,
        context=context,
        label="prompt-smoke",
    )

    assert result.returncode == 0, result.output
    assert result.answers
    assert result.answers[0].prompt.startswith("Any stack")
    assert "got:Keep the tiny Python app local-first" in result.output


def test_fake_codex_runtime_can_apply_brownfield_calculator_extension(tmp_path: Path) -> None:
    harness = _load_shared_harness()
    project_root = harness.create_scratch_project(tmp_path / "target")
    calculator = project_root / "src" / "calculator.py"
    calculator.write_text(
        '"""Tiny module for the CES scratch smoke test."""\n\n'
        "def add(left: int, right: int) -> int:\n"
        "    return left + right\n",
        encoding="utf-8",
    )
    fake_bin = harness.install_fake_codex_runtime(tmp_path / "fake-bin")

    result = subprocess.run(  # noqa: S603
        [
            str(fake_bin / "codex"),
            "exec",
            "Add subtract, multiply, and divide to the calculator",
            "-C",
            str(project_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    source = calculator.read_text(encoding="utf-8")
    tests = (project_root / "tests" / "test_calculator.py").read_text(encoding="utf-8")
    assert "def subtract" in source
    assert "def multiply" in source
    assert "def divide" in source
    assert "pytest.raises(ZeroDivisionError)" in tests


def test_direct_smoke_environment_adds_src_to_pythonpath() -> None:
    harness = _load_shared_harness()

    env = harness.direct_smoke_env({"PYTHONPATH": "/existing/path"})

    assert env["PYTHONPATH"].split(harness.os.pathsep)[:2] == ["src", "/existing/path"]


def test_brownfield_summary_uses_brownfield_manifest_not_preflight() -> None:
    harness = _load_brownfield_harness()
    results = [
        SimpleNamespace(label="pre-ces-status-expert", output="Current manifest M-old123"),
        SimpleNamespace(label="ces-build-brownfield-interactive", output="Build Review Complete\nManifest: M-new456"),
    ]

    assert harness.extract_labeled_manifest_id(results, "ces-build-brownfield-interactive") == "M-new456"
