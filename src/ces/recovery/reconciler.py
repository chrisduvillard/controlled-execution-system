"""Reconcile stale builder runtime sessions into actionable recovery state."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_STALE_AFTER_SECONDS = 3900
_RUNTIME_LOCK_NAME = "builder-runtime.lock"


@dataclass(frozen=True)
class BuilderSessionReconciliation:
    changed: bool
    session_id: str | None
    reason: str | None
    message: str | None
    stale: bool = False
    active_runtime: bool = False


def write_builder_runtime_lock(*, project_root: Path, session_id: str | None, manifest_id: str | None) -> Path:
    """Persist a parent-process runtime lock so recovery can distinguish live work from interruption."""
    lock_path = _runtime_lock_path(project_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "session_id": _safe_lock_value(session_id),
                "manifest_id": _safe_lock_value(manifest_id),
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return lock_path


def clear_builder_runtime_lock(
    *, project_root: Path, session_id: str | None = None, manifest_id: str | None = None
) -> None:
    """Remove the runtime lock for a completed parent process when it still belongs to this run."""
    lock_path = _runtime_lock_path(project_root)
    if not lock_path.exists():
        return
    session_id = _safe_lock_value(session_id)
    manifest_id = _safe_lock_value(manifest_id)
    lock = _read_runtime_lock(lock_path)
    if lock is not None:
        if session_id is not None and lock.get("session_id") not in {None, session_id}:
            return
        if manifest_id is not None and lock.get("manifest_id") not in {None, manifest_id}:
            return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return


def reconcile_stale_builder_session(
    *,
    project_root: Path,
    local_store: Any,
    stale_after_seconds: int = _DEFAULT_STALE_AFTER_SECONDS,
    mutate: bool = True,
) -> BuilderSessionReconciliation:
    """Mark stale running builder sessions blocked so recovery/status are actionable.

    A running session is considered stale immediately when CES left behind a
    runtime lock whose parent PID is no longer alive. Without lock evidence,
    reconciliation falls back to an old ``updated_at`` timestamp so legacy
    interrupted sessions remain recoverable, but the default threshold is
    intentionally longer than the default runtime timeout to avoid corrupting
    legitimate long-running work.
    """
    getter = getattr(local_store, "get_latest_builder_session", None)
    updater = getattr(local_store, "update_builder_session", None)
    if not callable(getter) or not callable(updater):
        return BuilderSessionReconciliation(False, None, None, None)

    session = getter()
    session_id = getattr(session, "session_id", None)
    if session is None or getattr(session, "stage", None) != "running":
        return BuilderSessionReconciliation(False, session_id, None, None)

    lock_status = _runtime_lock_status(project_root, session)
    if lock_status == "live":
        return BuilderSessionReconciliation(False, session_id, None, None, active_runtime=True)

    stale = lock_status == "dead"
    if not stale:
        updated_at = _parse_datetime(getattr(session, "updated_at", None))
        if updated_at is None:
            return BuilderSessionReconciliation(False, session_id, None, None)
        age = (datetime.now(timezone.utc) - updated_at).total_seconds()
        stale = age >= stale_after_seconds
    if not stale:
        return BuilderSessionReconciliation(False, session_id, None, None)

    message = (
        "CES found a stale running builder session with no live CES runtime lock; "
        "run `ces continue` to retry the saved request."
    )
    if mutate:
        updater(
            session.session_id,
            stage="blocked",
            next_action="retry_runtime",
            last_action="runtime_interrupted",
            recovery_reason="runtime_interrupted",
            last_error=message,
        )
        update_manifest = getattr(local_store, "update_manifest_workflow_state", None)
        manifest_id = _manifest_id_from_session(session)
        if callable(update_manifest) and manifest_id:
            update_manifest(manifest_id, "rejected")
    return BuilderSessionReconciliation(mutate, session.session_id, "runtime_interrupted", message, stale=True)


def _runtime_lock_path(project_root: Path) -> Path:
    return project_root / ".ces" / _RUNTIME_LOCK_NAME


def _safe_lock_value(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _manifest_id_from_session(session: Any) -> str | None:
    for attr in ("runtime_manifest_id", "manifest_id", "approval_manifest_id"):
        value = getattr(session, attr, None)
        if value:
            return str(value)
    return None


def _runtime_lock_status(project_root: Path, session: Any) -> str | None:
    lock_path = _runtime_lock_path(project_root)
    lock = _read_runtime_lock(lock_path)
    if lock is None:
        return None
    session_id = getattr(session, "session_id", None)
    manifest_ids = {
        value
        for value in (
            getattr(session, "runtime_manifest_id", None),
            getattr(session, "manifest_id", None),
            getattr(session, "approval_manifest_id", None),
        )
        if value
    }
    lock_session_id = lock.get("session_id")
    lock_manifest_id = lock.get("manifest_id")
    if lock_session_id not in {None, session_id}:
        return None
    if manifest_ids and lock_manifest_id not in {None, *manifest_ids}:
        return None
    pid = lock.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return "dead"
    return "live" if _pid_is_alive(pid) else "dead"


def _read_runtime_lock(lock_path: Path) -> dict[str, Any] | None:
    try:
        raw = lock_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"pid": None}
    return data if isinstance(data, dict) else {"pid": None}


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
