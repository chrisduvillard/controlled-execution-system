"""Tests for ces.control.services package-level lazy import.

ClassificationOracle is exposed via PEP 562 ``__getattr__`` to avoid an
import cycle with ces.control.models. These tests pin that contract.
"""

from __future__ import annotations

import pytest


class TestLazyClassificationOracle:
    """ClassificationOracle is importable from the package via lazy resolution."""

    def test_classification_oracle_lazy_import(self) -> None:
        from ces.control.services import ClassificationOracle
        from ces.control.services.classification_oracle import (
            ClassificationOracle as Direct,
        )

        assert ClassificationOracle is Direct

    def test_unknown_attribute_raises_attribute_error(self) -> None:
        import ces.control.services as services_pkg

        with pytest.raises(AttributeError, match="DefinitelyNotARealService"):
            services_pkg.DefinitelyNotARealService  # noqa: B018
