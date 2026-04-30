"""Tests for MultiModelConfig -- diversity validation and from_roster factory.

Validates:
- MultiModelConfig accepts configs with distinct models for each role
- MultiModelConfig rejects all-same-model configs with ModelDiversityError
- min_distinct_models is configurable and enforced
- from_roster() assigns models round-robin from a roster list
- ModelDiversityError is a ValueError subclass
- MultiModelConfig is frozen (immutable after construction)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ces.execution.providers.multi_model import ModelDiversityError, MultiModelConfig


class TestMultiModelConfig:
    """MultiModelConfig validates model diversity on construction."""

    def test_valid_two_role_config(self) -> None:
        """Config with two distinct models for two roles succeeds."""
        config = MultiModelConfig(
            role_model_map={"synthesizer": "claude-3-opus", "challenger": "gpt-4o"},
        )
        assert config.role_model_map == {"synthesizer": "claude-3-opus", "challenger": "gpt-4o"}

    def test_same_model_for_two_roles_raises_diversity_error(self) -> None:
        """Config with same model for all roles raises ModelDiversityError via ValidationError."""
        with pytest.raises(ValidationError, match="Model diversity violation"):
            MultiModelConfig(
                role_model_map={"synthesizer": "claude-3-opus", "challenger": "claude-3-opus"},
            )

    def test_single_role_config_succeeds(self) -> None:
        """Single-role config succeeds (diversity not enforced for < 2 roles)."""
        config = MultiModelConfig(role_model_map={"a": "m1"})
        assert config.role_model_map == {"a": "m1"}

    def test_three_role_config_with_three_distinct_models(self) -> None:
        """Three roles with three distinct models and min_distinct_models=3 succeeds."""
        config = MultiModelConfig(
            role_model_map={
                "structural": "claude-3-opus",
                "semantic": "gpt-4o",
                "red_team": "claude-3-sonnet",
            },
            min_distinct_models=3,
        )
        assert len(config.role_model_map) == 3

    def test_three_roles_two_unique_min_three_raises_error(self) -> None:
        """Three roles with only 2 unique models but min_distinct_models=3 raises error."""
        with pytest.raises(ValidationError, match="Model diversity violation"):
            MultiModelConfig(
                role_model_map={
                    "structural": "claude-3-opus",
                    "semantic": "gpt-4o",
                    "red_team": "gpt-4o",
                },
                min_distinct_models=3,
            )

    def test_three_roles_two_unique_min_two_succeeds(self) -> None:
        """Three roles with 2 unique models and min_distinct_models=2 succeeds."""
        config = MultiModelConfig(
            role_model_map={
                "structural": "claude-3-opus",
                "semantic": "gpt-4o",
                "red_team": "gpt-4o",
            },
            min_distinct_models=2,
        )
        assert len(set(config.role_model_map.values())) == 2

    def test_from_roster_two_roles(self) -> None:
        """from_roster() with 2 roles and 3-model roster creates config with 2 distinct models."""
        config = MultiModelConfig.from_roster(
            roles=["synthesizer", "challenger"],
            roster=["claude-3-opus", "gpt-4o", "claude-3-sonnet"],
        )
        assert len(config.role_model_map) == 2
        assert config.role_model_map["synthesizer"] != config.role_model_map["challenger"]

    def test_from_roster_three_roles_min_three(self) -> None:
        """from_roster() with 3 roles, 3-model roster, min_distinct_models=3 succeeds."""
        config = MultiModelConfig.from_roster(
            roles=["a", "b", "c"],
            roster=["m1", "m2", "m3"],
            min_distinct_models=3,
        )
        assert len(set(config.role_model_map.values())) == 3

    def test_from_roster_insufficient_roster_raises_error(self) -> None:
        """from_roster() with roster too small for role count raises ModelDiversityError."""
        with pytest.raises(ModelDiversityError, match="Model diversity violation"):
            MultiModelConfig.from_roster(
                roles=["a", "b", "c"],
                roster=["m1"],
            )

    def test_model_diversity_error_is_value_error(self) -> None:
        """ModelDiversityError is a subclass of ValueError."""
        assert issubclass(ModelDiversityError, ValueError)

    def test_config_is_frozen(self) -> None:
        """MultiModelConfig instances are immutable (frozen)."""
        config = MultiModelConfig(
            role_model_map={"synthesizer": "claude-3-opus", "challenger": "gpt-4o"},
        )
        with pytest.raises(ValidationError):
            config.role_model_map = {"new": "value"}  # type: ignore[misc]
