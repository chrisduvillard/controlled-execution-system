"""Local-first harness evolution substrate.

PR1 intentionally exposes only models, file paths, manifest IO, and a
conservative CLI. It does not inject harness content into runtime prompts.
"""

from ces.harness_evolution.models import HarnessChangeManifest, HarnessComponentType

__all__ = ["HarnessChangeManifest", "HarnessComponentType"]
