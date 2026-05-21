# First 15 Minutes

Use this path when you want one small greenfield project and you do not want to learn every CES command first.

## 1. Install and Check Runtime

```bash
uv tool install --python 3.13 controlled-execution-system
uv tool update-shell
ces doctor
ces doctor --runtime-safety
```

CES does not ship Codex CLI or Claude Code. Install and authenticate one before `ces build`.

## 2. Create a Read-Only Plan

```bash
ces create "Create a small task tracker with add/list/complete tasks, tests, and a README" --name task-tracker
```

This is read-only. It prints the folder and command sequence; it does not create `.ces/` or launch a runtime.

## 3. Build in a New Folder

```bash
mkdir task-tracker
cd task-tracker
ces build --from-scratch "Create a small task tracker with add/list/complete tasks, tests, and a README"
```

If you use Codex, CES may ask you to explicitly accept the runtime side-effect boundary. Read the notice before rerunning with `--accept-runtime-side-effects`.

## 4. Verify Before Approval

```bash
ces verify
ces proof
```

Approve only when proof is proven and the recommendation is safe to review:

```bash
ces approve --yes
```

If proof is partial or blocked, run:

```bash
ces why
ces recover --dry-run
```

## What Good Output Looks Like

Good proof answers:

- what changed
- how to run it
- how it was tested
- what remains unproven
- whether the result is safe to review

If those answers are missing, do not approve. Re-run verification, recover the builder session, or ask the runtime for a smaller fix.
