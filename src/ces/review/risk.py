"""Deterministic risk scoring and review path generation."""

from __future__ import annotations

from collections import defaultdict

from ces.review.models import (
    AreaRisk,
    DiffIndex,
    ReviewPath,
    ReviewPathStep,
    RiskItem,
    RiskMap,
    RiskSignal,
    VerificationSummary,
)

_HIGH_AREAS = {"execution", "runtime", "persistence", "security", "safety", "governance", "verification", "review"}
_MEDIUM_AREAS = {"cli", "ci", "packaging", "harness", "intake"}
_PATTERN_SIGNALS = {
    "subprocess_execution": (
        "subprocess",
        "subprocess",
        "high",
        25,
        "Changed content references subprocess execution.",
    ),
    "shell_execution": ("subprocess", "shell=True", "critical", 35, "Changed content references shell execution."),
    "filesystem_write": (
        "filesystem_boundary",
        "write_text",
        "high",
        20,
        "Changed content references filesystem writes.",
    ),
    "filesystem_delete": ("data_loss", "unlink", "high", 25, "Changed content references deletion/removal."),
    "network_call": ("network", "httpx", "medium", 14, "Changed content references network clients."),
    "secret_handling": ("security", "secret", "high", 25, "Changed content references secrets or credentials."),
    "external_side_effect": (
        "external_side_effect",
        "send_message",
        "high",
        25,
        "Changed content references external sends/posts.",
    ),
    "concurrency": (
        "concurrency",
        "asyncio",
        "medium",
        10,
        "Changed content references concurrency or async behavior.",
    ),
}
_PATTERN_ALIASES = {
    "filesystem_write": ("open(", "os.replace", "mkdir", "write_bytes"),
    "filesystem_delete": ("rmtree", "remove(", "delete"),
    "network_call": ("requests", "urllib", "socket", "curl"),
    "secret_handling": ("token", "password", "credential", "api_key"),
    "external_side_effect": ("github-comment", "gh pr comment", "post_comment", "send("),
    "concurrency": ("threading", "retry", "idempot"),
}
_CHECKPOINTS = {
    "subprocess": "Is user-controlled input passed into subprocesses or shell commands?",
    "filesystem_boundary": "Are generated paths normalized and contained under the project root?",
    "data_loss": "Can this change delete or overwrite user data outside CES-owned paths?",
    "network": "Are network calls optional, bounded, and free of secret leakage?",
    "external_side_effect": "Can retries double-send, double-post, or spam external systems?",
    "security": "Are tokens, credentials, and secret-shaped values redacted before persistence/output?",
    "public_cli_api": "Does the CLI behavior match existing user-facing conventions?",
    "persistence": "Do state writes preserve migration and backward-compatibility expectations?",
    "packaging_release": "Could dependency, lockfile, or release metadata changes alter installs?",
    "test_gap": "Are tests proving changed behavior rather than implementation details?",
    "prompt_injection": "Is repository-derived text treated as data, not instructions?",
}


def build_risk_map(diff_index: DiffIndex, verification: VerificationSummary) -> RiskMap:
    """Compute explainable file and area risks for a diff."""

    file_risks = tuple(
        sorted((_risk_item(file, verification) for file in diff_index.changed_files), key=_risk_sort_key)
    )
    area_risks = _area_risks(file_risks)
    warnings: list[str] = list(diff_index.warnings)
    if len({item.conceptual_area for item in file_risks}) >= 4 or len(file_risks) > 20:
        warnings.append("Broad cross-cutting change: review multiple conceptual areas before approval.")
    review_first = file_risks[:8]
    checkpoints = _checkpoints(file_risks)
    overall_score = max((item.score for item in file_risks), default=0)
    if warnings:
        overall_score += 5
    return RiskMap(
        overall_score=overall_score,
        overall_level=_level(overall_score),
        file_risks=file_risks,
        area_risks=area_risks,
        review_first=review_first,
        checkpoints=checkpoints,
        warnings=tuple(warnings),
    )


def build_review_path(risk_map: RiskMap) -> ReviewPath:
    """Turn a risk map into a short, risk-first human review path."""

    steps: list[ReviewPathStep] = []
    for index, item in enumerate(risk_map.review_first, start=1):
        reason = item.signals[0].reason if item.signals else "Changed file needs human review."
        steps.append(
            ReviewPathStep(
                order=index,
                target=item.path,
                kind="file",
                reason=reason,
                risk_level=item.level,
                files=(item.path,),
                checkpoints=tuple(_checkpoint_for_signal(signal) for signal in item.signals[:3]),
            )
        )
    if not steps:
        steps.append(
            ReviewPathStep(
                order=1,
                target="No changed files",
                kind="summary",
                reason="The requested diff has no changed files.",
                risk_level="low",
            )
        )
    return ReviewPath(steps=tuple(steps), checkpoints=risk_map.checkpoints)


def _risk_item(file, verification: VerificationSummary) -> RiskItem:
    signals: list[RiskSignal] = []
    score = 0
    classification = file.classification
    if file.status in {"deleted", "renamed", "type_changed", "unmerged"}:
        delta = {"deleted": 25, "renamed": 12, "type_changed": 18, "unmerged": 25}.get(file.status, 10)
        signals.append(
            RiskSignal(
                kind=f"status_{file.status}",
                category="change_operation",
                severity=_level(delta),
                score=delta,
                reason=f"File status is {file.status}.",
            )
        )
        score += delta
    changed_lines = file.additions + file.deletions
    if changed_lines > 500:
        signals.append(
            RiskSignal(
                kind="large_change",
                category="broad_diff",
                severity="high",
                score=20,
                reason="File has more than 500 changed lines.",
            )
        )
        score += 20
    elif changed_lines > 50:
        signals.append(
            RiskSignal(
                kind="moderate_change",
                category="broad_diff",
                severity="medium",
                score=8,
                reason="File has more than 50 changed lines.",
            )
        )
        score += 8
    if classification.conceptual_area in _HIGH_AREAS:
        signals.append(
            RiskSignal(
                kind=f"area_{classification.conceptual_area}",
                category="semantic_area",
                severity="high",
                score=18,
                reason=f"Changed file is in the {classification.conceptual_area} surface.",
            )
        )
        score += 18
    elif classification.conceptual_area in _MEDIUM_AREAS:
        category = (
            "public_cli_api"
            if classification.conceptual_area == "cli"
            else "packaging_release"
            if classification.conceptual_area in {"ci", "packaging"}
            else "semantic_area"
        )
        signals.append(
            RiskSignal(
                kind=f"area_{classification.conceptual_area}",
                category=category,
                severity="medium",
                score=10,
                reason=f"Changed file is in the {classification.conceptual_area} surface.",
            )
        )
        score += 10
    if classification.lockfile:
        signals.append(
            RiskSignal(
                kind="lockfile",
                category="packaging_release",
                severity="medium",
                score=10,
                reason="Lockfile/dependency changes can alter installs.",
            )
        )
        score += 10
    if classification.generated:
        signals.append(
            RiskSignal(
                kind="generated_artifact",
                category="generated_artifact",
                severity="low",
                score=2,
                reason="Generated artifact detected; review source of generation first.",
            )
        )
        score += 2
    pattern_score, pattern_signals = _content_signals(file.content_excerpt)
    score += pattern_score
    signals.extend(pattern_signals)
    if verification.status in {"failed", "skipped", "not_run", "unknown"} and classification.role == "source":
        delta = 14 if verification.status == "failed" else 8
        signals.append(
            RiskSignal(
                kind="verification_gap",
                category="test_gap",
                severity="medium",
                score=delta,
                reason=f"Verification status is {verification.status}; source risk cannot be downgraded.",
            )
        )
        score += delta
    if classification.role in {"doc", "test"} and not pattern_signals and file.status not in {"deleted", "unmerged"}:
        score = min(score, 12)
    return RiskItem(
        path=file.path,
        role=classification.role,
        conceptual_area=classification.conceptual_area,
        score=score,
        level=_level(score),
        signals=tuple(
            signals
            or (
                RiskSignal(
                    kind="changed_file",
                    category="semantic_area",
                    severity="low",
                    score=1,
                    reason="File changed with no high-risk deterministic signal.",
                ),
            )
        ),
    )


def _content_signals(excerpt: str) -> tuple[int, list[RiskSignal]]:
    lowered = excerpt.lower()
    score = 0
    signals: list[RiskSignal] = []
    for kind, (category, primary, severity, delta, reason) in _PATTERN_SIGNALS.items():
        aliases = (primary.lower(), *(_PATTERN_ALIASES.get(kind, ())))
        if any(alias.lower() in lowered for alias in aliases):
            signals.append(RiskSignal(kind=kind, category=category, severity=severity, score=delta, reason=reason))
            score += delta
    return score, signals


def _area_risks(file_risks: tuple[RiskItem, ...]) -> tuple[AreaRisk, ...]:
    scores: dict[str, int] = defaultdict(int)
    files: dict[str, list[str]] = defaultdict(list)
    for item in file_risks:
        scores[item.conceptual_area] += item.score
        files[item.conceptual_area].append(item.path)
    return tuple(
        AreaRisk(area=area, score=score, level=_level(score), files=tuple(sorted(files[area])))
        for area, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    )


def _checkpoints(file_risks: tuple[RiskItem, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for item in file_risks:
        for signal in item.signals:
            checkpoint = _checkpoint_for_signal(signal)
            if checkpoint and checkpoint not in seen:
                seen.append(checkpoint)
    if not seen:
        seen.append("Are tests proving the changed behavior rather than only implementation details?")
    return tuple(seen[:8])


def _checkpoint_for_signal(signal: RiskSignal) -> str:
    return _CHECKPOINTS.get(signal.category, "Does this change match the stated intent and existing conventions?")


def _level(score: int) -> str:
    if score >= 70:
        return "critical"
    if score >= 40:
        return "high"
    if score >= 20:
        return "medium"
    return "low"


def _risk_sort_key(item: RiskItem) -> tuple[int, str]:
    return (-item.score, item.path)
