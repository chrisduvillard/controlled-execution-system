"""Tests for deterministic Project MRI scanning."""

from __future__ import annotations

import json
from pathlib import Path


def test_scan_project_mri_detects_core_python_signals_and_risks(tmp_path: Path) -> None:
    from ces.verification.mri import scan_project_mri

    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"
dependencies = ["pytest", "ruff"]

[tool.pytest.ini_options]
addopts = "-q"

[tool.ruff]
line-length = 100
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.py").write_text("# TODO: split this later\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("DATABASE_PASSWORD=do-not-print\n", encoding="utf-8")

    report = scan_project_mri(tmp_path)

    assert report.project_type == "python-package"
    signal_names = {signal.name for signal in report.signals}
    assert {"pyproject.toml", "pytest", "ruff", "tests-directory"}.issubset(signal_names)
    assert any(finding.category == "secret-hygiene" for finding in report.risk_findings)
    assert any(finding.category == "maintainability" for finding in report.risk_findings)
    assert "do-not-print" not in report.to_markdown()


def test_project_mri_classifies_fully_signaled_project_as_production_ready(tmp_path: Path) -> None:
    from ces.verification.mri import scan_project_mri

    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "ready"
dependencies = ["pytest", "ruff", "mypy"]

[tool.pytest.ini_options]
addopts = "-q"

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.12"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Ready\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ready.py").write_text("def test_ready():\n    assert True\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (tmp_path / "Procfile").write_text("web: ready\n", encoding="utf-8")
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "verification-profile.json").write_text("{}\n", encoding="utf-8")

    report = scan_project_mri(tmp_path)

    assert report.maturity == "production-ready"


def test_project_mri_treats_tool_ces_runtime_declaration_as_runtime_signal(tmp_path: Path) -> None:
    from ces.verification.mri import scan_project_mri

    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "ready"
dependencies = ["pytest", "ruff", "mypy"]

[tool.ces.runtime_declaration]
kind = "local-cli"
entrypoint = "uv run ready"
smoke_test = "uv run ready --help"

[tool.pytest.ini_options]
addopts = "-q"

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.12"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Ready\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ready.py").write_text("def test_ready():\n    assert True\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "verification-profile.json").write_text("{}\n", encoding="utf-8")

    report = scan_project_mri(tmp_path)

    assert report.maturity == "production-ready"
    assert "deployment/runtime declaration" not in report.missing_readiness_signals
    assert any(signal.name == "ces-runtime-declaration" for signal in report.signals)


def test_project_mri_treats_node_ces_runtime_declaration_as_runtime_signal(tmp_path: Path) -> None:
    from ces.verification.mri import scan_project_mri

    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "scripts": {"test": "vitest run", "typecheck": "tsc --noEmit", "desktop": "electron ."},
                "devDependencies": {"typescript": "latest"},
                "ces": {
                    "runtime_declaration": {
                        "kind": "electron-desktop",
                        "entrypoint": "npm run desktop",
                        "smoke_test": "npm run desktop:check",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Ready\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "completion-contract.json").write_text(
        json.dumps({"inferred_commands": [{"command": "npm test", "required": True}]}),
        encoding="utf-8",
    )

    report = scan_project_mri(tmp_path)

    assert "runtime" in report.readiness_score["passed"]
    assert "ces" in report.readiness_score["passed"]
    assert "deployment/runtime declaration" not in report.missing_readiness_signals
    assert "CES verification profile" not in report.missing_readiness_signals
    assert any(signal.name == "ces-runtime-declaration" for signal in report.signals)
    assert any(signal.name == ".ces/completion-contract.json" for signal in report.signals)


def test_project_mri_detects_bun_lock_as_dependency_signal(tmp_path: Path) -> None:
    from ces.verification.mri import scan_project_mri

    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "bun test"}}), encoding="utf-8")
    (tmp_path / "bun.lock").write_text("", encoding="utf-8")

    report = scan_project_mri(tmp_path)

    assert any(signal.name == "bun.lock" and signal.category == "dependency" for signal in report.signals)


def test_project_mri_json_shape_is_stable(tmp_path: Path) -> None:
    from ces.verification.mri import scan_project_mri

    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"typescript": "latest"}, "devDependencies": {"eslint": "latest"}}),
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text("{}\n", encoding="utf-8")

    report = scan_project_mri(tmp_path)
    payload = report.to_dict()

    assert list(payload) == [
        "schema_version",
        "project_root",
        "project_type",
        "maturity",
        "summary",
        "readiness_score",
        "maturity_ladder",
        "signals",
        "strongest_evidence",
        "risk_findings",
        "missing_readiness_signals",
        "recommended_next_actions",
    ]
    assert payload["project_type"] == "node-app"
    assert any(signal["name"] == "typescript" for signal in payload["signals"])
    assert any(signal["name"] == "eslint" for signal in payload["signals"])


def test_project_mri_reports_secret_keys_without_secret_like_values(tmp_path: Path) -> None:
    from ces.verification.mri import scan_project_mri

    (tmp_path / ".env").write_text("API_TOKEN=SECRET_TOKEN_VALUE\n", encoding="utf-8")
    (tmp_path / "config.json").write_text(
        json.dumps({"SERVICE_PASSWORD": "PRIVATE_KEY_VALUE", "nested": {"ACCESS_TOKEN": "TOKEN_VALUE"}}),
        encoding="utf-8",
    )

    report = scan_project_mri(tmp_path)
    rendered = report.to_markdown() + report.to_json()

    assert "API_TOKEN" in rendered
    assert "SERVICE_PASSWORD" in rendered
    assert "ACCESS_TOKEN" in rendered
    assert "SECRET_TOKEN_VALUE" not in rendered
    assert "PRIVATE_KEY_VALUE" not in rendered
    assert "TOKEN_VALUE" not in rendered


def test_project_mri_skips_symlinked_files_outside_project(tmp_path: Path) -> None:
    from ces.verification.mri import scan_project_mri

    outside = tmp_path / "outside"
    project = tmp_path / "project"
    outside.mkdir()
    project.mkdir()
    (outside / ".env").write_text("OUTSIDE_API_TOKEN=SECRET_TOKEN_VALUE\n", encoding="utf-8")
    (outside / "package.json").write_text(
        json.dumps({"dependencies": {"typescript": "latest"}, "scripts": {"test": "vitest"}}),
        encoding="utf-8",
    )
    (outside / "pyproject.toml").write_text(
        "[project]\nname = 'outside'\ndependencies = ['pytest']\n", encoding="utf-8"
    )
    (outside / "README.md").write_text("# Outside\n", encoding="utf-8")
    (outside / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    (outside / "ci.yml").write_text("name: Outside\n", encoding="utf-8")
    (outside / "tests").mkdir()
    (outside / "tests" / "test_outside.py").write_text("def test_outside():\n    assert True\n", encoding="utf-8")
    (project / ".github" / "workflows").mkdir(parents=True)
    (project / ".env").symlink_to(outside / ".env")
    (project / "package.json").symlink_to(outside / "package.json")
    (project / "pyproject.toml").symlink_to(outside / "pyproject.toml")
    (project / "README.md").symlink_to(outside / "README.md")
    (project / "tsconfig.json").symlink_to(outside / "tsconfig.json")
    (project / ".github" / "workflows" / "ci.yml").symlink_to(outside / "ci.yml")
    (project / "tests").symlink_to(outside / "tests", target_is_directory=True)

    report = scan_project_mri(project)
    rendered = report.to_markdown() + report.to_json()

    assert report.project_type == "unknown"
    assert "OUTSIDE_API_TOKEN" not in rendered
    assert "SECRET_TOKEN_VALUE" not in rendered
    assert "package.json" not in {signal.name for signal in report.signals}
    assert "pyproject.toml" not in {signal.name for signal in report.signals}
    assert "github-actions" not in {signal.name for signal in report.signals}
    assert "tests-directory" not in {signal.name for signal in report.signals}
    assert "typescript" not in {signal.name for signal in report.signals}
