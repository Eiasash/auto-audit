# Proxy secret rotation — runbook

For the value clients send to `https://toranot.netlify.app/api/claude` in the
`x-api-secret` header. Currently `shlav-a-mega-2026`. Rotation closes the
secret-rotation tickets (Geri #79, Pnimit #38, Toranot #75).

## Why no Toranot code change is needed

`netlify/functions/_utils.ts::checkAuth` already accepts a comma-separated
list in `API_SECRET` via `matchesSecret`. Rotation = env-var work + client
repo updates. Nothing to patch in Toranot.

## Verified runtime locations of the secret

| Repo | File | Notes |
|---|---|---|
| `Eiasash/Geriatrics` | `shlav-a-mega.html` | Single-file HTML; `index.html` only redirects |
| `Eiasash/InternalMedicine` | `src/core/constants.js` | exports `AI_SECRET` |
| `Eiasash/FamilyMedicine` | `src/core/constants.js` | exports `AI_SECRET` |
| `Eiasash/ward-helper` | `src/agent/client.ts` | exports `PROXY_SECRET` |

Plus ~15 non-runtime references (scripts, docs, SKILL.md). Stale ones
don't break anything but rotate them for hygiene with `gh search code`.

## Procedure

### 0. Generate new secret

```bash
NEW_SECRET="shlav-$(openssl rand -hex 12)-2026"
```

### 1. Fetch PATs (the OLD secret is still live — this works)

```bash
export NETLIFY_PAT=$(curl -s -H "x-api-secret: shlav-a-mega-2026" \
  https://toranot.netlify.app/.netlify/functions/netlify-pat | jq -r .pat)
export GITHUB_PAT=$(curl -s -H "x-api-secret: shlav-a-mega-2026" \
  https://toranot.netlify.app/api/github-pat | jq -r .pat)
```

### 2. Run rotation

```bash
python scripts/rotate_proxy_secret.py \
  --old-secret 'shlav-a-mega-2026' \
  --new-secret "$NEW_SECRET" \
  --toranot-site 85d12386-b960-4f65-bee8-80e210ecd683 \
  --probe-url https://toranot.netlify.app/api/claude \
  --client 'Eiasash/Geriatrics:main:shlav-a-mega.html:https://eiasash.github.io/Geriatrics/' \
  --client 'Eiasash/InternalMedicine:main:src/core/constants.js:https://eiasash.github.io/InternalMedicine/' \
  --client 'Eiasash/FamilyMedicine:main:src/core/constants.js:https://eiasash.github.io/FamilyMedicine/' \
  --client 'Eiasash/ward-helper:main:src/agent/client.ts:https://eiasash.github.io/ward-helper/' \
  --phase all
```

### 3. With soak window (recommended)

```bash
... --phase open    # Day 0
... --phase roll    # Day 0 +5min
# Wait 24h for SW caches to expire on user devices
... --phase close --yes   # Day 1
```

State persists in `./rotate_proxy_state.json`. Delete after final ✓✓✓.

### 4. Sweep non-runtime references

```bash
gh search code 'shlav-a-mega-2026' --owner Eiasash --json repository,path
# Then sed-batch each repo, or one-off PRs.
```

### 5. Close tickets

```bash
gh issue close 79 --repo Eiasash/Geriatrics --comment "Rotated $(date +%Y-%m-%d)"
gh issue close 38 --repo Eiasash/InternalMedicine --comment "Rotated $(date +%Y-%m-%d)"
gh issue close 75 --repo Eiasash/Toranot --comment "Rotated $(date +%Y-%m-%d)"
```

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| OPEN: "old-secret not present in csv" | Already rotated, or typo | Check Netlify env page |
| OPEN: both probes 401 | API_SECRET write failed silently | Inspect Netlify env page |
| ROLL: "old secret not found in repo:path" | Wrong path | Update `--client` arg, re-run |
| ROLL: bundle hash never changes | Client GH Actions failing | Fix CI, re-run `--phase roll` |
| CLOSE: old=200 (want 401) | Promotion didn't take | Inspect Netlify env page |

## Cadence

The proxy secret is in client JS — anyone with DevTools can extract it.
This isn't confidential; rotation is hygiene to make casual abuse harder.
**Don't rotate impulsively** — schedule for a calm Sunday.

Auto-reminder (5-line addition to auto-audit):

```yaml
# .github/workflows/rotation-reminder.yml
on: { schedule: [{ cron: "0 9 1 */6 *" }] }
jobs:
  remind:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.create({
              owner: 'Eiasash', repo: 'auto-audit',
              title: '[reminder] Proxy secret rotation due',
              body: 'Run scripts/rotate_proxy_secret.py. See PROXY_SECRET_ROTATION.md.',
              labels: ['rotation-reminder']
            })
```
