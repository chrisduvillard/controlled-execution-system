"""Multi-model configuration with diversity validation.

Provides MultiModelConfig for mapping agent roles to distinct LLM models,
ensuring model diversity is enforced at configuration time (T-36-01).

ModelDiversityError is raised when a config violates the minimum distinct
models constraint. CESBaseModel's frozen=True makes configs immutable
after construction (T-36-01).

T-36-02 mitigation: Only model ID strings are stored -- never API keys.
"""

from __future__ import annotations

from pydantic import model_validator

from ces.shared.base import CESBaseModel


class ModelDiversityError(ValueError):
    """Raised when a multi-model config violates model diversity constraints.

    Model diversity is required to ensure agent independence -- using
    the same model for multiple roles defeats the purpose of multi-model
    review and composite operations.
    """


class MultiModelConfig(CESBaseModel):
    """Configuration mapping agent roles to distinct LLM model IDs.

    Validates that the assigned models satisfy a minimum diversity
    threshold on construction. Frozen (immutable) after creation.

    Attributes:
        role_model_map: Maps role names to model IDs (e.g. {"synthesizer": "claude-3-opus"}).
        min_distinct_models: Minimum number of distinct model IDs required (default 2).
    """

    role_model_map: dict[str, str]
    min_distinct_models: int = 2

    @model_validator(mode="after")
    def _validate_diversity(self) -> MultiModelConfig:
        """Enforce minimum model diversity across roles.

        Single-role configs skip the check (diversity is meaningless
        with only one role). For 2+ roles, the number of unique model
        IDs must meet or exceed min_distinct_models.

        Raises:
            ModelDiversityError: If diversity constraint is violated.
        """
        if len(self.role_model_map) < 2:
            return self

        unique = set(self.role_model_map.values())
        if len(unique) < self.min_distinct_models:
            msg = (
                f"Model diversity violation: {len(unique)} unique model(s) "
                f"for {len(self.role_model_map)} roles. "
                f"Minimum {self.min_distinct_models} distinct models required. "
                f"Roles: {dict(self.role_model_map)}"
            )
            raise ModelDiversityError(msg)

        return self

    @classmethod
    def from_roster(
        cls,
        roles: list[str],
        roster: list[str],
        min_distinct_models: int = 2,
    ) -> MultiModelConfig:
        """Create a MultiModelConfig by assigning models round-robin from a roster.

        Models are assigned to roles in order, cycling through the roster.
        The resulting config is validated normally -- if the roster is too
        small to satisfy diversity constraints, ModelDiversityError is raised.

        Args:
            roles: Role names to assign models to.
            roster: Available model IDs to draw from.
            min_distinct_models: Minimum distinct models required.

        Returns:
            A validated MultiModelConfig instance.

        Raises:
            ModelDiversityError: If the resulting assignment violates diversity.
        """
        role_model_map = {role: roster[i % len(roster)] for i, role in enumerate(roles)}

        # Pre-validate diversity before constructor so callers get
        # ModelDiversityError directly (not wrapped in ValidationError).
        if len(role_model_map) >= 2:
            unique = set(role_model_map.values())
            if len(unique) < min_distinct_models:
                msg = (
                    f"Model diversity violation: {len(unique)} unique model(s) "
                    f"for {len(role_model_map)} roles. "
                    f"Minimum {min_distinct_models} distinct models required. "
                    f"Roles: {dict(role_model_map)}"
                )
                raise ModelDiversityError(msg)

        return cls(role_model_map=role_model_map, min_distinct_models=min_distinct_models)
