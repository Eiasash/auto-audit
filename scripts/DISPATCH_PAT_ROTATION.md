# AUTO_AUDIT_DISPATCH_PAT rotation runbook

## What this PAT does

Each watched PWA repo (`Geriatrics`, `InternalMedicine`, `FamilyMedicine`,
`ward-helper`) runs `.github/workflows/notify-auto-audit.yml` on push-to-main.
That workflow fires a `repository_dispatch` event to `Eiasash/auto-audit` so
the cross-repo Tier 1 health check runs within ~15s of any merge.

The dispatch needs a token with `Actions: write` on `Eiasash/auto-audit`.
That token lives in each watched repo as the `AUTO_AUDIT_DISPATCH_PAT` secret.

## When to rotate

- **On schedule:** every 90 days (or sooner) for a fine-grained PAT scoped only to
  `Eiasash/auto-audit`.
- **On suspicion:** any time the PAT may have leaked (e.g. accidentally logged).
- **On scope change:** if the watched-repo set changes.

## How to rotate

### 1. Generate the new PAT

`github.com/settings/personal-access-tokens/new` — fine-grained:

- Resource owner: **Eiasash**
- Repository access: **Only select repositories → Eiasash/auto-audit**
- Repository permissions:
  - **Contents: Read-only**
  - **Actions: Read and write** (required for `repository_dispatch`)
- Expiration: **90 days** (set a calendar reminder for next rotation)

### 2. Run the rotation script

```bash
# Admin PAT must have Secrets: write on each watched repo. Ephemeral —
# revoke immediately after rotation completes.
export GITHUB_PAT="<admin-pat-with-secrets-write>"
export NEW_DISPATCH_PAT="<the-new-fine-grained-pat-from-step-1>"

pip install pynacl  # one-time, libsodium for sealed-box encryption
python scripts/rotate_dispatch_pat.py
```

The script will:
1. Fetch the public key for each watched repo.
2. Encrypt `NEW_DISPATCH_PAT` against each repo's public key (sealed box).
3. PUT the encrypted value to that repo's `AUTO_AUDIT_DISPATCH_PAT` secret.
4. Verify the secret's `updated_at` timestamp moved.
5. Fire a no-op `repository_dispatch` (event_type `rotation-test`) to confirm
   the admin PAT has end-to-end working access.

### 3. Verify end-to-end

Push a trivial commit to one of the watched repos (e.g. a typo fix in README):

```bash
# in any watched repo
git commit --allow-empty -m "test: trigger auto-audit dispatch"
git push origin main
```

Within ~30s, check:
- The watched repo's `Notify auto-audit` workflow run is **success**.
- A new run of auto-audit's `health-check.yml` appears, triggered by
  `repository_dispatch` (not `schedule`).

If the auto-audit run was triggered, the new PAT is live across all repos.

### 4. Revoke the OLD PAT

`github.com/settings/tokens` — delete the previous `AUTO_AUDIT_DISPATCH_PAT`.

The admin PAT used in step 2 should also be revoked if it was a session token.

## Troubleshooting

**`Notify auto-audit` workflow fails on a watched repo:** the new PAT didn't land
in that repo's secrets. Re-run `rotate_dispatch_pat.py --repos owner/name` for
the affected repo only.

**`repository_dispatch` accepted (HTTP 204) but auto-audit doesn't run:** the new
PAT lacks `Actions: write` on auto-audit. Check the PAT's repository permissions.

**Sealed-box encryption fails:** ensure `pynacl` is installed (`pip install pynacl`).
The pure-Python implementation works without native libsodium.
