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
| **1** | Deterministic probe → opens GitHub issues on red findings, **auto-dispatches known fix templates** | Free | every 30 min during work hours, hourly at night | ✅ live |
| **2** | Auto-fix dispatcher (PR back to target repo) — manual entrypoint AND auto-dispatch target | Free for `version_trinity` / `sibling_sync` / `regenerate_misaligned_distractors`; `ANTHROPIC_API_KEY`-gated for `investigate` | dispatched by Tier 1 for known templates; manual `workflow_dispatch` otherwise | ✅ live; `version_trinity` and `regenerate_misaligned_distractors` proven end-to-end on Geri 2026-04-28; `investigate` wired 2026-04-28 (Sonnet 4.6 headless via Claude Code CLI; requires `ANTHROPIC_API_KEY` secret) |
| **3** | Cross-repo synthesis (sibling sync, secret-rotation reminders, spend trends) | Free | weekly | 🟡 planned |

### Tier 1 — `health-check.yml` + `scripts/probe.py`

Every 30 minutes, the probe:

1. For each watched repo, reads version-bearing files from the `main` branch (e.g. `package.json`, `src/core/constants.js`, `sw.js`, `shlav-a-mega.html`).
2. Fetches the deployed `sw.js` from GitHub Pages and extracts the live `CACHE` version.
3. Compares — if `live != main` or files inside the repo disagree (the **version-trinity** invariant), that's a critical finding.
4. Pulls the latest `CI` and `Deploy to GitHub Pages` workflow runs on `main`. Any `failure` is critical.
5. Hits Toranot's `/self-audit` and `watch-advisor2`'s `/skill-snapshot` endpoints. Non-200 or `status != HEALTHY` is a warning.
6. Hashes `shared/fsrs.js` and `harrison_chapters.json` across the three medical PWAs. Any divergence is a warning.
7. **Smoke-tests the shared `study_plan_get` RPC** for each app's documented `APP_KEY` (`geri` / `pnimit` / `mishpacha`) using a sentinel username. `{ok:false, error:'invalid_app'}` from the server is critical (whitelist drift). Catches the class of bug that surfaced 2026-04-28 (Geri v10.46.0 sent `'shlav'`, server rejected, user saw `invalid_app ✗` despite HTTP 200). Cross-cutting critical findings open ONE issue in `auto-audit` itself, not N copies in N repos.

Outputs:

- `health-reports/YYYY-MM-DDTHH-MM*.md` and `.json` — committed every run as the audit trail.
- A GitHub issue in the affected repo, labeled `auto-audit` (and `auto-fix-eligible` if the failure has a known fix template). Idempotent by title within the same day, so a persistent problem doesn't spam.
- Run summary inline in GitHub Actions UI.

#### Auto-dispatch

For known-safe fix templates (currently just `regenerate_misaligned_distractors`), the probe also fires a `workflow_dispatch` against the matching workflow in this repo immediately after filing the issue. The issue gets a comment with a link to the dispatched run. This closes the loop without needing a human to click "Run workflow".

Safeguards:

- **Allowlist** — only templates in `AUTO_DISPATCH_TEMPLATES` (in `scripts/probe.py`) are eligible. New templates stay manual until they earn trust.
- **Idempotency** — before dispatching, the probe queries this repo's queued + in-progress runs of the target workflow. If one is already running, dispatch is skipped (with a comment on the issue noting the skip).
- **Kill switch** — set `AUTO_DISPATCH_DISABLED=1` in the cron env (or surface it from a repo variable) to revert to manual click-to-fix without code changes.
- **No prod push** — auto-dispatched workflows still open PRs, never push to `main`. Same review gate as manual dispatch.

#### Modifying the probe

When changing `scripts/probes/probe_distractor_alignment.py` or its adapter in `scripts/probe.py`, run `python scripts/probes/test_alignment_dispatch.py` before pushing. Exit 0 = ship. Deliberately not in CI — it pulls ~17 MB twice and depends on a known-bad SHA that could be force-pushed away.

### Tier 2 — `auto-fix.yml` + standalone fix workflows

Tier 2 is a set of `workflow_dispatch` workflows in this repo that fix issues
in the target PWAs. They're triggered three ways:

1. **Auto-dispatched by Tier 1** — when the probe files an issue with an
   `auto_fix` template that's in the `AUTO_DISPATCH_TEMPLATES` allowlist
   (currently just `regenerate_misaligned_distractors`), Tier 1 fires the
   matching workflow immediately.
2. **Manual click** — Actions tab → pick workflow → Run workflow.
3. **Manual API call** — `gh api -X POST .../actions/workflows/<name>/dispatches`.

**Tier 2 never pushes to `main` of any target repo.** Every fix is a PR you
review. If a fix produces no diff (e.g. version_trinity ran but everything
was already in sync), the workflow exits green without opening an empty PR.

#### Living templates

- **`auto-fix.yml`** — generic dispatcher with `version_trinity` and
  `sibling_sync` templates.
  - `version_trinity` — reads `package.json` version, propagates it to
    `APP_VERSION` (in `shlav-a-mega.html` for Geri or `src/core/constants.js`
    for FM/Pnimit) and `sw.js CACHE`. Per-repo normalization handles the
    Pnimit `pkg=X.Y.Z.0 → APP_VERSION=X.Y.Z` quirk; Geri/FM use exact match.
    Runs the target repo's vitest suite before opening a PR. Proven on Geri
    2026-04-28 (no-diff short-circuit path).
  - `sibling_sync` — propagates `shared/fsrs.js` from a chosen source repo
    to its two siblings. Listed in the dispatcher choice list but the
    implementation block is missing; dispatching it currently runs `npm ci`,
    finds no diff, and exits cleanly. **Wire-in pending** — see
    `WIRE_IN_SIBLING_SYNC.md` (TODO).
  - `investigate` — Claude-driven generic fix loop. Wired 2026-04-28 via
    the Claude Code CLI (`@anthropic-ai/claude-code`) in headless mode
    (`claude --print --max-turns 30 --model claude-sonnet-4-6`).
    Pre-fetches issue title + body + labels via the GitHub API, builds a
    prompt with hard guardrails (no shared-engine edits, no version
    bumps, must pass vitest, bails to `/tmp/investigate-failure.md` if
    the fix is unsafe), runs Claude in the cloned target repo, then
    flows through the same test + PR-open gates as the deterministic
    templates. Requires `ANTHROPIC_API_KEY` repo secret. Per-dispatch
    cost ~$0.50–2 in Sonnet usage. Pre-flight guard only requires the
    key for this template so the deterministic ones run on the current
    secret set.

- **`regenerate-misaligned-distractors.yml`** — standalone Geri-specific
  fix. Triggered by Tier 1 when `probe_distractor_alignment` finds
  `DIS[k]` empty-slot ≠ `Q[k].c`. Clones Geri, drops misaligned entries,
  regenerates via the Toranot proxy (Haiku 4.5, 6 workers), bumps the
  version trinity, runs `tests/distractorsDrift.test.js`, opens a PR.
  Wall time ~30–60 min, ~$10 spend. Resumable on retry. Proven on the
  early-exit path 2026-04-28 (3833 aligned/0 misaligned → exit 0
  cleanly).

#### Trust ladder for new templates

New auto-fix templates start as **manual-only** (added to the workflow but
*not* added to `AUTO_DISPATCH_TEMPLATES`). Once they've proven safe under
manual dispatch — clean diffs, no false positives, well-bounded blast
radius — they get promoted into the allowlist and Tier 1 starts dispatching
them automatically. Kill switch: set `AUTO_DISPATCH_DISABLED=1` in the
cron env to revert all auto-dispatch to manual without a code change.

### Tier 3 — planned

- Diff sibling-engine files weekly and auto-PR the canonical version to drifting siblings.
- Track open security issues age (e.g. `Geriatrics #79` rotation reminder); bump severity after N days.
- Watch monthly token-usage trend on `Toranot` — alarm on month-over-month spike (runaway-loop indicator).
- Generate a "state-of-the-suite" markdown report each Sunday and pin to a tracker issue in this repo.

## Setup (one-time)

1. **Create a fine-grained PAT** at https://github.com/settings/tokens?type=beta with:
   - Resource: `Eiasash/Geriatrics`, `Eiasash/InternalMedicine`, `Eiasash/FamilyMedicine`, `Eiasash/ward-helper`, `Eiasash/Toranot`, `Eiasash/watch-advisor2`, `Eiasash/auto-audit`.
   - Permissions: **Contents** → Read & write (for committing fix branches), **Issues** → Read & write, **Pull requests** → Read & write, **Actions** → Read & write (the last one is required for Tier 1 auto-dispatch — it triggers `workflow_dispatch` on `Eiasash/auto-audit`).
   - Lifetime: 1 year (rotate annually). 90-day is fine if you prefer.
2. **Add it as a repository secret** in this repo: Settings → Secrets and variables → Actions → New repository secret → name `MONITOR_PAT`, paste the token.
3. **For Tier 2 `investigate`**: add `ANTHROPIC_API_KEY` the same way (Settings → Secrets and variables → Actions → New repository secret → name `ANTHROPIC_API_KEY`). The deterministic templates run without it; only `investigate` is gated. See `WIRE_IN_INVESTIGATE.md` for verification steps.
4. **Trigger first run**: Actions tab → Tier 1 — Health Check → Run workflow → check the box for `dry_run` first time, then run live.

## What you'll see

After setup, GitHub will email you (and surface in your notifications) when any of the watched repos hits a critical issue. The notification links to the auto-audit issue in the affected repo, which contains the full snapshot. From there you can:

- Trigger Tier 2 to open a PR with the proposed fix.
- Or fix it yourself; the next probe run will close the loop and the issue can be closed manually.

## What this does NOT do (yet)

- Doesn't watch private/secret rotation (the open security issues in Geriatrics/Pnimit/Toranot about hardcoded secrets need manual rotation in the Supabase dashboard).
- Doesn't audit content quality of the question banks (that's the per-repo `weekly-audit.yml`).
- Doesn't run the audit-fix-deploy skill end-to-end. That's Tier 3 territory.
