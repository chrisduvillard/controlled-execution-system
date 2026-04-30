"""Sample FreshCart task data for end-to-end testing.

Contains fictional task descriptions representing the FreshCart grocery
delivery application.  Three tasks span all risk tiers (A, B, C) to
exercise the full classification spectrum.

Exports:
    SAMPLE_TASKS: List of dicts with description, risk_tier, affected_files.
    PROJECT_NAME: Default project name for the FreshCart example.
"""

from __future__ import annotations

SAMPLE_TASKS = [
    {
        "description": "Add shopping cart checkout flow with payment validation",
        "risk_tier": "B",
        "affected_files": [
            "src/cart/checkout.py",
            "src/cart/payment.py",
            "tests/test_checkout.py",
        ],
    },
    {
        "description": "Fix null pointer in product search when category is empty",
        "risk_tier": "C",
        "affected_files": [
            "src/search/product_search.py",
        ],
    },
    {
        "description": "Migrate user authentication from session-based to JWT tokens",
        "risk_tier": "A",
        "affected_files": [
            "src/auth/jwt.py",
            "src/auth/middleware.py",
            "src/models/user.py",
        ],
    },
]

PROJECT_NAME = "freshcart"
