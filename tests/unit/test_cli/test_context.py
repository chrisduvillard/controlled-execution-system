"""Tests for CLI project root detection (_context module)."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from ces.cli._context import find_project_root, get_project_config, get_project_id


class TestFindProjectRoot:
    """Tests for find_project_root()."""

    def test_finds_root_from_project_dir(self, ces_project: Path) -> None:
        """find_project_root returns the dir containing .ces/ when called from it."""
        result = find_project_root(start=ces_project)
        assert result == ces_project

    def test_finds_root_from_subdirectory(self, nested_ces_project: Path, ces_project: Path) -> None:
        """find_project_root walks up from a nested subdir to find .ces/ marker."""
        result = find_project_root(start=nested_ces_project)
        assert result == ces_project

    def test_raises_when_no_ces_directory(self, non_ces_dir: Path) -> None:
        """find_project_root raises typer.BadParameter when no .ces/ found."""
        with pytest.raises(typer.BadParameter, match="ces init"):
            find_project_root(start=non_ces_dir)

    def test_returns_path_object(self, ces_project: Path) -> None:
        """find_project_root returns a Path instance."""
        result = find_project_root(start=ces_project)
        assert isinstance(result, Path)

    def test_resolves_symlinks(self, ces_project: Path, tmp_path: Path) -> None:
        """find_project_root resolves the path before traversal."""
        result = find_project_root(start=ces_project)
        assert result == result.resolve()

    def test_default_cwd_with_ces_dir(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """find_project_root uses cwd when start is None."""
        monkeypatch.chdir(ces_project)
        result = find_project_root(start=None)
        assert result == ces_project.resolve()

    def test_default_cwd_without_ces_dir(self, non_ces_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """find_project_root raises BadParameter when cwd has no .ces/ and start=None."""
        monkeypatch.chdir(non_ces_dir)
        with pytest.raises(typer.BadParameter, match="ces init"):
            find_project_root(start=None)

    def test_walks_multiple_levels_up(self, ces_project: Path) -> None:
        """find_project_root walks through multiple parent directories."""
        deep = ces_project / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        result = find_project_root(start=deep)
        assert result == ces_project


class TestProjectConfigYamlErrors:
    """get_project_id / get_project_config swallow malformed YAML and fall back."""

    def test_get_project_id_falls_back_on_yaml_error(self, ces_project: Path) -> None:
        """A corrupt config.yaml yields the 'default' project_id (line 66-67)."""
        (ces_project / ".ces" / "config.yaml").write_text(
            "project_id: [unterminated",
            encoding="utf-8",
        )
        assert get_project_id(start=ces_project) == "default"

    def test_get_project_config_falls_back_on_yaml_error(self, ces_project: Path) -> None:
        """A corrupt config.yaml yields an empty dict from get_project_config (line 80-81)."""
        (ces_project / ".ces" / "config.yaml").write_text(
            "project_id: [unterminated",
            encoding="utf-8",
        )
        assert get_project_config(start=ces_project) == {}
