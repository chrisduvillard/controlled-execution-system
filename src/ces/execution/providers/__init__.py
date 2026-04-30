"""LLM provider abstraction layer for CES execution plane.

Exports the CLI-backed and demo providers that CES actually ships today.
"""

from __future__ import annotations

from ces.execution.providers.cli_provider import CLILLMProvider
from ces.execution.providers.demo_provider import DemoLLMProvider
from ces.execution.providers.multi_model import ModelDiversityError, MultiModelConfig
from ces.execution.providers.protocol import (
    ChainOfCustodyTracker,
    LLMError,
    LLMProviderProtocol,
    LLMResponse,
)
from ces.execution.providers.registry import ProviderRegistry

__all__ = [
    "CLILLMProvider",
    "ChainOfCustodyTracker",
    "DemoLLMProvider",
    "LLMError",
    "LLMProviderProtocol",
    "LLMResponse",
    "ModelDiversityError",
    "MultiModelConfig",
    "ProviderRegistry",
]
