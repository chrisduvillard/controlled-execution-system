"""Security sensor pack.

Runs deterministic secret-detection checks on affected files.
Scans for common secret patterns (API keys, private keys, passwords)
using regex. No external tool dependencies.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from ces.harness.models.sensor_result import SensorFinding
from ces.harness.sensors._file_reader import filter_by_extension, read_file_safe
from ces.harness.sensors.base import BaseSensor

# Compiled patterns for secret detection
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Private key header", re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"gh[ps]_[A-Za-z0-9_]{36,}")),
    (
        "Generic API key assignment",
        re.compile(
            r"""(?:api[_\-]?key|api[_\-]?token|api[_\-]?secret)\s*[=:]\s*['"][^'"]{8,}['"]""",
            re.IGNORECASE,
        ),
    ),
    (
        "Password assignment",
        re.compile(
            r"""(?:password|passwd|pwd)\s*[=:]\s*['"][^'"]{4,}['"]""",
            re.IGNORECASE,
        ),
    ),
    (
        "High-entropy secret assignment",
        re.compile(
            r"""(?:secret|token)\s*=\s*['"][A-Za-z0-9+/=]{20,}['"]""",
        ),
    ),
]

# File paths that should never appear in commits
_SENSITIVE_PATHS = {".env", ".env.local", ".env.production", "credentials.json", "secrets.json"}
_SENSITIVE_EXTENSIONS = (".pem", ".key", ".p12", ".pfx", ".jks")


class SecuritySensor(BaseSensor):
    """Security sensor pack -- detects secrets and sensitive files.

    Sensor ID: security_scan
    Sensor Pack: security
    """

    def __init__(self) -> None:
        super().__init__(sensor_id="security_scan", sensor_pack="security")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        affected_files: list[str] = context.get("affected_files", [])
        project_root: str = context.get("project_root", "")

        if not affected_files:
            return (True, 1.0, "No files in scope for security scan")

        findings: list[str] = []

        # Path-based checks (no file reading needed)
        for fpath in affected_files:
            # Cross-platform: normalize separators then extract final component
            name = PurePosixPath(fpath.replace("\\", "/")).name
            if name in _SENSITIVE_PATHS:
                findings.append(f"Sensitive file in changeset: {fpath}")
                self._findings.append(
                    SensorFinding(
                        category="sensitive_file",
                        severity="high",
                        location=fpath,
                        message=f"Sensitive file in changeset: {fpath}",
                        suggestion="Add to .gitignore and remove from version control",
                    )
                )
            if fpath.endswith(_SENSITIVE_EXTENSIONS):
                findings.append(f"Private key/cert file in changeset: {fpath}")
                self._findings.append(
                    SensorFinding(
                        category="sensitive_file",
                        severity="high",
                        location=fpath,
                        message=f"Private key/cert file in changeset: {fpath}",
                        suggestion="Add to .gitignore and remove from version control",
                    )
                )

        # Content-based checks (requires project_root)
        files_scanned = 0
        scannable = filter_by_extension(
            affected_files,
            (
                ".py",
                ".js",
                ".ts",
                ".jsx",
                ".tsx",
                ".yml",
                ".yaml",
                ".toml",
                ".json",
                ".cfg",
                ".ini",
                ".conf",
                ".sh",
                ".bash",
                ".env",
                ".tf",
                ".hcl",
            ),
        )
        for fpath in scannable:
            content = read_file_safe(project_root, fpath)
            if content is None:
                continue
            files_scanned += 1
            for pattern_name, pattern in _SECRET_PATTERNS:
                matches = pattern.findall(content)
                if matches:
                    findings.append(f"{pattern_name} in {fpath} ({len(matches)} match(es))")
                    self._findings.append(
                        SensorFinding(
                            category="secret_detected",
                            severity="critical",
                            location=fpath,
                            message=f"{pattern_name} in {fpath} ({len(matches)} match(es))",
                            suggestion="Remove secret and rotate credentials",
                        )
                    )

        if findings:
            score = max(0.0, 1.0 - 0.2 * len(findings))
            details = f"Found {len(findings)} potential secret(s): " + "; ".join(findings)
            return (False, score, details)

        return (
            True,
            1.0,
            f"No secrets detected ({files_scanned} file(s) scanned, {len(affected_files)} path(s) checked)",
        )
