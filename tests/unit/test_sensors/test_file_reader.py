"""Tests for _file_reader utility module."""

from __future__ import annotations

from ces.harness.sensors._file_reader import filter_by_extension, read_file_safe


class TestReadFileSafe:
    """Tests for read_file_safe."""

    def test_reads_existing_file(self, tmp_path):
        (tmp_path / "hello.py").write_text("print('hello')", encoding="utf-8")
        result = read_file_safe(str(tmp_path), "hello.py")
        assert result == "print('hello')"

    def test_returns_none_for_missing_file(self, tmp_path):
        result = read_file_safe(str(tmp_path), "nonexistent.py")
        assert result is None

    def test_returns_none_for_empty_project_root(self):
        result = read_file_safe("", "some_file.py")
        assert result is None

    def test_returns_none_for_oversized_file(self, tmp_path):
        big_file = tmp_path / "big.txt"
        big_file.write_text("x" * 100, encoding="utf-8")
        result = read_file_safe(str(tmp_path), "big.txt", max_size=50)
        assert result is None

    def test_reads_file_within_size_limit(self, tmp_path):
        f = tmp_path / "small.txt"
        f.write_text("small", encoding="utf-8")
        result = read_file_safe(str(tmp_path), "small.txt", max_size=1000)
        assert result == "small"

    def test_returns_none_for_directory(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        result = read_file_safe(str(tmp_path), "subdir")
        assert result is None

    def test_rejects_path_traversal_outside_project_root(self, tmp_path):
        """A relative_path that escapes project_root is refused."""
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        try:
            project = tmp_path / "project"
            project.mkdir()
            result = read_file_safe(str(project), "../outside.txt")
            assert result is None
        finally:
            outside.unlink(missing_ok=True)

    def test_returns_none_when_read_raises_oserror(self, tmp_path, monkeypatch):
        """Read failures (e.g. permission denied) yield None instead of crashing."""
        from pathlib import Path

        target = tmp_path / "exists.txt"
        target.write_text("ok", encoding="utf-8")

        original_read_text = Path.read_text

        def boom(self, *args, **kwargs):
            if self == target.resolve():
                raise PermissionError("denied")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", boom)

        result = read_file_safe(str(tmp_path), "exists.txt")
        assert result is None


class TestFilterByExtension:
    """Tests for filter_by_extension."""

    def test_filters_python_files(self):
        files = ["a.py", "b.js", "c.py", "d.txt"]
        assert filter_by_extension(files, (".py",)) == ["a.py", "c.py"]

    def test_multiple_extensions(self):
        files = ["a.py", "b.js", "c.ts"]
        assert filter_by_extension(files, (".js", ".ts")) == ["b.js", "c.ts"]

    def test_empty_list(self):
        assert filter_by_extension([], (".py",)) == []

    def test_no_matches(self):
        files = ["a.txt", "b.md"]
        assert filter_by_extension(files, (".py",)) == []
