"""Agent provenance loading for semantic review artifacts."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ces.execution.secrets import scrub_secrets_recursive
from ces.review.models import AgentProvenance


def load_agent_provenance(project_root: Path, *, build_id: str | None = None) -> AgentProvenance:
    """Load CES builder provenance when available, else emit a safe local-diff fallback."""

    root = project_root.resolve()
    snapshot = _latest_builder_snapshot(root)
    if snapshot is None:
        return AgentProvenance(
            mode="local_diff_limited",
            build_id=build_id,
            limitations=("No CES builder session metadata was found for this diff.",),
        )
    manifest = _dict(snapshot.get("manifest"))
    runtime = _dict(snapshot.get("runtime_execution"))
    brief = _dict(snapshot.get("brief"))
    session = _dict(snapshot.get("session"))
    return AgentProvenance(
        mode="ces_builder" if build_id or runtime or manifest or session else "local_diff_limited",
        build_id=build_id or _str(runtime.get("invocation_ref") or runtime.get("run_id") or session.get("session_id")),
        manifest_id=_str(
            manifest.get("manifest_id") or session.get("manifest_id") or session.get("runtime_manifest_id")
        ),
        runtime=_str(runtime.get("runtime") or runtime.get("runtime_name")),
        model=_str(runtime.get("model") or runtime.get("model_id") or runtime.get("reported_model")),
        agent=_str(runtime.get("agent") or runtime.get("provider") or runtime.get("runtime_name")),
        assumptions=tuple(str(item) for item in _list(brief.get("assumptions"))[:8]),
        dissent=tuple(str(item) for item in _list(brief.get("dissent"))[:8]),
        limitations=tuple(str(item) for item in _list(brief.get("limitations"))[:8])
        or ("Repository-derived provenance is summarized and redacted.",),
        source_refs=tuple(str(item) for item in _list(snapshot.get("source_refs"))[:8]),
    )


def _latest_builder_snapshot(root: Path) -> dict[str, Any] | None:
    state_db = root / ".ces" / "state.db"
    if not state_db.is_file() or state_db.is_symlink():
        return None
    try:
        conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            session = _fetch_one(
                conn,
                "SELECT * FROM builder_sessions WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                ("default",),
            )
            if session is None:
                return None
            brief = None
            brief_id = _str(session.get("brief_id"))
            if brief_id:
                brief = _fetch_one(
                    conn,
                    "SELECT * FROM builder_briefs WHERE brief_id = ? AND project_id = ?",
                    (brief_id, "default"),
                )
            if brief is None:
                brief = _fetch_one(
                    conn,
                    "SELECT * FROM builder_briefs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                    ("default",),
                )
            manifest_id = _str(
                session.get("manifest_id") or session.get("runtime_manifest_id") or (brief or {}).get("manifest_id")
            )
            manifest = (
                _fetch_one(
                    conn,
                    "SELECT * FROM manifests WHERE manifest_id = ? AND project_id = ?",
                    (manifest_id, "default"),
                )
                if manifest_id
                else None
            )
            runtime_manifest_id = _str(session.get("runtime_manifest_id") or manifest_id)
            runtime = (
                _fetch_one(
                    conn,
                    "SELECT * FROM runtime_executions WHERE manifest_id = ? AND project_id = ?",
                    (runtime_manifest_id, "default"),
                )
                if runtime_manifest_id
                else None
            )
            return scrub_secrets_recursive(
                {
                    "session": session,
                    "brief": brief,
                    "manifest": manifest,
                    "runtime_execution": runtime,
                    "source_refs": _source_refs(session, brief, manifest, runtime),
                }
            )
        finally:
            conn.close()
    except (sqlite3.Error, OSError, RuntimeError, ValueError):
        return None


def _fetch_one(conn: sqlite3.Connection, query: str, params: tuple[object, ...]) -> dict[str, Any] | None:
    row = conn.execute(query, params).fetchone()
    return _row_dict(row) if row is not None else None


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(zip(row.keys(), row, strict=True))


def _source_refs(*records: dict[str, Any] | None) -> list[str]:
    refs: list[str] = []
    for record in records:
        if not record:
            continue
        for key in ("session_id", "brief_id", "manifest_id", "packet_id", "invocation_ref"):
            value = _str(record.get(key))
            if value:
                refs.append(f"{key}:{value}")
    return refs[:8]


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _str(value: object) -> str | None:
    return str(value) if value not in (None, "") else None
