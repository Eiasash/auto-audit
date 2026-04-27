#!/usr/bin/env python3
"""
rotate_proxy_secret.py — cross-repo orchestrator for Toranot proxy secret.

Lives in Eiasash/auto-audit/scripts/.

WHY NO TORANOT CODE PATCH IS NEEDED
-----------------------------------
`netlify/functions/_utils.ts::checkAuth` already supports comma-separated
`API_SECRET` values via `matchesSecret`:

    function matchesSecret(reqSecret, envSecret) {
      if (!reqSecret || !envSecret) return false;
      return envSecret.split(",").some(s => s.trim() === reqSecret);
    }

So rotation is purely env-var work + client-repo updates.

Three phases, idempotent, resumable:

  OPEN  — append NEW to API_SECRET csv, deploy, probe both old+new = 200
  ROLL  — for each client repo: GET file -> replace literal -> commit ->
          poll deploy URL until bundle hash changes
  CLOSE — remove OLD from API_SECRET csv, deploy, probe old=401 new=200

USAGE
-----
    NETLIFY_PAT=xxx GITHUB_PAT=xxx \\
    python rotate_proxy_secret.py \\
        --old-secret 'shlav-a-mega-2026' \\
        --new-secret 'shlav-b-mega-2027' \\
        --toranot-site 85d12386-b960-4f65-bee8-80e210ecd683 \\
        --probe-url https://toranot.netlify.app/api/claude \\
        --client 'Eiasash/Geriatrics:main:index.html:https://eiasash.github.io/Geriatrics/' \\
        --client 'Eiasash/InternalMedicine:main:src/lib/proxy.js:https://eiasash.github.io/InternalMedicine/' \\
        --client 'Eiasash/FamilyMedicine:main:src/lib/proxy.js:https://eiasash.github.io/FamilyMedicine/' \\
        --phase all     # or open | roll | close

State at ./rotate_proxy_state.json — delete to start fresh.

NOTES
-----
* Secrets never logged.
* On any failure, script bails — no auto-rollback. State file pinpoints stop.
* ROLL does NOT bump version-trinity. The OPEN→CLOSE soak window covers
  SW-cached clients.
* If API_SECRET csv contains other values (multi-app), they're preserved.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

NETLIFY_API = "https://api.netlify.com/api/v1"
GITHUB_API = "https://api.github.com"
DEPLOY_TIMEOUT = 600
DEPLOY_POLL = 15
GHPAGES_TIMEOUT = 300
GHPAGES_POLL = 20
STATE_FILE = "./rotate_proxy_state.json"


def _request(method, url, *, headers=None, body=None, timeout=30):
    req = urllib.request.Request(
        url, method=method, headers=headers or {},
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"_error": e.read().decode()[:400]}


def netlify_api(method, path, *, pat, body=None, query=None):
    url = f"{NETLIFY_API}{path}"
    if query:
        url += "?" + "&".join(f"{k}={v}" for k, v in query.items())
    status, data = _request(method, url, headers={
        "Authorization": f"Bearer {pat}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }, body=body)
    if status >= 400:
        raise RuntimeError(f"Netlify {method} {path} -> {status}: {str(data.get('_error',''))[:200]}")
    return data


def github_api(method, path, *, pat, body=None, params=None):
    url = f"{GITHUB_API}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    status, data = _request(method, url, headers={
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }, body=body)
    if status >= 400:
        raise RuntimeError(f"GitHub {method} {path} -> {status}: {str(data.get('_error',''))[:200]}")
    return data


def get_account_slug(site_id, pat):
    return netlify_api("GET", f"/sites/{site_id}", pat=pat)["account_slug"]


def read_env(account, site_id, key, pat):
    try:
        ev = netlify_api("GET", f"/accounts/{account}/env/{key}",
                         pat=pat, query={"site_id": site_id})
    except RuntimeError as e:
        if "404" in str(e):
            return None
        raise
    for v in ev.get("values", []):
        if v.get("context") in {"all", "production"}:
            return v.get("value")
    return None


def set_env(account, site_id, key, value, pat):
    body = {
        "key": key,
        "values": [{"value": value, "context": "all"}],
        "scopes": ["builds", "functions", "runtime", "post_processing"],
        "is_secret": True,
    }
    try:
        netlify_api("PUT", f"/accounts/{account}/env/{key}",
                    pat=pat, body=body, query={"site_id": site_id})
    except RuntimeError as e:
        if "404" in str(e):
            netlify_api("POST", f"/accounts/{account}/env",
                        pat=pat, body=[body], query={"site_id": site_id})
        else:
            raise


def trigger_deploy(site_id, pat):
    d = netlify_api("POST", f"/sites/{site_id}/builds", pat=pat)
    return d.get("deploy_id") or d.get("id")


def wait_deploy(site_id, deploy_id, pat):
    start = time.time()
    last = None
    while time.time() - start < DEPLOY_TIMEOUT:
        d = netlify_api("GET", f"/sites/{site_id}/deploys/{deploy_id}", pat=pat)
        s = d.get("state")
        if s != last:
            print(f"      netlify deploy state: {s}", flush=True)
            last = s
        if s == "ready":
            return True
        if s in {"error", "rejected"}:
            return False
        time.sleep(DEPLOY_POLL)
    return False


def probe_secret(url, secret):
    payload = {
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
        "model": "claude-haiku-4-5-20251001",
    }
    status, _ = _request("POST", url, headers={
        "Content-Type": "application/json",
        "x-api-secret": secret,
    }, body=payload, timeout=30)
    return status


def parse_csv(value):
    if not value:
        return []
    return [s.strip() for s in value.split(",") if s.strip()]


def gh_get_file(repo, branch, path, pat):
    data = github_api("GET", f"/repos/{repo}/contents/{path}",
                      pat=pat, params={"ref": branch})
    return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]


def gh_put_file(repo, branch, path, content, sha, message, pat):
    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "sha": sha,
        "branch": branch,
    }
    return github_api("PUT", f"/repos/{repo}/contents/{path}", pat=pat, body=body)


def fetch_live_bundle_hash(deploy_url):
    try:
        req = urllib.request.Request(deploy_url, headers={"Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception:
        return None
    m = re.search(r'-([a-f0-9]{8,16})\.(?:js|css)', html)
    return m.group(1) if m else None


def wait_for_client_deploy(deploy_url, baseline):
    start = time.time()
    while time.time() - start < GHPAGES_TIMEOUT:
        h = fetch_live_bundle_hash(deploy_url)
        if h and h != baseline:
            print(f"      bundle hash: {baseline} -> {h}")
            return True
        time.sleep(GHPAGES_POLL)
    return False


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"phases_done": [], "rolled_clients": []}
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


@dataclass
class ClientCfg:
    repo: str
    branch: str
    path: str
    deploy_url: str

    @classmethod
    def parse(cls, spec):
        parts = spec.split(":", 3)
        if len(parts) != 4:
            raise ValueError(f"--client format: repo:branch:path:deploy_url, got {spec!r}")
        return cls(*parts)


def phase_open(cfg, state):
    print("\n[OPEN] add NEW to API_SECRET csv")
    account = get_account_slug(cfg["site_id"], cfg["netlify_pat"])
    cur_list = parse_csv(read_env(account, cfg["site_id"], "API_SECRET", cfg["netlify_pat"]))
    print(f"  current API_SECRET has {len(cur_list)} value(s)")

    if cfg["old_secret"] not in cur_list:
        raise RuntimeError(
            "old-secret not present in current API_SECRET csv. "
            "Either typo or someone already rotated. NOT modifying."
        )
    if cfg["new_secret"] in cur_list:
        print("  new-secret already present, skipping env update")
    else:
        new_list = cur_list + [cfg["new_secret"]]
        set_env(account, cfg["site_id"], "API_SECRET", ",".join(new_list), cfg["netlify_pat"])
        print(f"  API_SECRET now has {len(new_list)} value(s)")

    print("  triggering deploy")
    deploy_id = trigger_deploy(cfg["site_id"], cfg["netlify_pat"])
    if not wait_deploy(cfg["site_id"], deploy_id, cfg["netlify_pat"]):
        raise RuntimeError("Toranot deploy failed in OPEN")

    print("  probing OLD (expect 200)")
    s_old = probe_secret(cfg["probe_url"], cfg["old_secret"])
    print(f"    -> {s_old}")
    print("  probing NEW (expect 200)")
    s_new = probe_secret(cfg["probe_url"], cfg["new_secret"])
    print(f"    -> {s_new}")

    if not (200 <= s_old < 300 and 200 <= s_new < 300):
        raise RuntimeError(f"OPEN probe failed: old={s_old} new={s_new}")

    state["phases_done"].append("open")
    save_state(state)
    print("  ✓ OPEN done")


def phase_roll(cfg, state):
    print("\n[ROLL] update client repos")
    if "open" not in state["phases_done"]:
        raise RuntimeError("Cannot ROLL before OPEN")

    for spec in cfg["clients"]:
        cli = ClientCfg.parse(spec)
        if cli.repo in state["rolled_clients"]:
            print(f"  skip {cli.repo} (already rolled)")
            continue

        print(f"\n  {cli.repo}:{cli.branch}:{cli.path}")
        baseline = fetch_live_bundle_hash(cli.deploy_url)
        print(f"    baseline hash: {baseline}")

        content, sha = gh_get_file(cli.repo, cli.branch, cli.path, cfg["github_pat"])
        if cfg["old_secret"] not in content:
            raise RuntimeError(
                f"Old secret literal not found in {cli.repo}:{cli.path}. "
                "Wrong path or different sourcing. Bailing."
            )

        n = content.count(cfg["old_secret"])
        new_content = content.replace(cfg["old_secret"], cfg["new_secret"])
        print(f"    replacing {n} occurrence(s)")

        gh_put_file(cli.repo, cli.branch, cli.path, new_content, sha,
                    "chore: rotate proxy secret", cfg["github_pat"])
        print("    committed")

        print(f"    waiting for {cli.deploy_url} redeploy…")
        if not wait_for_client_deploy(cli.deploy_url, baseline):
            raise RuntimeError(
                f"{cli.repo} bundle hash didn't change in {GHPAGES_TIMEOUT}s. "
                "Check Actions and re-run --phase roll."
            )

        state["rolled_clients"].append(cli.repo)
        save_state(state)
        print(f"    ✓ {cli.repo} rolled")

    state["phases_done"].append("roll")
    save_state(state)
    print("\n  ✓ ROLL done")


def phase_close(cfg, state):
    print("\n[CLOSE] retire OLD from API_SECRET csv")
    if "roll" not in state["phases_done"]:
        raise RuntimeError("Cannot CLOSE before ROLL")

    print("  ⚠ Soak: SW-cached clients may still send OLD for ~24h. "
          "Continue? [y/N] ", end="", flush=True)
    if cfg["non_interactive"]:
        print("y (non-interactive)")
    else:
        if input().strip().lower() != "y":
            print("  aborted"); return

    account = get_account_slug(cfg["site_id"], cfg["netlify_pat"])
    cur_list = parse_csv(read_env(account, cfg["site_id"], "API_SECRET", cfg["netlify_pat"]))
    new_list = [s for s in cur_list if s != cfg["old_secret"]]

    if cfg["new_secret"] not in new_list:
        raise RuntimeError("new-secret not in current csv list. Refusing to close.")

    if len(new_list) == len(cur_list):
        print("  old-secret already removed, skipping env update")
    else:
        set_env(account, cfg["site_id"], "API_SECRET", ",".join(new_list), cfg["netlify_pat"])
        print(f"  API_SECRET now has {len(new_list)} value(s)")

    print("  triggering deploy")
    deploy_id = trigger_deploy(cfg["site_id"], cfg["netlify_pat"])
    if not wait_deploy(cfg["site_id"], deploy_id, cfg["netlify_pat"]):
        raise RuntimeError("Toranot deploy failed in CLOSE")

    print("  probing OLD (expect 401)")
    s_old = probe_secret(cfg["probe_url"], cfg["old_secret"])
    print(f"    -> {s_old}")
    print("  probing NEW (expect 200)")
    s_new = probe_secret(cfg["probe_url"], cfg["new_secret"])
    print(f"    -> {s_new}")

    if not (s_old == 401 and 200 <= s_new < 300):
        raise RuntimeError(f"CLOSE probe wrong: old={s_old} (want 401), new={s_new} (want 200)")

    state["phases_done"].append("close")
    save_state(state)
    print("  ✓ CLOSE done")


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                description=__doc__)
    p.add_argument("--old-secret", required=True)
    p.add_argument("--new-secret", required=True)
    p.add_argument("--toranot-site", required=True)
    p.add_argument("--probe-url", required=True)
    p.add_argument("--client", action="append", default=[])
    p.add_argument("--phase", choices=["open", "roll", "close", "all"], default="all")
    p.add_argument("--yes", action="store_true")
    args = p.parse_args()

    netlify_pat = os.environ.get("NETLIFY_PAT")
    github_pat = os.environ.get("GITHUB_PAT")
    if not netlify_pat:
        sys.exit("NETLIFY_PAT required")
    if args.phase in {"roll", "all"} and not github_pat:
        sys.exit("GITHUB_PAT required for ROLL")
    if args.phase in {"roll", "all"} and not args.client:
        sys.exit("--client required for ROLL")
    if args.old_secret == args.new_secret:
        sys.exit("--old-secret and --new-secret must differ")

    cfg = {
        "old_secret": args.old_secret,
        "new_secret": args.new_secret,
        "site_id": args.toranot_site,
        "probe_url": args.probe_url,
        "clients": args.client,
        "netlify_pat": netlify_pat,
        "github_pat": github_pat,
        "non_interactive": args.yes,
    }

    state = load_state()
    print(f"State: phases_done={state['phases_done']} rolled={state['rolled_clients']}")

    try:
        if args.phase in {"open", "all"} and "open" not in state["phases_done"]:
            phase_open(cfg, state)
        if args.phase in {"roll", "all"} and "roll" not in state["phases_done"]:
            phase_roll(cfg, state)
        if args.phase in {"close", "all"} and "close" not in state["phases_done"]:
            phase_close(cfg, state)
    except RuntimeError as e:
        print(f"\n✗ {e}", file=sys.stderr)
        print(f"  state preserved at {STATE_FILE}", file=sys.stderr)
        sys.exit(1)

    if all(p in state["phases_done"] for p in ["open", "roll", "close"]):
        print("\n✓✓✓ Rotation complete. Delete state file.")
    else:
        print(f"\nDone. Phases: {state['phases_done']}")


if __name__ == "__main__":
    main()
