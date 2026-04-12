# Git Workflow & Branch Policy Proposal

---

## 1. Branch Strategy

**Model: Simplified GitHub Flow** (no `develop` branch — ship from `main`)

```
main (protected, production)
  │
  ├── feature/add-user-export       ← new functionality
  ├── fix/chat-streaming-timeout    ← bug fix
  └── chore/upgrade-dependencies    ← maintenance, CI, config
```

### Branch Naming Rules

| Prefix | When to use | Example |
|--------|-------------|---------|
| `feature/` | New functionality | `feature/add-document-search` |
| `fix/` | Bug fix | `fix/msal-cache-stale-token` |
| `chore/` | CI, config, dependencies, docs | `chore/update-node-to-22` |

**Format**: `<type>/<short-description-in-kebab-case>`

**Retired prefixes**: `claude/`, `feat/`, `runonthespot/` — no longer used.

---

## 2. PR Rules

### 2.1 Branch Protection on `main`

| Rule | Setting |
|------|---------|
| Require PR before merging | Yes |
| Required approvals | 1 minimum |
| Require status checks to pass | Yes — all 4 CI jobs below |
| Require branch up-to-date | Yes |
| Allow force push | No |
| Allow deletion | No |

### 2.2 Required CI Checks (already in place)

| # | Job | What it runs |
|---|-----|-------------|
| 1 | lint-and-test | `pnpm lint` → `pnpm typecheck` → `pnpm test` |
| 2 | backend-test | `ruff check` → `mypy` → `pytest` |
| 3 | security-scan | Trivy (CRITICAL/HIGH) + Gitleaks |
| 4 | sbom | Software bill of materials |

### 2.3 PR Template

Add `.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
## What

<!-- One sentence: what does this PR do? -->

## Why

<!-- Why is this change needed? Link to issue if applicable. -->

## How to test

- [ ] Step 1
- [ ] Step 2

## Checklist

- [ ] `pnpm lint && pnpm typecheck && pnpm test` passes
- [ ] `cd backend && uv run ruff check src/ tests/ && uv run mypy src/` passes
- [ ] No `.env` files or secrets committed
- [ ] Commit messages follow `<type>: <description>` format
```

---

## 3. Commit Convention

### Format

```
<type>: <short description>

<optional body>

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
```

### Types

| Type | When |
|------|------|
| `feat` | New feature |
| `fix` | Bug fix |
| `chore` | Maintenance, deps, CI |
| `refactor` | Code restructure, no behavior change |
| `docs` | Documentation only |
| `test` | Add or update tests |

### Rules

- First line: `<type>: <description>` (lowercase type, no period at end)
- Body: optional, separated by blank line
- `Co-Authored-By` trailer: **required on every commit** (enforced by hook)

---

## 4. Git Hooks (3 layers)

### Overview

```
git commit
  │
  ├─ pre-commit     → code quality + secret scanning (existing)
  ├─ commit-msg     → validate format + co-author trailer (NEW)
  │
git push
  │
  └─ pre-push       → full lint + typecheck before push (NEW)
```

### 4.1 pre-commit (existing — no changes)

Already configured in `.pre-commit-config.yaml`:

| Hook | Purpose |
|------|---------|
| trailing-whitespace | Remove trailing spaces |
| end-of-file-fixer | Ensure newline at EOF |
| check-yaml / check-json | Validate config files |
| check-added-large-files | Block files > 1MB |
| detect-private-key | Catch private keys |
| check-merge-conflict | Catch conflict markers |
| gitleaks | Secret scanning |
| no-env-files | Block .env commits |

### 4.2 commit-msg (NEW)

**Purpose**: Enforce conventional commit format + co-author trailer.

Add to `.pre-commit-config.yaml`:

```yaml
  - repo: local
    hooks:
      - id: commit-msg-format
        name: Validate commit message format
        entry: bash scripts/hooks/commit-msg.sh
        language: system
        stages: [commit-msg]
```

`scripts/hooks/commit-msg.sh`:

```bash
#!/usr/bin/env bash
# Validate commit message: conventional format + co-author trailer

MSG_FILE="$1"
MSG=$(cat "$MSG_FILE")
FIRST_LINE=$(head -1 "$MSG_FILE")

# 1. Check conventional commit format on first line
if ! echo "$FIRST_LINE" | grep -qE '^(feat|fix|chore|refactor|docs|test|perf|ci)(\(.+\))?: .+'; then
  echo "ERROR: Commit message must start with: <type>: <description>"
  echo "  Types: feat, fix, chore, refactor, docs, test, perf, ci"
  echo "  Got: $FIRST_LINE"
  exit 1
fi

# 2. Check Co-Authored-By trailer exists
if ! echo "$MSG" | grep -q 'Co-Authored-By:'; then
  echo "ERROR: Missing Co-Authored-By trailer."
  echo "  Add: Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
  exit 1
fi

exit 0
```

### 4.3 pre-push (NEW)

**Purpose**: Run lint + typecheck before code reaches remote. Catches errors faster than waiting for CI.

Add to `.pre-commit-config.yaml`:

```yaml
  - repo: local
    hooks:
      - id: pre-push-checks
        name: Pre-push quality checks
        entry: bash scripts/hooks/pre-push.sh
        language: system
        stages: [pre-push]
        pass_filenames: false
```

`scripts/hooks/pre-push.sh`:

```bash
#!/usr/bin/env bash
# Run lint + typecheck before push (mirrors CI)
set -e

echo "Running pre-push checks..."

# Frontend
echo "[1/3] Frontend lint..."
pnpm lint

echo "[2/3] Frontend typecheck..."
pnpm typecheck

# Backend
echo "[3/3] Backend lint + typecheck..."
cd backend
uv run ruff check src/ tests/
uv run mypy src/

echo "All pre-push checks passed."
```

### 4.4 Setup

After cloning, run once:

```bash
pre-commit install                          # pre-commit hooks
pre-commit install --hook-type commit-msg   # commit-msg hook
pre-commit install --hook-type pre-push     # pre-push hook
```

Update `scripts/setup.sh` to include these automatically.

---

## 5. Claude Code Integration

Add to `.claude/settings.json` so Claude auto-runs checks before committing:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "if": "Bash(git push*)",
        "hooks": [
          {
            "type": "command",
            "command": "cd $CLAUDE_PROJECT_DIR && pnpm lint && pnpm typecheck && cd backend && uv run ruff check src/ tests/ 2>&1 || echo '{\"continue\": false, \"stopReason\": \"Pre-push checks failed. Fix errors before pushing.\"}'",
            "timeout": 120
          }
        ]
      }
    ]
  }
}
```

This ensures Claude Code:
- Runs lint + typecheck before every `git push`
- Gets blocked with a clear error message if checks fail
- Fixes issues before retrying

---

## 6. Developer Daily Workflow

```
1. Pull latest
   git checkout main && git pull

2. Create branch
   git checkout -b feature/my-feature

3. Develop + commit (hooks run automatically)
   git add <files>
   git commit -m "$(cat <<'EOF'
   feat: add document export endpoint

   Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
   EOF
   )"
   → pre-commit: gitleaks, format checks ✓
   → commit-msg: format + co-author check ✓

4. Push (pre-push hook runs automatically)
   git push -u origin feature/my-feature
   → pre-push: lint + typecheck ✓

5. Create PR
   gh pr create --base main

6. CI runs → Review → Merge
```

---

## 7. Files to Add/Modify

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `.github/PULL_REQUEST_TEMPLATE.md` | PR template |
| **Create** | `scripts/hooks/commit-msg.sh` | Commit message validation |
| **Create** | `scripts/hooks/pre-push.sh` | Pre-push lint + typecheck |
| **Modify** | `.pre-commit-config.yaml` | Add commit-msg + pre-push hooks |
| **Modify** | `scripts/setup.sh` | Auto-install all hook types |
| **Modify** | `.claude/settings.json` | Add Claude Code pre-push hook |

---

## Summary

| Layer | When | What it checks | Existing? |
|-------|------|----------------|-----------|
| pre-commit | Every commit | Secrets, formatting, large files, .env | Yes |
| commit-msg | Every commit | Conventional format + Co-Authored-By | **New** |
| pre-push | Every push | Full lint + typecheck (frontend + backend) | **New** |
| CI (GitHub Actions) | Every PR | Full test suite + security scan | Yes |
| CI (Azure DevOps) | Merge to main | Docker build + deploy to dev | Yes |
