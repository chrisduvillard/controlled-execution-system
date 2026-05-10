"""DiffExtractor service for structured git diff extraction.

Provides models and a service for extracting and parsing git diffs into
structured data suitable for LLM-based code reviewers. All parsing is
deterministic -- no LLM calls.

Models:
    DiffStats: Insertion/deletion/file-change counts.
    DiffHunk: A single hunk from a unified diff.
    DiffContext: Complete structured diff with hunks, stats, and metadata.

Service:
    DiffExtractor: Extracts diffs via git subprocess or parses raw diff text.
"""

from __future__ import annotations

import re
from pathlib import Path

from ces.execution.processes import run_async_command
from ces.shared.base import CESBaseModel

# ---------------------------------------------------------------------------
# Regex patterns for unified diff parsing
# ---------------------------------------------------------------------------

_DIFF_FILE_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_NEW_FILE_MODE = re.compile(r"^new file mode")
_DELETED_FILE_MODE = re.compile(r"^deleted file mode")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DiffStats(CESBaseModel):
    """Aggregate statistics for a diff.

    Attributes:
        insertions: Number of added lines.
        deletions: Number of removed lines.
        files_changed: Number of files with changes.
    """

    insertions: int
    deletions: int
    files_changed: int


class DiffHunk(CESBaseModel):
    """A single hunk from a unified diff.

    Attributes:
        file_path: Path of the file this hunk belongs to.
        old_start: Starting line number in the old file.
        new_start: Starting line number in the new file.
        content: Raw text content of the hunk (header + diff lines).
        is_new_file: True if this hunk belongs to a newly created file.
        is_deleted_file: True if this hunk belongs to a deleted file.
    """

    file_path: str
    old_start: int
    new_start: int
    content: str
    is_new_file: bool = False
    is_deleted_file: bool = False


class DiffContext(CESBaseModel):
    """Complete structured representation of a git diff.

    Attributes:
        diff_text: Full raw diff text.
        files_changed: Tuple of file paths that were changed.
        hunks: Tuple of parsed DiffHunk objects.
        stats: Aggregate diff statistics.
        truncated: True if the diff was truncated to fit size limits.
    """

    diff_text: str
    files_changed: tuple[str, ...]
    hunks: tuple[DiffHunk, ...]
    stats: DiffStats
    truncated: bool = False


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class DiffExtractor:
    """Extracts and parses git diffs into structured data.

    Provides both async git-based extraction and synchronous text parsing.
    All operations are deterministic -- no LLM calls.
    """

    @staticmethod
    async def extract_diff(
        base_ref: str = "HEAD~1",
        working_dir: Path | None = None,
    ) -> DiffContext:
        """Extract a diff from git and parse it into a DiffContext.

        Runs ``git diff --unified=5 {base_ref}`` as an async subprocess
        and parses the output into structured form.

        Args:
            base_ref: Git ref to diff against (default ``HEAD~1``).
            working_dir: Working directory for the git command.
                Falls back to the current directory when *None*.

        Returns:
            Parsed DiffContext with hunks, stats, and metadata.

        Raises:
            RuntimeError: If the git command fails.
        """
        if not base_ref or base_ref.startswith("-") or "\x00" in base_ref:
            msg = "Invalid git base ref."
            raise ValueError(msg)
        result = await run_async_command(
            [
                "git",
                "diff",
                "--unified=5",
                base_ref,
                # ``--`` terminates revisions before pathspecs so ``base_ref`` is
                # interpreted as a revision instead of a path.
                "--",
            ],
            cwd=working_dir,
            timeout_seconds=30,
        )

        if result.exit_code != 0:
            err_msg = result.stderr.strip() or "unknown error"
            msg = f"git diff failed (exit {result.exit_code}): {err_msg}"
            raise RuntimeError(msg)

        diff_text = result.stdout
        return DiffExtractor.extract_diff_from_text(diff_text)

    @staticmethod
    def extract_diff_from_text(diff_text: str) -> DiffContext:
        """Parse unified diff text into a structured DiffContext.

        Pure function -- no git or filesystem access required.

        Args:
            diff_text: Raw unified diff text to parse.

        Returns:
            Parsed DiffContext with hunks, stats, and metadata.
        """
        if not diff_text.strip():
            return DiffContext(
                diff_text=diff_text,
                files_changed=(),
                hunks=(),
                stats=DiffStats(insertions=0, deletions=0, files_changed=0),
            )

        files_changed: list[str] = []
        hunks: list[DiffHunk] = []
        insertions = 0
        deletions = 0

        # State tracking while iterating lines
        current_file: str | None = None
        is_new_file = False
        is_deleted_file = False
        current_hunk_lines: list[str] = []
        current_old_start = 0
        current_new_start = 0
        in_hunk = False

        lines = diff_text.split("\n")

        for line in lines:
            # New file header: diff --git a/... b/...
            file_match = _DIFF_FILE_HEADER.match(line)
            if file_match:
                # Flush any pending hunk
                if in_hunk and current_file is not None:
                    hunks.append(
                        DiffHunk(
                            file_path=current_file,
                            old_start=current_old_start,
                            new_start=current_new_start,
                            content="\n".join(current_hunk_lines),
                            is_new_file=is_new_file,
                            is_deleted_file=is_deleted_file,
                        )
                    )
                    current_hunk_lines = []
                    in_hunk = False

                current_file = file_match.group(2)
                if current_file not in files_changed:
                    files_changed.append(current_file)
                is_new_file = False
                is_deleted_file = False
                continue

            # Detect new/deleted file markers
            if _NEW_FILE_MODE.match(line):
                is_new_file = True
                continue
            if _DELETED_FILE_MODE.match(line):
                is_deleted_file = True
                continue

            # Hunk header: @@ -X,Y +A,B @@
            hunk_match = _HUNK_HEADER.match(line)
            if hunk_match:
                # Flush previous hunk for same file
                if in_hunk and current_file is not None:
                    hunks.append(
                        DiffHunk(
                            file_path=current_file,
                            old_start=current_old_start,
                            new_start=current_new_start,
                            content="\n".join(current_hunk_lines),
                            is_new_file=is_new_file,
                            is_deleted_file=is_deleted_file,
                        )
                    )

                current_old_start = int(hunk_match.group(1))
                current_new_start = int(hunk_match.group(2))
                current_hunk_lines = [line]
                in_hunk = True
                continue

            # Inside a hunk: collect lines and count insertions/deletions
            if in_hunk:
                current_hunk_lines.append(line)
                if line.startswith("+"):
                    insertions += 1
                elif line.startswith("-"):
                    deletions += 1

        # Flush final hunk
        if in_hunk and current_file is not None:
            hunks.append(
                DiffHunk(
                    file_path=current_file,
                    old_start=current_old_start,
                    new_start=current_new_start,
                    content="\n".join(current_hunk_lines),
                    is_new_file=is_new_file,
                    is_deleted_file=is_deleted_file,
                )
            )

        return DiffContext(
            diff_text=diff_text,
            files_changed=tuple(files_changed),
            hunks=tuple(hunks),
            stats=DiffStats(
                insertions=insertions,
                deletions=deletions,
                files_changed=len(files_changed),
            ),
        )

    @staticmethod
    def truncate_diff(
        context: DiffContext,
        max_chars: int = 50_000,
    ) -> DiffContext:
        """Truncate a diff to fit within an LLM context window.

        Keeps complete hunks up to *max_chars* total content. If any hunks
        are dropped the returned context has ``truncated=True``.

        Args:
            context: The DiffContext to potentially truncate.
            max_chars: Maximum character budget for diff text.

        Returns:
            Original context unchanged if within budget, otherwise a
            new DiffContext with fewer hunks and ``truncated=True``.
        """
        if len(context.diff_text) <= max_chars:
            return context

        kept_hunks: list[DiffHunk] = []
        total_chars = 0
        kept_insertions = 0
        kept_deletions = 0
        kept_files: list[str] = []

        for hunk in context.hunks:
            hunk_size = len(hunk.content)
            if total_chars + hunk_size > max_chars:
                break
            kept_hunks.append(hunk)
            total_chars += hunk_size
            if hunk.file_path not in kept_files:
                kept_files.append(hunk.file_path)
            # Re-count stats for kept hunks
            for line in hunk.content.split("\n"):
                if line.startswith("+"):
                    kept_insertions += 1
                elif line.startswith("-"):
                    kept_deletions += 1

        # Rebuild diff_text from kept hunks
        truncated_text = "\n".join(h.content for h in kept_hunks)

        return DiffContext(
            diff_text=truncated_text,
            files_changed=tuple(kept_files),
            hunks=tuple(kept_hunks),
            stats=DiffStats(
                insertions=kept_insertions,
                deletions=kept_deletions,
                files_changed=len(kept_files),
            ),
            truncated=True,
        )
