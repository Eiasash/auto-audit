#!/usr/bin/env python3
"""
tier3_synthesis.py — weekly cross-repo synthesis.

Aggregates the past N days of Tier 1 health-reports + spend snapshots, fetches
recent GitHub activity across the six watched repos + auto-audit's own issue
queue, detects emergent patterns (repeat probe firings, workflow failure
streaks, aging open issues, spend trajectory, secret-rotation deadlines), and
emits a single markdown synthesis. Optionally appends a narrative paragraph
produced by Claude (Sonnet 4.6, single call, capped tokens).

Output:
  - Writes  health-reports/synthesis-YYYY-MM-DD.md  for the audit trail.
  - Opens or comments on a GitHub issue tagged 'tier3-synthesis' in
    Eiasash/auto-audit.

Env required for full operation:
  MONITOR_PAT         — for GitHub API (commits, PRs, issues)
  ANTHROPIC_API_KEY   — optional; gates the narrative paragraph

Designed to degrade gracefully:
  no MONITOR_PAT       → skip GH fetches, emit local-only report
  no ANTHROPIC_API_KEY → skip narrative
  --dry-run            → no issue created, report still written + printed
  --no-narrative       → suppress Claude call even if key present

Cost guard: Claude call is bounded to ~5 KB input / 800 tokens output ≈ $0.05.
The script aborts the narrative path if the structured facts payload exceeds
20 KB (defensive against an unbounded growth bug in upstream probes).
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Optional

# ─── Constants ───────────────────────────────────────────────────────────────
REPO = "Eiasash/auto-audit"
WATCHED_REPOS = [
    "Eiasash/Geriatrics",
    "Eiasash/InternalMedicine",
    "Eiasash/FamilyMedicine",
    "Eiasash/ward-helper",
    "Eiasash/Toranot",
    "Eiasash/watch-advisor2",
]
GITHUB_API = "https://api.github.com"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
NARRATIVE_MODEL = "claude-sonnet-4-6"
NARRATIVE_MAX_TOKENS = 800
NARRATIVE_PAYLOAD_CAP_BYTES = 20_000

# Probe firing escalation: if a probe shows up in >= this many reports during
# the window, surface it as a recurring signal rather than a transient.
RECURRING_PROBE_THRESHOLD = 3

# Workflow failure escalation: if a workflow has >= this many failures across
# distinct SHAs during the window, surface it.
RECURRING_FAILURE_THRESHOLD = 3

# Workflow names to exclude from failure aggregation. These are auto-generated
# dependency-update runs (one workflow run per dependency per branch) which
# create noise in the per-repo failure tally without representing signal.
WORKFLOW_NOISE_PATTERNS = (
    "npm_and_yarn in",      # Dependabot npm/yarn updates
    "github_actions in",    # Dependabot GHA updates
    "pip in",               # Dependabot pip updates
    "Dependabot ",          # Catch-all Dependabot prefix
)


def is_noise_workflow(name: str) -> bool:
    return any(name.startswith(p) for p in WORKFLOW_NOISE_PATTERNS)


# Cap per-repo workflow listing in the markdown emit so a noisy repo doesn't
# produce a wall of text. If there are more, we surface a summary line.
MAX_WORKFLOWS_PER_REPO = 5

# Known-flap workflow names — mirror of probe.WORKFLOW_FAILURE_ALLOWLIST but
# keyed by workflow display name (which is what the health report carries).
# These are surfaced in the per-repo block with a "_(known flap)_" marker
# but are NOT counted toward escalation signals.
KNOWN_FLAP_WORKFLOWS: dict[str, set[str]] = {
    "watch-advisor2": {"Weekly Autonomous Audit"},
    "Toranot": {"Toranot Weekly Audit"},
}


def is_known_flap(repo_short: str, wf_name: str) -> bool:
    return wf_name in KNOWN_FLAP_WORKFLOWS.get(repo_short, set())

# Open issue age escalation thresholds (days).
ISSUE_AGE_WARN_DAYS = 14
ISSUE_AGE_CRIT_DAYS = 30

# Dispatch PAT install date — the session PAT was installed 2026-04-29 per
# auto-audit#14 closing comment. Surface as warning at 60d, critical at 90d.
DISPATCH_PAT_INSTALL = dt.date(2026, 4, 29)
DISPATCH_PAT_WARN_DAYS = 60
DISPATCH_PAT_CRIT_DAYS = 90

# Spend MTD hard threshold (matches spend_alarm.py).
SPEND_MTD_HARD_USD = 400.0


# ─── HTTP helpers ────────────────────────────────────────────────────────────
def _http(method: str, url: str, headers: dict, body: Optional[bytes] = None,
          timeout: int = 30) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            try:
                return resp.status, json.loads(data) if data else {}
            except json.JSONDecodeError:
                return resp.status, data.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"_raw": str(e)}
    except urllib.error.URLError as e:
        return 0, {"_raw": str(e)}


def gh(method: str, path: str, *, pat: str, body: Optional[dict] = None) -> tuple[int, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    return _http(method, f"{GITHUB_API}{path}", headers, payload)


# ─── Health report aggregation ───────────────────────────────────────────────
def load_reports_in_window(days: int, now: dt.datetime) -> list[dict]:
    """Load every health report whose generated_at falls in the last N days.

    Filenames look like '2026-04-30T18-47-05.602863+00-00.json'. We parse the
    leading date for cheap filtering, then validate against generated_at."""
    cutoff = now - dt.timedelta(days=days)
    out: list[dict] = []
    for path in sorted(glob.glob("health-reports/*.json")):
        base = os.path.basename(path)
        if base.startswith("spend-"):
            continue
        if base.startswith("synthesis-"):
            continue
        if base.startswith("."):
            continue
        # Cheap date prefix check before parse:
        try:
            day_str = base[:10]  # YYYY-MM-DD
            day = dt.date.fromisoformat(day_str)
            if day < cutoff.date():
                continue
        except ValueError:
            continue
        try:
            with open(path) as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        # Validate against generated_at
        gen = doc.get("generated_at")
        if gen:
            try:
                gen_dt = dt.datetime.fromisoformat(gen.replace("Z", "+00:00"))
                if gen_dt < cutoff:
                    continue
            except ValueError:
                pass
        out.append(doc)
    return out


def load_spend_snapshots(days: int, now: dt.datetime) -> list[dict]:
    """Load spend-YYYY-MM-DD.json files for the last N days, oldest first."""
    cutoff = (now - dt.timedelta(days=days)).date()
    out: list[dict] = []
    for path in sorted(glob.glob("health-reports/spend-*.json")):
        base = os.path.basename(path)
        try:
            day = dt.date.fromisoformat(base[len("spend-"):-len(".json")])
        except ValueError:
            continue
        if day < cutoff:
            continue
        try:
            with open(path) as f:
                out.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def aggregate_per_repo(reports: list[dict]) -> dict[str, dict]:
    """Per-repo aggregates from the loaded reports.

    Output shape per repo:
      {
        'versions_seen': [v1, v2, ...],  # unique, in time order
        'workflow_failures': {wf_name: {sha: url}},  # distinct failed SHAs
        'last_live_sw': str,
        'critical_issues_emitted': int,  # count of report.repos.<r>.issues
      }
    """
    agg: dict[str, dict] = {
        r.split("/", 1)[1]: {
            "versions_seen": [],
            "workflow_failures": collections.defaultdict(dict),
            "last_live_sw": None,
            "critical_issues_emitted": 0,
        }
        for r in WATCHED_REPOS
    }
    for rpt in reports:
        for repo_name, payload in (rpt.get("repos") or {}).items():
            if repo_name not in agg:
                continue
            slot = agg[repo_name]
            raw = payload.get("raw") or {}
            live = raw.get("live_sw_version")
            if live and live not in slot["versions_seen"]:
                slot["versions_seen"].append(live)
            if live:
                slot["last_live_sw"] = live
            for wf_name, wf in (raw.get("workflows") or {}).items():
                if is_noise_workflow(wf_name):
                    continue
                if wf.get("conclusion") in ("failure", "timed_out", "startup_failure"):
                    sha = wf.get("sha", "?")
                    slot["workflow_failures"][wf_name][sha] = wf.get("url", "")
            slot["critical_issues_emitted"] += len(payload.get("issues") or [])
    # Convert defaultdict → dict for JSON-friendliness
    for v in agg.values():
        v["workflow_failures"] = {k: dict(d) for k, d in v["workflow_failures"].items()}
    return agg


def aggregate_cross_cutting(reports: list[dict]) -> dict[str, dict]:
    """For each cross_cutting probe key, count how many reports had a non-empty
    list, and capture sample messages from the last firing.

    Output: {probe_name: {'firing_reports': int, 'last_firing_at': str,
                          'last_messages': [str, ...]}}
    """
    out: dict[str, dict] = {}
    for rpt in reports:
        gen = rpt.get("generated_at", "")
        for probe, val in (rpt.get("cross_cutting") or {}).items():
            if not isinstance(val, list) or not val:
                continue
            slot = out.setdefault(probe, {
                "firing_reports": 0,
                "last_firing_at": "",
                "last_messages": [],
            })
            slot["firing_reports"] += 1
            if gen > slot["last_firing_at"]:
                slot["last_firing_at"] = gen
                # Capture up to 3 short message excerpts
                msgs = []
                for item in val[:3]:
                    if isinstance(item, dict):
                        msgs.append(item.get("message") or item.get("issue") or json.dumps(item)[:240])
                    else:
                        msgs.append(str(item)[:240])
                slot["last_messages"] = msgs
    return out


def aggregate_spend(snaps: list[dict], now: dt.datetime) -> dict:
    """Compute spend deltas and projection."""
    if not snaps:
        return {"available": False}
    snaps_sorted = sorted(snaps, key=lambda s: s["date"])
    first = snaps_sorted[0]
    latest = snaps_sorted[-1]
    same_month = first.get("month") == latest.get("month")
    delta_usd = round(latest["mtd_usd"] - first["mtd_usd"], 2) if same_month else None

    # Project month-end spend by simple linear extrapolation.
    proj_eom = None
    try:
        latest_date = dt.date.fromisoformat(latest["date"])
        # Days elapsed in latest's month
        first_of_month = latest_date.replace(day=1)
        next_month = (first_of_month + dt.timedelta(days=32)).replace(day=1)
        days_in_month = (next_month - first_of_month).days
        days_elapsed = (latest_date - first_of_month).days + 1
        if days_elapsed > 0:
            proj_eom = round(latest["mtd_usd"] / days_elapsed * days_in_month, 2)
    except (ValueError, KeyError):
        pass

    return {
        "available": True,
        "first": first,
        "latest": latest,
        "delta_usd": delta_usd,
        "same_month": same_month,
        "projected_eom_usd": proj_eom,
        "over_hard_threshold": (proj_eom is not None and proj_eom > SPEND_MTD_HARD_USD),
    }


# ─── GitHub API fetches ──────────────────────────────────────────────────────
def fetch_recent_commits(repo: str, since: dt.datetime, pat: str, limit: int = 100) -> list[dict]:
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    status, data = gh(
        "GET",
        f"/repos/{repo}/commits?sha=main&since={since_str}&per_page={limit}",
        pat=pat,
    )
    if status != 200 or not isinstance(data, list):
        return []
    return data


def fetch_merged_prs(repo: str, since: dt.datetime, pat: str, limit: int = 100) -> list[dict]:
    """Recently-closed PRs that were merged inside the window."""
    status, data = gh(
        "GET",
        f"/repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page={limit}",
        pat=pat,
    )
    if status != 200 or not isinstance(data, list):
        return []
    out = []
    for pr in data:
        if not pr.get("merged_at"):
            continue
        try:
            merged = dt.datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if merged >= since:
            out.append(pr)
    return out


def fetch_open_issues(repo: str, label: str, pat: str) -> list[dict]:
    status, data = gh(
        "GET",
        f"/repos/{repo}/issues?state=open&labels={label}&per_page=100",
        pat=pat,
    )
    if status != 200 or not isinstance(data, list):
        return []
    # Filter out PRs (the issues endpoint returns both)
    return [i for i in data if "pull_request" not in i]


# ─── Detection ───────────────────────────────────────────────────────────────
def detect_signals(per_repo: dict, cross_cutting: dict, spend: dict,
                   open_self_issues: dict[str, list],
                   open_target_issues: dict[str, list],
                   now: dt.datetime) -> list[dict]:
    """Compute the 'action needed' list. Each signal: severity / category / msg."""
    sigs: list[dict] = []

    # Recurring cross-cutting probe firings
    for probe, info in cross_cutting.items():
        if info["firing_reports"] >= RECURRING_PROBE_THRESHOLD:
            sigs.append({
                "severity": "warn",
                "category": "probe-recurring",
                "msg": (f"Probe `{probe}` fired in {info['firing_reports']} reports this window. "
                        f"Last: {info['last_firing_at']}."),
            })

    # Recurring workflow failures (excluding known flaps that are documented elsewhere)
    for repo_name, slot in per_repo.items():
        for wf_name, shas in slot["workflow_failures"].items():
            if is_known_flap(repo_name, wf_name):
                continue
            if len(shas) >= RECURRING_FAILURE_THRESHOLD:
                sigs.append({
                    "severity": "warn",
                    "category": "workflow-streak",
                    "msg": (f"`{repo_name}` / `{wf_name}` failed across "
                            f"{len(shas)} distinct SHAs this window."),
                })

    # Spend trajectory
    if spend.get("available") and spend.get("projected_eom_usd") is not None:
        if spend["over_hard_threshold"]:
            sigs.append({
                "severity": "crit",
                "category": "spend-projection",
                "msg": (f"Projected end-of-month spend ${spend['projected_eom_usd']:.2f} > "
                        f"hard threshold ${SPEND_MTD_HARD_USD:.0f}. "
                        f"Drop emit effort dial high → medium."),
            })

    # Aging open issues on auto-audit itself
    for label, issues in open_self_issues.items():
        for issue in issues:
            try:
                created = dt.datetime.fromisoformat(
                    issue["created_at"].replace("Z", "+00:00"))
            except (ValueError, KeyError):
                continue
            age_days = (now - created).days
            if age_days >= ISSUE_AGE_CRIT_DAYS:
                sigs.append({
                    "severity": "crit",
                    "category": "issue-aging",
                    "msg": (f"`{label}` issue [#{issue['number']}]({issue['html_url']}) "
                            f"open for {age_days} days: {issue['title']!s}"),
                })
            elif age_days >= ISSUE_AGE_WARN_DAYS:
                sigs.append({
                    "severity": "warn",
                    "category": "issue-aging",
                    "msg": (f"`{label}` issue [#{issue['number']}]({issue['html_url']}) "
                            f"open for {age_days} days: {issue['title']!s}"),
                })

    # Open auto-audit findings on target repos that haven't auto-resolved
    for repo, issues in open_target_issues.items():
        for issue in issues:
            try:
                created = dt.datetime.fromisoformat(
                    issue["created_at"].replace("Z", "+00:00"))
            except (ValueError, KeyError):
                continue
            age_days = (now - created).days
            if age_days >= ISSUE_AGE_WARN_DAYS:
                sigs.append({
                    "severity": "warn",
                    "category": "target-issue-aging",
                    "msg": (f"`{repo}` auto-audit finding "
                            f"[#{issue['number']}]({issue['html_url']}) "
                            f"open {age_days} days: {issue['title']!s}"),
                })

    # Dispatch PAT rotation deadline
    pat_age_days = (now.date() - DISPATCH_PAT_INSTALL).days
    if pat_age_days >= DISPATCH_PAT_CRIT_DAYS:
        sigs.append({
            "severity": "crit",
            "category": "secret-rotation",
            "msg": (f"`AUTO_AUDIT_DISPATCH_PAT` is {pat_age_days} days old "
                    f"(installed {DISPATCH_PAT_INSTALL.isoformat()}). "
                    f"Rotate via `scripts/rotate_dispatch_pat.py`."),
        })
    elif pat_age_days >= DISPATCH_PAT_WARN_DAYS:
        sigs.append({
            "severity": "warn",
            "category": "secret-rotation",
            "msg": (f"`AUTO_AUDIT_DISPATCH_PAT` will hit the {DISPATCH_PAT_CRIT_DAYS}-day "
                    f"rotation deadline in {DISPATCH_PAT_CRIT_DAYS - pat_age_days} days. "
                    f"Plan: create a fine-grained PAT scoped to auto-audit + "
                    f"run `scripts/rotate_dispatch_pat.py`."),
        })

    return sigs


# ─── Optional Claude narrative ───────────────────────────────────────────────
def claude_narrative(facts_md: str, api_key: str) -> Optional[str]:
    if len(facts_md.encode("utf-8")) > NARRATIVE_PAYLOAD_CAP_BYTES:
        print(f"::warning::Facts payload {len(facts_md)} bytes > "
              f"{NARRATIVE_PAYLOAD_CAP_BYTES}; skipping narrative.")
        return None

    system = (
        "You are summarizing a weekly health report for a one-developer engineering "
        "operation. The reader wrote the system you're summarizing. You have ONE job: "
        "in 250 words or less, surface what's emergent — patterns across multiple "
        "signals that a flat list misses. NO speculation. NO fix proposals (the system "
        "has Tier 2 templates for that). NO cheerleading. NO restating the data; "
        "the structured report below already lists everything. Format: 2-4 short "
        "paragraphs. If nothing emergent, say so in one sentence."
    )
    user = (
        "Structured facts from the past week. Identify cross-cutting patterns "
        "(probe firings that correlate with deploys, workflow failure clusters, "
        "spend trajectory implications, etc.) — or say 'No emergent patterns this "
        "week.' if there are none.\n\n" + facts_md
    )

    payload = {
        "model": NARRATIVE_MODEL,
        "max_tokens": NARRATIVE_MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    status, data = _http("POST", ANTHROPIC_API, headers, body, timeout=60)
    if status != 200 or not isinstance(data, dict):
        print(f"::warning::Claude narrative failed: HTTP {status}: "
              f"{str(data)[:200]}")
        return None
    blocks = data.get("content") or []
    text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    return text or None


# ─── Markdown emission ───────────────────────────────────────────────────────
def fmt_signals(sigs: list[dict]) -> str:
    if not sigs:
        return "_None._"
    by_sev = collections.defaultdict(list)
    for s in sigs:
        by_sev[s["severity"]].append(s)
    out = []
    for sev_label, sev_key in [("Critical", "crit"), ("Warning", "warn")]:
        items = by_sev.get(sev_key) or []
        if not items:
            continue
        out.append(f"**{sev_label}** ({len(items)})")
        for s in items:
            out.append(f"- ({s['category']}) {s['msg']}")
        out.append("")
    return "\n".join(out).rstrip() or "_None._"


def fmt_per_repo(per_repo: dict, activity: dict) -> str:
    lines = []
    for repo_short, slot in per_repo.items():
        full = f"Eiasash/{repo_short}"
        commits = activity.get(full, {}).get("commits", [])
        prs = activity.get(full, {}).get("merged_prs", [])
        live = slot.get("last_live_sw") or "?"
        bumps = len(slot["versions_seen"])
        wf_fail_count = sum(len(v) for v in slot["workflow_failures"].values())
        # Hint when we hit the GH page cap (per_page=100). For PRs the cap
        # is on the "closed" filter, not "merged", so even fewer would
        # display as 100 if cap-hit. Be honest about uncertainty.
        commits_label = f"{len(commits)}{'+' if len(commits) >= 100 else ''}"
        prs_label = f"{len(prs)}{'+' if len(prs) >= 100 else ''}"
        lines.append(f"### {repo_short}")
        lines.append(
            f"- live SW: `{live}` · version bumps this week: **{bumps}** · "
            f"workflow failures (distinct SHAs): **{wf_fail_count}** · "
            f"commits to main: **{commits_label}** · merged PRs: **{prs_label}**"
        )
        if wf_fail_count:
            # Sort by failure count descending so the worst offenders surface first
            sorted_wfs = sorted(
                slot["workflow_failures"].items(),
                key=lambda kv: -len(kv[1]),
            )
            shown = sorted_wfs[:MAX_WORKFLOWS_PER_REPO]
            hidden = sorted_wfs[MAX_WORKFLOWS_PER_REPO:]
            for wf, shas in shown:
                if shas:
                    sha_links = ", ".join(
                        f"[`{sha[:7]}`]({url})" for sha, url in list(shas.items())[:5]
                    )
                    flap_marker = " _(known flap)_" if is_known_flap(repo_short, wf) else ""
                    lines.append(f"  - `{wf}` ({len(shas)}){flap_marker}: {sha_links}")
            if hidden:
                hidden_total = sum(len(v) for _, v in hidden)
                lines.append(f"  - _and {len(hidden)} more workflows "
                             f"({hidden_total} additional failures)_")
        if prs:
            lines.append("  - Recent merged PRs:")
            for pr in prs[:5]:
                lines.append(f"    - [#{pr['number']}]({pr['html_url']}) "
                             f"{pr['title']!s}")
        lines.append("")
    return "\n".join(lines).rstrip()


def fmt_cross_cutting(cc: dict) -> str:
    if not cc:
        return "_All probes quiet._"
    rows = []
    for probe in sorted(cc, key=lambda p: -cc[p]["firing_reports"]):
        info = cc[probe]
        rows.append(f"- `{probe}` — fired in **{info['firing_reports']}** reports "
                    f"(last: {info['last_firing_at']})")
        for m in info["last_messages"][:2]:
            short = m.replace("\n", " ").strip()[:240]
            rows.append(f"  - {short}")
    return "\n".join(rows)


def fmt_spend(spend: dict) -> str:
    if not spend.get("available"):
        return "_No spend snapshots in window._"
    f = spend["first"]
    l = spend["latest"]
    parts = [
        f"- Earliest snapshot ({f['date']}): MTD **${f['mtd_usd']:.2f}**, "
        f"{f['call_count']:,} calls",
        f"- Latest snapshot ({l['date']}): MTD **${l['mtd_usd']:.2f}**, "
        f"{l['call_count']:,} calls",
    ]
    if spend.get("delta_usd") is not None:
        parts.append(f"- Window delta: **+${spend['delta_usd']:.2f}**")
    if spend.get("projected_eom_usd") is not None:
        flag = " ⚠️" if spend["over_hard_threshold"] else ""
        parts.append(f"- Projected end-of-month: **${spend['projected_eom_usd']:.2f}**{flag}")
    return "\n".join(parts)


def fmt_open_issues(open_self: dict[str, list], open_targets: dict[str, list]) -> str:
    lines = []
    total_self = sum(len(v) for v in open_self.values())
    if total_self:
        lines.append(f"**auto-audit self ({total_self})**")
        for label, issues in open_self.items():
            if not issues:
                continue
            lines.append(f"- `{label}`: {len(issues)} open")
            for i in issues[:3]:
                lines.append(f"  - [#{i['number']}]({i['html_url']}) {i['title']!s}")
    total_target = sum(len(v) for v in open_targets.values())
    if total_target:
        lines.append("")
        lines.append(f"**Target repos ({total_target})**")
        for repo, issues in open_targets.items():
            if not issues:
                continue
            lines.append(f"- `{repo}`: {len(issues)} open with `auto-audit` label")
            for i in issues[:3]:
                lines.append(f"  - [#{i['number']}]({i['html_url']}) {i['title']!s}")
    if not lines:
        return "_No open issues._"
    return "\n".join(lines)


def build_markdown(now: dt.datetime, days: int, reports: list[dict],
                   per_repo: dict, cross_cutting: dict, spend: dict,
                   activity: dict, open_self: dict, open_targets: dict,
                   signals: list[dict], narrative: Optional[str],
                   prior_issue_url: Optional[str]) -> str:
    parts: list[str] = []
    iso_today = now.date().isoformat()
    parts.append(f"# Tier 3 — Weekly synthesis · {iso_today}")
    parts.append("")
    parts.append(f"_Window: last {days} days · {len(reports)} health reports parsed · "
                 f"generated {now.strftime('%Y-%m-%d %H:%MZ')}_")
    if prior_issue_url:
        parts.append("")
        parts.append(f"_Prior week: {prior_issue_url}_")
    parts.append("")

    parts.append("## Action needed")
    parts.append("")
    parts.append(fmt_signals(signals))
    parts.append("")

    if narrative:
        parts.append("## Narrative")
        parts.append("")
        parts.append(narrative)
        parts.append("")

    parts.append("## Cross-cutting probe activity")
    parts.append("")
    parts.append(fmt_cross_cutting(cross_cutting))
    parts.append("")

    parts.append("## Spend trajectory")
    parts.append("")
    parts.append(fmt_spend(spend))
    parts.append("")

    parts.append("## Per-repo activity")
    parts.append("")
    parts.append(fmt_per_repo(per_repo, activity))
    parts.append("")

    parts.append("## Open issues")
    parts.append("")
    parts.append(fmt_open_issues(open_self, open_targets))
    parts.append("")

    parts.append("---")
    parts.append("")
    parts.append("_Auto-generated by `scripts/tier3_synthesis.py` "
                 "([source](https://github.com/Eiasash/auto-audit/blob/main/scripts/tier3_synthesis.py))._")
    return "\n".join(parts)


def build_facts_for_narrative(per_repo: dict, cross_cutting: dict, spend: dict,
                              signals: list[dict]) -> str:
    """A compact factual digest fed to Claude for narrative synthesis."""
    parts = []
    parts.append("=== SIGNALS ===")
    if signals:
        for s in signals:
            parts.append(f"- [{s['severity']}/{s['category']}] {s['msg']}")
    else:
        parts.append("(none)")
    parts.append("")
    parts.append("=== CROSS-CUTTING PROBES ===")
    for probe, info in sorted(cross_cutting.items(), key=lambda x: -x[1]["firing_reports"]):
        parts.append(f"- {probe}: {info['firing_reports']} firings; "
                     f"last={info['last_firing_at']}")
    parts.append("")
    parts.append("=== PER REPO ===")
    for r, slot in per_repo.items():
        wf_lines = []
        for wf, shas in slot["workflow_failures"].items():
            if shas:
                wf_lines.append(f"{wf}={len(shas)}")
        parts.append(f"- {r}: live_sw={slot.get('last_live_sw')}; "
                     f"bumps={len(slot['versions_seen'])}; "
                     f"workflow_failures=[{', '.join(wf_lines) or 'none'}]; "
                     f"emitted_issues={slot['critical_issues_emitted']}")
    parts.append("")
    parts.append("=== SPEND ===")
    if spend.get("available"):
        parts.append(f"- delta_usd={spend.get('delta_usd')}; "
                     f"projected_eom={spend.get('projected_eom_usd')}; "
                     f"over_hard_threshold={spend.get('over_hard_threshold')}")
    else:
        parts.append("- (no spend data)")
    return "\n".join(parts)


# ─── Issue creation ──────────────────────────────────────────────────────────
def find_existing_open_synthesis_issue(pat: str) -> Optional[dict]:
    """Idempotency: don't open a second issue for the same week. Look for any
    open issue with the 'tier3-synthesis' label."""
    status, data = gh(
        "GET",
        f"/repos/{REPO}/issues?state=open&labels=tier3-synthesis&per_page=10",
        pat=pat,
    )
    if status != 200 or not isinstance(data, list):
        return None
    for issue in data:
        if "pull_request" in issue:
            continue
        return issue
    return None


def find_prior_synthesis_issue(pat: str) -> Optional[str]:
    """Find the most recently-closed (or open) prior synthesis issue and
    return its URL for back-linking."""
    status, data = gh(
        "GET",
        f"/repos/{REPO}/issues?state=all&labels=tier3-synthesis&per_page=5&sort=created&direction=desc",
        pat=pat,
    )
    if status != 200 or not isinstance(data, list) or not data:
        return None
    for issue in data:
        if "pull_request" in issue:
            continue
        return issue.get("html_url")
    return None


def open_issue(title: str, body: str, pat: str) -> Optional[str]:
    payload = {"title": title, "body": body, "labels": ["tier3-synthesis", "auto-audit"]}
    status, data = gh("POST", f"/repos/{REPO}/issues", pat=pat, body=payload)
    if status != 201 or not isinstance(data, dict):
        print(f"::warning::Failed to open issue: HTTP {status}: {str(data)[:200]}")
        return None
    return data.get("html_url")


def comment_on_issue(issue_number: int, body: str, pat: str) -> Optional[str]:
    status, data = gh(
        "POST",
        f"/repos/{REPO}/issues/{issue_number}/comments",
        pat=pat,
        body={"body": body},
    )
    if status != 201:
        print(f"::warning::Failed to comment on #{issue_number}: HTTP {status}")
        return None
    return data.get("html_url") if isinstance(data, dict) else None


# ─── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--days", type=int, default=7, help="Lookback window in days")
    p.add_argument("--dry-run", action="store_true",
                   help="Don't open/comment on any issue; print report to stdout")
    p.add_argument("--no-narrative", action="store_true",
                   help="Skip Claude narrative even if ANTHROPIC_API_KEY is set")
    p.add_argument("--no-fetch-github", action="store_true",
                   help="Skip all GitHub API calls (offline mode for local testing)")
    p.add_argument("--out", default=None,
                   help="Write report to this path (default: "
                        "health-reports/synthesis-YYYY-MM-DD.md)")
    args = p.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    pat = os.environ.get("MONITOR_PAT") or os.environ.get("GITHUB_PAT")
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not pat and not args.no_fetch_github:
        print("::warning::No MONITOR_PAT/GITHUB_PAT set; running with --no-fetch-github implied")
        args.no_fetch_github = True

    print(f"Loading reports from last {args.days} days...")
    reports = load_reports_in_window(args.days, now)
    print(f"  {len(reports)} reports loaded")
    spend_snaps = load_spend_snapshots(args.days, now)
    print(f"  {len(spend_snaps)} spend snapshots loaded")

    per_repo = aggregate_per_repo(reports)
    cross_cutting = aggregate_cross_cutting(reports)
    spend = aggregate_spend(spend_snaps, now)

    # GitHub fetches
    activity: dict[str, dict] = {}
    open_self: dict[str, list] = {}
    open_targets: dict[str, list] = {}
    prior_issue_url: Optional[str] = None
    existing_open: Optional[dict] = None

    if not args.no_fetch_github and pat:
        since = now - dt.timedelta(days=args.days)
        print("Fetching GitHub activity...")
        for full in WATCHED_REPOS:
            commits = fetch_recent_commits(full, since, pat)
            prs = fetch_merged_prs(full, since, pat)
            activity[full] = {"commits": commits, "merged_prs": prs}
            print(f"  {full}: {len(commits)} commits, {len(prs)} merged PRs")
        # Open issues on auto-audit itself
        for label in ("auto-audit", "spend-alarm", "rotation-reminder", "auto-fix-eligible"):
            open_self[label] = fetch_open_issues(REPO, label, pat)
        # Open auto-audit-labeled issues on each watched repo
        for full in WATCHED_REPOS:
            open_targets[full] = fetch_open_issues(full, "auto-audit", pat)
        prior_issue_url = find_prior_synthesis_issue(pat)
        existing_open = find_existing_open_synthesis_issue(pat)

    signals = detect_signals(per_repo, cross_cutting, spend, open_self,
                             open_targets, now)

    # Narrative
    narrative: Optional[str] = None
    if not args.no_narrative and api_key:
        facts = build_facts_for_narrative(per_repo, cross_cutting, spend, signals)
        print("Calling Claude for narrative...")
        narrative = claude_narrative(facts, api_key)
        if narrative:
            print(f"  narrative: {len(narrative)} chars")

    md = build_markdown(now, args.days, reports, per_repo, cross_cutting,
                       spend, activity, open_self, open_targets, signals,
                       narrative, prior_issue_url)

    # Always write the report file (audit trail)
    out_path = args.out or f"health-reports/synthesis-{now.date().isoformat()}.md"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(md)
    print(f"Wrote synthesis to {out_path}")

    if args.dry_run:
        print("\n──── BEGIN REPORT ────\n")
        print(md)
        print("\n────  END REPORT  ────\n")
        return 0

    if args.no_fetch_github or not pat:
        print("--no-fetch-github / no PAT → skipping issue creation")
        return 0

    crit_count = sum(1 for s in signals if s["severity"] == "crit")
    warn_count = sum(1 for s in signals if s["severity"] == "warn")
    title_suffix = ""
    if crit_count:
        title_suffix = f" — {crit_count} crit, {warn_count} warn"
    elif warn_count:
        title_suffix = f" — {warn_count} warn"
    title = f"[Tier 3] Weekly synthesis · {now.date().isoformat()}{title_suffix}"

    if existing_open:
        # Idempotency: comment instead of opening duplicate
        url = comment_on_issue(existing_open["number"], md, pat)
        if url:
            print(f"Commented on existing #{existing_open['number']}: {url}")
        else:
            print("::warning::Could not comment on existing issue")
            return 1
    else:
        url = open_issue(title, md, pat)
        if url:
            print(f"Opened issue: {url}")
        else:
            print("::error::Failed to open issue")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
