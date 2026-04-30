#!/usr/bin/env python3
"""Run a two-task CES brownfield scratch-project smoke test."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_scratch_harness import (
    CodexAnswerProvider,
    CommandResult,
    EvidenceRecorder,
    FallbackAnswerProvider,
    HarnessContext,
    InteractiveCommandDriver,
    build_env,
    ces_command,
    commit_all,
    create_scratch_project,
    direct_calculator_smoke_command,
    direct_smoke_env,
    ensure_success,
    install_fake_codex_runtime,
    parse_manifest_id,
    repo_root,
    run_command,
)

BASELINE_REQUEST = (
    "Fix the tiny Python calculator so calculator.add returns sums, then verify the existing pytest suite passes."
)
BROWNFIELD_REQUEST = (
    "Extend this existing calculator module by adding subtract, multiply, and divide functions. "
    "Keep calculator.add working, add pytest coverage for all operations, and make divide raise "
    "ZeroDivisionError on division by zero."
)


def extract_labeled_manifest_id(results: Iterable[CommandResult], label: str) -> str | None:
    for result in results:
        if result.label == label:
            return parse_manifest_id(result.output)
    return None


def run_harness(args: argparse.Namespace) -> int:
    ces_repo = Path(args.ces_repo).resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_dir = (
        Path(args.project_dir).resolve() if args.project_dir else Path(tempfile.mkdtemp(prefix="ces-brownfield-e2e-"))
    )
    project_root = base_dir if args.project_dir else base_dir / "testing-project"
    evidence_dir = (
        Path(args.evidence_dir).resolve()
        if args.evidence_dir
        else Path(tempfile.mkdtemp(prefix=f"ces-brownfield-e2e-evidence-{timestamp}-"))
    )
    recorder = EvidenceRecorder(evidence_dir)
    pytest_command = f"{sys.executable} -m pytest -q"
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
        driver = InteractiveCommandDriver(timeout_seconds=args.timeout)

        ensure_success(recorder, run_command([*cli, "--help"], cwd=project_root, env=env, label="ces-help"))
        ensure_success(
            recorder,
            run_command([*cli, "init", "codex-brownfield-testing"], cwd=project_root, env=env, label="ces-init"),
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

        baseline_context = HarnessContext(
            project_root=project_root,
            request=BASELINE_REQUEST,
            pytest_command=pytest_command,
            runtime=args.runtime,
        )
        baseline_build = driver.run(
            [*cli, "build", BASELINE_REQUEST, "--runtime", args.runtime, "--brownfield", "--governance", "--full"],
            cwd=project_root,
            env=env,
            answer_provider=answer_provider,
            context=baseline_context,
            label="ces-build-baseline-interactive",
        )
        ensure_success(recorder, baseline_build)

        baseline_pytest = run_command(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=project_root,
            env=env,
            label="baseline-pytest",
        )
        ensure_success(recorder, baseline_pytest)
        commit_all(project_root, "Accept CES calculator baseline")
        ensure_success(
            recorder,
            run_command(
                ["git", "status", "--short", "--branch"], cwd=project_root, env=env, label="baseline-git-status"
            ),
        )

        brownfield_context = HarnessContext(
            project_root=project_root,
            request=BROWNFIELD_REQUEST,
            pytest_command=pytest_command,
            runtime=args.runtime,
        )
        brownfield_build = driver.run(
            [*cli, "build", BROWNFIELD_REQUEST, "--runtime", args.runtime, "--brownfield", "--governance", "--full"],
            cwd=project_root,
            env=env,
            answer_provider=answer_provider,
            context=brownfield_context,
            label="ces-build-brownfield-interactive",
        )
        ensure_success(recorder, brownfield_build)

        post_merge_review = run_command(
            [*cli, "review", "--full"], cwd=project_root, env=env, label="post-merge-review"
        )
        recorder.record(post_merge_review)
        post_merge_approve = run_command(
            [*cli, "approve", "--yes"], cwd=project_root, env=env, label="post-merge-approve"
        )
        recorder.record(post_merge_approve)

        for label, command in (
            ("post-ces-triage", [*cli, "triage"]),
            ("post-ces-status-expert", [*cli, "status", "--expert"]),
            ("post-ces-explain", [*cli, "explain"]),
            (
                "post-ces-report-builder",
                [*cli, "report", "builder", "--output-dir", str(evidence_dir / "builder-report")],
            ),
            ("post-ces-audit", [*cli, "audit", "--limit", "20"]),
        ):
            ensure_success(recorder, run_command(command, cwd=project_root, env=env, label=label))

        diff_result = run_command(
            ["git", "diff", "--", "src", "tests", "pyproject.toml"],
            cwd=project_root,
            env=env,
            label="target-git-diff",
        )
        ensure_success(recorder, diff_result)
        final_pytest = run_command(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=project_root,
            env=env,
            label="final-pytest",
        )
        ensure_success(recorder, final_pytest)
        smoke = run_command(
            direct_calculator_smoke_command(),
            cwd=project_root,
            env=direct_smoke_env(env),
            label="direct-calculator-smoke",
        )
        ensure_success(recorder, smoke)
        final_status = run_command(
            ["git", "status", "--short", "--branch"],
            cwd=project_root,
            env=env,
            label="final-git-status",
        )
        ensure_success(recorder, final_status)

        recorder.write_text("target-project.diff", diff_result.output)
        recorder.write_text("scratch-test-output.txt", final_pytest.output)
        recorder.write_text("direct-calculator-smoke.txt", smoke.output)

        baseline_manifest_id = extract_labeled_manifest_id(recorder.results, "ces-build-baseline-interactive")
        brownfield_manifest_id = extract_labeled_manifest_id(recorder.results, "ces-build-brownfield-interactive")
        passed = True
        recorder.write_summary(
            {
                "passed": True,
                "mode": args.mode,
                "runtime": args.runtime,
                "scratch_project": str(project_root),
                "evidence_dir": str(evidence_dir),
                "baseline_manifest_id": baseline_manifest_id,
                "brownfield_manifest_id": brownfield_manifest_id,
                "post_merge_review_returncode": post_merge_review.returncode,
                "post_merge_approve_returncode": post_merge_approve.returncode,
                "final_pytest_returncode": final_pytest.returncode,
                "direct_smoke_returncode": smoke.returncode,
                "final_git_status": final_status.output,
                "commands": [asdict(result) for result in recorder.results],
            }
        )
        print(f"PASS brownfield CES E2E ({args.mode} mode)")
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
        print(f"FAIL brownfield CES E2E: {exc}", file=sys.stderr)
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
