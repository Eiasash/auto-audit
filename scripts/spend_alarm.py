#!/usr/bin/env python3
"""
spend_alarm.py — daily Anthropic spend trend monitor for the Toranot proxy.

Fetches /api/self-audit, computes MTD USD spend from token counts,
checks against (a) absolute threshold, (b) daily delta from yesterday's
snapshot, (c) week-over-week multiplier. Opens GitHub issue if breached.

Pricing (Sonnet 4.6 blended):
  input  $3 / 1M tokens
  output $15 / 1M tokens

Env: TORANOT_API_SECRET, MONITOR_PAT
Outputs: health-reports/spend-YYYY-MM-DD.json — committed by workflow
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import urllib.error
import urllib.request

PRICE_INPUT_PER_MTOK = 3.0
PRICE_OUTPUT_PER_MTOK = 15.0

MTD_HARD_USD = 400.0
DAILY_DELTA_USD = 40.0
WOW_MULT = 2.5

REPO = "Eiasash/auto-audit"


def fetch_audit():
    secret = os.environ["TORANOT_API_SECRET"]
    req = urllib.request.Request(
        "https://toranot.netlify.app/api/self-audit",
        headers={"x-api-secret": secret},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def usd_from_tokens(in_tok, out_tok):
    return (in_tok / 1_000_000) * PRICE_INPUT_PER_MTOK + \
           (out_tok / 1_000_000) * PRICE_OUTPUT_PER_MTOK


def open_issue(title, body):
    pat = os.environ["MONITOR_PAT"]
    payload = {"title": title, "body": body, "labels": ["spend-alarm"]}
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/issues",
        method="POST",
        headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload).encode(),
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["html_url"]


def load_snapshot(date):
    p = f"health-reports/spend-{date.isoformat()}.json"
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def save_snapshot(snap):
    os.makedirs("health-reports", exist_ok=True)
    with open(f"health-reports/spend-{snap['date']}.json", "w") as f:
        json.dump(snap, f, indent=2)


def main():
    today = datetime.date.today()
    audit = fetch_audit()
    tu = audit.get("summary", {}).get("tokenUsage", {})
    mtd = tu.get("currentMonthTotals", {})

    in_tok = mtd.get("input_tokens", 0)
    out_tok = mtd.get("output_tokens", 0)
    calls = mtd.get("call_count", 0)
    mtd_usd = round(usd_from_tokens(in_tok, out_tok), 2)

    snap = {
        "date": today.isoformat(),
        "month": tu.get("currentMonth", today.strftime("%Y-%m")),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "call_count": calls,
        "mtd_usd": mtd_usd,
    }
    save_snapshot(snap)

    findings = []

    if mtd_usd > MTD_HARD_USD:
        findings.append(f"**MTD over hard threshold:** ${mtd_usd:.2f} > ${MTD_HARD_USD:.2f}")

    y = load_snapshot(today - datetime.timedelta(days=1))
    if y and y["month"] == snap["month"]:
        delta = mtd_usd - y["mtd_usd"]
        if delta > DAILY_DELTA_USD:
            findings.append(
                f"**Daily spike:** +${delta:.2f} since yesterday "
                f"(threshold ${DAILY_DELTA_USD:.2f})"
            )

    w = load_snapshot(today - datetime.timedelta(days=7))
    if w and w["month"] == snap["month"] and w["mtd_usd"] > 5:
        ratio = mtd_usd / w["mtd_usd"]
        if ratio > WOW_MULT:
            findings.append(
                f"**Week-over-week:** {ratio:.1f}× "
                f"(${w['mtd_usd']:.2f} → ${mtd_usd:.2f}, threshold {WOW_MULT}×)"
            )

    if findings:
        body = "\n".join([
            f"# Spend alarm — {today}",
            "",
            f"- MTD: **${mtd_usd:.2f}** ({calls:,} calls)",
            f"- Tokens: in={in_tok:,}  out={out_tok:,}",
            "",
            "## Findings",
            *[f"- {f}" for f in findings],
            "",
            "## Investigate",
            "- [ ] Check `proxy_rate_limits` for outlier UIDs",
            "- [ ] Check Anthropic console for abuse patterns",
            "- [ ] If confirmed abuse, rotate via `scripts/rotate_proxy_secret.py`",
        ])
        url = open_issue(
            f"[spend-alarm] MTD ${mtd_usd:.2f} — {len(findings)} threshold breach",
            body,
        )
        print(f"ALARM: {url}")
        sys.exit(1)

    print(f"OK: MTD ${mtd_usd:.2f}, {calls:,} calls — within thresholds")


if __name__ == "__main__":
    main()
