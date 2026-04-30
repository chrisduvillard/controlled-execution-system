#!/usr/bin/env python3
"""Run a real CES scratch-project smoke test driven by Codex prompt answers."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_scratch_harness import (
    CodexAnswerProvider,
    EvidenceRecorder,
    FallbackAnswerProvider,
    HarnessContext,
    InteractiveCommandDriver,
    build_env,
    ces_command,
    create_scratch_project,
    ensure_success,
    install_fake_codex_runtime,
    parse_manifest_id,
    repo_root,
    run_command,
)


def run_harness(args: argparse.Namespace) -> int:
    ces_repo = Path(args.ces_repo).resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_dir = (
        Path(args.project_dir).resolve() if args.project_dir else Path(tempfile.mkdtemp(prefix="ces-scratch-e2e-"))
    )
    project_root = base_dir if args.project_dir else base_dir / "testing-project"
    evidence_dir = (
        Path(args.evidence_dir).resolve()
        if args.evidence_dir
        else Path(tempfile.mkdtemp(prefix=f"ces-scratch-e2e-evidence-{timestamp}-"))
    )
    recorder = EvidenceRecorder(evidence_dir)
    request = (
        "Fix the tiny Python calculator so calculator.add returns sums, then verify the existing pytest suite passes."
    )
    pytest_command = f"{sys.executable} -m pytest -q"
    context = HarnessContext(
        project_root=project_root,
        request=request,
        pytest_command=pytest_command,
        runtime=args.runtime,
    )
    fake_bin = install_fake_codex_runtime(base_dir / "fake-bin") if args.mode == "fallback" else None
    env = build_env(mode=args.mode, fake_bin=fake_bin)
    if args.mode == "codex" and shutil.which("codex", path=env.get("PATH")) is None:
        raise RuntimeError("Codex CLI is not on PATH. Re-run with --mode fallback for deterministic CI smoke.")
    answer_provider = (
        FallbackAnswerProvider() if args.mode == "fallback" else CodexAnswerProvider(codex_binary=args.codex_binary)
    )

    passed = False
    try:
        create_scratch_project(project_root)
        cli = ces_command(ces_repo)

        ensure_success(recorder, run_command([*cli, "--help"], cwd=project_root, env=env, label="ces-help"))
        ensure_success(
            recorder, run_command([*cli, "init", "codex-scratch-testing"], cwd=project_root, env=env, label="ces-init")
        )

        initial_pytest = run_command(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=project_root,
            env=env,
            label="initial-pytest-expected-fail",
        )
        recorder.record(initial_pytest)
        if initial_pytest.returncode == 0:
            raise RuntimeError("Initial scratch pytest unexpectedly passed; the harness did not plant a failing test.")

        interactive_driver = InteractiveCommandDriver(timeout_seconds=args.timeout)
        build = interactive_driver.run(
            [*cli, "build", request, "--runtime", args.runtime, "--brownfield", "--governance", "--full"],
            cwd=project_root,
            env=env,
            answer_provider=answer_provider,
            context=context,
            label="ces-build-interactive",
        )
        ensure_success(recorder, build)

        manifest_id = parse_manifest_id(build.output)
        for label, command in (
            ("ces-status", [*cli, "status"]),
            ("ces-explain", [*cli, "explain"]),
            ("ces-report-builder", [*cli, "report", "builder", "--output-dir", str(evidence_dir / "builder-report")]),
        ):
            ensure_success(recorder, run_command(command, cwd=project_root, env=env, label=label))

        final_pytest = run_command(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=project_root,
            env=env,
            label="final-pytest",
        )
        ensure_success(recorder, final_pytest)

        diff_result = run_command(
            ["git", "diff", "--", "src", "tests", "pyproject.toml"], cwd=project_root, env=env, label="target-git-diff"
        )
        ensure_success(recorder, diff_result)
        recorder.write_text("target-project.diff", diff_result.output)
        recorder.write_text("scratch-test-output.txt", final_pytest.output)

        calculator = (project_root / "src" / "calculator.py").read_text(encoding="utf-8")
        if "return left + right" not in calculator and "return a + b" not in calculator:
            raise RuntimeError("Target project did not contain the expected calculator.add fix.")
        if "return left + right" not in diff_result.output and "return a + b" not in diff_result.output:
            raise RuntimeError("Target git diff did not show the expected calculator.add fix.")

        passed = True
        recorder.write_summary(
            {
                "passed": True,
                "mode": args.mode,
                "runtime": args.runtime,
                "scratch_project": str(project_root),
                "evidence_dir": str(evidence_dir),
                "manifest_id": manifest_id,
                "commands": [asdict(result) for result in recorder.results],
            }
        )
        print(f"PASS scratch CES E2E ({args.mode} mode)")
        print(f"Evidence: {evidence_dir}")
        print(f"Scratch project: {project_root}")
        return 0
    except Exception as exc:
        recorder.write_summary(
            {
                "passed": False,
                "mode": args.mode,
                "runtime": args.runtime,
                "scratch_project": str(project_root),
                "evidence_dir": str(evidence_dir),
                "error": str(exc),
                "commands": [asdict(result) for result in recorder.results],
            }
        )
        print(f"FAIL scratch CES E2E: {exc}", file=sys.stderr)
        print(f"Evidence: {evidence_dir}", file=sys.stderr)
        print(f"Scratch project preserved: {project_root}", file=sys.stderr)
        return 1
    finally:
        should_cleanup = passed and not args.keep and args.project_dir is None
        if should_cleanup:
            shutil.rmtree(base_dir, ignore_errors=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("codex", "fallback"), default="codex")
    parser.add_argument("--runtime", default="codex", choices=("codex", "claude", "auto"))
    parser.add_argument("--codex-binary", default="codex")
    parser.add_argument("--ces-repo", default=str(repo_root()))
    parser.add_argument("--project-dir", help="Use this scratch project path instead of creating one under /tmp.")
    parser.add_argument("--evidence-dir", help="Directory for transcripts, answers, diffs, reports, and summary JSON.")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--keep", action="store_true", help="Preserve the scratch project even when the run passes.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run_harness(parse_args(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
