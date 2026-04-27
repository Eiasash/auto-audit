# MONITOR_PAT scope upgrade

The `MONITOR_PAT` secret in this repo's Actions secrets needs specific scopes
to allow the auto-fix workflows to push branches and open PRs. Whenever the
token rotates (fine-grained PATs expire after 90 days max), the new token
needs the same scopes set.

## Required scopes

Repository access: `Eiasash/Geriatrics`, `Eiasash/InternalMedicine`,
`Eiasash/FamilyMedicine`, `Eiasash/Toranot`, `Eiasash/ward-helper`,
`Eiasash/watch-advisor2`, `Eiasash/auto-audit`.

Repository permissions:

| Permission | Scope | Why |
|---|---|---|
| Contents | Read and write | Push auto-fix branches |
| Pull requests | Read and write | Open auto-fix PRs |
| Issues | Read and write | Open/comment/close auto-audit issues |
| Actions | Read and write | Re-trigger repaired workflows |
| Metadata | Read-only | (auto-included) |

## Click-by-click

1. <https://github.com/settings/tokens?type=beta>
2. **Generate new token** (or click an existing one to edit)
3. **Token name:** `auto-audit MONITOR_PAT`
4. **Expiration:** 90 days (max for fine-grained)
5. **Repository access:** Select the 7 repos listed above
6. **Repository permissions:** Set the 5 permissions above
7. **Generate token** → copy the value (`github_pat_...`)
8. <https://github.com/Eiasash/auto-audit/settings/secrets/actions>
9. Find `MONITOR_PAT` → **Update** → paste new value → **Update secret**

## Verifying

Trigger a manual run of `regenerate-misaligned-distractors.yml` with no
issue number. Expected output: clones Geri, audits, exits 0 with "No
misalignment found". If the run fails on a `git push` step with 403, the
PAT either isn't set or doesn't have Contents:write on Geriatrics.

## Calendar reminder

Set a calendar reminder for 80 days from token creation. The token expires
at day 90; rotating with 10 days of buffer means auto-audit never goes
silent due to expiry mid-incident.
