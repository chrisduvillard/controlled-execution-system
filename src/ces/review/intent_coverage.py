"""Intent coverage mapping for semantic review artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ces.execution.secrets import scrub_secrets_from_text
from ces.review.models import DiffIndex, IntentCoverageItem, IntentCoverageMap, VerificationSummary

_TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]{3,}")


def build_intent_coverage(
    project_root: Path,
    diff_index: DiffIndex,
    verification: VerificationSummary,
    *,
    objective: str | None = None,
    deferred_scope: tuple[str, ...] = (),
) -> IntentCoverageMap:
    """Derive coverage items from CES contracts or objective fallback."""

    requirement_texts, sources = _load_requirements(project_root, objective)
    return build_intent_coverage_from_items(
        objective=objective or (requirement_texts[0] if requirement_texts else None),
        requirement_texts=tuple(requirement_texts or (objective or "Review local diff",)),
        diff_index=diff_index,
        verification=verification,
        deferred_scope=deferred_scope,
        sources=tuple(sources or ("objective",)),
    )


def build_intent_coverage_from_items(
    *,
    objective: str | None,
    requirement_texts: tuple[str, ...],
    diff_index: DiffIndex,
    verification: VerificationSummary,
    deferred_scope: tuple[str, ...] = (),
    sources: tuple[str, ...] = ("objective",),
) -> IntentCoverageMap:
    """Map requirement texts to deterministic diff and verification evidence."""

    deferred_normalized = {item.lower() for item in deferred_scope}
    items: list[IntentCoverageItem] = []
    for index, text in enumerate(requirement_texts, start=1):
        clean_text = scrub_secrets_from_text(str(text).strip())
        req_id = _requirement_id(clean_text, index)
        if _is_deferred(req_id, clean_text, deferred_normalized):
            items.append(
                IntentCoverageItem(
                    requirement_id=req_id,
                    text=clean_text,
                    source=_source_for_index(sources, index),
                    status="intentionally_deferred",
                    evidence_quality="contract_boundary",
                    confidence="high",
                    notes=("Requirement appears in deferred/non-goal scope.",),
                )
            )
            continue
        matched_files = _matched_files(clean_text, diff_index)
        verification_refs = tuple(
            command.command for command in verification.commands if _command_matches(command.command, clean_text)
        )
        status, quality, confidence, notes = _status(matched_files, verification_refs, verification)
        items.append(
            IntentCoverageItem(
                requirement_id=req_id,
                text=clean_text,
                source=_source_for_index(sources, index),
                status=status,
                changed_files=matched_files,
                verification_refs=verification_refs,
                evidence_quality=quality,
                confidence=confidence,
                notes=notes,
            )
        )
    return IntentCoverageMap(
        objective=scrub_secrets_from_text(objective or ""),
        items=tuple(items),
        summary=_summary(items),
        sources=sources,
        warnings=()
        if sources != ("objective",)
        else ("No CES execution contract/spec metadata found; objective fallback used.",),
    )


def _load_requirements(project_root: Path, objective: str | None) -> tuple[list[str], list[str]]:
    root = project_root.resolve()
    requirements: list[str] = []
    sources: list[str] = []
    for rel, source in (
        (Path(".ces/contracts/latest.json"), "execution_contract"),
        (Path(".ces/completion-contract.json"), "completion_contract"),
    ):
        path = root / rel
        if not path.is_file() or path.is_symlink():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        extracted = _extract_requirements(payload)
        if extracted:
            requirements.extend(extracted)
            sources.extend([source] * len(extracted))
    if objective:
        requirements.insert(0, objective)
        sources.insert(0, "objective")
    return requirements, sources


def _extract_requirements(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    texts: list[str] = []
    for key in ("objective", "request", "problem"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value)
    for key in ("acceptance_criteria", "required_evidence", "requirements", "must_not_break", "non_goals"):
        texts.extend(_iter_text_items(payload.get(key)))
    behavior = payload.get("behavior_delta")
    if isinstance(behavior, dict):
        for key, value in behavior.items():
            for item in _iter_text_items(value):
                texts.append(f"{key}: {item}")
    return [scrub_secrets_from_text(text) for text in texts if text.strip()]


def _iter_text_items(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                result.append(str(item.get("text") or item.get("description") or item.get("name") or item))
        return result
    if isinstance(value, dict):
        return [str(item) for item in value.values() if isinstance(item, str)]
    return []


def _requirement_id(text: str, index: int) -> str:
    match = re.match(r"\s*([A-Z]{2,}[-_ ]?\d+)", text)
    return match.group(1).replace(" ", "-") if match else f"REQ-{index:03d}"


def _is_deferred(req_id: str, text: str, deferred: set[str]) -> bool:
    lowered = text.lower()
    return (
        req_id.lower() in deferred
        or any(item and item in lowered for item in deferred)
        or "defer" in lowered
        or "non-goal" in lowered
    )


def _matched_files(text: str, diff_index: DiffIndex) -> tuple[str, ...]:
    tokens = {token.lower().strip("./") for token in _TOKEN_RE.findall(text) if len(token) >= 4}
    matches: list[str] = []
    for file in diff_index.changed_files:
        haystack = f"{file.path} {file.classification.role} {file.classification.conceptual_area}".lower()
        if any(token in haystack or token.replace("_", "-") in haystack for token in tokens):
            matches.append(file.path)
    return tuple(sorted(set(matches)))


def _command_matches(command: str, text: str) -> bool:
    lowered = command.lower()
    tokens = {token.lower() for token in _TOKEN_RE.findall(text)}
    return any(token in lowered for token in tokens if len(token) >= 4)


def _status(
    matched_files: tuple[str, ...],
    verification_refs: tuple[str, ...],
    verification: VerificationSummary,
) -> tuple[str, str, str, tuple[str, ...]]:
    if matched_files and verification.status == "passed" and verification_refs:
        return (
            "implemented",
            "deterministic",
            "high",
            ("Changed files and passed verification command matched deterministically.",),
        )
    if matched_files:
        return (
            "partially_implemented",
            "diff_match",
            "medium",
            ("Changed files match, but verification evidence is incomplete or not specific.",),
        )
    return "unknown", "missing", "low", ("No deterministic file or verification evidence matched this requirement.",)


def _summary(items: list[IntentCoverageItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def _source_for_index(sources: tuple[str, ...], index: int) -> str:
    return sources[index - 1] if index - 1 < len(sources) else sources[-1] if sources else "objective"
