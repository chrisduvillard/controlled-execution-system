#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Prepare a clean CES worktree for an external gnhf trial.

Usage:
  ./scripts/gnhf_trial.sh [options] <trial-name>

Options:
  --agent AGENT          Agent name for the printed gnhf example (default: codex)
  --base-ref REF         Git ref to seed the clean worktree from (default: current branch)
  --max-iterations N     Suggested gnhf iteration cap in the printed example (default: 4)
  --worktree-dir PATH    Destination path for the clean sibling worktree
  --help                 Show this help text

This helper does not run gnhf for you. It creates a clean sibling worktree and
prints the next steps, so you can run a bounded gnhf trial outside your active
CES checkout.
EOF
}

fail() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

slugify() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9._-]+/-/g; s/^-+//; s/-+$//; s/-{2,}/-/g'
}

agent="codex"
base_ref=""
max_iterations="4"
worktree_dir=""

while (($# > 0)); do
  case "$1" in
    --agent)
      shift
      (($# > 0)) || fail "--agent requires a value"
      agent="$1"
      ;;
    --base-ref)
      shift
      (($# > 0)) || fail "--base-ref requires a value"
      base_ref="$1"
      ;;
    --max-iterations)
      shift
      (($# > 0)) || fail "--max-iterations requires a value"
      max_iterations="$1"
      ;;
    --worktree-dir)
      shift
      (($# > 0)) || fail "--worktree-dir requires a value"
      worktree_dir="$1"
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --*)
      fail "unknown option: $1"
      ;;
    *)
      break
      ;;
  esac
  shift
done

(($# == 1)) || {
  usage >&2
  exit 1
}

trial_name="$1"
trial_slug="$(slugify "$trial_name")"
[[ -n "$trial_slug" ]] || fail "trial name must contain at least one letter or number"

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "run this inside a Git checkout"
cd "$repo_root"

if [[ -n "$(git status --porcelain)" ]]; then
  fail "gnhf trials require a clean Git worktree; use a clean clone or clean checkout first"
fi

if [[ -z "$base_ref" ]]; then
  base_ref="$(git rev-parse --abbrev-ref HEAD)"
fi

git rev-parse --verify --quiet "$base_ref^{commit}" >/dev/null \
  || fail "base ref not found: $base_ref"

repo_name="$(basename "$repo_root")"
trial_branch="trial/gnhf-${trial_slug}"
default_parent="$(dirname "$repo_root")/${repo_name}-gnhf-worktrees"
worktree_dir="${worktree_dir:-${default_parent}/${trial_slug}}"

git show-ref --verify --quiet "refs/heads/${trial_branch}" \
  && fail "trial branch already exists: ${trial_branch}"

[[ ! -e "$worktree_dir" ]] || fail "worktree path already exists: $worktree_dir"

mkdir -p "$(dirname "$worktree_dir")"
git worktree add -b "$trial_branch" "$worktree_dir" "$base_ref"

cat <<EOF
Created clean CES trial worktree.

Worktree: $worktree_dir
Base ref: $base_ref
Trial branch: $trial_branch

Next steps:
  1. cd "$worktree_dir"
  2. Install gnhf separately if needed: npm install -g gnhf
  3. Review docs/GNHF_Trial_Guide.md for allowed and excluded CES surfaces
  4. Run one bounded trial, for example:

     gnhf --agent $agent --max-iterations $max_iterations "Improve CES <scoped task>. Stay within the explicitly allowed files. Do not touch src/ces/control/, src/ces/execution/, approval, triage, review, manifest, audit, or kill-switch logic. Add or update tests for any behavior change."

Cleanup:
  git worktree remove "$worktree_dir"
  git branch -D "$trial_branch"
EOF
