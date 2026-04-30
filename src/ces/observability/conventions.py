"""CES governance semantic conventions for OpenTelemetry (OBS-08).

Defines the ``GovernanceAttributes`` Pydantic model that maps CES governance
fields to OpenTelemetry span attributes with a ``ces.`` namespace prefix.
All attribute keys follow the pattern ``ces.<field_name>``.

These conventions ensure consistent, low-cardinality attribute names across
all CES instrumentation, making governance telemetry queryable in any
OTel-compatible backend (Jaeger, Grafana Tempo, Datadog, etc.).
"""

from __future__ import annotations

from pydantic import BaseModel

from ces.shared.enums import ChangeClass, RiskTier, TrustStatus

CES_ATTR_PREFIX: str = "ces."


class GovernanceAttributes(BaseModel):
    """Maps CES governance fields to OTel span attributes.

    All fields are optional — only non-None values are included in the
    span attribute dict returned by :meth:`as_span_attributes`.

    Enum fields (risk_tier, change_class, trust_status) are converted to
    their string values. String fields (manifest_id, behavior_confidence,
    review_outcome, project_id) are passed through as-is.
    """

    manifest_id: str | None = None
    risk_tier: RiskTier | None = None
    change_class: ChangeClass | None = None
    behavior_confidence: str | None = None
    trust_status: TrustStatus | None = None
    review_outcome: str | None = None
    project_id: str | None = None

    def as_span_attributes(self) -> dict[str, str]:
        """Convert non-None fields to a dict with ``ces.`` prefixed keys.

        Enum values are extracted via ``.value``; plain strings are passed
        through with ``str()``.

        Returns:
            Dictionary suitable for passing to ``span.set_attributes()``.
        """
        result: dict[str, str] = {}
        for key, value in self.model_dump(mode="json", exclude_none=True).items():
            attr_key = f"{CES_ATTR_PREFIX}{key}"
            # mode="json" serializes str Enums to their .value strings,
            # so str() is only needed for type consistency.
            result[attr_key] = str(value)
        return result
