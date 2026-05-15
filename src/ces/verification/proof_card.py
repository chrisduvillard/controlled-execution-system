"""Beginner-facing proof card reports for CES-built projects."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ces.execution.secrets import scrub_secrets_recursive
from ces.verification.completion_contract import CompletionContract, VerificationCommand

_SCHEMA_VERSION = "1.0"
_VERIFICATION_RESULT_PATH = Path(".ces") / "latest-verification.json"


@dataclass(frozen=True)
class ProofCardReport:
    """Compact shareable proof summary for a local project."""

    project_root: Path
    objective: str | None
    evidence_status: str
    ship_recommendation: str
    changed_files: tuple[str, ...]
    commands_run: tuple[dict[str, Any], ...]
    verification_commands: tuple[VerificationCommand, ...]
    missing_required_artifacts: tuple[str, ...]
    unproven_areas: tuple[str, ...]
    next_command: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_root": self.project_root.name or ".",
            "objective": self.objective,
            "evidence_status": self.evidence_status,
            "ship_recommendation": self.ship_recommendation,
            "changed_files": list(self.changed_files),
            "commands_run": list(self.commands_run),
            "verification_commands": [
                _shareable_verification_command(command) for command in self.verification_commands
            ],
            "missing_required_artifacts": list(self.missing_required_artifacts),
            "unproven_areas": list(self.unproven_areas),
            "next_command": self.next_command,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def to_markdown(self) -> str:
        payload = self.to_dict()
        command_lines = _bullet(
            f"`{command['command']}` — {command['kind']} / {command['id']}" for command in payload["commands_run"]
        )
        return (
            "\n".join(
                [
                    "# CES Proof Card",
                    "",
                    f"Project root: `{payload['project_root']}`",
                    f"Objective: {payload['objective'] or 'No completion contract found.'}",
                    f"Evidence status: **{payload['evidence_status']}**",
                    f"Ship recommendation: **{payload['ship_recommendation']}**",
                    f"Next command: `{payload['next_command']}`",
                    "",
                    "## Changed files",
                    "",
                    *_bullet(payload["changed_files"]),
                    "",
                    "## Commands / evidence",
                    "",
                    *command_lines,
                    "",
                    "## Missing required artifacts",
                    "",
                    *_bullet(payload["missing_required_artifacts"]),
                    "",
                    "## Unproven areas",
                    "",
                    *_bullet(payload["unproven_areas"]),
                ]
            ).rstrip()
            + "\n"
        )


def build_proof_card(project_root: str | Path) -> ProofCardReport:
    """Build a read-only proof card from local CES evidence and project files."""

    root = Path(project_root).resolve()
    contract_path = root / ".ces" / "completion-contract.json"
    contract = CompletionContract.read(contract_path) if contract_path.is_file() else None
    verification = _load_latest_verification(root)
    missing = _missing_required_artifacts(root, contract, verification)
    unproven = _unproven_areas(contract, missing, verification, root=root)
    verification_matches = _verification_matches_contract(contract, verification, root)
    status = (
        "candidate"
        if contract and _verification_passed(verification) and verification_matches and not missing and not unproven
        else "incomplete"
    )
    recommendation = "candidate" if status == "candidate" else "no-ship"
    return ProofCardReport(
        project_root=root,
        objective=contract.request if contract else None,
        evidence_status=status,
        ship_recommendation=recommendation,
        changed_files=_changed_files(root),
        commands_run=_commands_run(verification),
        verification_commands=contract.inferred_commands if contract else (),
        missing_required_artifacts=tuple(missing),
        unproven_areas=tuple(unproven),
        next_command=contract.next_ces_command if contract else "ces ship",
    )


def _missing_required_artifacts(
    root: Path,
    contract: CompletionContract | None,
    verification: dict[str, Any] | None,
) -> list[str]:
    if contract is None:
        return ["completion contract"]
    missing: list[str] = []
    known_artifacts = {"readme.md", "run command", "test command", "verification evidence"}
    for artifact in contract.required_artifacts:
        normalized = artifact.strip().lower()
        known_missing = (
            (normalized == "readme.md" and not (root / "README.md").is_file())
            or (normalized == "run command" and not _readme_has_instruction(root, ("run", "start")))
            or (normalized == "test command" and not _readme_has_instruction(root, ("test", "pytest", "npm test")))
            or (normalized == "verification evidence" and not _verification_passed(verification))
        )
        if known_missing or (normalized not in known_artifacts and not _safe_project_artifact_exists(root, artifact)):
            missing.append(artifact)
    return missing


def _unproven_areas(
    contract: CompletionContract | None,
    missing: list[str],
    verification: dict[str, Any] | None,
    *,
    root: Path,
) -> list[str]:
    if contract is None:
        return ["No completion contract found; run `ces build --from-scratch ...` or `ces ship ...` first."]
    areas: list[str] = []
    if missing:
        areas.append("Required beginner handoff artifacts are incomplete.")
    if not contract.inferred_commands:
        areas.append("No inferred verification commands are recorded.")
    if verification is None:
        areas.append("No persisted verification run found; run `ces verify --json` before treating this as proof.")
    elif not _verification_passed(verification):
        areas.append("Latest persisted verification run did not pass.")
    elif not _verification_matches_contract(contract, verification, root):
        areas.append("Latest persisted verification run does not match the current completion contract.")
    if contract.proof_requirements and missing:
        areas.extend(contract.proof_requirements)
    return areas


def _load_latest_verification(root: Path) -> dict[str, Any] | None:
    path = root / _VERIFICATION_RESULT_PATH
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _verification_payload(verification: dict[str, Any] | None) -> dict[str, Any] | None:
    if verification is None:
        return None
    payload = verification.get("verification", verification)
    return payload if isinstance(payload, dict) else None


def _verification_passed(verification: dict[str, Any] | None) -> bool:
    payload = _verification_payload(verification)
    return bool(payload and payload.get("passed") is True)


def _verification_matches_contract(
    contract: CompletionContract | None,
    verification: dict[str, Any] | None,
    root: Path,
) -> bool:
    """Return True when persisted verification belongs to this contract."""

    if contract is None:
        return False
    payload = _verification_payload(verification)
    if payload is None:
        return False
    expected_contract_path = root / ".ces" / "completion-contract.json"
    recorded_contract_path = verification.get("contract_path") if verification else None
    if isinstance(recorded_contract_path, str) and recorded_contract_path:
        try:
            if Path(recorded_contract_path).resolve() != expected_contract_path.resolve():
                return False
        except OSError:
            return False
    commands = payload.get("commands", [])
    if not isinstance(commands, list):
        return False
    by_id = {command.get("id"): command for command in commands if isinstance(command, dict)}
    for expected in contract.inferred_commands:
        actual = by_id.get(expected.id)
        if not actual:
            return False
        expected_codes = tuple(expected.expected_exit_codes or (0,))
        actual_codes = _int_tuple(actual.get("expected_exit_codes"))
        actual_timeout = _optional_int(actual.get("timeout_seconds"))
        if (
            actual.get("command") != scrub_secrets_recursive(expected.command)
            or actual.get("kind") != expected.kind
            or actual.get("required") is not expected.required
            or actual.get("cwd", ".") != expected.cwd
            or actual_timeout != expected.timeout_seconds
            or actual_codes != expected_codes
        ):
            return False
        if actual.get("exit_code") not in expected_codes:
            return False
        if expected.required and actual.get("passed") is not True:
            return False
    return True


def _int_tuple(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list | tuple):
        return ()
    try:
        return tuple(int(item) for item in value)
    except (TypeError, ValueError):
        return ()


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _commands_run(verification: dict[str, Any] | None) -> tuple[dict[str, Any], ...]:
    payload = _verification_payload(verification)
    if payload is None:
        return ()
    commands = payload.get("commands", [])
    if not isinstance(commands, list):
        return ()
    return tuple(_shareable_command(command) for command in commands if isinstance(command, dict))


def _shareable_command(command: dict[str, Any]) -> dict[str, Any]:
    """Return command evidence safe for a compact shareable proof card."""

    allowed = {
        "id",
        "kind",
        "command",
        "required",
        "cwd",
        "timeout_seconds",
        "exit_code",
        "expected_exit_codes",
        "passed",
    }
    return scrub_secrets_recursive({key: command[key] for key in allowed if key in command})


def _shareable_verification_command(command: VerificationCommand) -> dict[str, Any]:
    """Return contract command metadata without leaking inline secrets."""

    return scrub_secrets_recursive(asdict(command))


def _readme_has_instruction(root: Path, verbs: tuple[str, ...]) -> bool:
    readme = root / "README.md"
    if not readme.is_file():
        return False
    text = readme.read_text(encoding="utf-8", errors="ignore")
    for verb in verbs:
        escaped = re.escape(verb)
        if re.search(rf"(?im)^\s*(?:[-*]\s*)?{escaped}\s*:\s*`?\S+", text):
            return True
        if re.search(rf"(?im)^\s*(?:```(?:bash|sh|shell)?\s*)?\$\s*\S*{escaped}\S*\b", text):
            return True
    return False


def _safe_project_artifact_exists(root: Path, artifact: str) -> bool:
    path = Path(artifact)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    try:
        resolved_root = root.resolve()
        candidate = (resolved_root / path).resolve()
        candidate.relative_to(resolved_root)
    except (OSError, ValueError):
        return False
    return candidate.exists()


def _changed_files(root: Path) -> tuple[str, ...]:
    git = shutil.which("git")
    if git is None:
        return ()
    try:
        result = subprocess.run(  # noqa: S603
            [git, "--no-optional-locks", "status", "--porcelain=v1", "-z"],
            cwd=root,
            check=False,
            capture_output=True,
            text=False,
            timeout=5,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if result.returncode != 0:
        return ()
    files: list[str] = []
    entries = [entry for entry in result.stdout.split(b"\0") if entry]
    skip_next = False
    for raw in entries:
        if skip_next:
            skip_next = False
            continue
        entry = raw.decode("utf-8", errors="replace")
        if len(entry) < 4:
            continue
        status = entry[:2]
        path = entry[3:]
        if status.startswith(("R", "C")):
            # Porcelain -z emits the source path as a second entry; the first path is the destination.
            skip_next = True
        if path:
            files.append(path)
    return tuple(files)


def _bullet(items: list[str] | tuple[str, ...] | Any) -> list[str]:
    values = list(items)
    if not values:
        return ["- None recorded."]
    return [f"- {item}" for item in values]
