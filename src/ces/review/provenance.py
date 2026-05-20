"""Agent provenance loading for semantic review artifacts."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from ces.review.models import AgentProvenance
from ces.shared.secrets import scrub_secrets_from_text, scrub_secrets_recursive

_DEFAULT_PROJECT_ID = "default"


def load_agent_provenance(project_root: Path, *, build_id: str | None = None) -> AgentProvenance:
    """Load CES builder provenance when available, else emit a safe local-diff fallback."""

    root = project_root.resolve()
    snapshot = _builder_snapshot(root, build_id=build_id)
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


def load_build_context(project_root: Path, build_id: str) -> dict[str, Any] | None:
    """Return intent/provenance context for a specific CES builder run identifier."""

    snapshot = _builder_snapshot(project_root.resolve(), build_id=build_id)
    if snapshot is None:
        return None
    brief = _dict(snapshot.get("brief"))
    session = _dict(snapshot.get("session"))
    manifest = _dict(snapshot.get("manifest"))
    objective = _first_text(brief.get("request"), session.get("request"), manifest.get("description"))
    requirement_texts = _build_requirement_texts(brief, session, manifest)
    return scrub_secrets_recursive(
        {
            "build_id": build_id,
            "objective": scrub_secrets_from_text(objective) if objective else None,
            "requirement_texts": requirement_texts,
            "snapshot": snapshot,
            "source_refs": tuple(str(item) for item in _list(snapshot.get("source_refs"))[:8]),
        }
    )


def _latest_builder_snapshot(root: Path) -> dict[str, Any] | None:
    return _builder_snapshot(root, build_id=None)


def _builder_snapshot(root: Path, *, build_id: str | None) -> dict[str, Any] | None:
    state_db = root / ".ces" / "state.db"
    if not state_db.is_file() or state_db.is_symlink():
        return None
    project_id = _project_id(root)
    try:
        conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            if build_id:
                return _snapshot_for_build_id(conn, project_id=project_id, build_id=build_id)
            session = _fetch_latest(conn, "builder_sessions", project_id)
            return _snapshot_from_session(conn, project_id, session) if session else None
        finally:
            conn.close()
    except (sqlite3.Error, OSError, RuntimeError, ValueError):
        return None


def _snapshot_for_build_id(conn: sqlite3.Connection, *, project_id: str, build_id: str) -> dict[str, Any] | None:
    """Resolve a build ID through one primary match, then derive related rows from it.

    Resolution order is intentionally strict to avoid mixing unrelated records
    that merely share a string value: session ID, brief ID, manifest ID,
    runtime invocation/run ID, then legacy session-linked IDs.
    """

    session = _fetch_one_by_any(conn, "builder_sessions", build_id, ("session_id",), project_id)
    if session is not None:
        return _snapshot_from_session(conn, project_id, session)

    brief = _fetch_one_by_any(conn, "builder_briefs", build_id, ("brief_id",), project_id)
    if brief is not None:
        return _snapshot_from_brief(conn, project_id, brief)

    manifest = _fetch_one_by_any(conn, "manifests", build_id, ("manifest_id",), project_id)
    if manifest is not None:
        return _snapshot_from_manifest_id(conn, project_id, _str(manifest.get("manifest_id")), manifest=manifest)

    runtime = _fetch_one_by_any(
        conn, "runtime_executions", build_id, ("invocation_ref", "run_id", "execution_id"), project_id
    )
    if runtime is not None:
        return _snapshot_from_runtime(conn, project_id, runtime)

    session = _fetch_one_by_any(
        conn,
        "builder_sessions",
        build_id,
        ("manifest_id", "runtime_manifest_id", "evidence_packet_id", "approval_manifest_id"),
        project_id,
    )
    if session is not None:
        return _snapshot_from_session(conn, project_id, session)
    return None


def _snapshot_from_session(
    conn: sqlite3.Connection, project_id: str, session: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not session:
        return None
    brief = None
    brief_id = _str(session.get("brief_id"))
    if brief_id:
        brief = _fetch_one_project_match(conn, "builder_briefs", "brief_id", brief_id, project_id)
    manifest_id = _str(
        session.get("manifest_id") or session.get("runtime_manifest_id") or (brief or {}).get("manifest_id")
    )
    if brief is None and manifest_id:
        brief = _fetch_one_project_match(conn, "builder_briefs", "manifest_id", manifest_id, project_id)
    manifest = (
        _fetch_one_project_match(conn, "manifests", "manifest_id", manifest_id, project_id) if manifest_id else None
    )
    runtime_manifest_id = _str(session.get("runtime_manifest_id") or manifest_id)
    runtime = (
        _fetch_one_project_match(conn, "runtime_executions", "manifest_id", runtime_manifest_id, project_id)
        if runtime_manifest_id
        else None
    )
    return _snapshot(session=session, brief=brief, manifest=manifest, runtime=runtime)


def _snapshot_from_brief(conn: sqlite3.Connection, project_id: str, brief: dict[str, Any]) -> dict[str, Any] | None:
    brief_id = _str(brief.get("brief_id"))
    manifest_id = _str(brief.get("manifest_id"))
    session = _fetch_one_project_match(conn, "builder_sessions", "brief_id", brief_id, project_id) if brief_id else None
    if session is None and manifest_id:
        session = _session_for_manifest_id(conn, project_id, manifest_id)
    manifest = (
        _fetch_one_project_match(conn, "manifests", "manifest_id", manifest_id, project_id) if manifest_id else None
    )
    runtime = (
        _fetch_one_project_match(conn, "runtime_executions", "manifest_id", manifest_id, project_id)
        if manifest_id
        else None
    )
    return _snapshot(session=session, brief=brief, manifest=manifest, runtime=runtime)


def _snapshot_from_manifest_id(
    conn: sqlite3.Connection,
    project_id: str,
    manifest_id: str | None,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not manifest_id:
        return None
    session = _session_for_manifest_id(conn, project_id, manifest_id)
    brief = _fetch_one_project_match(conn, "builder_briefs", "manifest_id", manifest_id, project_id)
    if manifest is None:
        manifest = _fetch_one_project_match(conn, "manifests", "manifest_id", manifest_id, project_id)
    runtime = _fetch_one_project_match(conn, "runtime_executions", "manifest_id", manifest_id, project_id)
    return _snapshot(session=session, brief=brief, manifest=manifest, runtime=runtime)


def _snapshot_from_runtime(conn: sqlite3.Connection, project_id: str, runtime: dict[str, Any]) -> dict[str, Any] | None:
    manifest_id = _str(runtime.get("manifest_id"))
    if not manifest_id:
        return _snapshot(session=None, brief=None, manifest=None, runtime=runtime)
    session = _session_for_manifest_id(conn, project_id, manifest_id)
    brief = _fetch_one_project_match(conn, "builder_briefs", "manifest_id", manifest_id, project_id)
    manifest = _fetch_one_project_match(conn, "manifests", "manifest_id", manifest_id, project_id)
    return _snapshot(session=session, brief=brief, manifest=manifest, runtime=runtime)


def _session_for_manifest_id(conn: sqlite3.Connection, project_id: str, manifest_id: str) -> dict[str, Any] | None:
    return _fetch_one_by_any(conn, "builder_sessions", manifest_id, ("manifest_id", "runtime_manifest_id"), project_id)


def _snapshot(
    *,
    session: dict[str, Any] | None,
    brief: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    runtime: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if session is None and brief is None and manifest is None and runtime is None:
        return None
    return scrub_secrets_recursive(
        {
            "session": session,
            "brief": brief,
            "manifest": manifest,
            "runtime_execution": runtime,
            "source_refs": _source_refs(session, brief, manifest, runtime),
        }
    )


def _project_id(root: Path) -> str:
    config = root / ".ces" / "config.yaml"
    if not config.is_file() or config.is_symlink():
        return _DEFAULT_PROJECT_ID
    try:
        payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return _DEFAULT_PROJECT_ID
    if not isinstance(payload, dict):
        return _DEFAULT_PROJECT_ID
    value = payload.get("project_id")
    return str(value) if value not in (None, "") else _DEFAULT_PROJECT_ID


def _fetch_latest(conn: sqlite3.Connection, table: str, project_id: str) -> dict[str, Any] | None:
    columns = _table_columns(conn, table)
    if "project_id" not in columns:
        return None
    order = " ORDER BY created_at DESC" if "created_at" in columns else ""
    return _fetch_one(conn, f"SELECT * FROM {table} WHERE project_id = ?{order} LIMIT 1", (project_id,))  # noqa: S608


def _fetch_one_project_match(
    conn: sqlite3.Connection, table: str, column: str | None, value: str | None, project_id: str
) -> dict[str, Any] | None:
    if not column or not value:
        return None
    columns = _table_columns(conn, table)
    if column not in columns or "project_id" not in columns:
        return None
    order = " ORDER BY created_at DESC" if "created_at" in columns else ""
    return _fetch_one(
        conn,
        f"SELECT * FROM {table} WHERE {column} = ? AND project_id = ?{order} LIMIT 1",  # noqa: S608
        (value, project_id),
    )


def _fetch_one_by_any(
    conn: sqlite3.Connection, table: str, value: str, candidate_columns: tuple[str, ...], project_id: str
) -> dict[str, Any] | None:
    columns = _table_columns(conn, table)
    usable = [column for column in candidate_columns if column in columns]
    if not usable or "project_id" not in columns:
        return None
    where = " OR ".join(f"{column} = ?" for column in usable)
    order = " ORDER BY created_at DESC" if "created_at" in columns else ""
    params: tuple[object, ...] = (project_id, *([value] * len(usable)))
    return _fetch_one(conn, f"SELECT * FROM {table} WHERE project_id = ? AND ({where}){order} LIMIT 1", params)  # noqa: S608


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {str(row["name"] if isinstance(row, sqlite3.Row) else row[1]) for row in rows}


def _fetch_one(conn: sqlite3.Connection, query: str, params: tuple[object, ...]) -> dict[str, Any] | None:
    try:
        row = conn.execute(query, params).fetchone()
    except sqlite3.Error:
        return None
    return _row_dict(row) if row is not None else None


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(zip(row.keys(), row, strict=True))


def _source_refs(*records: dict[str, Any] | None) -> list[str]:
    refs: list[str] = []
    for record in records:
        if not record:
            continue
        for key in (
            "session_id",
            "brief_id",
            "manifest_id",
            "runtime_manifest_id",
            "evidence_packet_id",
            "packet_id",
            "invocation_ref",
        ):
            value = _str(record.get(key))
            if value:
                refs.append(f"{key}:{value}")
    deduped: list[str] = []
    for ref in refs:
        if ref not in deduped:
            deduped.append(ref)
    return deduped[:8]


def _build_requirement_texts(
    brief: dict[str, Any], session: dict[str, Any], manifest: dict[str, Any]
) -> tuple[str, ...]:
    texts: list[str] = []
    for record in (brief, session, manifest):
        for key in (
            "request",
            "description",
            "constraints",
            "acceptance_criteria",
            "must_not_break",
            "source_of_truth",
            "critical_flows",
        ):
            texts.extend(_text_items(record.get(key)))
    deduped: list[str] = []
    for text in texts:
        clean = scrub_secrets_from_text(text.strip())
        if clean and clean not in deduped:
            deduped.append(clean)
    return tuple(deduped)


def _text_items(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return [stripped]
        return _text_items(decoded)
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_text_items(item))
        return result
    if isinstance(value, list | tuple | set):
        result = []
        for item in value:
            result.extend(_text_items(item))
        return result
    return [str(value)]


def _first_text(*values: object) -> str | None:
    for value in values:
        items = _text_items(value)
        if items:
            return items[0]
    return None


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _str(value: object) -> str | None:
    return str(value) if value not in (None, "") else None
