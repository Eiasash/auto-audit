# Wire-in instructions — Tier 2 `investigate` template

Live as of 2026-04-28. Two things needed for activation: a secret in `Eiasash/auto-audit`, and a smoke test.

## What it is

`investigate` is the fallback Tier 2 template for issues that don't fit one of the deterministic templates (`version_trinity`, `sibling_sync`, `regenerate_misaligned_distractors`). It runs Claude Code CLI in headless mode against the cloned target repo with hard guardrails, then opens a PR through the same gates as the deterministic templates.

```
Tier 1 probe finds something weird
  ↓ (issue filed with auto-fix-eligible label, no specific template)
Manual: Actions → Tier 2 — Auto-fix dispatcher → Run workflow → fix_kind=investigate
  ↓
Workflow fetches issue title + body + labels via GitHub API
  ↓
Installs Claude Code CLI in the runner (~30s)
  ↓
Builds prompt with: issue context + hard guardrails
  ↓
claude --print --max-turns 30 --model claude-sonnet-4-6 < prompt.md
  ↓
Tests run (vitest) — same gate as deterministic templates
  ↓
PR opened back to target repo. Or zero diff → exits clean.
```

## Hard guardrails (baked into the prompt)

1. **No shared-engine edits.** `shared/fsrs.js`, `harrison_chapters.json`, `drugs.json` are off-limits — those are sibling_sync's lane.
2. **No version bumps.** APP_VERSION, `package.json` version, sw.js CACHE strings — version_trinity owns those. If a version mismatch is the root cause, Claude is instructed to bail and write the diagnosis to `/tmp/investigate-failure.md` instead of fixing.
3. **Must pass vitest.** Up to three iterations to get tests green; otherwise bail.
4. **Prefer no diff over a wrong diff.** If the issue is unclear or the fix is risky, Claude bails and the runner exits cleanly with no PR.
5. **Auto-summary.** Claude writes a one-paragraph summary to `/tmp/investigate-summary.md`. The PR body uses it.

These are prompt-level, not enforcement-level — Claude could theoretically violate them. The downstream gates (vitest, manual PR review) catch the violations that matter.

## Setup — `ANTHROPIC_API_KEY` (one-time)

1. Generate an API key at <https://console.anthropic.com/settings/keys>.
2. Recommend a key dedicated to this purpose, scoped to a usage limit (e.g. $20/mo). The workflow's max-turns=30 caps single-run cost at ~$2, but a stuck loop in a future template could burn through quickly.
3. Add it to `Eiasash/auto-audit` Settings → Secrets and variables → Actions → New repository secret:
   - Name: `ANTHROPIC_API_KEY`
   - Value: the key from step 1
4. The pre-flight guard in `auto-fix.yml` checks the secret is present only when `fix_kind=investigate`. The deterministic templates keep running without it.

## Verify wire-in (no real issue needed)

1. Pick any open auto-audit issue — the issue body content doesn't matter for the smoke test, only that it exists. Or file a synthetic one:
   ```bash
   curl -X POST \
     -H "Authorization: token $YOUR_PAT" \
     -H "Accept: application/vnd.github+json" \
     https://api.github.com/repos/Eiasash/Geriatrics/issues \
     -d '{"title":"smoke test for investigate template","body":"This is a synthetic issue. Claude should bail without making changes.","labels":["auto-audit","smoke-test"]}'
   ```
2. Note the issue number returned.
3. Go to <https://github.com/Eiasash/auto-audit/actions/workflows/auto-fix.yml> → Run workflow:
   - target_repo: Geriatrics
   - issue_number: (the synthetic issue's number)
   - fix_kind: investigate
4. Watch the run. Expected outcome:
   - Pre-flight guard passes (ANTHROPIC_API_KEY present).
   - Issue context fetched.
   - Claude Code CLI installs.
   - Claude reads the prompt, recognizes there's nothing to fix, writes `/tmp/investigate-failure.md` with a "no actionable change" note, exits cleanly.
   - Diffstat: empty.
   - "Open PR" step: bails on zero-diff with "No changes — nothing to PR".
   - Run goes green.
5. Close the synthetic issue.

If that runs cleanly, the wire-in is verified end-to-end. The next real ambiguous issue can be dispatched with `fix_kind=investigate`.

## How to actually use it (for real issues)

1. Tier 1 cron files an auto-audit issue. The issue carries the `auto-fix-eligible` label but no specific template was matched (the probe didn't recognize the failure shape).
2. You eyeball it. If it fits a deterministic template (e.g. version drift), dispatch that. If it doesn't, dispatch `investigate`.
3. Wait 5–15 min. Either:
   - A PR appears at `Eiasash/<target>/pulls` with a Claude-written summary. Review carefully — Claude is fallible.
   - The run exits cleanly with no PR; the GH Actions log will contain Claude's `/tmp/investigate-failure.md` note explaining why no fix was attempted. Read it; decide manually.
4. Never merge an `investigate` PR without spot-checking the diff. Tier 2 never bypasses CI, but CI doesn't catch every category of regression (e.g. silent UX changes).

## Cost / spend notes

- Per dispatch: ~$0.50–2 in Sonnet 4.6 usage. Most of the cost is in the agent loop (file reads, edits, vitest runs).
- A stuck agent capped at `--max-turns 30` is bounded above ~$5.
- Failed runs (Claude bails) cost a few cents — just one prompt, no agent loop.
- No usage tracking in this workflow. If you want monthly visibility, add a step that logs `ANTHROPIC_USAGE` headers from the API responses to a file in `health-reports/`.

## Reverting / killing it

To disable `investigate` without removing the wiring:

1. Delete the `ANTHROPIC_API_KEY` secret in repo settings.
2. The pre-flight guard at the top of the job will fail with `ANTHROPIC_API_KEY required for fix_kind=investigate`.
3. Deterministic templates continue to work.

To remove entirely:

1. Drop the three steps marked `if: inputs.fix_kind == 'investigate'` from `.github/workflows/auto-fix.yml`.
2. Remove `investigate` from the `fix_kind` choice list.
3. Drop the `ANTHROPIC_API_KEY` env line and the conditional guard.

## Failure modes the wiring handles

- **Claude bails with `/tmp/investigate-failure.md`** → runner does `git reset --hard HEAD` and exits cleanly with no PR.
- **Claude makes edits but tests fail** → vitest step exits non-zero; PR never opens. The branch isn't pushed.
- **Claude edits a forbidden file** → not enforced at runtime; relies on PR review. (TODO: add a post-Claude diff scan that rejects edits to `shared/fsrs.js` etc.)
- **`ANTHROPIC_API_KEY` missing** → pre-flight guard fails the run with a clear error. No tokens consumed.
- **Network flake during install** → `npm install -g @anthropic-ai/claude-code` retries on failure (npm's default behavior). If it persists, the run fails clean.

## What this does NOT do

- Doesn't auto-dispatch from Tier 1. `investigate` is **manual-only**. New templates earn auto-dispatch trust through the deterministic ladder; a Claude-driven generic fixer doesn't get auto-dispatched, full stop.
- Doesn't enforce the guardrails at the file system level. They're prompt-level. PR review is the real gate.
- Doesn't post a comment on the originating issue. (TODO: add a step that comments the dispatched run URL on the issue, mirroring `regenerate-misaligned-distractors`.)
- Doesn't survive a force-push of `main` mid-run. Same caveat as every other template.
