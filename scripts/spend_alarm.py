#!/usr/bin/env python3
"""
spend_alarm.py — daily Toranot proxy spend monitor.

Hits /api/self-audit, computes month-end projection from MTD usage,
opens (or comments on) a GitHub issue if projection exceeds threshold.

Pricing assumption: Sonnet 4.6 at $3/Mtok input, $15/Mtok output.
If the proxy's claudeModel changes, update PRICING below.

Env:
  GITHUB_TOKEN — for issue creation (provided by Actions)
  THRESHOLD_USD — default 250 (1.5x April 2026 baseline of ~$166)
  AUDIT_URL — default https://toranot.netlify.app/api/self-audit
  REPO — default Eiasash/auto-audit (where issues open)
"""

from __future__ import annotations
import json, os, sys, calendar, urllib.request
from datetime import datetime, timezone

PRICING = {
    "claude-sonnet-4-6":          {"input": 3.0,  "output": 15.0},
    "claude-opus-4-6":            {"input": 15.0, "output": 75.0},
    "claude-haiku-4-5-20251001":  {"input": 1.0,  "output": 5.0},
}
DEFAULT_PRICE = PRICING["claude-sonnet-4-6"]


def fetch(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def compute_spend(token_usage, model_hint):
    cm = token_usage.get("currentMonthTotals", {})
    inp = cm.get("input_tokens", 0)
    out = cm.get("output_tokens", 0)
    calls = cm.get("call_count", 0)
    price = PRICING.get(model_hint, DEFAULT_PRICE)
    mtd_usd = (inp / 1_000_000) * price["input"] + (out / 1_000_000) * price["output"]
    return mtd_usd, inp, out, calls


def project_month_end(mtd_usd, now):
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    day_of_month = now.day
    if day_of_month < 1:
        day_of_month = 1
    return mtd_usd * (days_in_month / day_of_month)


def find_or_comment_issue(repo, token, title_prefix, body, label):
    """Open a new issue, OR comment on an existing open issue with the same prefix."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # Search open issues with our label
    url = f"https://api.github.com/repos/{repo}/issues?state=open&labels={label}"
    issues = fetch(url, headers=headers)
    if issues:
        existing = issues[0]
        # Comment instead of opening duplicate
        comment_url = f"https://api.github.com/repos/{repo}/issues/{existing['number']}/comments"
        req = urllib.request.Request(
            comment_url, method="POST",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps({"body": body}).encode(),
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"commented on existing #{existing['number']} (status {r.status})")
        return existing["number"]
    # Open new
    url = f"https://api.github.com/repos/{repo}/issues"
    req = urllib.request.Request(
        url, method="POST",
        headers={**headers, "Content-Type": "application/json"},
        data=json.dumps({
            "title": f"{title_prefix} {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            "body": body,
            "labels": [label, "auto-audit"],
        }).encode(),
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        new = json.loads(r.read())
        print(f"opened new #{new['number']} (status {r.status})")
        return new["number"]


def main():
    threshold = float(os.environ.get("THRESHOLD_USD", "250"))
    audit_url = os.environ.get("AUDIT_URL", "https://toranot.netlify.app/api/self-audit")
    repo = os.environ.get("REPO", "Eiasash/auto-audit")
    gh_token = os.environ.get("GITHUB_TOKEN")
    if not gh_token:
        sys.exit("GITHUB_TOKEN required")

    print(f"Fetching {audit_url}")
    audit = fetch(audit_url)
    summary = audit.get("summary", {})
    token_usage = summary.get("tokenUsage", {})
    if not token_usage:
        sys.exit("self-audit response has no tokenUsage block")

    # Try to detect model from snapshot endpoint
    snap_url = audit_url.replace("/api/self-audit", "/.netlify/functions/skill-snapshot")
    try:
        snap = fetch(snap_url)
        model = snap.get("claudeModel", "claude-sonnet-4-6")
    except Exception:
        model = "claude-sonnet-4-6"

    mtd_usd, inp, out, calls = compute_spend(token_usage, model)
    now = datetime.now(timezone.utc)
    projected = project_month_end(mtd_usd, now)

    print(f"Month: {token_usage.get('currentMonth')}")
    print(f"Model assumed: {model}")
    print(f"Calls: {calls:,}")
    print(f"Input tokens: {inp:,}")
    print(f"Output tokens: {out:,}")
    print(f"MTD spend: ${mtd_usd:.2f}")
    print(f"Projected month-end: ${projected:.2f}")
    print(f"Threshold: ${threshold:.2f}")

    if projected <= threshold:
        print("✓ Within threshold")
        return

    print(f"✗ Projected ${projected:.2f} > threshold ${threshold:.2f}")
    body = (
        f"## Spend alarm — projected month-end overrun\n\n"
        f"- **Month**: {token_usage.get('currentMonth')}\n"
        f"- **As of**: {now.strftime('%Y-%m-%d %H:%M UTC')} (day {now.day})\n"
        f"- **MTD spend**: ${mtd_usd:.2f}\n"
        f"- **Projected month-end**: **${projected:.2f}**\n"
        f"- **Threshold**: ${threshold:.2f}\n"
        f"- **Pricing model**: `{model}` ($"
        f"{PRICING.get(model, DEFAULT_PRICE)['input']}/Mtok in, "
        f"${PRICING.get(model, DEFAULT_PRICE)['output']}/Mtok out)\n\n"
        f"### Usage\n"
        f"- Calls: {calls:,}\n"
        f"- Input tokens: {inp:,}\n"
        f"- Output tokens: {out:,}\n\n"
        f"### Investigate\n"
        f"1. Check call_count vs prior days — sudden spike = abuse or runaway loop\n"
        f"2. Look at proxy_rate_limits in Supabase — uid distribution\n"
        f"3. If abuse: rotate the proxy secret using `scripts/rotate_proxy_secret.py`\n"
        f"4. If runaway loop: check recent client deploys for accidental retry storms\n\n"
        f"_Auto-generated by `scripts/spend_alarm.py`_"
    )
    find_or_comment_issue(repo, gh_token, "[spend-alarm]", body, "spend-alarm")


if __name__ == "__main__":
    main()
