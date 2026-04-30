"""Oracle classification result model.

Frozen dataclass holding the result of a ClassificationOracle.classify() call,
including the matched rule, confidence score, top candidate matches, and the
recommended action (auto_accept / human_review / human_classify).

Exports:
    OracleClassificationResult: Frozen dataclass for oracle classification output.
"""

from __future__ import annotations

from dataclasses import dataclass

from ces.control.services.classification import ClassificationRule


@dataclass(frozen=True)
class OracleClassificationResult:
    """Result of oracle classification with confidence score.

    Attributes:
        matched_rule: The best-matching ClassificationRule, or None when
            confidence is below the human_review threshold.
        confidence: Cosine similarity score in [0.0, 1.0]. Exact matches
            from the Phase 1 engine return 1.0.
        top_matches: Up to 3 (ClassificationRule, float) pairs sorted by
            confidence descending.
        action: One of "auto_accept", "human_review", "human_classify"
            indicating the recommended next step based on confidence thresholds.
    """

    matched_rule: ClassificationRule | None
    confidence: float  # cosine similarity 0.0-1.0
    top_matches: tuple[tuple[ClassificationRule, float], ...]
    action: str  # "auto_accept" | "human_review" | "human_classify"
