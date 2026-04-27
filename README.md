# auto-audit

Cross-repo health monitoring + auto-fix dispatcher for Eias's PWA suite.

Watches: `Geriatrics`, `InternalMedicine`, `FamilyMedicine`, `ward-helper`, `Toranot`, `watch-advisor2`.

## Why this exists

The `weekly-audit.yml` cron in each medical repo validates **data integrity** but only runs once a week and only sees the repo it lives in. It does not catch:

- A deploy that fails after CI passes (e.g. FamilyMedicine v1.7.3 sat broken for 24h on 2026-04-26 because `package.json` was bumped but `APP_VERSION` and `sw.js CACHE` were not — `deployConfigGuard.test.js` failed in CI which cancelled the Pages deploy, but nobody was watching).
- Drift between the live SW served at `eiasash.github.io/<repo>/` and the latest commit on `main`.
- Sibling-engine drift across the three medical PWAs (`shared/fsrs.js`, `harrison_chapters.json`).
- Unhealthy proxies (Toranot self-audit / watch-advisor2 skill-snapshot endpoints).

## Architecture

Three tiers, build-on-each-other:

| Tier | What | Cost | When it runs | Status |
|------|------|------|--------------|--------|
| **1** | Deterministic probe → opens GitHub issues on red findings | Free | every 30 min during work hours, hourly at night | ✅ live |
| **2** | Auto-fix dispatcher (PR back to target repo) | Free for `version_trinity`; API tokens for `investigate` | manual (`workflow_dispatch`) | ✅ scaffold; `version_trinity` works without Claude; `investigate` requires `ANTHROPIC_API_KEY` |
| **3** | Cross-repo synthesis (sibling sync, secret-rotation reminders, spend trends) | Free | weekly | 🟡 planned |

### Tier 1 — `health-check.yml` + `scripts/probe.py`

Every 30 minutes, the probe:

1. For each watched repo, reads version-bearing files from the `main` branch (e.g. `package.json`, `src/core/constants.js`, `sw.js`, `shlav-a-mega.html`).
2. Fetches the deployed `sw.js` from GitHub Pages and extracts the live `CACHE` version.
3. Compares — if `live != main` or files inside the repo disagree (the **version-trinity** invariant), that's a critical finding.
4. Pulls the latest `CI` and `Deploy to GitHub Pages` workflow runs on `main`. Any `failure` is critical.
5. Hits Toranot's `/self-audit` and `watch-advisor2`'s `/skill-snapshot` endpoints. Non-200 or `status != HEALTHY` is a warning.
6. Hashes `shared/fsrs.js` and `harrison_chapters.json` across the three medical PWAs. Any divergence is a warning.

Outputs:

- `health-reports/YYYY-MM-DDTHH-MM*.md` and `.json` — committed every run as the audit trail.
- A GitHub issue in the affected repo, labeled `auto-audit` (and `auto-fix-eligible` if the failure has a known fix template). Idempotent by title within the same day, so a persistent problem doesn't spam.
- Run summary inline in GitHub Actions UI.

#### Modifying the probe

When changing `scripts/probes/probe_distractor_alignment.py` or its adapter in `scripts/probe.py`, run `python scripts/probes/test_alignment_dispatch.py` before pushing. Exit 0 = ship. Deliberately not in CI — it pulls ~17 MB twice and depends on a known-bad SHA that could be force-pushed away.

### Tier 2 — `auto-fix.yml`

Manual trigger via Actions UI. Pick:

- `target_repo` — which of the six PWAs.
- `issue_number` — the auto-audit issue number to close.
- `fix_kind` — currently:
  - `version_trinity` — deterministic. Reads `package.json` version, bumps `APP_VERSION` + `sw.js CACHE` to match. Runs the test suite. Opens a PR. **No Claude needed.**
  - `sibling_sync` — propagates `shared/fsrs.js` from a chosen source repo to its two siblings. (Stub — to be wired.)
  - `investigate` — placeholder for a Claude-Code-Action-driven fix loop. Disabled until `ANTHROPIC_API_KEY` is configured and the action is added.

**Tier 2 never pushes to `main` of any target repo.** Every fix is a PR you review.

### Tier 3 — planned

- Diff sibling-engine files weekly and auto-PR the canonical version to drifting siblings.
- Track open security issues age (e.g. `Geriatrics #79` rotation reminder); bump severity after N days.
- Watch monthly token-usage trend on `Toranot` — alarm on month-over-month spike (runaway-loop indicator).
- Generate a "state-of-the-suite" markdown report each Sunday and pin to a tracker issue in this repo.

## Setup (one-time)

1. **Create a fine-grained PAT** at https://github.com/settings/tokens?type=beta with:
   - Resource: `Eiasash/Geriatrics`, `Eiasash/InternalMedicine`, `Eiasash/FamilyMedicine`, `Eiasash/ward-helper`, `Eiasash/Toranot`, `Eiasash/watch-advisor2`, `Eiasash/auto-audit`.
   - Permissions: **Contents** → Read & write (for committing fix branches), **Issues** → Read & write, **Pull requests** → Read & write, **Actions** → Read.
   - Lifetime: 1 year (rotate annually). 90-day is fine if you prefer.
2. **Add it as a repository secret** in this repo: Settings → Secrets and variables → Actions → New repository secret → name `MONITOR_PAT`, paste the token.
3. **For Tier 2 `investigate` only**: add `ANTHROPIC_API_KEY` the same way. Skippable for now — the deterministic templates work without it.
4. **Trigger first run**: Actions tab → Tier 1 — Health Check → Run workflow → check the box for `dry_run` first time, then run live.

## What you'll see

After setup, GitHub will email you (and surface in your notifications) when any of the watched repos hits a critical issue. The notification links to the auto-audit issue in the affected repo, which contains the full snapshot. From there you can:

- Trigger Tier 2 to open a PR with the proposed fix.
- Or fix it yourself; the next probe run will close the loop and the issue can be closed manually.

## What this does NOT do (yet)

- Doesn't watch private/secret rotation (the open security issues in Geriatrics/Pnimit/Toranot about hardcoded secrets need manual rotation in the Supabase dashboard).
- Doesn't audit content quality of the question banks (that's the per-repo `weekly-audit.yml`).
- Doesn't run the audit-fix-deploy skill end-to-end. That's Tier 3 territory.
