# Wire-in instructions — auto-fix for distractor misalignment

Two files to add, one PAT scope to upgrade. Hand this entire document to Claude Code.

## Files to drop in

```
auto-audit/
├── scripts/
│   └── auto_fix/
│       └── regenerate_misaligned_distractors.sh    ← NEW (chmod +x)
└── .github/
    └── workflows/
        └── regenerate-misaligned-distractors.yml   ← NEW
```

The bash script and the workflow YAML are in the bundle alongside this README.

## What Claude Code should do

```bash
cd ~/repos/auto-audit

# 1. Place the auto-fix script
mkdir -p scripts/auto_fix
cp /path/to/regenerate_misaligned_distractors.sh scripts/auto_fix/
chmod +x scripts/auto_fix/regenerate_misaligned_distractors.sh

# 2. Place the workflow
cp /path/to/regenerate-misaligned-distractors.yml .github/workflows/

# 3. Sanity-check the bash script syntax
bash -n scripts/auto_fix/regenerate_misaligned_distractors.sh && echo "  syntax OK"

# 4. Commit + push
git add scripts/auto_fix/regenerate_misaligned_distractors.sh \
        .github/workflows/regenerate-misaligned-distractors.yml
git commit -m "auto-audit: wire regenerate_misaligned_distractors auto-fix

Tier 2 auto-fix for the alignment probe shipped earlier this session.
When probe_distractor_alignment fires CRITICAL, you can now dispatch
this workflow from the Actions tab — it clones Geriatrics, drops
misaligned entries, regenerates via Toranot proxy/Haiku, and opens a
PR with version-trinity bump. Never pushes to main; PR always
requires manual merge.

Workflow uses MONITOR_PAT (now needs contents:write +
pull-requests:write on Geriatrics; see PROBE_PAT_UPGRADE.md)."
git push origin main
```

## After pushing — PAT scope upgrade (one-time)

The existing `MONITOR_PAT` likely has read-only scopes. The auto-fix needs to push a branch and open a PR (write on `Eiasash/Geriatrics`), and the Tier 1 auto-dispatch needs to fire `workflow_dispatch` (Actions: write on `Eiasash/auto-audit`). Other repos stay read-only.

**Click-by-click:**

1. Go to <https://github.com/settings/tokens?type=beta>
2. Find your `MONITOR_PAT` token (or whatever you named it). Click it.
3. Under **"Repository access"** — confirm `Eiasash/Geriatrics` AND `Eiasash/auto-audit` are in the list. (They already are, since the existing probe reads from both.)
4. Under **"Repository permissions"**, find these and set them as shown:

   | Permission | Old value | New value |
   |---|---|---|
   | Contents | Read-only | **Read and write** |
   | Pull requests | (none) | **Read and write** |
   | Issues | Read-only | **Read and write** |
   | Actions | Read-only | **Read and write** |

   Issues:write is needed so the auto-fix can comment on / close the originating auto-audit issue. Actions:write is needed so Tier 1 can `workflow_dispatch` against this repo (closes the loop without manual click).

5. Click **"Update token"** at the bottom.

That's it. `MONITOR_PAT` keeps the same value — you don't have to update the secret in `auto-audit` Settings, the token name and value are unchanged. Only the scopes are upgraded.

## How to actually use it

Once shipped:

1. Auto-audit Tier 1 cron runs `probe_distractor_alignment` every 30 min.
2. If `Eiasash/Geriatrics` distractors are misaligned, the probe opens a CRITICAL issue on the affected repo (`Eiasash/Geriatrics`), labeled `auto-fix-eligible`.
3. **Tier 1 auto-dispatches the fix workflow immediately after filing the issue** (`regenerate_misaligned_distractors` is in the allowlist in `scripts/probe.py::AUTO_DISPATCH_TEMPLATES`). The issue gets a comment with a link to the dispatched run.
4. Wait 30–60 min. The PR appears at `Eiasash/Geriatrics/pulls`.
5. Review the PR. Spot-check 2-3 questions on the preview deploy. Merge if clean.

The PR will never merge itself. You always do the final review.

### Reverting to manual (if you want to)

If for any reason you want the old "click Run workflow yourself" flow back, set `AUTO_DISPATCH_DISABLED=1` in `.github/workflows/health-check.yml`'s `Run probe` step env block. No code change needed — the probe checks that env var on every run.

You can still dispatch manually anytime:

1. Go to <https://github.com/Eiasash/auto-audit/actions/workflows/regenerate-misaligned-distractors.yml>
2. Click **"Run workflow"** (top right of the workflow runs list).
3. Optionally paste the issue number into the input box (so the PR cross-links).
4. Click the green **"Run workflow"** button.

Manual dispatch is also the right path during the same probe cycle if auto-dispatch was skipped because a previous run was still in progress.

## Test it works (no real corruption needed)

After PAT upgrade + push, before any real corruption shows up:

1. Manually click **Run workflow** on the new workflow with no issue number.
2. The script will clone Geri, audit, find no misalignment, exit code 0 with the message "No misalignment found".
3. No PR opened, no commit made.

If that runs cleanly — wire-in is verified end-to-end. The next real corruption event will dispatch with the same path and produce a real PR.

## Cost / spend notes

- Each successful auto-fix run that actually does work costs ~$10 on the Toranot proxy (Haiku 4.5 × ~2700 calls).
- Failed/no-op runs cost nothing — the script bails before regen if there's nothing to fix.
- The probe itself costs zero — just two raw.githubusercontent fetches every 30 min.

## Failure modes the script handles

- **Generator dies mid-run** → script retries up to 3 times. Generator is resumable, so each retry picks up where the last left off.
- **Toranot proxy returns 5xx / DNS overflow / ENOTFOUND** → handled by the v10.45.0 generator hardening already in place.
- **PR already exists** → `git push` fails on duplicate branch name; the timestamp suffix prevents this in practice.
- **No misalignment found at audit time** → exits cleanly, closes the originating issue with "already-fixed" comment.

## What the script will NOT do

- Push to `main` directly. Ever. Always opens a PR.
- Force-push anything.
- Bump minor/major version. Patch bump only (10.45.0 → 10.45.1).
- Touch any other repo or any other Geri file.
