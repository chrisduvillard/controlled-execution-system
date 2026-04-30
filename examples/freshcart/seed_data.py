"""DEMO-01: Seed database with FreshCart sample truth artifacts.

Populates a CES database with sample PRL items, architecture blueprint,
and interface contracts for the FreshCart grocery delivery application.

Usage:
    uv run python -m examples.freshcart.seed_data

Requires PostgreSQL running with migrations applied.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tests.integration._compat.control_db.tables import TruthArtifactRow


def _truth_artifact_row_from_artifact(artifact: dict[str, Any]) -> TruthArtifactRow:
    """Translate demo artifact data into the current TruthArtifactRow schema."""
    # Lazy import: avoid import-time DB engine setup triggered by tables module.
    from ces.shared.crypto import sha256_hash
    from tests.integration._compat.control_db.tables import TruthArtifactRow

    return TruthArtifactRow(
        id=artifact["artifact_id"],
        type=artifact["type"],
        version=1,
        status=artifact["content"].get("status", "approved"),
        content=artifact["content"],
        content_hash=sha256_hash(json.dumps(artifact["content"], sort_keys=True)),
        owner="freshcart-demo",
        project_id="freshcart",
    )


async def seed_freshcart() -> None:
    """Seed the database with FreshCart truth artifacts."""
    from ces.shared.config import CESSettings
    from tests.integration._compat.control_db.base import get_async_engine, get_async_session_factory

    settings = CESSettings()
    engine = get_async_engine(settings.database_url)

    try:
        session_factory = get_async_session_factory(engine)
        async with session_factory() as session:
            artifacts = _build_artifacts()
            for artifact in artifacts:
                session.add(_truth_artifact_row_from_artifact(artifact))

            await session.commit()
            print(f"Seeded {len(artifacts)} FreshCart truth artifacts.")

    finally:
        await engine.dispose()


def _build_artifacts() -> list[dict]:
    """Build the set of FreshCart truth artifacts."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        # PRL Items
        {
            "artifact_id": f"PRL-{uuid.uuid4().hex[:8]}",
            "type": "prl_item",
            "content": {
                "schema_type": "prl_item",
                "title": "Shopping Cart Checkout Flow",
                "description": "Users can add items to cart, view cart, proceed to checkout with payment validation.",
                "risk_tier": "B",
                "behavior_confidence": "BC1",
                "change_class": "Class 2",
                "acceptance_criteria": [
                    {"criterion": "Cart total matches sum of item prices", "verification": "unit_test"},
                    {"criterion": "Payment validation rejects invalid card numbers", "verification": "unit_test"},
                    {"criterion": "Checkout creates order record in database", "verification": "integration_test"},
                ],
                "status": "approved",
                "created_at": now,
            },
        },
        {
            "artifact_id": f"PRL-{uuid.uuid4().hex[:8]}",
            "type": "prl_item",
            "content": {
                "schema_type": "prl_item",
                "title": "Product Search with Filtering",
                "description": "Users can search products by name, filter by category, sort by price or relevance.",
                "risk_tier": "C",
                "behavior_confidence": "BC1",
                "change_class": "Class 1",
                "acceptance_criteria": [
                    {"criterion": "Search returns matching products within 500ms", "verification": "perf_test"},
                    {"criterion": "Empty category filter returns all products", "verification": "unit_test"},
                ],
                "status": "approved",
                "created_at": now,
            },
        },
        {
            "artifact_id": f"PRL-{uuid.uuid4().hex[:8]}",
            "type": "prl_item",
            "content": {
                "schema_type": "prl_item",
                "title": "JWT Authentication Migration",
                "description": "Migrate user authentication from session-based to JWT tokens with refresh token rotation.",
                "risk_tier": "A",
                "behavior_confidence": "BC3",
                "change_class": "Class 5",
                "acceptance_criteria": [
                    {
                        "criterion": "Existing sessions remain valid during migration window",
                        "verification": "integration_test",
                    },
                    {"criterion": "JWT tokens expire after 15 minutes", "verification": "unit_test"},
                    {"criterion": "Refresh tokens are rotated on use", "verification": "unit_test"},
                    {"criterion": "No session data leaked in JWT payload", "verification": "security_review"},
                ],
                "status": "approved",
                "created_at": now,
            },
        },
        # Architecture Blueprint
        {
            "artifact_id": f"ARCH-{uuid.uuid4().hex[:8]}",
            "type": "architecture_blueprint",
            "content": {
                "schema_type": "architecture_blueprint",
                "name": "FreshCart Application Architecture",
                "components": [
                    {"name": "API Gateway", "type": "service", "description": "FastAPI REST API"},
                    {"name": "Cart Service", "type": "service", "description": "Shopping cart management"},
                    {"name": "Search Service", "type": "service", "description": "Product search and filtering"},
                    {"name": "Auth Service", "type": "service", "description": "Authentication and authorization"},
                    {"name": "Order Service", "type": "service", "description": "Order processing and fulfillment"},
                    {"name": "PostgreSQL", "type": "database", "description": "Primary data store"},
                    {"name": "Redis", "type": "cache", "description": "Session cache and search index"},
                ],
                "trust_boundaries": [
                    {"name": "Public Internet", "description": "Untrusted user requests"},
                    {"name": "Internal Services", "description": "Trusted service-to-service calls"},
                ],
                "status": "approved",
                "created_at": now,
            },
        },
    ]


if __name__ == "__main__":
    asyncio.run(seed_freshcart())
