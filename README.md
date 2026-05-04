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
| **3** | Cross-repo synthesis (probe firings, workflow streaks, spend trajectory, secret-rotation deadlines) | Free (≤$0.05/wk if Claude narrative enabled) | weekly Sunday 06:00 UTC | ✅ live |

### Tier 1 — `health-check.yml` + `scripts/probe.py`

Every 30 minutes, the probe:

1. For each watched repo, reads version-bearing files from the `main` branch (e.g. `package.json`, `src/core/constants.js`, `sw.js`, `shlav-a-mega.html`).
2. Fetches the deployed `sw.js` from GitHub Pages and extracts the live `CACHE` version.
3. Compares — if `live != main` or files inside the repo disagree (the **version-trinity** invariant), that's a critical finding.
4. Pulls the latest `CI` and `Deploy to GitHub Pages` workflow runs on `main`. Any `failure` is critical.
5. **Watches every other workflow under `.github/workflows/` for failure streaks** (issue #9). For each active workflow that isn't `CI` / `Deploy to GitHub Pages` / `Integrity Guard`, fetches the last 3 completed runs on `main`. If all 3 are `failure` / `timed_out` / `startup_failure`, emits a **warning** with a link to the latest run. Allowlist for known-acceptable failures is `WORKFLOW_FAILURE_ALLOWLIST` in `scripts/probe.py` (currently: `watch-advisor2/weekly-audit.yml` needs `ANTHROPIC_API_KEY`; `Toranot/toranot-weekly-audit.yml` is a deprioritized bundle-size flap). Catches the class of rot that bit Geri+Pnimit on 2026-04-28 (`cowork/distractor-autopsy` branch wipe → 5/5 silent failures over 10h while the health-report stayed green).
6. Hits Toranot's `/self-audit` and `watch-advisor2`'s `/skill-snapshot` endpoints. Non-200 or `status != HEALTHY` is a warning.
7. **Tracks call-count deltas** (Toranot only) — compares `tokenUsage.currentMonthTotals.call_count` against the previous run (30-min interval). Alarms if delta exceeds thresholds: **WARN** at >500 calls/30min (~17/min), **CRITICAL** at >2000 calls/30min (~67/min). This catches runaway-loop scenarios (auth-failure retry storms, malformed-JSON re-prompt loops, misconfigured bulk-gen workers) that today's static checks miss. State persists in `health-reports/.last_call_count.json`. Suppression: set `BULK_GEN_ACTIVE=1` repo variable during legitimate bulk-gen events to silence alarms.
8. Hashes `shared/fsrs.js` and `harrison_chapters.json` across the three medical PWAs. Any divergence is a warning.
9. **Smoke-tests the shared `study_plan_get` RPC** for each app's documented `APP_KEY` (`geri` / `pnimit` / `mishpacha`) using a sentinel username. `{ok:false, error:'invalid_app'}` from the server is critical (whitelist drift). Catches the class of bug that surfaced 2026-04-28 (Geri v10.46.0 sent `'shlav'`, server rejected, user saw `invalid_app ✗` despite HTTP 200). Cross-cutting critical findings open ONE issue in `auto-audit` itself, not N copies in N repos.
10. **Monitors Tier 2 auto-fix workflow health** — checks the auto-fix workflows in this repo (`auto-fix.yml`, `regenerate-misaligned-distractors.yml`) for failure streaks, slow execution, and stale PRs. **CRITICAL** if 3 consecutive auto-fix runs fail (auto-fix is degraded). **WARNING** for single failures, PRs stuck open >7 days, or slow execution (>20 min for auto-fix.yml, >90 min for distractor regen). This is Tier 1 monitoring Tier 2 — catching when the auto-fix system itself needs attention.

> **Note on trend tracking**: The Toranot proxy previously returned `trends: []` in `/api/self-audit` due to a deprioritized feature. Per the stance on Toranot UI/feature work, **auto-audit now owns trend tracking** via the call-count-delta probe. The state file in `health-reports/.last_call_count.json` serves as the historical baseline for delta computation.

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

### Tier 3 — `tier3-synthesis.yml` + `scripts/tier3_synthesis.py`

Weekly cross-repo synthesis. Runs every **Sunday 06:00 UTC** (= 09:00 IDT) and
opens or comments on a GitHub issue tagged `tier3-synthesis` in this repo.
Manually triggerable via Actions tab → `Tier 3 — Weekly synthesis` →
Run workflow.

What it surfaces (in this order):

1. **Action needed** — emergent signals worth attention this week. Sources:
   - Probes that fired in ≥3 reports during the window (recurring pattern).
   - Workflows that failed across ≥3 distinct SHAs (streak, not flap).
   - Spend trajectory projecting to break the $400 MTD hard threshold.
   - Open auto-audit issues older than 14 days (warn) / 30 days (crit).
   - `AUTO_AUDIT_DISPATCH_PAT` rotation deadline (warn at 60d, crit at 90d
     from install date `2026-04-29`).
2. **Narrative** _(optional, if `ANTHROPIC_API_KEY` set)_ — single Sonnet 4.6
   call (~$0.05) that turns the structured facts into 2-4 paragraphs of
   pattern-spotting. Gated by hard prompt constraints: no speculation, no
   fix proposals, max 250 words, "no emergent patterns" if true.
3. **Cross-cutting probe activity** — every probe that fired this week with
   firing count + last-firing time + sample message excerpts.
4. **Spend trajectory** — earliest vs latest snapshot in window, MTD delta,
   projected end-of-month linear extrapolation.
5. **Per-repo activity** — live SW, version bumps in window, workflow
   failures (sorted by failure count, capped at 5/repo, known flaps from
   `KNOWN_FLAP_WORKFLOWS` marked), recent commits to main, recent merged
   PRs.
6. **Open issues** — auto-audit's own queue (by label) + each watched repo's
   open `auto-audit`-labeled findings.

Idempotency: if there's already an open issue tagged `tier3-synthesis`, the
new synthesis is appended as a comment instead of opening a duplicate.

Local testing:

```bash
# Fully offline, no GH calls, no Claude:
python3 scripts/tier3_synthesis.py --dry-run --no-fetch-github --no-narrative

# Online with PAT but no Claude:
MONITOR_PAT=... python3 scripts/tier3_synthesis.py --dry-run --no-narrative

# Full pipeline against current state, no issue created:
MONITOR_PAT=... ANTHROPIC_API_KEY=... \
  python3 scripts/tier3_synthesis.py --dry-run
```

Cost guard: the Claude narrative is suppressed if the structured-facts payload
exceeds 20 KB (defensive against an unbounded growth bug in upstream probes).
At normal volumes the payload is ~2-5 KB.

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
