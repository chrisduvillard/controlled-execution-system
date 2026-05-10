"""Tests for DiffExtractor and diff parsing models.

Covers: unified diff parsing, multi-file diffs, new/deleted file detection,
empty diffs, statistics computation, truncation behaviour, frozen model
enforcement, and hunk line number extraction.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ces.execution.processes import ProcessResult
from ces.harness.services.diff_extractor import (
    DiffContext,
    DiffExtractor,
    DiffHunk,
    DiffStats,
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

SIMPLE_DIFF = """\
diff --git a/src/main.py b/src/main.py
index abc1234..def5678 100644
--- a/src/main.py
+++ b/src/main.py
@@ -10,6 +10,8 @@ def main():
     existing_line()
+    new_line_1()
+    new_line_2()
     another_existing()
"""

MULTI_FILE_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
index 1111111..2222222 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,4 @@
 import os
+import sys

 def foo():
diff --git a/src/bar.py b/src/bar.py
index 3333333..4444444 100644
--- a/src/bar.py
+++ b/src/bar.py
@@ -5,4 +5,3 @@ def bar():
     x = 1
-    y = 2
     return x
"""

NEW_FILE_DIFF = """\
diff --git a/src/new_module.py b/src/new_module.py
new file mode 100644
index 0000000..abcdef1
--- /dev/null
+++ b/src/new_module.py
@@ -0,0 +1,3 @@
+\"\"\"New module.\"\"\"
+
+def hello(): ...
"""

DELETED_FILE_DIFF = """\
diff --git a/src/old_module.py b/src/old_module.py
deleted file mode 100644
index abcdef1..0000000
--- a/src/old_module.py
+++ /dev/null
@@ -1,3 +0,0 @@
-\"\"\"Old module.\"\"\"
-
-def goodbye(): ...
"""

MULTI_HUNK_DIFF = """\
diff --git a/src/utils.py b/src/utils.py
index aaa1111..bbb2222 100644
--- a/src/utils.py
+++ b/src/utils.py
@@ -5,3 +5,4 @@ def first():
     a = 1
+    b = 2
     return a
@@ -20,3 +21,4 @@ def second():
     x = 10
+    y = 20
     return x
"""


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestDiffStats:
    """DiffStats model validation."""

    def test_create_valid(self) -> None:
        stats = DiffStats(insertions=5, deletions=3, files_changed=2)
        assert stats.insertions == 5
        assert stats.deletions == 3
        assert stats.files_changed == 2

    def test_frozen(self) -> None:
        stats = DiffStats(insertions=1, deletions=0, files_changed=1)
        with pytest.raises(ValidationError):
            stats.insertions = 99  # type: ignore[misc]


class TestDiffHunk:
    """DiffHunk model validation."""

    def test_create_valid(self) -> None:
        hunk = DiffHunk(
            file_path="src/main.py",
            old_start=10,
            new_start=10,
            content="@@ -10,3 +10,4 @@\n context\n+added",
        )
        assert hunk.file_path == "src/main.py"
        assert hunk.is_new_file is False
        assert hunk.is_deleted_file is False

    def test_new_file_flag(self) -> None:
        hunk = DiffHunk(
            file_path="new.py",
            old_start=0,
            new_start=1,
            content="+hello",
            is_new_file=True,
        )
        assert hunk.is_new_file is True

    def test_frozen(self) -> None:
        hunk = DiffHunk(
            file_path="f.py",
            old_start=1,
            new_start=1,
            content="x",
        )
        with pytest.raises(ValidationError):
            hunk.file_path = "other.py"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------


class TestExtractDiffFromText:
    """DiffExtractor.extract_diff_from_text parsing logic."""

    def test_parse_simple_diff(self) -> None:
        """Parse a basic unified diff with one file and one hunk."""
        ctx = DiffExtractor.extract_diff_from_text(SIMPLE_DIFF)

        assert ctx.files_changed == ("src/main.py",)
        assert len(ctx.hunks) == 1
        assert ctx.hunks[0].file_path == "src/main.py"
        assert ctx.stats.insertions == 2
        assert ctx.stats.deletions == 0
        assert ctx.stats.files_changed == 1
        assert ctx.truncated is False

    def test_parse_multi_file_diff(self) -> None:
        """Parse diff with changes to two files."""
        ctx = DiffExtractor.extract_diff_from_text(MULTI_FILE_DIFF)

        assert set(ctx.files_changed) == {"src/foo.py", "src/bar.py"}
        assert len(ctx.hunks) == 2
        assert ctx.stats.files_changed == 2
        assert ctx.stats.insertions == 1  # +import sys
        assert ctx.stats.deletions == 1  # -    y = 2

    def test_parse_new_file(self) -> None:
        """Parse diff containing 'new file mode' -- is_new_file must be True."""
        ctx = DiffExtractor.extract_diff_from_text(NEW_FILE_DIFF)

        assert ctx.files_changed == ("src/new_module.py",)
        assert len(ctx.hunks) == 1
        assert ctx.hunks[0].is_new_file is True
        assert ctx.hunks[0].is_deleted_file is False

    def test_parse_deleted_file(self) -> None:
        """Parse diff containing 'deleted file mode' -- is_deleted_file must be True."""
        ctx = DiffExtractor.extract_diff_from_text(DELETED_FILE_DIFF)

        assert ctx.files_changed == ("src/old_module.py",)
        assert len(ctx.hunks) == 1
        assert ctx.hunks[0].is_deleted_file is True
        assert ctx.hunks[0].is_new_file is False

    def test_parse_empty_diff(self) -> None:
        """Empty string yields an empty DiffContext."""
        ctx = DiffExtractor.extract_diff_from_text("")

        assert ctx.files_changed == ()
        assert ctx.hunks == ()
        assert ctx.stats.insertions == 0
        assert ctx.stats.deletions == 0
        assert ctx.stats.files_changed == 0
        assert ctx.truncated is False

    def test_stats_computed_correctly(self) -> None:
        """Verify insertions, deletions, and files_changed counts."""
        ctx = DiffExtractor.extract_diff_from_text(MULTI_FILE_DIFF)

        assert ctx.stats.insertions == 1
        assert ctx.stats.deletions == 1
        assert ctx.stats.files_changed == 2

    def test_hunk_line_numbers_parsed(self) -> None:
        """Verify old_start and new_start from @@ -X,Y +A,B @@ header."""
        ctx = DiffExtractor.extract_diff_from_text(MULTI_HUNK_DIFF)

        assert len(ctx.hunks) == 2
        assert ctx.hunks[0].old_start == 5
        assert ctx.hunks[0].new_start == 5
        assert ctx.hunks[1].old_start == 20
        assert ctx.hunks[1].new_start == 21

    def test_extract_diff_from_text_roundtrip(self) -> None:
        """Parse real diff text and verify all fields are populated."""
        ctx = DiffExtractor.extract_diff_from_text(SIMPLE_DIFF)

        assert ctx.diff_text == SIMPLE_DIFF
        assert isinstance(ctx.files_changed, tuple)
        assert isinstance(ctx.hunks, tuple)
        assert isinstance(ctx.stats, DiffStats)
        assert len(ctx.files_changed) > 0
        assert len(ctx.hunks) > 0
        assert ctx.stats.files_changed == len(ctx.files_changed)
        # Verify hunk content contains the @@ header
        assert ctx.hunks[0].content.startswith("@@")


class TestExtractDiffFromGit:
    """DiffExtractor.extract_diff git subprocess behaviour."""

    @pytest.mark.asyncio
    async def test_extract_diff_treats_base_ref_as_ref_not_pathspec(self, tmp_path, monkeypatch) -> None:
        """The base ref is passed before `--`, so git treats it as a revision."""
        captured: dict[str, object] = {}

        async def fake_run_async_command(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return ProcessResult(
                command=tuple(command),
                exit_code=0,
                stdout="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n",
                stderr="",
            )

        monkeypatch.setattr(
            "ces.harness.services.diff_extractor.run_async_command",
            fake_run_async_command,
        )

        ctx = await DiffExtractor.extract_diff(base_ref="HEAD", working_dir=tmp_path)

        assert captured["command"] == ["git", "diff", "--unified=5", "HEAD", "--"]
        assert captured["kwargs"]["cwd"] == tmp_path  # type: ignore[index]
        assert ctx.files_changed == ("app.py",)
        assert "-value = 1" in ctx.diff_text
        assert "+value = 2" in ctx.diff_text


# ---------------------------------------------------------------------------
# Truncation tests
# ---------------------------------------------------------------------------


class TestTruncateDiff:
    """DiffExtractor.truncate_diff behaviour."""

    def test_truncate_no_op_when_small(self) -> None:
        """Diff under the limit returns unchanged with truncated=False."""
        ctx = DiffExtractor.extract_diff_from_text(SIMPLE_DIFF)
        result = DiffExtractor.truncate_diff(ctx, max_chars=100_000)

        assert result is ctx  # exact same object
        assert result.truncated is False

    def test_truncate_trims_large_diff(self) -> None:
        """Diff over limit returns trimmed with truncated=True."""
        ctx = DiffExtractor.extract_diff_from_text(MULTI_FILE_DIFF)
        # Set a very small limit so at least one hunk gets dropped
        result = DiffExtractor.truncate_diff(ctx, max_chars=1)

        assert result.truncated is True
        assert len(result.hunks) < len(ctx.hunks)

    def test_truncate_preserves_complete_hunks(self) -> None:
        """Truncation does not cut a hunk in the middle."""
        ctx = DiffExtractor.extract_diff_from_text(MULTI_HUNK_DIFF)
        # Allow enough room for the first hunk but not both
        first_hunk_size = len(ctx.hunks[0].content)
        result = DiffExtractor.truncate_diff(ctx, max_chars=first_hunk_size + 1)

        assert result.truncated is True
        assert len(result.hunks) == 1
        # The kept hunk is intact -- matches original first hunk
        assert result.hunks[0].content == ctx.hunks[0].content


# ---------------------------------------------------------------------------
# Frozen model tests
# ---------------------------------------------------------------------------


class TestDiffContextFrozen:
    """DiffContext is frozen (immutable)."""

    def test_diff_context_frozen(self) -> None:
        """Attempting to set attributes on DiffContext raises ValidationError."""
        ctx = DiffExtractor.extract_diff_from_text(SIMPLE_DIFF)

        with pytest.raises(ValidationError):
            ctx.truncated = True  # type: ignore[misc]

        with pytest.raises(ValidationError):
            ctx.diff_text = "changed"  # type: ignore[misc]
