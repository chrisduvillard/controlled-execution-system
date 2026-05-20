"""Git diff indexing for semantic review generation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ces.execution.processes import ProcessResult, run_sync_command
from ces.execution.secrets import scrub_secrets_from_text
from ces.review.file_classifier import classify_path
from ces.review.models import ChangedFile, DiffIndex, DiffStats

_MAX_EXCERPT_BYTES = 64_000
_BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".gz", ".ico"}


def build_diff_index(
    repo_root: Path,
    *,
    base_ref: str | None = None,
    head_ref: str | None = None,
    include_untracked: bool = True,
) -> DiffIndex:
    """Build a deterministic diff index for a local git repository."""

    root = resolve_git_root(repo_root)
    base = _safe_ref(base_ref or "HEAD")
    if base is None:
        raise ValueError("Invalid git base ref for semantic review diff.")
    head = _safe_ref(head_ref) if head_ref else None
    warnings: list[str] = []
    base_sha = _git_optional(root, "rev-parse", "--verify", base)
    head_sha = _git_optional(root, "rev-parse", "--verify", head) if head else "WORKTREE"
    merge_base = _git_optional(root, "merge-base", base, head) if head else None
    diff_args = [base, head] if head else [base]
    name_status = _git(root, "diff", "--name-status", "--find-renames", "--find-copies", *diff_args, "--")
    numstat = _git(root, "diff", "--numstat", "--find-renames", "--find-copies", *diff_args, "--")
    patch = _git(root, "diff", "--unified=5", *diff_args, "--")
    stats_by_path = _parse_numstat(numstat)
    changed_files = _parse_name_status(name_status, stats_by_path, root, patch, head_ref=head)
    if include_untracked and not head:
        changed_files.extend(_untracked_files(root))
    changed_files = sorted(changed_files, key=lambda item: item.path)
    stats = DiffStats(
        files_changed=len(changed_files),
        insertions=sum(item.additions for item in changed_files),
        deletions=sum(item.deletions for item in changed_files),
    )
    fingerprint = _fingerprint(
        base,
        head or "WORKTREE",
        base_sha,
        head_sha,
        changed_files,
        stats,
        include_untracked=include_untracked,
    )
    if not changed_files:
        warnings.append("No changed files detected for the requested diff.")
    return DiffIndex(
        base_ref=base,
        head_ref=head or "WORKTREE",
        merge_base=merge_base,
        base_sha=base_sha,
        head_sha=head_sha,
        diff_fingerprint=fingerprint,
        changed_files=tuple(changed_files),
        stats=stats,
        warnings=tuple(warnings),
    )


def resolve_git_root(repo_root: Path) -> Path:
    """Resolve the canonical top-level git repository root."""

    result = run_sync_command(["git", "rev-parse", "--show-toplevel"], cwd=repo_root, timeout_seconds=30)
    if result.exit_code != 0:
        msg = result.stderr.strip() or "not a git repository"
        raise ValueError(f"Cannot generate semantic review without a git repository: {msg}")
    return Path(result.stdout.strip()).resolve()


def _safe_ref(ref: str | None) -> str | None:
    if ref is None:
        return None
    candidate = ref.strip()
    if not candidate or candidate.startswith("-") or "\x00" in candidate:
        raise ValueError("Invalid git ref for semantic review diff.")
    return candidate


def _git(root: Path, *args: str) -> str:
    result = run_sync_command(["git", *args], cwd=root, timeout_seconds=30)
    if result.exit_code != 0:
        raise ValueError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _git_optional(root: Path, *args: str | None) -> str | None:
    if any(arg is None for arg in args):
        return None
    result: ProcessResult = run_sync_command(
        ["git", *(str(arg) for arg in args if arg is not None)], cwd=root, timeout_seconds=30
    )
    if result.exit_code != 0:
        return None
    return result.stdout.strip() or None


def _parse_numstat(numstat: str) -> dict[str, tuple[int, int, bool]]:
    stats: dict[str, tuple[int, int, bool]] = {}
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, path = parts[0], parts[1], parts[-1]
        binary = added == "-" or deleted == "-"
        stats[_normalize_rename_path(path)] = (0 if binary else int(added), 0 if binary else int(deleted), binary)
    return stats


def _normalize_rename_path(path: str) -> str:
    if " => " not in path or "{" not in path or "}" not in path:
        return path
    prefix, rest = path.split("{", 1)
    change, suffix = rest.split("}", 1)
    if " => " in change:
        return prefix + change.split(" => ", 1)[1] + suffix
    return path


def _parse_name_status(
    name_status: str,
    stats_by_path: dict[str, tuple[int, int, bool]],
    root: Path,
    patch: str,
    *,
    head_ref: str | None,
) -> list[ChangedFile]:
    changed: list[ChangedFile] = []
    hunk_counts = _hunk_counts_by_path(patch)
    patch_hashes = _patch_hashes_by_path(patch)
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0]
        status = _status_name(code)
        old_path = parts[1] if code.startswith(("R", "C")) and len(parts) > 2 else None
        path = parts[2] if old_path is not None and len(parts) > 2 else parts[1]
        additions, deletions, binary_from_stat = stats_by_path.get(path, (0, 0, False))
        changed.append(
            _changed_file(
                root,
                path,
                status,
                additions,
                deletions,
                binary_from_stat,
                hunk_counts,
                old_path,
                head_ref=head_ref,
                patch_hash=patch_hashes.get(path),
            )
        )
    return changed


def _status_name(code: str) -> str:
    first = code[:1]
    return {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "T": "type_changed",
        "U": "unmerged",
    }.get(first, "unknown")


def _changed_file(
    root: Path,
    path: str,
    status: str,
    additions: int,
    deletions: int,
    binary_from_stat: bool,
    hunk_counts: dict[str, int],
    old_path: str | None = None,
    *,
    head_ref: str | None = None,
    patch_hash: str | None = None,
) -> ChangedFile:
    candidate = root / path
    extension = candidate.suffix.lower()
    binary = binary_from_stat or extension in _BINARY_EXTS
    classification = classify_path(path)
    deleted = status == "deleted"
    if head_ref is not None:
        file_size = _blob_size(root, head_ref, path) if not deleted else None
        content_hash = _blob_hash(root, head_ref, path) if not deleted else None
        excerpt = _safe_blob_excerpt(root, head_ref, path, binary=binary, deleted=deleted)
    else:
        file_size = _safe_size(candidate)
        content_hash = _worktree_content_hash(root, path) if not deleted else None
        excerpt = _safe_excerpt(candidate, binary=binary, deleted=deleted)
    return ChangedFile(
        path=path,
        old_path=old_path,
        status=status,
        additions=additions,
        deletions=deletions,
        binary=binary,
        extension=extension,
        top_level_dir=path.split("/", 1)[0] if "/" in path else "",
        file_size_bytes=file_size,
        content_hash=content_hash,
        patch_hash=patch_hash,
        patch_available=not binary and not deleted,
        hunk_count=hunk_counts.get(path, 0),
        classification=classification,
        content_excerpt=excerpt,
    )


def _safe_size(path: Path) -> int | None:
    try:
        if path.exists() and not path.is_symlink() and path.is_file():
            return path.stat().st_size
    except OSError:
        return None
    return None


def _safe_excerpt(path: Path, *, binary: bool, deleted: bool) -> str:
    if binary or deleted:
        return ""
    try:
        if not path.exists() or path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_EXCERPT_BYTES:
            return ""
        data = path.read_bytes()[:_MAX_EXCERPT_BYTES]
        return scrub_secrets_from_text(data.decode("utf-8", errors="ignore"))
    except OSError:
        return ""


def _safe_blob_excerpt(root: Path, ref: str, path: str, *, binary: bool, deleted: bool) -> str:
    if binary or deleted:
        return ""
    size = _blob_size(root, ref, path)
    if size is None or size > _MAX_EXCERPT_BYTES:
        return ""
    result = run_sync_command(["git", "show", f"{ref}:{path}"], cwd=root, timeout_seconds=30)
    if result.exit_code != 0:
        return ""
    return scrub_secrets_from_text(result.stdout[:_MAX_EXCERPT_BYTES])


def _blob_size(root: Path, ref: str, path: str) -> int | None:
    result = run_sync_command(["git", "cat-file", "-s", f"{ref}:{path}"], cwd=root, timeout_seconds=30)
    if result.exit_code != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def _blob_hash(root: Path, ref: str, path: str) -> str | None:
    result = run_sync_command(["git", "rev-parse", f"{ref}:{path}"], cwd=root, timeout_seconds=30)
    if result.exit_code != 0:
        return None
    return result.stdout.strip() or None


def _worktree_content_hash(root: Path, path: str) -> str | None:
    candidate = root / path
    if not candidate.is_file() or candidate.is_symlink():
        return None
    result = run_sync_command(["git", "hash-object", "--", path], cwd=root, timeout_seconds=30)
    if result.exit_code != 0:
        return None
    return result.stdout.strip() or None


def _hunk_counts_by_path(patch: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    current: str | None = None
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            current = _path_from_diff_header(line)
        elif current and line.startswith("@@ "):
            counts[current] = counts.get(current, 0) + 1
    return counts


def _patch_hashes_by_path(patch: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            current = _path_from_diff_header(line)
            if current:
                sections[current] = [line]
        elif current:
            sections[current].append(line)
    return {
        path: hashlib.sha256("\n".join(lines).encode("utf-8", errors="surrogateescape")).hexdigest()
        for path, lines in sections.items()
    }


def _path_from_diff_header(line: str) -> str | None:
    parts = line.split(" b/", 1)
    if len(parts) != 2:
        return None
    return parts[1]


def _untracked_files(root: Path) -> list[ChangedFile]:
    result = run_sync_command(["git", "ls-files", "--others", "--exclude-standard"], cwd=root, timeout_seconds=30)
    if result.exit_code != 0:
        return []
    files: list[ChangedFile] = []
    for path in result.stdout.splitlines():
        if path.startswith(".ces/") or not path:
            continue
        candidate = root / path
        size = _safe_size(candidate) or 0
        files.append(
            _changed_file(
                root,
                path,
                "untracked",
                _count_lines(candidate),
                0,
                candidate.suffix.lower() in _BINARY_EXTS,
                {},
                None,
            ).model_copy(update={"file_size_bytes": size})
        )
    return files


def _count_lines(path: Path) -> int:
    try:
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= _MAX_EXCERPT_BYTES:
            return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0
    return 0


def _fingerprint(
    base: str,
    head: str,
    base_sha: str | None,
    head_sha: str | None,
    changed_files: list[ChangedFile],
    stats: DiffStats,
    *,
    include_untracked: bool,
) -> str:
    payload = {
        "base": base,
        "head": head,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "include_untracked": include_untracked,
        "stats": stats.model_dump(mode="json"),
        "files": [
            {
                "path": item.path,
                "old_path": item.old_path,
                "status": item.status,
                "additions": item.additions,
                "deletions": item.deletions,
                "binary": item.binary,
                "size": item.file_size_bytes,
                "content_hash": item.content_hash,
                "patch_hash": item.patch_hash,
            }
            for item in sorted(changed_files, key=lambda file: file.path)
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


_resolve_git_root = resolve_git_root
