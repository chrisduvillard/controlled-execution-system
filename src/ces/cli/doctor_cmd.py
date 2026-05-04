"""Implementation of the ``ces doctor`` command.

Pre-flight health check for a CES installation. Validates that the
local environment satisfies the minimum requirements to run the
builder-first workflow before any real command fails.

Checks:
    * Python version (>= 3.12 required).
    * Local runtime availability: ``claude`` or ``codex`` CLI on PATH.
      At least one is required for the builder-first ``ces build`` flow.
    * Optional demo-helper availability: CES_DEMO_MODE=1. Demo mode helps
      LLM-backed helper flows but does not replace the required local runtime
      for ``ces build``.
    * Optional compatibility extras relevant to local usage.
    * ``.ces/`` project directory — present or absent in cwd.
    * ``--security``: also runs security-posture checks against ``.ces/keys/``
      (key material present and mode 0600), ``.ces/state.db`` permissions,
      and the ``CES_AUDIT_HMAC_SECRET`` env var (not set to the dev default).

Exit codes:
    0 — Python OK AND at least one supported local runtime available
        AND (if --security) every security check passes.
    1 — Otherwise. Remediation hints are shown in the output panel.

Exports:
    run_doctor: Typer command function for ``ces doctor``.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

import ces.cli._output as _output_mod
from ces.cli._context import find_project_root
from ces.cli._output import console, set_json_mode
from ces.execution.runtime_safety import safety_profile_for_runtime
from ces.shared.crypto import AUDIT_HMAC_FILENAME, DEV_DEFAULT_HMAC_MARKER

_MIN_PYTHON = (3, 12)

# Module -> extras-group mapping used to detect whether an optional dependency
# group is installed. Empty by default because CES currently has no
# runtime-critical optional extras.
_EXTRAS_PROBES: tuple[tuple[str, str], ...] = ()


def _check_python() -> tuple[bool, str]:
    """Return (ok, rendered_version) for the current Python runtime."""
    vi = sys.version_info
    rendered = f"{vi.major}.{vi.minor}.{vi.micro}"
    ok = (vi.major, vi.minor) >= _MIN_PYTHON
    return ok, rendered


def _check_providers() -> dict[str, bool]:
    """Return a dict mapping runtime/helper source name to availability."""
    return {
        "claude CLI": shutil.which("claude") is not None,
        "codex CLI": shutil.which("codex") is not None,
        "CES_DEMO_MODE": os.environ.get("CES_DEMO_MODE") == "1",
    }


def _runtime_auth_status(
    providers: dict[str, bool],
    *,
    verify_runtime: bool = False,
    runtime_filter: str = "all",
) -> dict[str, dict[str, object]]:
    """Return runtime auth metadata without pretending PATH checks verify auth."""
    statuses: dict[str, dict[str, object]] = {
        "claude": {
            "installed": providers.get("claude CLI", False),
            "auth_checked": False,
            "auth_ok": None,
            "detail": "on PATH; auth not verified" if providers.get("claude CLI", False) else "not on PATH",
        },
        "codex": {
            "installed": providers.get("codex CLI", False),
            "auth_checked": False,
            "auth_ok": None,
            "detail": "on PATH; auth not verified" if providers.get("codex CLI", False) else "not on PATH",
        },
    }
    if verify_runtime:
        for runtime, provider_key in (("claude", "claude CLI"), ("codex", "codex CLI")):
            if runtime_filter not in {"all", runtime}:
                statuses[runtime]["detail"] = "auth not checked; filtered by --runtime"
                continue
            executable = shutil.which(runtime)
            if not providers.get(provider_key, False) or executable is None:
                continue
            ok, detail = _probe_runtime_auth(runtime, executable, Path.cwd())
            statuses[runtime].update({"auth_checked": True, "auth_ok": ok, "detail": detail})
    return statuses


def _probe_runtime_auth(runtime: str, executable: str, cwd: Path) -> tuple[bool, str]:
    """Run a minimal runtime probe when explicitly requested by --verify-runtime."""
    try:
        if runtime == "codex":
            command = [
                executable,
                "exec",
                "Reply with READY and do not edit files.",
                "-C",
                str(cwd),
                "--sandbox",
                "danger-full-access",
                "--skip-git-repo-check",
            ]
        elif runtime == "claude":
            command = [executable, "-p", "Reply with READY and do not edit files."]
        else:
            return False, f"No auth probe is configured for {runtime}."
        completed = subprocess.run(  # noqa: S603 - command is a fixed CES runtime-auth probe.
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"auth probe failed before runtime completed: {exc}"
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    command_label = " ".join(Path(part).name if index == 0 else part for index, part in enumerate(command[:2]))
    if completed.returncode == 0:
        return (
            True,
            f"auth probe succeeded: runtime={runtime}; command={command_label}; "
            f"exit_code=0; stdout_tail={stdout[-240:] or '(empty)'}; "
            f"stderr_tail={stderr[-240:] or '(empty)'}",
        )
    return (
        False,
        f"auth probe failed: runtime={runtime}; command={command_label}; "
        f"exit_code={completed.returncode}; stdout_tail={stdout[-240:] or '(empty)'}; "
        f"stderr_tail={stderr[-240:] or '(empty)'}",
    )


def _check_extras() -> dict[str, bool]:
    """Return a dict mapping extras-group name to installed flag."""
    result: dict[str, bool] = {}
    for group, probe_module in _EXTRAS_PROBES:
        import importlib.util

        result[group] = importlib.util.find_spec(probe_module) is not None
    return result


def _check_project_dir() -> tuple[bool, Path]:
    """Return (exists, resolved_path) for a .ces/ directory in cwd."""
    try:
        path = find_project_root() / ".ces"
    except typer.BadParameter:
        path = Path.cwd() / ".ces"
    return path.is_dir(), path


def _check_dependency_freshness(project_root: Path) -> dict[str, tuple[bool, str]]:
    checks: dict[str, tuple[bool, str]] = {}
    pyproject = project_root / "pyproject.toml"
    uv_lock = project_root / "uv.lock"
    if pyproject.exists():
        if not uv_lock.exists():
            checks["dependency lockfile"] = (False, "pyproject.toml present but uv.lock is missing")
        elif uv_lock.stat().st_mtime < pyproject.stat().st_mtime:
            checks["dependency lockfile"] = (False, "uv.lock is older than pyproject.toml")
        else:
            checks["dependency lockfile"] = (True, "uv.lock is present and newer than pyproject.toml")
    return checks


def _status_icon(ok: bool) -> str:
    return "[green]OK[/green]" if ok else "[red]MISSING[/red]"


def _file_mode(path: Path) -> int | None:
    """Return the POSIX mode bits for ``path``, or ``None`` if it doesn't exist."""
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return None


def _check_security(ces_dir: Path) -> dict[str, tuple[bool, str]]:
    """Return ordered security checks for ``ces_dir`` (typically cwd/.ces).

    On Windows, permission bit checks degrade to "POSIX-only" — we report
    presence but not mode, since NTFS ACLs don't map cleanly to the 0o600
    pattern the 0o700 parent dir enforces on POSIX.

    The returned mapping preserves insertion order so the rendered table
    and JSON payload read top-down: parent dir → keys → state DB → env var.
    """
    posix = os.name == "posix"
    checks: dict[str, tuple[bool, str]] = {}

    keys_dir = ces_dir / "keys"
    hmac_path = keys_dir / AUDIT_HMAC_FILENAME
    priv_path = keys_dir / "ed25519_private.key"
    pub_path = keys_dir / "ed25519_public.key"
    db_path = ces_dir / "state.db"

    # Keys directory (must be 0700 on POSIX).
    if ces_dir.is_dir():
        if posix:
            mode = _file_mode(ces_dir) or 0
            checks[".ces/ permissions"] = (mode == 0o700, f"0o{mode:o}")
        else:
            checks[".ces/ permissions"] = (True, "POSIX-only check skipped")
    else:
        checks[".ces/ permissions"] = (False, "missing — run `ces init`")

    if keys_dir.is_dir():
        if posix:
            mode = _file_mode(keys_dir) or 0
            checks[".ces/keys/ permissions"] = (mode == 0o700, f"0o{mode:o}")
        else:
            checks[".ces/keys/ permissions"] = (True, "POSIX-only check skipped")
    else:
        checks[".ces/keys/ permissions"] = (False, "missing — run `ces init`")

    # Signing private key (must exist + 0600 on POSIX).
    if priv_path.exists():
        if posix:
            mode = _file_mode(priv_path) or 0
            checks["signing private key"] = (mode == 0o600, f"present, 0o{mode:o}")
        else:
            checks["signing private key"] = (True, "present (POSIX-only mode check skipped)")
    else:
        checks["signing private key"] = (False, "missing — run `ces init`")

    # Signing public key (presence only; it's public).
    checks["signing public key"] = (
        pub_path.exists(),
        "present" if pub_path.exists() else "missing — run `ces init`",
    )

    # Audit HMAC secret file (must exist + 0600 on POSIX).
    if hmac_path.exists():
        if posix:
            mode = _file_mode(hmac_path) or 0
            checks["audit HMAC secret file"] = (mode == 0o600, f"present, 0o{mode:o}")
        else:
            checks["audit HMAC secret file"] = (True, "present (POSIX-only mode check skipped)")
    else:
        checks["audit HMAC secret file"] = (False, "missing — run `ces init`")

    # state.db file perms (0600 on POSIX).
    if db_path.exists():
        if posix:
            mode = _file_mode(db_path) or 0
            checks[".ces/state.db permissions"] = (mode == 0o600, f"0o{mode:o}")
        else:
            checks[".ces/state.db permissions"] = (True, "POSIX-only check skipped")
    else:
        checks[".ces/state.db permissions"] = (False, "missing")

    # CES_AUDIT_HMAC_SECRET env override — dev default is a fail; unset or
    # real-value is OK (file-based secret is used when env is absent).
    env_secret = os.environ.get("CES_AUDIT_HMAC_SECRET", "")
    if not env_secret:
        checks["CES_AUDIT_HMAC_SECRET env"] = (True, "unset (uses .ces/keys/audit.hmac)")
    elif DEV_DEFAULT_HMAC_MARKER in env_secret:
        checks["CES_AUDIT_HMAC_SECRET env"] = (
            False,
            "set to development default — override or unset",
        )
    else:
        checks["CES_AUDIT_HMAC_SECRET env"] = (True, "set to custom value")

    return checks


def run_doctor(
    security: bool = typer.Option(
        False,
        "--security",
        help=(
            "Also run security-posture checks against .ces/keys/, .ces/state.db, "
            "and the CES_AUDIT_HMAC_SECRET env var. Exits non-zero if any fail."
        ),
    ),
    strict_providers: int = typer.Option(
        0,
        "--strict-providers",
        help=(
            "If > 0, fail unless at least N distinct LLM providers are registered "
            "(e.g. ``--strict-providers 3`` enforces the Tier-A model-roster diversity "
            "claim). Default 0 = no enforcement."
        ),
        min=0,
    ),
    expert: bool = typer.Option(
        False,
        "--expert",
        help="Show optional compatibility extras in the doctor table.",
    ),
    runtime_safety_report: bool = typer.Option(
        False,
        "--runtime-safety",
        help="Show runtime adapter safety, version, allowlist, and MCP grounding disclosures.",
    ),
    verify_runtime: bool = typer.Option(
        False,
        "--verify-runtime",
        help="Run a minimal installed-runtime auth probe. May contact the runtime provider and consume a small request.",
    ),
    runtime: str = typer.Option(
        "all",
        "--runtime",
        help="Runtime auth probe target when --verify-runtime is used: all, codex, or claude.",
    ),
    compat: bool = typer.Option(
        False,
        "--compat",
        help="Alias for --expert when checking optional compatibility extras.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output doctor results as JSON. Equivalent to `ces --json doctor`.",
    ),
) -> None:
    """Run pre-flight diagnostics for the CES installation.

    Validates Python version, local runtime availability, optional
    LLM helper availability, and .ces/ project status. With ``--security``, also checks file-permission and
    secret-material posture for the current ``.ces/`` directory.
    With ``--strict-providers N``, fails unless N distinct LLM providers
    are registered (verifies the Tier-A diversity claim).
    Use ``--expert`` or ``--compat`` to show optional compatibility extras.
    Prints a Rich table (or JSON when ``--json`` is set at the root).
    Exits 0 on full pass; 1 otherwise with remediation hints.
    """
    if json_output:
        set_json_mode(True)
    runtime = runtime.lower().strip()
    if runtime not in {"all", "codex", "claude"}:
        raise typer.BadParameter("--runtime must be one of: all, codex, claude")
    python_ok, python_version = _check_python()
    providers = _check_providers()
    runtime_auth = _runtime_auth_status(providers, verify_runtime=verify_runtime, runtime_filter=runtime)
    extras = _check_extras()
    project_exists, project_path = _check_project_dir()
    runtime_safety = {
        "claude": safety_profile_for_runtime("claude").model_dump(mode="json"),
        "codex": safety_profile_for_runtime("codex").model_dump(mode="json"),
    }
    dependency_freshness = _check_dependency_freshness(
        project_path.parent if project_path.name == ".ces" else Path.cwd()
    )
    security_checks: dict[str, tuple[bool, str]] = {}
    security_ok = True
    if security:
        security_checks = _check_security(project_path)
        security_ok = all(ok for ok, _detail in security_checks.values())

    runtime_available = (
        bool(providers.get(f"{runtime} CLI"))
        if runtime in {"codex", "claude"}
        else providers["claude CLI"] or providers["codex CLI"]
    )
    checked_auth = [status for status in runtime_auth.values() if bool(status.get("auth_checked"))]
    runtime_auth_ok = all(bool(status["auth_ok"]) for status in checked_auth)
    if verify_runtime and runtime_available and not checked_auth:
        runtime_auth_ok = False
    any_provider = any(providers.values())

    distinct_provider_count = 0
    distinct_provider_names: list[str] = []
    strict_providers_ok = True
    if strict_providers > 0:
        from ces.cli._factory import get_settings
        from ces.execution.providers.bootstrap import build_provider_registry

        registry, _ = build_provider_registry(get_settings())
        names_set = registry.distinct_provider_names()
        distinct_provider_names = sorted(names_set)
        distinct_provider_count = len(names_set)
        strict_providers_ok = distinct_provider_count >= strict_providers

    overall_ok = python_ok and runtime_available and runtime_auth_ok and security_ok and strict_providers_ok

    if _output_mod._json_mode:
        payload = {
            "python_version": python_version,
            "python_ok": python_ok,
            "providers": providers,
            "runtime_auth": runtime_auth,
            "runtime_filter": runtime,
            "runtime_available": runtime_available,
            "runtime_auth_ok": runtime_auth_ok,
            "any_provider": any_provider,
            "extras": extras,
            "runtime_safety": runtime_safety,
            "dependency_freshness": {
                name: {"ok": ok, "detail": detail} for name, (ok, detail) in dependency_freshness.items()
            },
            "project_dir": {"exists": project_exists, "path": str(project_path)},
            "overall_ok": overall_ok,
        }
        if security:
            payload["security"] = {name: {"ok": ok, "detail": detail} for name, (ok, detail) in security_checks.items()}
            payload["security_ok"] = security_ok
        if strict_providers > 0:
            payload["distinct_providers"] = {
                "required": strict_providers,
                "registered": distinct_provider_count,
                "names": distinct_provider_names,
                "ok": strict_providers_ok,
            }
        typer.echo(json.dumps(payload, indent=2))
        raise typer.Exit(code=0 if overall_ok else 1)

    table = Table(title="CES Doctor", show_lines=False)
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail")

    table.add_row(
        "Python >= 3.12",
        _status_icon(python_ok),
        python_version,
    )
    for name, ok in providers.items():
        if name in {"claude CLI", "codex CLI"}:
            runtime_key = "claude" if name.startswith("claude") else "codex"
            detail = str(runtime_auth[runtime_key]["detail"])
        elif name == "CES_DEMO_MODE":
            detail = "enabled" if ok else "disabled"
        else:
            detail = "set" if ok else "not set"
        table.add_row(f"Provider: {name}", _status_icon(ok), detail)
    table.add_row(
        "Runtime safety: Claude",
        _status_icon(True),
        "enforces CES --allowedTools allowlist",
    )
    table.add_row(
        "Runtime safety: Codex",
        "[yellow]NOTICE[/yellow]",
        "uses --sandbox danger-full-access; manifest allowed_tools are not enforced by the adapter",
    )
    if runtime_safety_report:
        for runtime_name, profile in runtime_safety.items():
            table.add_row(
                f"Runtime adapter: {runtime_name}",
                _status_icon(bool(profile.get("workspace_scoped"))),
                (
                    f"allowlist_enforced={profile.get('tool_allowlist_enforced')}; "
                    f"mcp_grounding_supported={profile.get('mcp_grounding_supported')}; "
                    f"{profile.get('mcp_grounding_notes')}"
                ),
            )
    for name, (ok, detail) in dependency_freshness.items():
        table.add_row(f"Dependency freshness: {name}", _status_icon(ok), detail)
    if expert or compat:
        if extras:
            for group, installed in extras.items():
                table.add_row(
                    f"Extras: {group}",
                    _status_icon(installed),
                    "installed" if installed else f"pip install controlled-execution-system[{group}]",
                )
        else:
            table.add_row("Extras", _status_icon(True), "no optional runtime extras")
    table.add_row(
        ".ces/ project directory",
        _status_icon(project_exists),
        str(project_path) if project_exists else "run 'ces init' or 'ces build'",
    )
    for name, (ok, detail) in security_checks.items():
        table.add_row(f"Security: {name}", _status_icon(ok), detail)
    if strict_providers > 0:
        names_summary = ", ".join(distinct_provider_names) if distinct_provider_names else "(none)"
        table.add_row(
            f"Distinct providers >= {strict_providers}",
            _status_icon(strict_providers_ok),
            f"{distinct_provider_count} registered: {names_summary}",
        )

    console.print(table)

    if overall_ok:
        console.print(
            Panel(
                "[green]All required checks passed.[/green] "
                'You can now run [bold]ces build "describe what you want"[/bold]. '
                "Runtime authentication and CES_DEMO_MODE are optional helpers, but the local runtime is ready.",
                border_style="green",
            )
        )
        raise typer.Exit(code=0)

    hints: list[str] = []
    if not python_ok:
        hints.append(f"Upgrade Python to {_MIN_PYTHON[0]}.{_MIN_PYTHON[1]} or newer (detected {python_version}).")
    if not runtime_available:
        hints.append(
            "Install at least one supported local runtime for `ces build`:\n"
            "    - install the `claude` CLI and ensure it is on PATH\n"
            "    - install the `codex` CLI and ensure it is on PATH\n"
            "    - then rerun `ces doctor`"
        )
    elif not providers["CES_DEMO_MODE"]:
        hints.append(
            "Optional: enable CES_DEMO_MODE=1 if you want offline helper responses "
            "for review and manifest-assist flows when a CLI-backed provider is unavailable."
        )
    if verify_runtime and not runtime_auth_ok:
        failed = [
            name for name, status in runtime_auth.items() if status.get("auth_checked") and not status.get("auth_ok")
        ]
        hints.append(
            "Runtime authentication probe failed for: "
            + ", ".join(failed)
            + ". Re-authenticate the runtime CLI, then rerun `ces doctor --verify-runtime`."
        )
    if security and not security_ok:
        failing = [name for name, (ok, _detail) in security_checks.items() if not ok]
        hints.append(
            "Security posture issues detected:\n    - "
            + "\n    - ".join(failing)
            + "\n\nRun `ces init` in a fresh project to generate key material, "
            "or fix file permissions manually: chmod 0700 .ces/keys/ && chmod 0600 .ces/keys/* .ces/state.db."
        )
    if strict_providers > 0 and not strict_providers_ok:
        hints.append(
            f"Tier-A diversity requires {strict_providers} distinct providers; "
            f"only {distinct_provider_count} registered "
            f"({', '.join(distinct_provider_names) or 'none'}). "
            "Install/authenticate additional CLI runtimes (e.g. both `claude` and `codex`) "
            "or wire SDK-backed providers into `register_cli_fallback`."
        )
    console.print(
        Panel(
            "\n\n".join(hints),
            title="[red]Pre-flight issues[/red]",
            border_style="red",
        )
    )
    raise typer.Exit(code=1)
