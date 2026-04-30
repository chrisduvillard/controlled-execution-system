"""Classification oracle with TF-IDF fuzzy matching (CLASS-03, CLASS-04, CLASS-05).

Extends the Phase 1 ClassificationEngine with cosine-similarity-based fuzzy
matching on pre-computed TF-IDF vectors of the 30-row decision table.

Confidence thresholds (D-03):
- >= 0.90: auto_accept (agent proceeds without human input)
- >= 0.70: human_review (present top matches to human)
- <  0.70: human_classify (escalate to full human classification)

LLM-05: NO LLM calls. Pure TF-IDF + cosine similarity. This module must
not import anthropic, openai, or httpx.

The TF-IDF + cosine implementation is hand-rolled (stdlib only) so the wheel
does not pull ``scikit-learn`` (which transitively brings ``scipy`` + ``numpy``,
~80 MB) for ten lines of behaviour. The corpus is the 30-row decision table —
exact retrieval semantics are not required, only sensible relative scoring.

Exports:
    ClassificationOracle: TF-IDF oracle for task auto-classification.
    OracleClassificationResult: Re-exported for convenience.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from ces.control.models.oracle_result import OracleClassificationResult
from ces.control.models.spec import SignalHints
from ces.control.services.classification import (
    CLASSIFICATION_TABLE,
    ClassificationEngine,
    ClassificationRule,
)
from ces.shared.enums import BehaviorConfidence, ChangeClass, RiskTier

# Common English stop words. Trimmed list is sufficient for the 30-row decision
# table; matches what users actually produce in task descriptions.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "this",
        "that",
        "these",
        "those",
        "my",
        "your",
        "our",
        "their",
        "its",
        "any",
        "some",
        "all",
        "no",
        "not",
        "so",
        "than",
        "too",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")

# Spec-hint mappings for classify_from_hints (LLM-05 compliant; pure lookup).
_SPEC_CHANGE_CLASS_MAP: dict[str, ChangeClass] = {
    "feature": ChangeClass.CLASS_3,  # new functionality, moderate risk
    "bug": ChangeClass.CLASS_2,  # targeted fix
    "refactor": ChangeClass.CLASS_2,
    "infra": ChangeClass.CLASS_4,  # operational surface
    "doc": ChangeClass.CLASS_1,  # lowest
}

_SPEC_BLAST_RADIUS_RISK: dict[str, RiskTier] = {
    "isolated": RiskTier.C,
    "module": RiskTier.B,
    "system": RiskTier.A,
    "cross-cutting": RiskTier.A,
}


class ClassificationOracle:
    """Extends ClassificationEngine with TF-IDF fuzzy matching.

    Pre-computes TF-IDF vectors for the decision table at construction time
    (D-02: cached embeddings). At classification time, only cosine similarity
    runs -- pure math, no LLM call.

    Attributes:
        auto_accept_threshold: Minimum confidence for auto_accept (default 0.90).
        human_review_threshold: Minimum confidence for human_review (default 0.70).
    """

    def __init__(
        self,
        table: list[ClassificationRule] | None = None,
        auto_accept_threshold: float = 0.90,
        human_review_threshold: float = 0.70,
    ) -> None:
        self._engine = ClassificationEngine(table)
        self._table = table or CLASSIFICATION_TABLE
        self._auto_accept = auto_accept_threshold
        self._human_review = human_review_threshold

        # Pre-compute TF-IDF vectors (D-02: cached embeddings).
        # IDF formula matches sklearn's smoothed default:
        #   idf(t) = ln((1 + n) / (1 + df(t))) + 1
        # Vectors are L2-normalised once at construction so cosine similarity
        # at query time reduces to a dot product against a normalised query.
        doc_terms = [self._tokenize(rule.description) for rule in self._table]
        n_docs = len(doc_terms)
        df: Counter[str] = Counter()
        for terms in doc_terms:
            df.update(set(terms))
        self._idf: dict[str, float] = {term: math.log((1 + n_docs) / (1 + dfreq)) + 1.0 for term, dfreq in df.items()}
        self._doc_vectors: list[dict[str, float]] = [self._tfidf(t) for t in doc_terms]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Lowercase tokenizer with stop-word filtering, plus bigrams.

        Matches ``TfidfVectorizer(lowercase=True, stop_words="english",
        ngram_range=(1, 2))`` closely enough for relative ranking on the
        decision table.
        """
        words = [w for w in _TOKEN_RE.findall(text.lower()) if w not in _STOP_WORDS]
        bigrams = [f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1)]
        return words + bigrams

    def _tfidf(self, terms: list[str]) -> dict[str, float]:
        """Return an L2-normalised TF-IDF vector for the given token list.

        Terms not present in the fitted IDF map (i.e. unseen at construction
        time) are weighted with the maximum observed IDF — the "out-of-vocab"
        smoothing sklearn applies via its frozen vocabulary at transform time.
        """
        if not terms:
            return {}
        tf = Counter(terms)
        idf_default = max(self._idf.values()) if self._idf else 1.0
        vec = {term: count * self._idf.get(term, idf_default) for term, count in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values()))
        if norm == 0:
            return {}
        return {term: v / norm for term, v in vec.items()}

    @staticmethod
    def _cosine_dot(a: dict[str, float], b: dict[str, float]) -> float:
        """Cosine similarity for two L2-normalised vectors. Reduces to a dot product."""
        if not a or not b:
            return 0.0
        smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
        return sum(weight * larger.get(term, 0.0) for term, weight in smaller.items())

    def classify(self, description: str) -> OracleClassificationResult:
        """Classify a task description with confidence score.

        Strategy:
            1. Try exact match via Phase 1 ClassificationEngine first.
            2. Fall back to TF-IDF cosine similarity for fuzzy matching.
            3. Route to action based on confidence thresholds (D-03).

        Args:
            description: Free-text task description to classify.

        Returns:
            OracleClassificationResult with matched_rule, confidence,
            top_matches, and recommended action.
        """
        # Step 1: Exact match first (Phase 1 engine, confidence=1.0)
        exact = self._engine.classify_by_description(description)
        if exact is not None:
            return OracleClassificationResult(
                matched_rule=exact,
                confidence=1.0,
                top_matches=((exact, 1.0),),
                action="auto_accept",
            )

        # Step 2: Fuzzy match via TF-IDF cosine similarity (stdlib).
        query_vec = self._tfidf(self._tokenize(description))
        similarities = [self._cosine_dot(query_vec, dv) for dv in self._doc_vectors]

        # Sort by similarity descending, take top 3.
        sorted_indices = sorted(range(len(similarities)), key=lambda i: -similarities[i])
        top_matches: tuple[tuple[ClassificationRule, float], ...] = tuple(
            (self._table[i], similarities[i]) for i in sorted_indices[:3]
        )

        best_idx = sorted_indices[0]
        best_score = similarities[best_idx]
        best_rule = self._table[best_idx]

        # Step 3: Determine action based on confidence thresholds (D-03)
        if best_score >= self._auto_accept:
            action = "auto_accept"
        elif best_score >= self._human_review:
            action = "human_review"
        else:
            action = "human_classify"

        return OracleClassificationResult(
            matched_rule=best_rule if best_score >= self._human_review else None,
            confidence=best_score,
            top_matches=top_matches,
            action=action,
        )

    def classify_from_hints(
        self,
        signals: SignalHints,
        risk_hint: str | None = None,
    ) -> OracleClassificationResult:
        """Pure-rules classification from spec signals (LLM-05 compliant).

        Produces an OracleClassificationResult based purely on declared spec
        signals — no diff content, no LLM. Sensitive touches (auth/billing)
        force RiskTier.A. An explicit ``risk_hint`` escalates the baseline
        tier but never downgrades it (highest risk wins).

        Args:
            signals: ``SignalHints`` carrying ``primary_change_class``,
                ``blast_radius_hint``, ``touches_data``, ``touches_auth``,
                ``touches_billing``.
            risk_hint: Optional explicit risk letter ("A" / "B" / "C").

        Returns:
            OracleClassificationResult wrapping a synthetic ClassificationRule
            with risk_tier/behavior_confidence/change_class derived from the
            hints. Confidence is fixed at 0.7 (human_review threshold).
        """
        change_class = _SPEC_CHANGE_CLASS_MAP[signals.primary_change_class]
        baseline_tier = _SPEC_BLAST_RADIUS_RISK[signals.blast_radius_hint]
        if signals.touches_auth or signals.touches_billing:
            baseline_tier = RiskTier.A
        if risk_hint:
            hinted = RiskTier(risk_hint)
            # Highest-risk wins: A > B > C in the ordering (A has ordering_value 3).
            tier = baseline_tier if baseline_tier >= hinted else hinted
        else:
            tier = baseline_tier
        rule = ClassificationRule(
            description=(f"spec-hint: {signals.primary_change_class} / {signals.blast_radius_hint}"),
            risk_tier=tier,
            behavior_confidence=BehaviorConfidence.BC2,
            change_class=change_class,
        )
        return OracleClassificationResult(
            matched_rule=rule,
            confidence=0.7,
            top_matches=((rule, 0.7),),
            action="human_review",
        )

    @staticmethod
    def check_downgrade(
        proposed: ClassificationRule,
        existing: ClassificationRule,
    ) -> bool:
        """Check if proposed classification is a downgrade from existing.

        CLASS-05: The oracle must never downgrade a classification without
        human confirmation. A downgrade is when the proposed classification
        has a lower risk_tier OR lower behavior_confidence than the existing
        classification.

        Args:
            proposed: The new classification being considered.
            existing: The current classification on record.

        Returns:
            True if the proposed classification is a downgrade (should be
            rejected without human confirmation). False if same or upgrade.
        """
        return proposed.risk_tier < existing.risk_tier or proposed.behavior_confidence < existing.behavior_confidence
