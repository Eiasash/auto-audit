#!/usr/bin/env python3
"""
build_dashboard.py — generate the State-of-the-Suite static dashboard.

Reads the most recent ``health-reports/*.json`` Tier-1 probe output and renders
a single self-contained ``dashboard/index.html`` page (vanilla HTML + embedded
CSS + minimal JS, no external libs). One card per watched repo with:

  * Repo name + live URL
  * Last health-check timestamp + overall status (OK / WARN / CRIT) — colour-coded
  * Version-trinity status (matched / drifted)
  * Live SW cache version vs main-branch SW cache version
  * Latest CI workflow run status + last "Deploy to GitHub Pages"
  * Open auto-audit issues count (link to filtered issue list on GitHub)
  * Sibling-engine drift status (FSRS md5, Harrison JSON hash) — from cross_cutting
  * Per-app proxy health (Toranot /self-audit, watch-advisor2 /skill-snapshot)

Plus a Spend Trend section: last 12 months of Toranot proxy token-usage as a
tiny vanilla SVG bar chart, with a month-over-month >50% jump amber/red alarm.

Spend trend data sources, in priority order:
  1. Toranot ``/skill-snapshot`` ``tokenUsage.history`` (proposed schema — see
     ``_collect_spend_history``). If present, used directly.
  2. Daily ``health-reports/spend-YYYY-MM-DD.json`` snapshots aggregated by
     month (current truth, partial because we only started snapshotting
     2026-04-28).
  3. The current month's totals from the latest probe ``skill_snapshot``.

If no historical data exists at all, a placeholder card with status
"schema needed" is rendered.

Stdlib only (no Jinja, no requests). Idempotent: same input → same output.

Usage:
    python3 scripts/build_dashboard.py [--report PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# --- Configuration ----------------------------------------------------------

REPO_ORDER = [
    "Geriatrics",
    "InternalMedicine",
    "FamilyMedicine",
    "Toranot",
    "ward-helper",
    "watch-advisor2",
]

REPO_LIVE_URLS = {
    "Geriatrics":      "https://eiasash.github.io/Geriatrics/",
    "InternalMedicine": "https://eiasash.github.io/InternalMedicine/",
    "FamilyMedicine":  "https://eiasash.github.io/FamilyMedicine/",
    "ward-helper":     "https://eiasash.github.io/ward-helper/",
    "Toranot":         "https://toranot.netlify.app",
    "watch-advisor2":  "https://watch-advisor2.netlify.app",
}

ISSUES_URL_TMPL = (
    "https://github.com/Eiasash/{repo}/issues?q=is%3Aissue+is%3Aopen+label%3Aauto-audit"
)

OWNER = "Eiasash"

# Spend alarm rule. Documented in code so it stays close to the renderer:
#
#   For each pair of consecutive months in the last 12 (oldest -> newest),
#   compute ratio = this_month_total_tokens / prev_month_total_tokens.
#   * ratio >= 1.50  → AMBER bar  (50% or more month-over-month jump)
#   * ratio >= 2.00  → RED bar    (doubled month-over-month — runaway loop)
#   * otherwise      → normal bar
#
# Threshold matches the spirit of `scripts/spend_alarm.py` (which uses 2.5x
# week-over-week for issue creation); the dashboard surfaces the earlier
# 1.5x signal so a human can react before the issue gets opened.
MOM_AMBER_RATIO = 1.50
MOM_RED_RATIO   = 2.00


# --- Data loading -----------------------------------------------------------

def find_latest_report(report_dir: Path) -> Path | None:
    """Return newest ``YYYY-...`` JSON probe report, ignoring spend snapshots."""
    candidates = sorted(
        p for p in report_dir.glob("*.json")
        if not p.name.startswith("spend-")
    )
    return candidates[-1] if candidates else None


def load_report(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_spend_snapshots(report_dir: Path) -> list[dict[str, Any]]:
    """Return all daily ``spend-YYYY-MM-DD.json`` snapshots, sorted by date."""
    out: list[dict[str, Any]] = []
    for p in sorted(report_dir.glob("spend-*.json")):
        try:
            with p.open("r", encoding="utf-8") as f:
                snap = json.load(f)
            out.append(snap)
        except (OSError, json.JSONDecodeError):
            continue
    return out


# --- Status derivation ------------------------------------------------------

def overall_status(repo_payload: dict[str, Any]) -> str:
    """Return one of OK / WARN / CRIT for a given repo block."""
    issues = repo_payload.get("issues") or []
    severities = {i.get("severity") for i in issues}
    if "critical" in severities or "error" in severities:
        return "CRIT"
    if "warning" in severities:
        return "WARN"
    raw = repo_payload.get("raw") or {}
    workflows = raw.get("workflows", {}) or {}
    # Watch CI / Deploy specifically.
    for name, info in workflows.items():
        if name in ("CI", "Deploy to GitHub Pages") and info.get("conclusion") == "failure":
            return "CRIT"
    # Toranot/watch-advisor2 — check proxy fields.
    sa = raw.get("self_audit")
    if isinstance(sa, dict) and sa.get("status") not in (None, "HEALTHY"):
        return "WARN"
    return "OK"


def version_trinity_status(raw: dict[str, Any]) -> tuple[str, str]:
    """Return (label, css_class). Label like 'matched 1.10.0' or 'drift'."""
    versions = raw.get("versions") or {}
    if not versions:
        return ("n/a", "muted")
    distinct = {v for v in versions.values() if v}
    if len(distinct) == 0:
        return ("unreadable", "warn")
    if len(distinct) == 1:
        return (f"matched {next(iter(distinct))}", "ok")
    return (f"drift ({', '.join(sorted(distinct))})", "crit")


def live_vs_main(raw: dict[str, Any]) -> tuple[str, str]:
    """Compare live SW cache version vs the main-branch versions."""
    live = raw.get("live_sw_version")
    versions = raw.get("versions") or {}
    main_set = {v for v in versions.values() if v}
    if not live and not main_set:
        return ("n/a", "muted")
    if not live:
        return ("no live SW", "warn")
    if not main_set:
        return (f"live={live}, main=?", "warn")
    if live in main_set:
        return (f"live={live} == main", "ok")
    return (f"live={live} != main={','.join(sorted(main_set))}", "crit")


def workflow_pill(workflows: dict[str, Any], name: str) -> tuple[str, str]:
    info = workflows.get(name)
    if not info:
        return (f"{name}: n/a", "muted")
    conc = info.get("conclusion") or info.get("status") or "?"
    css = {
        "success": "ok",
        "failure": "crit",
        "cancelled": "warn",
        "in_progress": "muted",
    }.get(conc, "muted")
    return (f"{name}: {conc}", css)


def proxy_health(repo: str, raw: dict[str, Any]) -> tuple[str, str]:
    if repo == "Toranot":
        sa = raw.get("self_audit")
        if isinstance(sa, dict):
            status = sa.get("status", "?")
            return (f"/self-audit: {status}", "ok" if status == "HEALTHY" else "warn")
        snap = raw.get("skill_snapshot")
        if isinstance(snap, dict):
            errs = snap.get("recentErrorCount", 0)
            return (f"/skill-snapshot: {errs} recent errors", "ok" if errs == 0 else "warn")
        return ("proxy: unknown", "muted")
    if repo == "watch-advisor2":
        snap = raw.get("skill_snapshot")
        if isinstance(snap, dict):
            tu = snap.get("tokenUsage") or {}
            month = tu.get("month") or "?"
            cost = tu.get("cost_usd")
            cost_s = f"${cost:.2f}" if isinstance(cost, (int, float)) else "?"
            return (f"/skill-snapshot OK ({month} {cost_s})", "ok")
        return ("/skill-snapshot: unknown", "muted")
    return ("n/a (GitHub Pages)", "muted")


def sibling_drift_summary(report: dict[str, Any], repo: str) -> tuple[str, str]:
    """Read top-level cross_cutting.sibling_drift; flag entries that mention this repo."""
    cc = report.get("cross_cutting") or {}
    drift = cc.get("sibling_drift") or []
    if not drift:
        return ("FSRS+Harrison: synced", "ok")
    mine = [d for d in drift if (isinstance(d, dict) and repo in (d.get("repos") or []))
            or (isinstance(d, str) and repo in d)]
    if not mine:
        return ("FSRS+Harrison: synced", "ok")
    return (f"drift: {len(mine)} file(s)", "warn")


# --- Spend trend ------------------------------------------------------------

def _collect_spend_history(report: dict[str, Any], snapshots: list[dict[str, Any]]
                           ) -> tuple[list[tuple[str, int]], str]:
    """
    Return (months, source) where ``months`` is a list of
    ``(YYYY-MM, total_tokens)`` ordered oldest -> newest, capped to 12.

    ``source`` is a human label describing where the data came from.

    Schema priority:
      1. PROPOSED schema — Toranot ``/skill-snapshot`` returns
         ``tokenUsage.history = [{ "month": "2026-04",
                                    "input_tokens": 21392098,
                                    "output_tokens": 8868171,
                                    "call_count": 29156 }, ...]``
         (currently NOT implemented in Toranot; the existing endpoint only
         returns ``currentMonth`` + ``currentMonthTotals``).
      2. Aggregate ``health-reports/spend-YYYY-MM-DD.json`` daily snapshots
         by month, taking the MAX cumulative-MTD value per month as the
         total (the snapshot is monotonic within a month).
      3. Fall back to the current month's totals only.
    """
    toranot = ((report.get("repos") or {}).get("Toranot") or {}).get("raw") or {}
    snap = toranot.get("skill_snapshot") or {}
    tu = snap.get("tokenUsage") or {}
    history = tu.get("history")
    if isinstance(history, list) and history:
        rows: list[tuple[str, int]] = []
        for h in history:
            if not isinstance(h, dict):
                continue
            month = h.get("month")
            tot = (h.get("input_tokens") or 0) + (h.get("output_tokens") or 0)
            if month and tot:
                rows.append((month, int(tot)))
        rows.sort(key=lambda r: r[0])
        return (rows[-12:], "Toranot tokenUsage.history")

    # --- Aggregate daily spend snapshots by month ---
    by_month: dict[str, int] = {}
    for s in snapshots:
        month = s.get("month")
        tot = (s.get("input_tokens") or 0) + (s.get("output_tokens") or 0)
        if month and tot:
            # MTD snapshots are cumulative within a month — take the max.
            by_month[month] = max(by_month.get(month, 0), int(tot))
    # Layer current month from the live probe.
    cur_month = tu.get("currentMonth")
    cur_totals = tu.get("currentMonthTotals") or {}
    if cur_month:
        cur_total = (cur_totals.get("input_tokens") or 0) + (cur_totals.get("output_tokens") or 0)
        if cur_total:
            by_month[cur_month] = max(by_month.get(cur_month, 0), int(cur_total))

    if not by_month:
        return ([], "no data")

    rows = sorted(by_month.items(), key=lambda r: r[0])[-12:]
    src = "spend-*.json snapshots"
    if cur_month and (cur_month, by_month.get(cur_month, 0)) in rows:
        src += " + live skill_snapshot"
    return (rows, src)


def _bar_class_for_ratio(ratio: float | None) -> str:
    if ratio is None:
        return "bar"
    if ratio >= MOM_RED_RATIO:
        return "bar bar-red"
    if ratio >= MOM_AMBER_RATIO:
        return "bar bar-amber"
    return "bar"


def render_spend_chart(months: list[tuple[str, int]], source: str) -> str:
    """Render a vanilla SVG bar chart. No external libs."""
    if not months:
        return (
            '<div class="card spend-card">'
            '<h3>Spend trend (Toranot)</h3>'
            '<div class="status warn">schema needed</div>'
            '<p class="meta">Toranot <code>/skill-snapshot</code> currently returns '
            'only <code>currentMonth</code> + <code>currentMonthTotals</code>. '
            'To render a 12-month trend we need the proposed '
            '<code>tokenUsage.history</code> array (see <code>build_dashboard.py</code> '
            'comment).</p></div>'
        )

    width = 480
    height = 160
    pad_l, pad_r, pad_t, pad_b = 36, 8, 8, 28
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    n = len(months)
    bar_w = inner_w / max(n, 1) * 0.7
    gap = inner_w / max(n, 1) - bar_w
    max_v = max(v for _, v in months) or 1

    bars: list[str] = []
    labels: list[str] = []
    for i, (month, total) in enumerate(months):
        prev = months[i-1][1] if i > 0 else None
        ratio = (total / prev) if prev else None
        cls = _bar_class_for_ratio(ratio)
        h_px = (total / max_v) * inner_h
        x = pad_l + i * (bar_w + gap) + gap / 2
        y = pad_t + (inner_h - h_px)
        ratio_s = f"{ratio:.2f}x MoM" if ratio else "first month"
        title = f"{month}: {total:,} tokens ({ratio_s})"
        bars.append(
            f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" '
            f'width="{bar_w:.1f}" height="{h_px:.1f}">'
            f'<title>{html.escape(title)}</title></rect>'
        )
        # Show every other label if crowded.
        if n <= 6 or i % 2 == 0 or i == n - 1:
            lx = x + bar_w / 2
            ly = height - 10
            labels.append(
                f'<text class="axis" x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle">'
                f'{html.escape(month[2:])}</text>'  # YY-MM
            )

    # Y axis: 0 and max only, plus axis line.
    y_max_label = (
        f'<text class="axis" x="4" y="{pad_t + 8}">{max_v//1_000_000}M</text>'
    )
    y_zero_label = f'<text class="axis" x="4" y="{height - pad_b}">0</text>'
    axis_line = (
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{height-pad_b}" class="axis-line"/>'
        f'<line x1="{pad_l}" y1="{height-pad_b}" x2="{width-pad_r}" y2="{height-pad_b}" class="axis-line"/>'
    )

    svg = (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Toranot proxy monthly token totals, last {n} months. '
        f'Amber bars indicate >=50% month-over-month rise; red bars indicate >=100%.">'
        f'{axis_line}{"".join(bars)}{y_max_label}{y_zero_label}{"".join(labels)}'
        f'</svg>'
    )

    legend = (
        '<div class="legend">'
        '<span class="swatch"></span> normal '
        '<span class="swatch swatch-amber"></span> &gt;=50% MoM '
        '<span class="swatch swatch-red"></span> &gt;=100% MoM'
        '</div>'
    )

    return (
        '<div class="card spend-card">'
        f'<h3>Spend trend (Toranot) <span class="badge">{n} mo</span></h3>'
        f'{svg}{legend}'
        f'<p class="meta">Source: {html.escape(source)}. Alarm rule: '
        f'month-over-month total-token ratio >= {MOM_AMBER_RATIO:.2f} = amber, '
        f'>= {MOM_RED_RATIO:.2f} = red. See <code>build_dashboard.py</code> for the '
        f'proposed <code>tokenUsage.history</code> schema.</p>'
        '</div>'
    )


# --- Card rendering ---------------------------------------------------------

STATUS_CLASS = {"OK": "ok", "WARN": "warn", "CRIT": "crit"}


def render_card(repo: str, payload: dict[str, Any], report: dict[str, Any],
                generated_at: str) -> str:
    raw = payload.get("raw") or {}
    workflows = raw.get("workflows") or {}
    issues = payload.get("issues") or []
    status = overall_status(payload)
    status_cls = STATUS_CLASS[status]

    vt_label, vt_cls = version_trinity_status(raw)
    lv_label, lv_cls = live_vs_main(raw)
    ci_label, ci_cls = workflow_pill(workflows, "CI")
    deploy_label, deploy_cls = workflow_pill(workflows, "Deploy to GitHub Pages")
    sd_label, sd_cls = sibling_drift_summary(report, repo)
    proxy_label, proxy_cls = proxy_health(repo, raw)

    issues_url = ISSUES_URL_TMPL.format(repo=repo)
    issues_count = len(issues)
    issues_cls = "muted" if issues_count == 0 else ("warn" if issues_count < 3 else "crit")

    live_url = REPO_LIVE_URLS.get(repo, f"https://github.com/{OWNER}/{repo}")

    rows = [
        ("Status",          status,                 f"status-{status_cls}"),
        ("Version trinity", vt_label,               vt_cls),
        ("Live vs main",    lv_label,               lv_cls),
        ("CI",              ci_label,               ci_cls),
        ("Deploy",          deploy_label,           deploy_cls),
        ("Sibling engines", sd_label,               sd_cls),
        ("Proxy",           proxy_label,            proxy_cls),
    ]
    rows_html = "".join(
        f'<tr><th scope="row">{html.escape(label)}</th>'
        f'<td><span class="pill pill-{cls}">{html.escape(value)}</span></td></tr>'
        for label, value, cls in rows
    )

    return (
        f'<article class="card card-{status_cls}" aria-labelledby="h-{repo}">'
        f'  <header class="card-h">'
        f'    <h2 id="h-{repo}">{html.escape(repo)}</h2>'
        f'    <span class="status-badge status-{status_cls}" aria-label="overall status {status}">{status}</span>'
        f'  </header>'
        f'  <p class="meta">'
        f'    <a href="{html.escape(live_url)}" rel="noopener">{html.escape(live_url)}</a><br>'
        f'    Last probe: <time datetime="{html.escape(generated_at)}" '
        f'title="{html.escape(generated_at)}">{html.escape(generated_at)}</time>'
        f'  </p>'
        f'  <table class="kv"><tbody>{rows_html}</tbody></table>'
        f'  <p class="meta"><a href="{html.escape(issues_url)}" rel="noopener">'
        f'<span class="pill pill-{issues_cls}">{issues_count} open auto-audit issue(s)</span></a></p>'
        f'</article>'
    )


# --- Page assembly ----------------------------------------------------------

CSS = """
:root {
  --bg: #0b0d10;
  --bg-card: #14181d;
  --bg-card-warn: #1c1810;
  --bg-card-crit: #1c1012;
  --fg: #e6e8eb;
  --fg-muted: #8a929b;
  --border: #232931;
  --ok: #4ade80;
  --warn: #fbbf24;
  --crit: #f87171;
  --muted: #6b7280;
  --accent: #60a5fa;
  --mono: 'Berkeley Mono', 'JetBrains Mono', 'Fira Code', ui-monospace,
          SFMono-Regular, Menlo, Consolas, monospace;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg);
             font-family: var(--mono); font-size: 14px; line-height: 1.4; }
a { color: var(--accent); text-decoration: none; }
a:hover, a:focus { text-decoration: underline; outline: 2px solid var(--accent);
                   outline-offset: 2px; }
header.page-h { padding: 24px 32px; border-bottom: 1px solid var(--border); }
header.page-h h1 { margin: 0 0 8px 0; font-size: 18px; letter-spacing: 0.5px; }
header.page-h .meta { color: var(--fg-muted); margin: 0; font-size: 12px; }
main { padding: 24px 32px; max-width: 1400px; margin: 0 auto; }
.grid { display: grid; gap: 16px;
        grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); }
.card { background: var(--bg-card); border: 1px solid var(--border);
        border-radius: 6px; padding: 16px; }
.card-warn { background: var(--bg-card-warn); border-color: #3f3520; }
.card-crit { background: var(--bg-card-crit); border-color: #4a2024; }
.card-h { display: flex; justify-content: space-between; align-items: center;
          margin-bottom: 8px; gap: 12px; }
.card-h h2 { margin: 0; font-size: 16px; }
.status-badge { font-weight: 700; padding: 2px 10px; border-radius: 3px;
                font-size: 11px; letter-spacing: 1px; }
.status-ok   { background: rgba(74,222,128,0.15); color: var(--ok); }
.status-warn { background: rgba(251,191,36,0.15); color: var(--warn); }
.status-crit { background: rgba(248,113,113,0.15); color: var(--crit); }
.meta { color: var(--fg-muted); font-size: 12px; margin: 4px 0 12px; }
.meta a { color: var(--fg-muted); }
.meta a:hover { color: var(--accent); }
.kv { width: 100%; border-collapse: collapse; font-size: 12px; }
.kv th { text-align: left; padding: 4px 8px 4px 0; color: var(--fg-muted);
         font-weight: 400; vertical-align: top; width: 35%; }
.kv td { padding: 4px 0; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 3px;
        font-size: 11px; }
.pill-ok    { background: rgba(74,222,128,0.10); color: var(--ok); }
.pill-warn  { background: rgba(251,191,36,0.10); color: var(--warn); }
.pill-crit  { background: rgba(248,113,113,0.10); color: var(--crit); }
.pill-muted { background: rgba(139,146,155,0.10); color: var(--fg-muted); }
.pill-status-ok   { background: rgba(74,222,128,0.10); color: var(--ok); }
.pill-status-warn { background: rgba(251,191,36,0.10); color: var(--warn); }
.pill-status-crit { background: rgba(248,113,113,0.10); color: var(--crit); }
.spend-card { grid-column: 1 / -1; }
.spend-card h3 { margin: 0 0 8px; font-size: 15px; }
.spend-card svg { width: 100%; max-width: 720px; height: auto; display: block; }
.spend-card .bar { fill: #4b5563; }
.spend-card .bar-amber { fill: var(--warn); }
.spend-card .bar-red { fill: var(--crit); }
.spend-card .axis { fill: var(--fg-muted); font-size: 9px; }
.spend-card .axis-line { stroke: var(--border); stroke-width: 1; }
.legend { font-size: 11px; color: var(--fg-muted); margin: 8px 0 0;
          display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.swatch { display: inline-block; width: 10px; height: 10px; vertical-align: middle;
          background: #4b5563; margin-right: 4px; border-radius: 1px; }
.swatch-amber { background: var(--warn); }
.swatch-red { background: var(--crit); }
.badge { display: inline-block; padding: 1px 6px; border-radius: 3px;
         background: rgba(96,165,250,0.10); color: var(--accent);
         font-size: 10px; margin-left: 6px; }
footer { padding: 16px 32px; color: var(--fg-muted); font-size: 11px;
         border-top: 1px solid var(--border); }
"""

JS = """
// Convert ISO timestamps to local-time tooltips.
document.querySelectorAll('time[datetime]').forEach(function (el) {
  try {
    var d = new Date(el.getAttribute('datetime'));
    if (!isNaN(d.getTime())) {
      el.title = d.toLocaleString();
    }
  } catch (e) { /* ignore */ }
});
"""


def render_page(report: dict[str, Any], snapshots: list[dict[str, Any]],
                source_path: str) -> str:
    generated_at = report.get("generated_at", "(unknown)")
    repos = report.get("repos") or {}

    overall_counts = {"OK": 0, "WARN": 0, "CRIT": 0}
    for repo in REPO_ORDER:
        if repo in repos:
            overall_counts[overall_status(repos[repo])] += 1

    cards: list[str] = []
    for repo in REPO_ORDER:
        if repo in repos:
            cards.append(render_card(repo, repos[repo], report, generated_at))
        else:
            cards.append(
                f'<article class="card card-warn" aria-labelledby="h-{repo}">'
                f'<header class="card-h"><h2 id="h-{repo}">{html.escape(repo)}</h2>'
                f'<span class="status-badge status-warn">N/A</span></header>'
                f'<p class="meta">Repo missing from latest probe report.</p>'
                f'</article>'
            )

    months, source = _collect_spend_history(report, snapshots)
    spend_html = render_spend_chart(months, source)

    summary = (
        f'OK={overall_counts["OK"]} '
        f'WARN={overall_counts["WARN"]} '
        f'CRIT={overall_counts["CRIT"]}'
    )

    page = (
        '<!DOCTYPE html>'
        '<html lang="en">'
        '<head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>State of the Suite — auto-audit</title>'
        f'<style>{CSS}</style>'
        '</head>'
        '<body>'
        '<header class="page-h">'
        '<h1>STATE OF THE SUITE</h1>'
        f'<p class="meta">Snapshot generated <time datetime="{html.escape(generated_at)}">'
        f'{html.escape(generated_at)}</time> &middot; {html.escape(summary)} '
        f'&middot; source: <code>{html.escape(source_path)}</code></p>'
        '</header>'
        '<main>'
        '<section aria-label="Repository status cards" class="grid">'
        f'{"".join(cards)}{spend_html}'
        '</section>'
        '</main>'
        '<footer>'
        'Generated by <code>scripts/build_dashboard.py</code>. '
        'Auto-rebuilt on each Tier 1 probe run via <code>.github/workflows/dashboard.yml</code>. '
        'See <a href="https://github.com/Eiasash/auto-audit">repo</a>.'
        '</footer>'
        f'<script>{JS}</script>'
        '</body></html>'
    )
    return page


# --- CLI --------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build the State-of-the-Suite dashboard.")
    parser.add_argument("--report", type=Path, default=None,
                        help="Path to a specific health-report JSON. Default: newest in --report-dir.")
    parser.add_argument("--report-dir", type=Path, default=Path("health-reports"),
                        help="Directory containing health reports (default: health-reports/).")
    parser.add_argument("--out", type=Path, default=Path("dashboard/index.html"),
                        help="Output HTML path (default: dashboard/index.html).")
    args = parser.parse_args(argv)

    report_dir: Path = args.report_dir
    if not report_dir.is_dir():
        print(f"ERROR: report dir not found: {report_dir}", file=sys.stderr)
        return 2

    report_path: Path | None = args.report or find_latest_report(report_dir)
    if not report_path or not report_path.exists():
        print(f"ERROR: no probe report JSON found in {report_dir}", file=sys.stderr)
        return 2

    try:
        report = load_report(report_path)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: failed to load {report_path}: {e}", file=sys.stderr)
        return 2

    snapshots = load_spend_snapshots(report_dir)
    page = render_page(report, snapshots, source_path=str(report_path).replace("\\", "/"))

    out_path: Path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Idempotent write: only touch the file if content changed, so workflow
    # commits don't generate spurious diffs.
    new_bytes = page.encode("utf-8")
    if out_path.exists() and out_path.read_bytes() == new_bytes:
        print(f"OK (unchanged): {out_path}")
    else:
        out_path.write_bytes(new_bytes)
        print(f"OK (wrote {len(new_bytes)} bytes): {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
