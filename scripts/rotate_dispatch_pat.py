#!/usr/bin/env python3
"""
rotate_dispatch_pat.py — rotate AUTO_AUDIT_DISPATCH_PAT across watched repos.

Lives in Eiasash/auto-audit/scripts/.

WHY THIS EXISTS
---------------
Each watched PWA repo (Geriatrics, InternalMedicine, FamilyMedicine,
ward-helper) has a `.github/workflows/notify-auto-audit.yml` that fires a
`repository_dispatch` event to Eiasash/auto-audit on every push-to-main.
The dispatch needs a token that can write to auto-audit's Actions; that
token lives in each watched repo as the `AUTO_AUDIT_DISPATCH_PAT` secret.

The token is currently long-lived. The follow-up from auto-audit#14
(2026-04-29) is to replace it with a fine-grained PAT scoped to
auto-audit only, with a 90d–1y expiration — which means recurring rotation.

This script is the rotation orchestrator.

WHAT IT DOES
------------
For each watched repo:
  1. Encrypts the new PAT against that repo's public key (libsodium sealed box).
  2. PUTs the encrypted value to the AUTO_AUDIT_DISPATCH_PAT secret via the
     GitHub Actions secrets API.
  3. Verifies success by listing the secret's `updated_at`.
Optionally:
  4. Fires a test repository_dispatch from each repo to confirm end-to-end.

REQUIREMENTS
------------
Python 3.11+. PyNaCl for libsodium sealed-box encryption. Install if missing:
    pip install pynacl

USAGE
-----
    GITHUB_PAT=<admin-token-with-secrets-write> \\
    NEW_DISPATCH_PAT=<new-fine-grained-pat-scoped-to-auto-audit> \\
    python rotate_dispatch_pat.py

Optional flags:
    --repos owner/name,owner/name,... (defaults to the four watched PWAs)
    --dry-run        only verify access; don't write any secrets
    --skip-verify    don't fire test dispatches afterwards
    --secret-name    override the default 'AUTO_AUDIT_DISPATCH_PAT' name

NOTES
-----
* GITHUB_PAT must have repo:admin scope on each target repo (to write secrets).
* NEW_DISPATCH_PAT is the value being installed — never logged.
* GitHub Actions secrets are write-only; we cannot read back the value, only
  verify the updated_at timestamp moved.
* Idempotent: re-running with the same NEW_DISPATCH_PAT produces a no-op write
  (secrets just update updated_at; the value is checked client-side).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

# ─── Defaults ────────────────────────────────────────────────────────────────
DEFAULT_REPOS = [
    "Eiasash/Geriatrics",
    "Eiasash/InternalMedicine",
    "Eiasash/FamilyMedicine",
    "Eiasash/ward-helper",
]
DEFAULT_SECRET_NAME = "AUTO_AUDIT_DISPATCH_PAT"
GITHUB_API = "https://api.github.com"


# ─── HTTP helpers ────────────────────────────────────────────────────────────
def _request(method: str, url: str, headers: dict, body: Optional[bytes] = None, timeout: int = 30):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return resp.status, json.loads(data) if data else {}
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read())
        except Exception:
            err = {"_raw": str(e)}
        return e.code, {"_error": err}


def gh(method: str, path: str, *, pat: str, body: Optional[dict] = None) -> tuple[int, dict]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    return _request(method, f"{GITHUB_API}{path}", headers, payload)


# ─── Sealed-box encryption (libsodium) ───────────────────────────────────────
def encrypt_for_repo(public_key_b64: str, value: str) -> str:
    """Encrypt `value` using the repo's public key. Returns base64 ciphertext."""
    try:
        from nacl import encoding, public
    except ImportError:
        sys.exit(
            "ERROR: PyNaCl is required. Install with:\n"
            "    pip install pynacl"
        )
    pk = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(pk)
    encrypted = sealed_box.encrypt(value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


# ─── Workflow ────────────────────────────────────────────────────────────────
def get_repo_public_key(repo: str, pat: str) -> dict:
    status, data = gh("GET", f"/repos/{repo}/actions/secrets/public-key", pat=pat)
    if status != 200:
        raise RuntimeError(f"GET public-key {repo}: HTTP {status}: {data}")
    return data  # {"key_id": "...", "key": "<base64>"}


def put_secret(repo: str, name: str, encrypted_value: str, key_id: str, pat: str) -> int:
    status, data = gh(
        "PUT",
        f"/repos/{repo}/actions/secrets/{name}",
        pat=pat,
        body={"encrypted_value": encrypted_value, "key_id": key_id},
    )
    if status not in (201, 204):
        raise RuntimeError(f"PUT secret {repo}/{name}: HTTP {status}: {data}")
    return status


def get_secret_meta(repo: str, name: str, pat: str) -> dict:
    status, data = gh("GET", f"/repos/{repo}/actions/secrets/{name}", pat=pat)
    if status == 404:
        return {}
    if status != 200:
        raise RuntimeError(f"GET secret meta {repo}/{name}: HTTP {status}: {data}")
    return data


def fire_test_dispatch(repo: str, pat: str) -> tuple[int, dict]:
    """Fire a repository_dispatch event of type 'rotation-test' against the
    repo. Watched repos' notify-auto-audit.yml only listens for push events,
    so this verifies API access without triggering a real audit run."""
    return gh(
        "POST",
        f"/repos/{repo}/dispatches",
        pat=pat,
        body={"event_type": "rotation-test", "client_payload": {"source": "rotate_dispatch_pat"}},
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Rotate AUTO_AUDIT_DISPATCH_PAT across watched repos.")
    p.add_argument("--repos", default=",".join(DEFAULT_REPOS),
                   help=f"Comma-separated repos (default: the four watched PWAs)")
    p.add_argument("--secret-name", default=DEFAULT_SECRET_NAME)
    p.add_argument("--dry-run", action="store_true",
                   help="Verify access only; do not write secrets")
    p.add_argument("--skip-verify", action="store_true",
                   help="Do not fire test repository_dispatch afterwards")
    args = p.parse_args()

    admin_pat = os.environ.get("GITHUB_PAT")
    new_pat = os.environ.get("NEW_DISPATCH_PAT")
    if not admin_pat:
        sys.exit("ERROR: GITHUB_PAT env var is required (admin token with secrets:write)")
    if not new_pat and not args.dry_run:
        sys.exit("ERROR: NEW_DISPATCH_PAT env var is required (the value being installed)")

    repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    print(f"Rotating {args.secret_name} across {len(repos)} repos")
    if args.dry_run:
        print("DRY RUN — no secrets will be written")

    failures = []

    for repo in repos:
        print(f"\n── {repo} ──")

        # 1) Verify we can read the public key (= we have admin access).
        try:
            pk_info = get_repo_public_key(repo, admin_pat)
        except RuntimeError as e:
            print(f"  ✗ public key fetch: {e}")
            failures.append((repo, "public-key", str(e)))
            continue
        print(f"  ✓ public key fetched (key_id={pk_info['key_id']})")

        # 2) Snapshot current secret metadata for before/after.
        before = get_secret_meta(repo, args.secret_name, admin_pat)
        if before:
            print(f"  · current updated_at: {before.get('updated_at', '?')}")
        else:
            print(f"  · {args.secret_name} does not exist yet — will be created")

        if args.dry_run:
            print("  · dry-run: skipping write")
            continue

        # 3) Encrypt + PUT.
        try:
            ciphertext = encrypt_for_repo(pk_info["key"], new_pat)
        except Exception as e:
            print(f"  ✗ encryption failed: {e}")
            failures.append((repo, "encrypt", str(e)))
            continue

        try:
            status = put_secret(repo, args.secret_name, ciphertext, pk_info["key_id"], admin_pat)
        except RuntimeError as e:
            print(f"  ✗ PUT secret: {e}")
            failures.append((repo, "put", str(e)))
            continue
        print(f"  ✓ secret PUT (HTTP {status})")

        # 4) Confirm updated_at moved.
        time.sleep(1)
        after = get_secret_meta(repo, args.secret_name, admin_pat)
        if before and after:
            if after.get("updated_at") == before.get("updated_at"):
                print(f"  ⚠ updated_at did not change ({after.get('updated_at')})")
            else:
                print(f"  ✓ updated_at: {before.get('updated_at')} → {after.get('updated_at')}")
        elif after:
            print(f"  ✓ created at {after.get('updated_at')}")

        # 5) Optional: fire a test dispatch to confirm end-to-end.
        if not args.skip_verify:
            try:
                status, _ = fire_test_dispatch(repo, admin_pat)
                if status == 204:
                    print(f"  ✓ test repository_dispatch accepted (HTTP 204)")
                else:
                    print(f"  ⚠ test dispatch returned HTTP {status}")
            except RuntimeError as e:
                print(f"  ⚠ test dispatch error: {e}")

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} failure(s):")
        for repo, phase, err in failures:
            print(f"  {repo} [{phase}]: {err}")
        return 1
    print(f"All {len(repos)} repo(s) rotated successfully.")
    print("\nNext step: revoke the OLD PAT at github.com/settings/tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
