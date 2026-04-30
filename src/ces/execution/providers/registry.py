"""Provider registry for model-to-provider mapping (LLM-03).

Maps model ID prefixes to provider instances, enabling model swapping
at call time. The registry resolves the longest matching prefix so
that more specific registrations take precedence.

Example:
    registry = ProviderRegistry()
    registry.register("claude", claude_cli_provider)
    registry.register("gpt", codex_cli_provider)
    provider = registry.get_provider("claude-3-opus")  # returns claude_cli_provider
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ces.execution.providers.protocol import LLMProviderProtocol

if TYPE_CHECKING:
    from ces.execution.providers.multi_model import MultiModelConfig


class ProviderRegistry:
    """Registry mapping model ID prefixes to LLM provider instances.

    Supports longest-prefix matching so 'claude-3' takes precedence
    over 'claude' when resolving 'claude-3-opus'.
    """

    def __init__(self) -> None:
        self._providers: dict[str, LLMProviderProtocol] = {}

    def register(self, model_prefix: str, provider: LLMProviderProtocol) -> None:
        """Register a provider for a model ID prefix.

        Args:
            model_prefix: Prefix to match (e.g. 'claude', 'gpt').
            provider: Provider instance implementing LLMProviderProtocol.
        """
        self._providers[model_prefix] = provider

    def get_provider(self, model_id: str) -> LLMProviderProtocol:
        """Resolve a model ID to its registered provider.

        Uses longest-prefix matching: if both 'claude' and 'claude-3'
        are registered, 'claude-3-opus' resolves to the 'claude-3' provider.

        Args:
            model_id: Full model ID (e.g. 'claude-3-opus-20240229').

        Returns:
            The provider registered for the longest matching prefix.

        Raises:
            KeyError: If no registered prefix matches the model_id.
        """
        # Sort by prefix length descending for longest-prefix match
        matches = [(prefix, provider) for prefix, provider in self._providers.items() if model_id.startswith(prefix)]
        if not matches:
            available = ", ".join(sorted(self._providers.keys())) or "(none)"
            msg = f"No provider registered for model '{model_id}'. Available prefixes: {available}"
            raise KeyError(msg)

        # Return provider with longest matching prefix
        matches.sort(key=lambda x: len(x[0]), reverse=True)
        return matches[0][1]

    def resolve_roles(
        self,
        config: MultiModelConfig,
    ) -> dict[str, tuple[LLMProviderProtocol, str]]:
        """Resolve all roles in a MultiModelConfig to provider instances.

        Args:
            config: Role-to-model-ID mapping (already diversity-validated).

        Returns:
            Dict mapping role name to (provider_instance, model_id) tuple.

        Raises:
            KeyError: If any model_id has no registered provider (T-36-03).
        """
        result: dict[str, tuple[LLMProviderProtocol, str]] = {}
        for role, model_id in config.role_model_map.items():
            provider = self.get_provider(model_id)
            result[role] = (provider, model_id)
        return result

    def list_models(self) -> list[str]:
        """Return sorted list of all registered model prefixes."""
        return sorted(self._providers.keys())

    def distinct_provider_names(self) -> set[str]:
        """Return the set of distinct ``provider_name`` values registered.

        Two prefixes mapped to the same provider instance count as one
        distinct provider. Used by ``ces doctor --strict-providers`` to
        verify the Tier-A model-roster diversity claim — see ``F042`` in
        ``TECH_DEBT_AUDIT.md`` for the motivation.
        """
        return {provider.provider_name for provider in self._providers.values()}
