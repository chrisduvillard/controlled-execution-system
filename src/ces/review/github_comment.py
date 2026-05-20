"""GitHub PR comment rendering for semantic review artifacts."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ces.execution.processes import run_sync_command
from ces.execution.secrets import scrub_secrets_from_text
from ces.review.models import GithubReviewComment, ReviewArtifactBundle

_MAX_COMMENT_CHARS = 6000


def render_github_comment(
    bundle: ReviewArtifactBundle, *, max_chars: int = _MAX_COMMENT_CHARS, pr: int | None = None
) -> GithubReviewComment:
    """Render a concise, redacted GitHub PR comment body."""

    marker = f"<!-- ces-semantic-review:fingerprint={bundle.metadata.diff_fingerprint};review_id={bundle.metadata.review_id} -->"
    top = bundle.risk_map.review_first[:5]
    coverage = (
        ", ".join(f"{status}={count}" for status, count in sorted(bundle.intent_coverage.summary.items())) or "unknown"
    )
    risks = "\n".join(f"- `{item.path}`: {item.level} ({item.score})" for item in top) or "- No changed files detected."
    verification = bundle.verification_summary.status
    stale_warning = (
        "\n> [!WARNING]\n> This semantic review artifact is stale relative to the current diff. Regenerate before relying on it.\n"
        if bundle.metadata.stale
        else ""
    )
    body = f"""{marker}
## CES Semantic Review
{stale_warning}
**Bottom line:** risk `{bundle.risk_map.overall_level}`, verification `{verification}`.

**Review first**
{risks}

**Intent coverage:** {coverage}

**Artifacts:** `{_public_path(bundle.review_brief_path)}`

_Regenerate locally with `ces review generate` if this artifact is stale._
"""
    body = scrub_secrets_from_text(body)
    if len(body) > max_chars:
        body = body[: max_chars - 80].rstrip() + "\n\n_Comment truncated by CES length cap._\n"
    return GithubReviewComment(
        review_id=bundle.metadata.review_id,
        body=body,
        dry_run=True,
        pr=pr,
        stale=bundle.metadata.stale,
        update_marker=marker,
    )


def post_github_comment(
    comment: GithubReviewComment,
    *,
    pr: int,
    repo_root: Path | None = None,
    update_existing: bool = True,
) -> None:
    """Post a pre-rendered comment with the GitHub CLI after explicit CLI approval."""

    cwd = repo_root.resolve() if repo_root is not None else None
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
        handle.write(comment.body)
        body_file = Path(handle.name)
    try:
        if update_existing:
            comment_id = _find_existing_semantic_comment_id(pr, comment.update_marker, cwd=cwd)
            if comment_id:
                result = run_sync_command(
                    [
                        "gh",
                        "api",
                        f"repos/:owner/:repo/issues/comments/{comment_id}",
                        "--method",
                        "PATCH",
                        "--field",
                        f"body={comment.body}",
                    ],
                    cwd=cwd,
                    timeout_seconds=60,
                )
                if result.exit_code != 0:
                    raise RuntimeError(result.stderr.strip() or "gh api comment update failed")
                return
        result = run_sync_command(
            ["gh", "pr", "comment", str(pr), "--body-file", str(body_file)], cwd=cwd, timeout_seconds=60
        )
        if result.exit_code != 0:
            raise RuntimeError(result.stderr.strip() or "gh pr comment failed")
    finally:
        try:
            body_file.unlink()
        except OSError:
            pass


def _find_existing_semantic_comment_id(pr: int, marker: str, *, cwd: Path | None) -> str | None:
    user_result = run_sync_command(["gh", "api", "user", "--jq", ".login"], cwd=cwd, timeout_seconds=60)
    if user_result.exit_code != 0:
        raise RuntimeError(user_result.stderr.strip() or "gh api viewer lookup failed")
    viewer = user_result.stdout.strip()
    marker_literal = json.dumps(marker)
    viewer_literal = json.dumps(viewer)
    jq = f'.[] | select((.body // "") | contains({marker_literal})) | select(.user.login == {viewer_literal}) | .id'
    result = run_sync_command(
        [
            "gh",
            "api",
            f"repos/:owner/:repo/issues/{pr}/comments",
            "--paginate",
            "--jq",
            jq,
        ],
        cwd=cwd,
        timeout_seconds=60,
    )
    if result.exit_code != 0:
        raise RuntimeError(result.stderr.strip() or "gh api comment lookup failed")
    ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return ids[-1] if ids else None


def _public_path(path: Path) -> str:
    parts = path.parts
    if ".ces" in parts:
        index = parts.index(".ces")
        return "/".join(parts[index:])
    return path.name
