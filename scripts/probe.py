#!/usr/bin/env python3
"""
Cross-repo health probe for the 6 PWAs in Eias's stack.

Tier 1 of the auto-audit system. Deterministic, free, runs in seconds.
Catches the failure modes that ship to production silently:
  * Live SW version != latest commit (deploy failure or pending)
  * GitHub Actions latest run = failure (CI red)
  * Sibling-engine drift (shared/fsrs.js, harrison_chapters.json, drugs.json)
  * Toranot proxy unhealthy (self-audit endpoint)

Outputs:
  - health-reports/YYYY-MM-DD_HH-MM.md   (audit trail in this repo)
  - GitHub issue in the affected repo if anything is RED, labeled
    `auto-audit` and `auto-fix-eligible` for the Tier 2 workflow to pick up.

Inputs (env vars):
  GH_TOKEN       — GitHub PAT with repo + issues scopes (required)
  REPORT_DIR     — defaults to ./health-reports
  DRY_RUN        — '1' to skip issue creation (default '0')

Reference for repo metadata: this is the central source of truth.
Edit REPO_CONFIG below when adding/removing a tracked repo.
"""

import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from probes.probe_distractor_alignment import check_distractor_alignment

# ─────────────────────────── config ────────────────────────────

OWNER = "Eiasash"

REPO_CONFIG: dict[str, dict[str, Any]] = {
    "Geriatrics": {
        "live_url": "https://eiasash.github.io/Geriatrics/",
        "sw_url":   "https://eiasash.github.io/Geriatrics/sw.js",
        "sw_re":    r"CACHE\s*=\s*'shlav-a-v([^']+)'",
        "version_files": [
            ("package.json",      r'"version"\s*:\s*"([^"]+)"'),
            ("shlav-a-mega.html", r"APP_VERSION\s*=\s*'([^']+)'"),
        ],
        "shared_engine_files": ["shared/fsrs.js", "harrison_chapters.json", "drugs.json"],
        "deploy_workflow": "Deploy to GitHub Pages",
        "ci_workflow": "CI",
    },
    "InternalMedicine": {
        "live_url": "https://eiasash.github.io/InternalMedicine/",
        "sw_url":   "https://eiasash.github.io/InternalMedicine/sw.js",
        "sw_re":    r"CACHE\s*=\s*'pnimit-v([^']+)'",
        "version_files": [
            ("src/core/constants.js", r"APP_VERSION\s*=\s*'([^']+)'"),
            ("sw.js",                 r"CACHE\s*=\s*'pnimit-v([^']+)'"),
        ],
        "shared_engine_files": ["shared/fsrs.js", "harrison_chapters.json", "drugs.json"],
        "deploy_workflow": "Deploy to GitHub Pages",
        "ci_workflow": "CI",
    },
    "FamilyMedicine": {
        "live_url": "https://eiasash.github.io/FamilyMedicine/",
        "sw_url":   "https://eiasash.github.io/FamilyMedicine/sw.js",
        "sw_re":    r"CACHE\s*=\s*'mishpacha-v([^']+)'",
        "version_files": [
            ("package.json",          r'"version"\s*:\s*"([^"]+)"'),
            ("src/core/constants.js", r"APP_VERSION\s*=\s*'([^']+)'"),
            ("sw.js",                 r"CACHE\s*=\s*'mishpacha-v([^']+)'"),
        ],
        "shared_engine_files": ["shared/fsrs.js", "harrison_chapters.json"],
        "deploy_workflow": "Deploy to GitHub Pages",
        "ci_workflow": "CI",
    },
    "ward-helper": {
        "live_url": "https://eiasash.github.io/ward-helper/",
        "sw_url":   "https://eiasash.github.io/ward-helper/sw.js",
        "sw_re":    r"VERSION\s*=\s*'ward-v([^']+)'",
        "version_files": [
            ("package.json", r'"version"\s*:\s*"([^"]+)"'),
        ],
        "shared_engine_files": [],
        "deploy_workflow": "Deploy to GitHub Pages",
        "ci_workflow": "CI",
    },
    "Toranot": {
        "live_url":   "https://toranot.netlify.app",
        "audit_url":  "https://toranot.netlify.app/.netlify/functions/self-audit",
        "snapshot_url": "https://toranot.netlify.app/.netlify/functions/skill-snapshot",
        "version_files": [],
        "shared_engine_files": [],
        # Toranot has no GH Pages — Netlify deploys; we trust the self-audit endpoint.
    },
    "watch-advisor2": {
        "live_url":   "https://watch-advisor2.netlify.app",
        "snapshot_url": "https://watch-advisor2.netlify.app/.netlify/functions/skill-snapshot",
        "version_files": [],
        "shared_engine_files": [],
    },
}

# ─────────────────────────── helpers ────────────────────────────

GH_TOKEN = os.environ.get("GH_TOKEN", "").strip()
DRY_RUN  = os.environ.get("DRY_RUN", "0") == "1"
# Auto-dispatch is on by default. Set AUTO_DISPATCH_DISABLED=1 in the workflow
# env (or a repo secret/variable surfaced as env) to revert to manual-click
# behaviour without code changes.
AUTO_DISPATCH_DISABLED = os.environ.get("AUTO_DISPATCH_DISABLED", "0") == "1"
REPORT_DIR = Path(os.environ.get("REPORT_DIR", "health-reports"))

# Call-count delta alarm thresholds (30-min intervals, matches health-check.yml cron)
CALL_COUNT_WARN_DELTA = 500   # WARN: >500 calls in 30 min (~17/min)
CALL_COUNT_CRIT_DELTA = 2000  # CRIT: >2000 calls in 30 min (~67/min)
# Suppression flag for legitimate bulk-gen events
BULK_GEN_ACTIVE = os.environ.get("BULK_GEN_ACTIVE", "0") == "1"

USER_AGENT = "Eiasash-auto-audit/1.0"

# Map of auto_fix template name → (workflow filename in this repo, dispatch ref).
# A template is only auto-dispatched if it's in this allowlist. Anything else
# stays as a labeled issue waiting for manual workflow_dispatch — the safe
# default for new fix templates that haven't earned trust yet.
AUTO_DISPATCH_TEMPLATES: dict[str, tuple[str, str]] = {
    "regenerate_misaligned_distractors": (
        "regenerate-misaligned-distractors.yml",
        "main",
    ),
}

# ── Ad-hoc workflow failure streak detection (issue #9) ────────────────
#
# probe_workflows() above only flags CI / Deploy / Integrity Guard as
# critical. Anything else (distractor-autopsy, weekly-audit,
# claude-code-review, distractor-merge-pr, …) can fail every cron
# indefinitely and never surface — exactly what bit Geri+Pnimit on
# 2026-04-28 (cowork/distractor-autopsy branch wipe → 5/5 silent
# failures over 10h, invisible in the green health-report).
#
# The probe_workflow_failure_streaks() function below catches that
# class of rot. Severity is warning, not critical — these are
# background-job failures, not deploy-blockers — so they surface in
# the markdown report (visible in $GITHUB_STEP_SUMMARY) without
# spamming auto-fix issues.
WORKFLOW_FAILURE_STREAK_THRESHOLD = 3  # consecutive failures before flagging

# Per-repo allowlist for known-acceptable failures. Use sparingly —
# every entry here is a workflow whose failures we have consciously
# decided to ignore. Adding noise here is exactly what the issue is
# trying to avoid catching from the OTHER direction.
#
# Format: { repo_name: { workflow_filename: "reason" } }
WORKFLOW_FAILURE_ALLOWLIST: dict[str, dict[str, str]] = {
    "watch-advisor2": {
        # Calls anthropics/claude-code-action@beta which needs
        # ANTHROPIC_API_KEY in repo secrets. Documented gap on Eias's
        # watch-list ("Tier 2 investigate template"). Will fail every
        # Monday until the key lands. No noise.
        "weekly-audit.yml": "needs ANTHROPIC_API_KEY (documented gap)",
    },
    "Toranot": {
        # Bundle-size cap (150 kB) is a flap — bundle is currently
        # 147.4 kB, last failure was a regex parse on the size-extract
        # step. Toranot is deprioritized for UI/feature work; if this
        # turns into real bundle bloat the cap should be bumped, not
        # the workflow alerted on.
        "toranot-weekly-audit.yml": "bundle-size flap; deprioritized repo",
    },
}


def _http_json(url: str, *, headers: Optional[dict] = None, body: Optional[bytes] = None,
               method: Optional[str] = None, timeout: int = 20, _retry: bool = True) -> tuple[int, Any]:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            try:
                return r.status, json.loads(payload) if payload else None
            except json.JSONDecodeError:
                return r.status, {"_raw": payload.decode("utf-8", "replace")[:5000]}
    except urllib.error.HTTPError as e:
        # Retry once on 5xx (Pages CDN warmup, Netlify cold start)
        if _retry and 500 <= e.code < 600:
            time.sleep(20)
            return _http_json(url, headers=headers, body=body, method=method, timeout=timeout, _retry=False)
        try:
            payload = e.read()
            return e.code, json.loads(payload) if payload else None
        except Exception:
            return e.code, {"_raw_error": str(e)}
    except Exception as e:  # network failure, DNS, etc.
        if _retry:
            time.sleep(10)
            return _http_json(url, headers=headers, body=body, method=method, timeout=timeout, _retry=False)
        return 0, {"_error": str(e)}


def _http_text(url: str, *, headers: Optional[dict] = None, timeout: int = 20,
               _retry: bool = True) -> tuple[int, str]:
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if _retry and 500 <= e.code < 600:
            time.sleep(20)
            return _http_text(url, headers=headers, timeout=timeout, _retry=False)
        try:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception:
            return e.code, ""
    except Exception as e:
        if _retry:
            time.sleep(10)
            return _http_text(url, headers=headers, timeout=timeout, _retry=False)
        return 0, f"_error: {e}"


def gh(path: str, **kw) -> tuple[int, Any]:
    """Call GitHub API with auth."""
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    headers.update(kw.pop("headers", {}))
    if kw.get("body") is not None and not isinstance(kw["body"], bytes):
        kw["body"] = json.dumps(kw["body"]).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    return _http_json(f"https://api.github.com{path}", headers=headers, **kw)


def auto_audit_workflow_running(workflow_filename: str) -> bool:
    """Return True if `workflow_filename` is queued or in_progress on this repo.

    Used as the idempotency check before auto-dispatch. The Tier 1 cron runs
    every 30 min; a real distractor regeneration takes 30–60 min. Without
    this guard the second cron tick would happily fire a duplicate run.
    """
    for status in ("in_progress", "queued"):
        sc, data = gh(
            f"/repos/{OWNER}/auto-audit/actions/workflows/"
            f"{workflow_filename}/runs?status={status}&per_page=5"
        )
        if sc == 200 and isinstance(data, dict) and data.get("total_count", 0) > 0:
            return True
    return False


def dispatch_auto_audit_workflow(
    workflow_filename: str, inputs: dict[str, str], ref: str = "main"
) -> bool:
    """Trigger workflow_dispatch on `workflow_filename` in this repo.

    Returns True on a 204 from GitHub. Caller is responsible for the
    idempotency check; this function is a thin shim.
    Requires PAT with Actions: Read & write on Eiasash/auto-audit.
    """
    sc, _ = gh(
        f"/repos/{OWNER}/auto-audit/actions/workflows/"
        f"{workflow_filename}/dispatches",
        method="POST",
        body={"ref": ref, "inputs": inputs},
    )
    return sc in (204, 200)


# ─────────────────────────── probes ────────────────────────────

def probe_repo_versions(repo: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Fetch each tracked version-bearing file from main + extract version.
    All versions in the same repo MUST agree (the version-trinity invariant)."""
    out: dict[str, Any] = {"versions": {}, "issues": []}
    for path, regex in cfg.get("version_files", []):
        status, data = gh(f"/repos/{OWNER}/{repo}/contents/{path}")
        if status != 200 or not isinstance(data, dict) or "content" not in data:
            out["issues"].append({
                "severity": "error",
                "kind": "version_file_unreadable",
                "msg": f"Couldn't read {path}: HTTP {status}",
            })
            continue
        text = base64.b64decode(data["content"]).decode("utf-8", "replace")
        m = re.search(regex, text)
        out["versions"][path] = m.group(1) if m else None
        if not m:
            out["issues"].append({
                "severity": "error",
                "kind": "version_regex_no_match",
                "msg": f"Regex didn't match in {path}",
            })

    distinct = {v for v in out["versions"].values() if v}
    # Pnimit's package.json has the +.0 convention — normalize before compare.
    if repo == "InternalMedicine":
        distinct = {v.rstrip(".0") if v.count(".") == 3 and v.endswith(".0") else v for v in distinct}
    if len(distinct) > 1:
        out["issues"].append({
            "severity": "critical",
            "kind": "version_trinity_mismatch",
            "msg": f"Versions disagree across files: {out['versions']}",
            "auto_fix": "version_trinity",
        })
    return out


def probe_live_sw(repo: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Fetch the deployed sw.js and confirm it matches the latest commit's version."""
    out: dict[str, Any] = {"live_sw_version": None, "issues": []}
    sw_url = cfg.get("sw_url")
    if not sw_url:
        return out
    # Cache-bust to dodge any CDN staleness
    bust_url = f"{sw_url}?cb={int(time.time())}"
    status, body = _http_text(bust_url)
    if status != 200:
        out["issues"].append({
            "severity": "warning",
            "kind": "live_sw_unreachable",
            "msg": f"sw.js HTTP {status}",
        })
        return out
    m = re.search(cfg.get("sw_re", ""), body)
    out["live_sw_version"] = m.group(1) if m else None
    return out


def probe_workflows(repo: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Look at the latest run for ci_workflow + deploy_workflow on main; flag failures."""
    out: dict[str, Any] = {"workflows": {}, "issues": []}
    status, data = gh(f"/repos/{OWNER}/{repo}/actions/runs?branch=main&per_page=20")
    if status != 200 or not isinstance(data, dict):
        out["issues"].append({
            "severity": "warning", "kind": "workflows_unreadable",
            "msg": f"GH Actions API HTTP {status}",
        })
        return out
    seen = set()
    for r in data.get("workflow_runs", []):
        name = r.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        info = {
            "conclusion": r.get("conclusion"),
            "status": r.get("status"),
            "sha": (r.get("head_sha") or "")[:7],
            "url": r.get("html_url"),
            "updated_at": r.get("updated_at"),
        }
        out["workflows"][name] = info
        # Flag the well-known critical workflows when they're red
        if name in (cfg.get("ci_workflow"), cfg.get("deploy_workflow")):
            if r.get("conclusion") == "failure":
                out["issues"].append({
                    "severity": "critical",
                    "kind": "workflow_failure",
                    "msg": f'{name} failed on main (sha {info["sha"]})',
                    "url": info["url"],
                    "auto_fix": "rerun_or_debug",
                })
    return out


def probe_workflow_failure_streaks(repo: str) -> list[dict[str, Any]]:
    """Catch ad-hoc workflow failure streaks invisible to probe_workflows().

    probe_workflows() only flags CI / Deploy / Integrity Guard. Workflows
    like distractor-autopsy, weekly-audit, claude-code-review,
    distractor-merge-pr can fail every cron indefinitely and never
    surface — exactly what bit Geri+Pnimit on 2026-04-28 (cowork/
    distractor-autopsy branch wipe → 5/5 silent failures over 10h, while
    the health-report stayed green).

    Strategy: enumerate active `.github/workflows/*.yml` files, fetch the
    last N runs on main for each, flag if the last STREAK_THRESHOLD
    completed runs are all conclusion=failure (or timed_out /
    startup_failure). Allowlist via WORKFLOW_FAILURE_ALLOWLIST so
    legitimately-broken workflows don't spam.

    Severity is warning, not critical — these are background-job rot, not
    deploy-blockers. Tier 2 has no auto-fix template wired for this; the
    fix is "go look at the workflow run" with the URL in the finding.
    """
    issues: list[dict[str, Any]] = []

    # 1. List active workflows for this repo
    sc, data = gh(f"/repos/{OWNER}/{repo}/actions/workflows")
    if sc != 200 or not isinstance(data, dict):
        return issues

    workflows = data.get("workflows", [])
    allowlist = WORKFLOW_FAILURE_ALLOWLIST.get(repo, {})

    # Severity-comparable failure conclusions
    fail_concls = {"failure", "timed_out", "startup_failure"}

    for wf in workflows:
        if wf.get("state") != "active":
            continue
        path = wf.get("path", "")
        # Skip GitHub-managed dynamic workflows (Pages build, Dependabot,
        # Copilot agent, anthropic-code-agent). Those have synthetic paths
        # like `dynamic/pages/...` and aren't user-controlled YAML.
        if not path.startswith(".github/workflows/"):
            continue
        filename = path.rsplit("/", 1)[-1]
        if filename in allowlist:
            continue

        # 2. Fetch the last few runs on main for this workflow.
        # Pull a couple extra so 1–2 in_progress runs at the head don't
        # silently shrink the completed-window below STREAK_THRESHOLD.
        sc2, runs_data = gh(
            f"/repos/{OWNER}/{repo}/actions/workflows/{filename}/runs"
            f"?branch=main&per_page={WORKFLOW_FAILURE_STREAK_THRESHOLD + 2}"
        )
        if sc2 != 200 or not isinstance(runs_data, dict):
            continue
        runs = runs_data.get("workflow_runs", [])

        # Only consider COMPLETED runs (skip queued/in_progress at the head).
        # If the workflow hasn't accumulated 3 completed runs yet, skip —
        # don't fire a false-positive on a fresh workflow.
        completed = [r for r in runs if r.get("status") == "completed"]
        if len(completed) < WORKFLOW_FAILURE_STREAK_THRESHOLD:
            continue

        recent = completed[:WORKFLOW_FAILURE_STREAK_THRESHOLD]
        if all(r.get("conclusion") in fail_concls for r in recent):
            latest = recent[0]
            wf_name = wf.get("name") or filename
            issues.append({
                "severity": "warning",
                "kind": "workflow_failure_streak",
                "msg": (
                    f"{wf_name} ({filename}) has failed "
                    f"{WORKFLOW_FAILURE_STREAK_THRESHOLD} consecutive runs on main. "
                    f"Latest: {latest.get('html_url', '?')}. If this is expected, "
                    f"add to WORKFLOW_FAILURE_ALLOWLIST in scripts/probe.py."
                ),
                "url": latest.get("html_url"),
            })

    return issues


# Grace window: if main HEAD is younger than this, demote drift critical→warning.
# Pages/Netlify CDN typically catches up within 30-60s of push, but we've seen
# up to 5 min of staleness. 10 min grace covers the long tail without masking
# a stuck deploy.
DEPLOY_DRIFT_GRACE_MINUTES = 10


def _main_head_age_minutes(repo: str) -> float | None:
    """Return age in minutes of the most recent commit on main, or None on error."""
    try:
        status, data = gh(f"/repos/{OWNER}/{repo}/commits/main")
        if status != 200 or not isinstance(data, dict):
            return None
        ts = data.get("commit", {}).get("committer", {}).get("date")
        if not ts:
            return None
        commit_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - commit_dt).total_seconds() / 60.0
    except Exception as e:
        sys.stderr.write(f"[deploy-drift] Failed to fetch main HEAD age for {repo}: {e}\n")
        return None


def probe_deploy_drift(repo: str, cfg: dict[str, Any], versions: dict[str, str | None],
                       live_ver: str | None) -> list[dict[str, Any]]:
    """If we have a live SW version AND a repo version, they must match.

    If main HEAD is younger than DEPLOY_DRIFT_GRACE_MINUTES, demote critical
    → warning to avoid false positives from in-flight CDN catch-up.
    """
    issues: list[dict[str, Any]] = []
    if not live_ver or not versions:
        return issues
    repo_vers = {v for v in versions.values() if v}
    # Pnimit normalize
    if repo == "InternalMedicine":
        repo_vers = {v.rstrip(".0") if v.count(".") == 3 and v.endswith(".0") else v for v in repo_vers}
    if not repo_vers:
        return issues
    if live_ver not in repo_vers:
        # Check grace window: if main was just pushed, CDN is probably catching up
        head_age = _main_head_age_minutes(repo)
        in_grace = head_age is not None and head_age < DEPLOY_DRIFT_GRACE_MINUTES
        msg_suffix = ""
        if in_grace:
            msg_suffix = f" (main HEAD {head_age:.1f} min old, within {DEPLOY_DRIFT_GRACE_MINUTES} min grace — likely in-flight deploy)"
        issues.append({
            "severity": "warning" if in_grace else "critical",
            "kind": "deploy_live_drift",
            "msg": f"Live SW serves v{live_ver} but main has v{sorted(repo_vers)}{msg_suffix}",
            "auto_fix": None if in_grace else "investigate_deploy_pipeline",
        })
    return issues


def probe_endpoint(name: str, url: str) -> dict[str, Any]:
    """Generic endpoint probe — for Toranot self-audit / skill-snapshot."""
    if not url:
        return {}
    status, data = _http_json(url)
    out: dict[str, Any] = {"http": status, "ok": status == 200, "issues": []}
    if status != 200:
        out["issues"].append({
            "severity": "warning", "kind": f"{name}_endpoint_unhealthy",
            "msg": f"{url} → HTTP {status}",
        })
    elif isinstance(data, dict):
        # Surface a few well-known fields if present
        if data.get("status") and data["status"] != "HEALTHY":
            out["issues"].append({
                "severity": "warning", "kind": f"{name}_self_reported_unhealthy",
                "msg": f"{url} reports status={data['status']}",
            })
        if data.get("recentErrorCount", 0) > 0:
            out["issues"].append({
                "severity": "warning", "kind": f"{name}_recent_errors",
                "msg": f"{data['recentErrorCount']} recent errors",
            })
        out["snapshot"] = {
            k: data.get(k) for k in
            ("status", "patientCount", "tokenUsage", "claudeModel", "recentErrorCount")
            if k in data
        }
    return out


def probe_call_count_delta(token_usage: dict[str, Any]) -> list[dict[str, Any]]:
    """Check call-count delta against previous run to detect runaway loops.

    Reads from /health-reports/.last_call_count.json, compares against current,
    writes new state back. Alarms if delta > thresholds in 30min window.

    Args:
        token_usage: The tokenUsage dict from Toranot skill_snapshot endpoint

    Returns:
        List of issues (severity: warning or critical)
    """
    issues: list[dict[str, Any]] = []

    # Extract current call count
    current_month_totals = token_usage.get("currentMonthTotals", {})
    current_call_count = current_month_totals.get("call_count", 0)
    current_month = token_usage.get("currentMonth", "")

    if not current_call_count:
        sys.stderr.write("[call-count-delta] No call_count in tokenUsage, skipping\n")
        return issues

    # State file path
    state_file = REPORT_DIR / ".last_call_count.json"

    # Load previous state
    previous_call_count = None
    previous_month = None
    if state_file.exists():
        try:
            with open(state_file) as f:
                state = json.load(f)
                previous_call_count = state.get("call_count")
                previous_month = state.get("month")
        except Exception as e:
            sys.stderr.write(f"[call-count-delta] Failed to load state: {e}\n")

    # Write current state (always update, even on first run or month boundary)
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, "w") as f:
            json.dump({
                "call_count": current_call_count,
                "month": current_month,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, f, indent=2)
    except Exception as e:
        sys.stderr.write(f"[call-count-delta] Failed to save state: {e}\n")

    # First run or no previous data
    if previous_call_count is None:
        sys.stderr.write(f"[call-count-delta] First run, baseline set to {current_call_count}\n")
        return issues

    # Month boundary crossed — reset baseline, don't alarm
    if previous_month and previous_month != current_month:
        sys.stderr.write(
            f"[call-count-delta] Month boundary crossed ({previous_month} → {current_month}), "
            f"resetting baseline\n"
        )
        return issues

    # Compute delta
    delta = current_call_count - previous_call_count
    sys.stderr.write(
        f"[call-count-delta] {previous_call_count} → {current_call_count} "
        f"(Δ={delta} in ~30min)\n"
    )

    # Check thresholds
    if delta > CALL_COUNT_CRIT_DELTA:
        severity = "critical"
        labels_hint = "auto-audit + priority/high"
        rate = delta / 30  # calls per minute
        issues.append({
            "severity": severity,
            "kind": "call_count_runaway_loop",
            "msg": (
                f"CRITICAL: {delta} calls in ~30min ({rate:.1f}/min) exceeds "
                f"threshold {CALL_COUNT_CRIT_DELTA}. Possible runaway loop."
            ),
            "delta": delta,
            "labels_hint": labels_hint,
        })
    elif delta > CALL_COUNT_WARN_DELTA:
        severity = "warning"
        labels_hint = "auto-audit"
        rate = delta / 30
        issues.append({
            "severity": severity,
            "kind": "call_count_elevated",
            "msg": (
                f"WARNING: {delta} calls in ~30min ({rate:.1f}/min) exceeds "
                f"threshold {CALL_COUNT_WARN_DELTA}. Monitor for continuation."
            ),
            "delta": delta,
            "labels_hint": labels_hint,
        })

    # Suppression for bulk-gen events
    if issues and BULK_GEN_ACTIVE:
        sys.stderr.write(
            f"[call-count-delta] BULK_GEN_ACTIVE=1, suppressing {len(issues)} alarm(s)\n"
        )
        return []

    return issues


def probe_sibling_drift() -> list[dict[str, Any]]:
    """Diff shared-engine files across the 3 medical PWAs by content hash."""
    issues: list[dict[str, Any]] = []
    siblings = ["Geriatrics", "InternalMedicine", "FamilyMedicine"]
    files = ["shared/fsrs.js", "harrison_chapters.json"]  # drugs.json varies slightly between Mishpacha & others, skip
    for f in files:
        hashes: dict[str, str] = {}
        for repo in siblings:
            status, data = gh(f"/repos/{OWNER}/{repo}/contents/{f}")
            if status == 200 and isinstance(data, dict) and "content" in data:
                blob = base64.b64decode(data["content"])
                hashes[repo] = hashlib.sha256(blob).hexdigest()[:12]
        distinct = set(hashes.values())
        if len(distinct) > 1:
            issues.append({
                "severity": "warning",
                "kind": "sibling_engine_drift",
                "msg": f"{f} differs across siblings: {hashes}",
                "auto_fix": "sibling_sync",
            })
    return issues


# Per-repo location of syllabus_data.json. The Vite-modular siblings
# (FM, Pnimit) keep it next to the algorithm; the single-file PWA (Geri)
# keeps it under data/ alongside the other runtime JSON.
STUDY_PLAN_SYLLABUS_PATHS: dict[str, str] = {
    "FamilyMedicine":   "src/features/study_plan/syllabus_data.json",
    "InternalMedicine": "src/features/study_plan/syllabus_data.json",
    "Geriatrics":       "data/syllabus_data.json",
}

# Shared Supabase project (krmlzwwelqvlfslwltol) — used by the RPC smoke probe
# below. The publishable (anon) key is already embedded in every PWA's client
# source, so it's safe to hard-code; the RPC layer (SECURITY DEFINER + RLS
# zero-policies on the underlying table) is what enforces access.
STUDY_PLAN_SUPABASE_URL = "https://krmlzwwelqvlfslwltol.supabase.co"
STUDY_PLAN_SUPABASE_KEY = "sb_publishable_tUuqQQ8RKMvLDwTz5cKkOg_o_y-rHtw"
# RPC server whitelist — must stay in sync with study_plan_upsert/get's
# `IF p_app NOT IN (...)`. If the server adds a fourth app, append here too.
STUDY_PLAN_RPC_APPS: tuple[str, ...] = ("geri", "pnimit", "mishpacha")
# Sentinel username — must NEVER match a real user. NOT_FOUND is the
# expected happy-path branch on study_plan_get for a non-existent user.
STUDY_PLAN_RPC_SENTINEL = "__auto_audit_healthcheck__"

# backup_get(p_app, p_id) — Phase 2 of backups RLS tightening, shipped
# 2026-04-29 across Geri #112 / Pnimit #53 / FM #18. Public SELECT was
# dropped on the three *_backups tables; the only read path is now this
# SECURITY DEFINER RPC. Whitelist must match the function body's
# `RAISE EXCEPTION USING ERRCODE='22023'` branch. Note 'samega' is the
# legacy alias for Geri (Shlav A Mega) — both must work because the
# Geri client may send either, and the table is named `samega_backups`.
BACKUPS_RPC_APPS: tuple[str, ...] = ("mishpacha", "pnimit", "geri", "samega")
# Sentinel id for the smoke read. Choose something that will never match
# a real backup id (the PWAs use either the cloud uid or a random
# per-device id, neither of which can collide with this dunder string).
BACKUPS_RPC_SENTINEL_ID = "__auto_audit_healthcheck_nonexistent__"


def probe_study_plan_parity() -> list[dict[str, Any]]:
    """Verify the three medical PWAs ship byte-identical syllabus_data.json.

    The frequency-weighted study plan generator (FM v1.9.1+, Pnimit v9.86.0+,
    Geri v10.46.0+) reads its 24/27/46-topic slice from this fixed JSON. Any
    drift between repos = users on different apps see different "shared"
    topic frequencies / Hebrew labels, and the cross-language fixture in
    each repo's tests starts silently disagreeing with the others.

    Pre-merge state: the file may not exist on `main` for all 3 repos
    yet (e.g., during a staged rollout where only FM has shipped). If any
    repo is missing the file, the probe emits a stderr note and skips the
    parity check entirely rather than firing CRITICAL on every cron tick
    until the rollout completes. Once all 3 ship, the probe activates
    automatically — no code change needed.

    Note: only checks `syllabus_data.json`. The algorithm primitives
    (allocateHours / schedule / render) are guarded per-repo by each
    app's own cross-language fixture in tests/studyPlanAlgorithm.test.js,
    which pins them against the canonical Python in
    `auto-audit/scripts/generate_study_plan.py`. A drift in the algorithm
    surfaces as a red CI run on the affected repo, not here.
    """
    issues: list[dict[str, Any]] = []
    hashes: dict[str, Optional[str]] = {}
    for repo, path in STUDY_PLAN_SYLLABUS_PATHS.items():
        status, data = gh(f"/repos/{OWNER}/{repo}/contents/{path}")
        if status == 200 and isinstance(data, dict) and "content" in data:
            blob = base64.b64decode(data["content"])
            hashes[repo] = hashlib.sha256(blob).hexdigest()[:12]
        else:
            hashes[repo] = None

    missing = [r for r, h in hashes.items() if h is None]
    if missing:
        sys.stderr.write(
            f"[study-plan-parity] skipping; syllabus_data.json missing on main in: "
            f"{missing}. Probe activates once all 3 apps ship the feature.\n"
        )
        return issues

    distinct = {h for h in hashes.values() if h is not None}
    if len(distinct) > 1:
        issues.append({
            "severity": "warning",
            "kind": "study_plan_syllabus_drift",
            "msg": f"syllabus_data.json differs across the three medical PWAs: {hashes}",
            "auto_fix": "sibling_sync_syllabus",
        })
    return issues


def probe_honest_stats_parity() -> list[dict[str, Any]]:
    """Verify each medical PWA ships tests/honestStats.test.js with the
    required structural markers.

    The honestStats CI guard (added 2026-04-29 across the 3 PWAs) codifies
    the principle: scoring functions returning percentages MUST return null
    on sparse/empty input, not a confident-looking default.

    The three test files aren't byte-identical (each repo has slightly
    different module paths and test counts), so a hash-diff like
    probe_sibling_drift won't work. Instead, this probe asserts each file
    contains a minimum set of markers — if any repo drifts off the pattern
    (file deleted, regression test removed, etc.) it warns.

    Required markers (per repo's honestStats.test.js):
      * 'returns null for completely empty state' — calcEstScore guard
      * 'REGRESSION' — at least one explicit regression test
      * 'toBeNull' — assertions that null is the right answer
      * 'acc=0\\.60' or 'acc\\s*=\\s*0\\.6' as a NEGATIVE-MATCH guard against
        the original 60% imputation bug
      * 'takeWeeklySnapshot' or 'tot\\s*>=\\s*[3-9]' — the snapshot
        threshold guard added in v9.92.1 / v1.17.1 / v10.61.1

    Anything missing → warning. The probe deliberately does not fire CRITICAL
    on this surface; missing test markers don't mean the code is broken,
    only that the regression guard has been weakened.
    """
    issues: list[dict[str, Any]] = []
    siblings = ["Geriatrics", "InternalMedicine", "FamilyMedicine"]
    path = "tests/honestStats.test.js"

    required_markers = [
        ("empty_state_null", r"returns null for (?:completely )?empty state"),
        ("regression_marker", r"REGRESSION"),
        ("null_assertion", r"toBeNull"),
        ("snapshot_guard", r"takeWeeklySnapshot|tot\s*>=\s*[3-9]"),
        # The source-level forbidden-pattern guards (acc=0.60, bare R aggregation)
        # live INSIDE each repo's honestStats.test.js — re-running them here
        # would fight with the test's own description strings. CI failure on
        # those guards surfaces via probe_workflows already.
        ("source_guard_calc_est", r"calcEstScore must NOT contain"),
        ("source_guard_heatmap", r"must NOT use pure FSRS R aggregation|must NOT use bare FSRS R"),
    ]

    for repo in siblings:
        status, data = gh(f"/repos/{OWNER}/{repo}/contents/{path}")
        if status != 200 or not isinstance(data, dict) or "content" not in data:
            issues.append({
                "severity": "warning",
                "kind": "honest_stats_missing",
                "repo": repo,
                "msg": f"{path} missing on main — honestStats CI guard not in place",
            })
            continue
        try:
            content = base64.b64decode(data["content"]).decode("utf-8")
        except Exception as e:
            issues.append({
                "severity": "warning",
                "kind": "honest_stats_unreadable",
                "repo": repo,
                "msg": f"{path} could not be decoded: {e}",
            })
            continue

        # Required markers must be present.
        for name, pattern in required_markers:
            if not re.search(pattern, content):
                issues.append({
                    "severity": "warning",
                    "kind": "honest_stats_marker_missing",
                    "repo": repo,
                    "msg": f"{path} missing required marker '{name}' (pattern: {pattern})",
                })

    return issues



def probe_study_plan_rpc() -> list[dict[str, Any]]:
    """Smoke-test the study_plan_get RPC for each app's documented APP_KEY.

    Calls study_plan_get with a sentinel username (no real user) and the
    APP_KEY each PWA's client claims to send. Any failure here means the
    server-side validation drifted away from the contract — exactly the
    class of bug that surfaced 2026-04-28 (Geri v10.46.0 sent 'shlav',
    server whitelist was ('geri','pnimit','mishpacha'), client got
    `{ok:false, error:'invalid_app'}` despite HTTP 200, and the user saw
    'invalid_app ✗' under the create-plan button).

    Happy path on a non-existent user: `{ok:true, plan:null}`.

    Detected drift modes:
      - HTTP non-200                    → critical (auth wedge / RPC gone)
      - {ok:false, error:'invalid_app'} → critical (RPC whitelist drift)
      - {ok:false, error:'invalid_username'} → warning (validator changed)
      - {ok:false, error:<other>}       → warning (db_error etc.)
      - body shape unexpected           → warning
      - network timeout / DNS           → warning

    The client-side mirror of this contract (each PWA's APP_KEY constant) is
    locked by appIntegrity.test.js / regressionGuards.test.js per repo —
    so the probe specifically catches *server*-side drift (whitelist edits
    in a future migration, RPC permission breakage, project outage).
    """
    issues: list[dict[str, Any]] = []
    url = STUDY_PLAN_SUPABASE_URL.rstrip("/") + "/rest/v1/rpc/study_plan_get"

    for app_key in STUDY_PLAN_RPC_APPS:
        body = json.dumps({
            "p_username": STUDY_PLAN_RPC_SENTINEL,
            "p_app": app_key,
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "apikey": STUDY_PLAN_SUPABASE_KEY,
                "Authorization": f"Bearer {STUDY_PLAN_SUPABASE_KEY}",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.getcode()
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            issues.append({
                "severity": "critical",
                "kind": "study_plan_rpc_http_error",
                "msg": (
                    f"study_plan_get(p_app='{app_key}') returned HTTP {e.code} — "
                    f"RPC unreachable or permissions broken."
                ),
            })
            continue
        except (urllib.error.URLError, TimeoutError) as e:
            issues.append({
                "severity": "warning",
                "kind": "study_plan_rpc_network",
                "msg": f"study_plan_get(p_app='{app_key}') network error: {e}",
            })
            continue
        except Exception as e:  # pragma: no cover — belt and suspenders
            issues.append({
                "severity": "warning",
                "kind": "study_plan_rpc_unexpected",
                "msg": f"study_plan_get(p_app='{app_key}') unexpected error: {e}",
            })
            continue

        if status != 200:
            issues.append({
                "severity": "critical",
                "kind": "study_plan_rpc_http_error",
                "msg": f"study_plan_get(p_app='{app_key}') returned HTTP {status}.",
            })
            continue

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            issues.append({
                "severity": "warning",
                "kind": "study_plan_rpc_bad_json",
                "msg": (
                    f"study_plan_get(p_app='{app_key}') returned non-JSON body "
                    f"({raw[:120]!r})."
                ),
            })
            continue

        if not isinstance(payload, dict):
            issues.append({
                "severity": "warning",
                "kind": "study_plan_rpc_bad_shape",
                "msg": (
                    f"study_plan_get(p_app='{app_key}') returned non-object "
                    f"payload: {payload!r}."
                ),
            })
            continue

        if payload.get("ok") is True:
            # Sentinel user → expect plan:null. plan:<obj> would mean somebody
            # actually created a plan with the sentinel username — note it
            # so we can clean up, but don't fail the probe.
            if payload.get("plan") is not None:
                issues.append({
                    "severity": "warning",
                    "kind": "study_plan_rpc_sentinel_polluted",
                    "msg": (
                        f"Sentinel username '{STUDY_PLAN_RPC_SENTINEL}' has a "
                        f"saved plan for app='{app_key}'. Delete it from "
                        f"public.study_plans to keep the probe a true smoke test."
                    ),
                })
            continue  # ok:true is the happy path

        err = payload.get("error", "<missing>")
        if err == "invalid_app":
            issues.append({
                "severity": "critical",
                "kind": "study_plan_rpc_whitelist_drift",
                "msg": (
                    f"study_plan_get rejected p_app='{app_key}' as invalid_app. "
                    f"Server whitelist no longer matches the documented set "
                    f"{STUDY_PLAN_RPC_APPS}. Check the latest migration on "
                    f"public.study_plan_get / study_plan_upsert."
                ),
            })
        elif err == "invalid_username":
            issues.append({
                "severity": "warning",
                "kind": "study_plan_rpc_username_validator_changed",
                "msg": (
                    f"study_plan_get rejected the sentinel username "
                    f"'{STUDY_PLAN_RPC_SENTINEL}' as invalid_username. "
                    f"Username validator likely tightened — update the probe "
                    f"sentinel to match the new format."
                ),
            })
        else:
            issues.append({
                "severity": "warning",
                "kind": "study_plan_rpc_unexpected_error",
                "msg": (
                    f"study_plan_get(p_app='{app_key}') returned ok=false "
                    f"error='{err}' (full payload: {payload!r})."
                ),
            })

    return issues


def probe_backup_get_rpc() -> list[dict[str, Any]]:
    """Smoke-test the backup_get(p_app, p_id) RPC for each whitelisted app.

    Phase 2 of the backups RLS tightening (shipped 2026-04-29) dropped the
    public SELECT policies on `mishpacha_backups`, `pnimit_backups`, and
    `samega_backups`. The ONLY read path now is this SECURITY DEFINER
    RPC. If it breaks, every "restore from cloud" tap across all three
    PWAs returns "no backup found" silently — a particularly bad failure
    mode because the user trusts the empty result.

    The probe runs four positive cases (one per whitelisted app) and one
    negative case:

      Positive (each of mishpacha / pnimit / geri / samega):
        Request:  POST /rpc/backup_get  body={p_app:<app>, p_id:<sentinel>}
        Expect:   HTTP 200, body=null  (sentinel id has no row)
        Catches:  RPC unreachable (HTTP 5xx), table-name mapping bug
                  inside the RPC body (would raise a SQL error → HTTP 500
                  instead of returning null), whitelist drift on this app.

      Negative (p_app='__auto_audit_invalid_app__'):
        Request:  POST /rpc/backup_get  body={p_app:'__auto_audit_invalid_app__',p_id:'x'}
        Expect:   HTTP 4xx, body.code='22023'
        Catches:  Whitelist enforcement was loosened or removed — a regression
                  that would let arbitrary app strings through to the dynamic
                  table lookup, exposing tables that shouldn't be readable.

    Why no write+read round-trip: anon INSERT is RLS-blocked (intentional;
    we proved that during probe design). Without service-role credentials,
    the smoke is the strongest assertion possible — and it's actually
    sufficient because a wrong table-name mapping in the RPC body would
    raise a Postgres `relation does not exist` error (HTTP 500), not
    silently return null. The smoke catches that.

    Detected drift modes:
      - HTTP 5xx on a positive case  → critical (RPC body broken /
                                       table-name mapping wrong)
      - HTTP 4xx on a positive case  → critical (RPC permissions broken
                                       or whitelist removed this app)
      - body != null on positive     → warning (sentinel polluted —
                                       someone wrote __auto_audit_…)
      - HTTP 200 on negative case    → critical (whitelist enforcement
                                       removed; arbitrary apps pass through)
      - HTTP 4xx but code != '22023' → warning (function still rejects
                                       invalid apps, but the contract
                                       (ERRCODE 22023) drifted)
      - network / DNS                 → warning
    """
    issues: list[dict[str, Any]] = []
    url = STUDY_PLAN_SUPABASE_URL.rstrip("/") + "/rest/v1/rpc/backup_get"

    def _call(p_app: str, p_id: str) -> tuple[int, str, Any]:
        """Returns (status, raw_body, parsed_json_or_None)."""
        body = json.dumps({"p_app": p_app, "p_id": p_id}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "apikey": STUDY_PLAN_SUPABASE_KEY,
                "Authorization": f"Bearer {STUDY_PLAN_SUPABASE_KEY}",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                status = resp.getcode()
        except urllib.error.HTTPError as e:
            # 4xx/5xx land here — capture the body so we can read the
            # ERRCODE and message that postgrest surfaces.
            status = e.code
            try:
                raw = e.read().decode("utf-8", errors="replace")
            except Exception:
                raw = ""
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = None
        return status, raw, parsed

    # ── Positive cases — one per whitelisted app ─────────────────────
    for app_key in BACKUPS_RPC_APPS:
        try:
            status, raw, parsed = _call(app_key, BACKUPS_RPC_SENTINEL_ID)
        except (urllib.error.URLError, TimeoutError) as e:
            issues.append({
                "severity": "warning",
                "kind": "backup_get_rpc_network",
                "msg": f"backup_get(p_app='{app_key}') network error: {e}",
            })
            continue
        except Exception as e:  # pragma: no cover — belt and suspenders
            issues.append({
                "severity": "warning",
                "kind": "backup_get_rpc_unexpected",
                "msg": f"backup_get(p_app='{app_key}') unexpected error: {e}",
            })
            continue

        if 500 <= status < 600:
            # Most likely cause: RPC body references a table that doesn't
            # exist for this app (table-name mapping bug). The Phase 2
            # rollout used `<p_app>_backups` for mishpacha/pnimit/samega
            # — `geri` is whitelisted as an alias but reads from
            # `samega_backups` inside the function body. If that aliasing
            # ever drifts, we'd see HTTP 500 here.
            issues.append({
                "severity": "critical",
                "kind": "backup_get_rpc_server_error",
                "msg": (
                    f"backup_get(p_app='{app_key}') returned HTTP {status} — "
                    f"likely a table-name mapping bug inside the RPC body "
                    f"(check the alias resolution for 'geri' → samega_backups). "
                    f"Body: {raw[:200]!r}"
                ),
            })
            continue

        if 400 <= status < 500:
            # The function returned an error for an app we documented as
            # whitelisted. Either the whitelist was tightened (regression)
            # or anon's GRANT EXECUTE was revoked.
            errcode = parsed.get("code") if isinstance(parsed, dict) else None
            issues.append({
                "severity": "critical",
                "kind": "backup_get_rpc_whitelist_drift",
                "msg": (
                    f"backup_get(p_app='{app_key}') returned HTTP {status} "
                    f"(ERRCODE={errcode!r}). The documented whitelist is "
                    f"{list(BACKUPS_RPC_APPS)}; check that the function body "
                    f"and the GRANT EXECUTE on anon both still cover '{app_key}'."
                ),
            })
            continue

        if status != 200:
            issues.append({
                "severity": "warning",
                "kind": "backup_get_rpc_unexpected_status",
                "msg": f"backup_get(p_app='{app_key}') returned HTTP {status} (expected 200).",
            })
            continue

        # HTTP 200 — postgrest serializes a SQL `null` return as the JSON
        # literal `null`. anything else means the sentinel id has been
        # written to that app's table, which is suspicious (probe-design
        # invariant: this id must never collide with a real backup).
        if parsed is not None:
            issues.append({
                "severity": "warning",
                "kind": "backup_get_rpc_sentinel_polluted",
                "msg": (
                    f"backup_get(p_app='{app_key}', p_id='{BACKUPS_RPC_SENTINEL_ID}') "
                    f"returned a non-null body. The sentinel id should never match a "
                    f"real backup. Likely cause: someone manually inserted a row with "
                    f"this id into {app_key}_backups (or samega_backups for geri). "
                    f"Delete the row to keep the probe a true smoke test. "
                    f"Body: {raw[:120]!r}"
                ),
            })

    # ── Negative case — invalid app must be rejected with ERRCODE 22023
    try:
        status, raw, parsed = _call("__auto_audit_invalid_app__", "x")
    except (urllib.error.URLError, TimeoutError):
        # Network failure on the negative case — already reported by the
        # positive loop above if it's a global outage. Don't double-warn.
        return issues
    except Exception:
        return issues

    if status == 200:
        # The function accepted an obviously-invalid app and returned a row
        # (or null). That's a critical regression — the whitelist was
        # bypassed or removed. An attacker with the publishable key could
        # then enumerate any table whose name matches `<app>_backups`.
        issues.append({
            "severity": "critical",
            "kind": "backup_get_rpc_whitelist_bypassed",
            "msg": (
                f"backup_get(p_app='__auto_audit_invalid_app__') returned HTTP 200 — "
                f"the whitelist enforcement is gone. Any string matching "
                f"`<app>_backups` could now be read. Re-deploy the function with "
                f"the documented `IF p_app NOT IN (...)` guard."
            ),
        })
        return issues

    if 400 <= status < 500:
        errcode = parsed.get("code") if isinstance(parsed, dict) else None
        if errcode != "22023":
            # The function still rejects the invalid app, but with a different
            # error code than documented. Not critical (security still holds)
            # but worth flagging because clients catching '22023' specifically
            # would now miss this branch.
            issues.append({
                "severity": "warning",
                "kind": "backup_get_rpc_errcode_drift",
                "msg": (
                    f"backup_get rejected an invalid app with ERRCODE={errcode!r} "
                    f"(documented: '22023'). Whitelist enforcement still holds, but "
                    f"clients matching on '22023' will fall through to a generic "
                    f"error path. Either restore the documented ERRCODE or update "
                    f"this probe + client error handlers."
                ),
            })
        # else: errcode == '22023' → happy path, no issue
    else:
        issues.append({
            "severity": "warning",
            "kind": "backup_get_rpc_negative_unexpected",
            "msg": (
                f"backup_get(invalid app) returned HTTP {status} — expected 4xx. "
                f"Body: {raw[:120]!r}"
            ),
        })

    return issues


# Watched repos that ship `.github/workflows/notify-auto-audit.yml` — the
# repository_dispatch firing that gives us sub-minute push-to-probe SLA on
# detecting CI-red main. If this set changes (a new PWA joins the family,
# or one is retired), update both this list AND the rotation tooling
# (`scripts/rotate_dispatch_pat.py`'s DEFAULT_REPOS).
DISPATCH_NOTIFY_REPOS: tuple[str, ...] = (
    "Geriatrics", "InternalMedicine", "FamilyMedicine", "ward-helper",
)
DISPATCH_NOTIFY_WORKFLOW = "notify-auto-audit.yml"


def probe_dispatch_chain_health() -> list[dict[str, Any]]:
    """Detect when the post-merge dispatch chain (auto-audit#14) is broken.

    Each watched PWA ships `.github/workflows/notify-auto-audit.yml` that
    fires a `repository_dispatch` to Eiasash/auto-audit on every
    push-to-main. The dispatch needs `AUTO_AUDIT_DISPATCH_PAT` installed
    as a secret in that repo, scoped Actions:write on auto-audit.

    The 30-min cron is the failsafe. The dispatch path is what gives us
    ~15s push-to-probe latency. If the dispatch PAT expires (currently a
    short-lived session PAT — see SESSION_LEARNINGS_2026-04-29 watchlist
    item #1), the dispatch silently degrades back to cron, and we lose
    sub-minute SLA WITHOUT any visible signal. This probe is that signal.

    What it checks: for each watched repo, look at the most recent
    completed run of notify-auto-audit.yml.

      conclusion=='success'   → healthy, no issue
      conclusion=='failure'   → critical: dispatch broken on this repo
      conclusion=='cancelled' → warning: someone cancelled the run
      no completed runs       → warning: workflow exists but never ran
                                (typical right after first install — fine
                                if recent; flag if older than 30d)
      workflow file missing   → critical: notify-auto-audit.yml was
                                deleted or renamed in this repo

    The single-failure threshold is intentional. `probe_workflow_failure_streaks`
    requires N consecutive failures across recent runs and is the right
    tool for noisy-but-eventually-self-healing workflows. notify-auto-audit
    is neither noisy nor self-healing — its only failure mode is auth
    (PAT dead/scope drift), which won't recover on its own. The first
    failed push-to-main IS the signal.

    Why cross_cutting and not per-repo: the typical fix is one PAT
    rotation that recovers all four repos. Grouping the findings makes
    that obvious in the issue body and avoids four duplicate-cause issues.
    """
    issues: list[dict[str, Any]] = []
    workflow = DISPATCH_NOTIFY_WORKFLOW

    for repo in DISPATCH_NOTIFY_REPOS:
        # Pull the 5 most recent runs. We only need the latest *completed*
        # one — runs in `in_progress` / `queued` are skipped because their
        # conclusion is null.
        path = (
            f"/repos/{OWNER}/{repo}/actions/workflows/{workflow}/runs"
            f"?per_page=5"
        )
        try:
            status, data = gh(path)
        except Exception as e:  # pragma: no cover — network/JSON glitches
            issues.append({
                "severity": "warning",
                "kind": "dispatch_chain_probe_error",
                "msg": (
                    f"Could not query notify-auto-audit runs for {repo}: {e}. "
                    f"Probe is non-fatal — cron failsafe still runs."
                ),
            })
            continue

        if status == 404:
            # The workflow file is gone. Either the repo was renamed (we'd
            # see a 404 on the whole repo first), or somebody deleted/
            # renamed notify-auto-audit.yml. Either way, push-to-probe is
            # broken for this repo.
            issues.append({
                "severity": "critical",
                "kind": "dispatch_chain_workflow_missing",
                "msg": (
                    f"{repo}: .github/workflows/{workflow} returned 404. "
                    f"The notify-auto-audit dispatcher is gone — push-to-probe "
                    f"SLA is broken for this repo (cron failsafe still runs). "
                    f"Restore the workflow from sibling repo "
                    f"(e.g. github.com/{OWNER}/Geriatrics/blob/main/.github/workflows/{workflow})."
                ),
            })
            continue

        if status != 200 or not isinstance(data, dict):
            issues.append({
                "severity": "warning",
                "kind": "dispatch_chain_unexpected_status",
                "msg": (
                    f"{repo}: GET notify-auto-audit runs returned HTTP {status}. "
                    f"Probe is non-fatal."
                ),
            })
            continue

        runs = data.get("workflow_runs", []) or []

        if not runs:
            # No runs ever. Could be: workflow newly added and no merge yet
            # (fine), or it never wired up (concerning but not critical).
            # Surface as a one-time warning; future probes will reclassify
            # once a real run lands.
            issues.append({
                "severity": "warning",
                "kind": "dispatch_chain_never_ran",
                "msg": (
                    f"{repo}: {workflow} has no run history. Workflow exists but "
                    f"hasn't fired yet — expected if newly installed. If this "
                    f"persists past the next merge, check the `on: push` trigger."
                ),
            })
            continue

        # First completed run wins. We tolerate an in-flight run at the top.
        latest_completed = next(
            (r for r in runs if r.get("conclusion") in ("success", "failure", "cancelled", "timed_out", "action_required")),
            None,
        )
        if not latest_completed:
            # All recent runs are in_progress or queued. Almost certainly a
            # transient state right at probe time — fine, will resolve.
            continue

        conclusion = latest_completed.get("conclusion")
        run_url = latest_completed.get("html_url", "")
        head_sha = (latest_completed.get("head_sha") or "")[:8]
        created = latest_completed.get("created_at", "?")

        if conclusion == "success":
            # Healthy. No issue.
            continue

        if conclusion == "failure":
            # The dispatch step failed — almost certainly the PAT. The
            # peter-evans/repository-dispatch action surfaces "Bad credentials"
            # with HTTP 401 when the token is dead, missing, or under-scoped.
            issues.append({
                "severity": "critical",
                "kind": "dispatch_chain_run_failed",
                "msg": (
                    f"{repo}: most recent notify-auto-audit run FAILED "
                    f"(sha {head_sha}, {created}). Most likely cause: "
                    f"AUTO_AUDIT_DISPATCH_PAT expired, was revoked, or lost the "
                    f"Actions:write scope on Eiasash/auto-audit. Push-to-probe "
                    f"SLA is broken; cron failsafe still runs every 30 min. "
                    f"Fix: rotate the PAT — see scripts/DISPATCH_PAT_ROTATION.md. "
                    f"Run: {run_url}"
                ),
            })
            continue

        if conclusion in ("cancelled", "timed_out", "action_required"):
            issues.append({
                "severity": "warning",
                "kind": "dispatch_chain_run_unexpected_conclusion",
                "msg": (
                    f"{repo}: most recent notify-auto-audit run finished with "
                    f"conclusion='{conclusion}' (sha {head_sha}, {created}). "
                    f"Not necessarily broken — re-trigger on next merge to confirm. "
                    f"Run: {run_url}"
                ),
            })

    return issues


# ward_helper_pull_by_username RPC — added 2026-04-29 alongside the
# ward_helper_backup.username column (option 2 hybrid bridge: cross-device
# restore via app_users login). The RPC bypasses the auth.uid()-based RLS
# SELECT policy because cross-device pulls cross the auth.uid() boundary.
WARD_HELPER_PULL_RPC = "ward_helper_pull_by_username"
WARD_HELPER_PULL_SENTINEL = "__auto_audit_healthcheck_nonexistent__"


def probe_ward_helper_pull_rpc() -> list[dict[str, Any]]:
    """Smoke-test the ward_helper_pull_by_username(p_username) RPC.

    The 2026-04-29 option 2 bridge added a SECURITY DEFINER RPC that lets
    an authed ward-helper user fetch their encrypted backup blobs from any
    device. It's the ONLY cross-device restore path for ward-helper —
    direct REST SELECT remains RLS-locked to the per-device anon
    auth.users.id, which would return nothing on a fresh device.

    If the RPC breaks, every "log in on a new device → see my history"
    flow silently fails with an empty restore. Same failure-mode shape
    as backup_get_rpc for the PWAs, same probe shape.

    Two cases:
      Positive: pull by a known-nonexistent username
        Expect: HTTP 200, body=[]
        Catches: RPC unreachable (HTTP 5xx), GRANT EXECUTE revoked
                 (HTTP 4xx), table reference broken (HTTP 5xx).
      Sentinel: same call, asserts no row matches the dunder username
        Catches: someone manually inserted a sentinel row → probe is
                 polluted; clean it up.

    Why no negative case (cf. backup_get): backup_get has a strict
    whitelist that raises ERRCODE 22023 on invalid app, so probing the
    rejection branch is meaningful. ward_helper_pull_by_username takes
    a free-form text username — there's no whitelist to test, by design
    (the cap is "knowing the username" + encryption).

    Why no write+read round-trip: the table has a FOREIGN KEY constraint
    `user_id REFERENCES auth.users(id)`. We can't insert a sentinel row
    via anon REST without minting a real auth.users row first, and
    auth.signInAnonymously() is a JS-client API the probe doesn't have.
    The smoke (RPC reachable + returns empty for unknown username) is
    sufficient because a broken table reference inside the RPC would
    raise HTTP 500, not silently return [].
    """
    issues: list[dict[str, Any]] = []
    url = STUDY_PLAN_SUPABASE_URL.rstrip("/") + "/rest/v1/rpc/" + WARD_HELPER_PULL_RPC

    body = json.dumps({"p_username": WARD_HELPER_PULL_SENTINEL}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "apikey": STUDY_PLAN_SUPABASE_KEY,
            # Note: deliberately NOT setting Authorization: Bearer here.
            # The publishable key in `apikey` resolves to the anon role,
            # which has GRANT EXECUTE on this RPC.
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode()
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
    except (urllib.error.URLError, TimeoutError) as e:
        issues.append({
            "severity": "warning",
            "kind": "ward_helper_pull_rpc_network",
            "msg": f"{WARD_HELPER_PULL_RPC} network error: {e}",
        })
        return issues
    except Exception as e:  # pragma: no cover — belt and suspenders
        issues.append({
            "severity": "warning",
            "kind": "ward_helper_pull_rpc_unexpected",
            "msg": f"{WARD_HELPER_PULL_RPC} unexpected error: {e}",
        })
        return issues

    if 500 <= status < 600:
        # Most likely cause: the RPC body references a column or table
        # that no longer exists (schema drift). For instance, if a future
        # migration drops the username column or rotates ward_helper_backup
        # to a new name, the RPC would throw `relation does not exist` or
        # `column does not exist` here.
        issues.append({
            "severity": "critical",
            "kind": "ward_helper_pull_rpc_server_error",
            "msg": (
                f"{WARD_HELPER_PULL_RPC} returned HTTP {status} — likely a "
                f"schema drift breaking the function body (column or table "
                f"reference invalid). Body: {raw[:200]!r}"
            ),
        })
        return issues

    if 400 <= status < 500:
        # The function returned an error for what should be an open RPC.
        # Almost certainly: GRANT EXECUTE was revoked, or the function
        # was dropped.
        issues.append({
            "severity": "critical",
            "kind": "ward_helper_pull_rpc_permission_drift",
            "msg": (
                f"{WARD_HELPER_PULL_RPC} returned HTTP {status}. Either the "
                f"RPC was dropped or anon GRANT EXECUTE was revoked. Body: "
                f"{raw[:200]!r}"
            ),
        })
        return issues

    if status != 200:
        issues.append({
            "severity": "warning",
            "kind": "ward_helper_pull_rpc_unexpected_status",
            "msg": f"{WARD_HELPER_PULL_RPC} returned HTTP {status} (expected 200).",
        })
        return issues

    # HTTP 200 — postgrest serializes a setof-returning function as a
    # JSON array. Empty array is the happy path for a nonexistent username.
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        issues.append({
            "severity": "warning",
            "kind": "ward_helper_pull_rpc_bad_json",
            "msg": f"{WARD_HELPER_PULL_RPC} returned non-JSON body ({raw[:120]!r}).",
        })
        return issues

    if parsed != []:
        # Either the sentinel got polluted by manual writes, OR the RPC
        # is returning something it shouldn't (e.g. ignoring the WHERE
        # clause and dumping all rows — a serious leak).
        issues.append({
            "severity": "warning",
            "kind": "ward_helper_pull_rpc_sentinel_polluted",
            "msg": (
                f"{WARD_HELPER_PULL_RPC}(p_username='{WARD_HELPER_PULL_SENTINEL}') "
                f"returned a non-empty body. Either someone wrote a row with "
                f"username='{WARD_HELPER_PULL_SENTINEL}' (clean it up) OR the "
                f"function is no longer filtering correctly (audit the WHERE "
                f"clause — could be a data leak). Body shape: "
                f"{type(parsed).__name__}, len={len(parsed) if hasattr(parsed, '__len__') else '?'}"
            ),
        })

    return issues


# ─────────────────────────── orchestration ────────────────────────────

def probe_scheduler_health() -> list[dict[str, Any]]:
    """Self-check: did the previous Tier 1 cron tick happen on time?

    GHA scheduled workflows drift on free/low-tier accounts under load
    (documented behaviour). When the cron runs more than 60 min after
    the previous run, raise a warning so we know the scheduler itself
    is unhealthy — separate from any real CI/deploy issue.

    Looks at this workflow's own run history. Skips the check when the
    triggering event isn't 'schedule' (e.g. workflow_dispatch / repository_dispatch
    runs aren't expected on a clock).

    Heartbeat thresholds:
      - delta <= 35 min  : healthy (cron is on time, with small drift)
      - 35 < delta <= 60 : silent (mild drift, no issue raised)
      - 60 < delta       : warning (the scheduler is dropping ticks)
    """
    issues: list[dict[str, Any]] = []
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event != "schedule":
        return issues

    # Self-introspect via gh API. The current run's workflow file is
    # health-check.yml; query its prior runs and compare timestamps.
    try:
        status, data = gh("/repos/{}/{}/actions/workflows/health-check.yml/runs?per_page=5".format(OWNER, "auto-audit"))
        if status != 200:
            return issues
        runs = data.get("workflow_runs", [])
        # The current run is the first entry; we want the previous SCHEDULED run.
        prev_scheduled = None
        for r in runs[1:]:
            if r.get("event") == "schedule":
                prev_scheduled = r
                break
        if not prev_scheduled:
            return issues
        from datetime import datetime as _dt
        now = datetime.now(timezone.utc)
        prev = _dt.fromisoformat(prev_scheduled["created_at"].replace("Z", "+00:00"))
        delta_min = (now - prev).total_seconds() / 60.0
        if delta_min > 60:
            issues.append({
                "severity": "warning",
                "kind": "scheduler-drift",
                "msg": (
                    f"GHA scheduler dropped ticks: previous Tier 1 schedule run was "
                    f"{delta_min:.0f} min ago (expected ≤ 30). Repository_dispatch path "
                    f"(issue #14) is the durable fix — verify AUTO_AUDIT_DISPATCH_PAT "
                    f"is set in all 4 watched repos."
                ),
                "url": f"https://github.com/{OWNER}/auto-audit/actions/workflows/health-check.yml",
            })
    except Exception as e:
        sys.stderr.write(f"[probe] scheduler_health failed: {e}\n")
    return issues


def run() -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "generated_at": started.isoformat(),
        "tool": "auto-audit Tier 1 monitor",
        "repos": {},
        "cross_cutting": {
            "sibling_drift": [],
            "study_plan_parity": [],
            "study_plan_rpc": [],
            "backup_get_rpc": [],
            "dispatch_chain": [],
            "ward_helper_pull_rpc": [],
        },
    }

    for repo, cfg in REPO_CONFIG.items():
        sys.stderr.write(f"[probe] {repo}\n")
        repo_report: dict[str, Any] = {"issues": [], "raw": {}}

        if cfg.get("version_files"):
            v = probe_repo_versions(repo, cfg)
            repo_report["raw"]["versions"] = v["versions"]
            repo_report["issues"].extend(v["issues"])

        live = probe_live_sw(repo, cfg) if cfg.get("sw_url") else {}
        if live:
            repo_report["raw"]["live_sw_version"] = live.get("live_sw_version")
            repo_report["issues"].extend(live.get("issues", []))

        wf = probe_workflows(repo, cfg)
        repo_report["raw"]["workflows"] = wf.get("workflows", {})
        repo_report["issues"].extend(wf.get("issues", []))

        # Catch ad-hoc workflow failure streaks (issue #9). Warns when any
        # workflow under .github/workflows/ has failed N consecutive runs
        # on main. Allowlisted via WORKFLOW_FAILURE_ALLOWLIST.
        repo_report["issues"].extend(probe_workflow_failure_streaks(repo))

        # Deploy-drift cross-check
        if live.get("live_sw_version") and repo_report["raw"].get("versions"):
            repo_report["issues"].extend(probe_deploy_drift(
                repo, cfg, repo_report["raw"]["versions"], live.get("live_sw_version")
            ))

        if cfg.get("audit_url"):
            ep = probe_endpoint(repo + ".self-audit", cfg["audit_url"])
            if ep:
                repo_report["raw"]["self_audit"] = ep.get("snapshot", ep)
                repo_report["issues"].extend(ep.get("issues", []))
        if cfg.get("snapshot_url"):
            ep = probe_endpoint(repo + ".skill-snapshot", cfg["snapshot_url"])
            if ep:
                repo_report["raw"]["skill_snapshot"] = ep.get("snapshot", ep)
                repo_report["issues"].extend(ep.get("issues", []))

                # Toranot-specific: call-count delta alarm (runaway-loop early warning)
                if repo == "Toranot" and ep.get("snapshot", {}).get("tokenUsage"):
                    token_usage = ep["snapshot"]["tokenUsage"]
                    call_count_issues = probe_call_count_delta(token_usage)
                    repo_report["issues"].extend(call_count_issues)

        # Geri-specific: distractor alignment probe (Tier 1, no token needed).
        # Returns the new probe schema (severity/title/body/labels/template);
        # adapt to the existing repo_report["issues"] shape.
        if repo == "Geriatrics":
            try:
                for f in check_distractor_alignment(f"{OWNER}/{repo}"):
                    sev_map = {"CRITICAL": "critical", "WARN": "warning", "ERROR": "error"}
                    issue = {
                        "severity": sev_map.get(f["severity"], "warning"),
                        "kind": f.get("template") or "distractor-alignment",
                        "msg": f["title"],
                    }
                    if f.get("template"):
                        issue["auto_fix"] = f["template"]
                    issue["url"] = (
                        f"https://github.com/{OWNER}/{repo}/blob/main/data/distractors.json"
                    )
                    repo_report["issues"].append(issue)
            except Exception as e:
                sys.stderr.write(f"[probe] distractor_alignment failed: {e}\n")

        report["repos"][repo] = repo_report

    sys.stderr.write("[probe] sibling drift\n")
    report["cross_cutting"]["sibling_drift"] = probe_sibling_drift()

    sys.stderr.write("[probe] study plan parity\n")
    report["cross_cutting"]["study_plan_parity"] = probe_study_plan_parity()

    sys.stderr.write("[probe] honest stats parity\n")
    report["cross_cutting"]["honest_stats_parity"] = probe_honest_stats_parity()

    sys.stderr.write("[probe] study plan rpc smoke\n")
    report["cross_cutting"]["study_plan_rpc"] = probe_study_plan_rpc()

    sys.stderr.write("[probe] backup_get rpc smoke\n")
    report["cross_cutting"]["backup_get_rpc"] = probe_backup_get_rpc()

    sys.stderr.write("[probe] dispatch chain health\n")
    report["cross_cutting"]["dispatch_chain"] = probe_dispatch_chain_health()

    sys.stderr.write("[probe] ward_helper pull rpc smoke\n")
    report["cross_cutting"]["ward_helper_pull_rpc"] = probe_ward_helper_pull_rpc()

    sys.stderr.write("[probe] scheduler health\n")
    report["cross_cutting"]["scheduler_health"] = probe_scheduler_health()

    return report


def render_md(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Health report — {report['generated_at']}")
    lines.append("")
    # Per-repo summary
    for repo, r in report["repos"].items():
        crit = sum(1 for i in r["issues"] if i["severity"] == "critical")
        warn = sum(1 for i in r["issues"] if i["severity"] == "warning")
        err  = sum(1 for i in r["issues"] if i["severity"] == "error")
        emoji = "🔴" if crit else ("🟡" if (warn or err) else "🟢")
        lines.append(f"## {emoji} {repo}")
        if r["raw"].get("versions"):
            lines.append("```")
            for path, ver in r["raw"]["versions"].items():
                lines.append(f"  {path:30}  {ver}")
            if r["raw"].get("live_sw_version"):
                lines.append(f"  {'(live SW)':30}  {r['raw']['live_sw_version']}")
            lines.append("```")
        if r["raw"].get("workflows"):
            lines.append("**Workflows on main:**")
            for name, info in r["raw"]["workflows"].items():
                if name in ("CI", "Deploy to GitHub Pages", "Integrity Guard", "Weekly Audit"):
                    c = info.get("conclusion") or info.get("status")
                    lines.append(f"- {name}: `{c}` ({info.get('sha')})")
        if r["raw"].get("self_audit") or r["raw"].get("skill_snapshot"):
            ss = r["raw"].get("skill_snapshot") or r["raw"].get("self_audit")
            lines.append(f"**Endpoint snapshot:** `{json.dumps(ss, default=str)[:300]}`")
        if r["issues"]:
            lines.append("**Issues:**")
            for i in r["issues"]:
                tag = {"critical": "🔴", "warning": "🟡", "error": "🟠"}.get(i["severity"], "⚪")
                lines.append(f"- {tag} [{i['kind']}] {i['msg']}")
        else:
            lines.append("_No issues._")
        lines.append("")
    # Sibling drift
    sib = report["cross_cutting"]["sibling_drift"]
    if sib:
        lines.append("## 🟡 Cross-cutting: sibling engine drift")
        for i in sib:
            lines.append(f"- {i['kind']}: {i['msg']}")
        lines.append("")
    # Study plan syllabus parity
    spp = report["cross_cutting"].get("study_plan_parity", [])
    if spp:
        lines.append("## 🟡 Cross-cutting: study plan syllabus drift")
        for i in spp:
            lines.append(f"- {i['kind']}: {i['msg']}")
        lines.append("")
    # Study plan RPC smoke (server whitelist, RPC reachability)
    spr = report["cross_cutting"].get("study_plan_rpc", [])
    if spr:
        worst = "🔴" if any(i.get("severity") == "critical" for i in spr) else "🟡"
        lines.append(f"## {worst} Cross-cutting: study plan RPC smoke")
        for i in spr:
            tag = {"critical": "🔴", "warning": "🟡", "error": "🟠"}.get(i.get("severity"), "⚪")
            lines.append(f"- {tag} [{i['kind']}] {i['msg']}")
        lines.append("")
    # backup_get RPC smoke (Phase 2 read path — only way to restore from cloud)
    bgr = report["cross_cutting"].get("backup_get_rpc", [])
    if bgr:
        worst = "🔴" if any(i.get("severity") == "critical" for i in bgr) else "🟡"
        lines.append(f"## {worst} Cross-cutting: backup_get RPC smoke")
        for i in bgr:
            tag = {"critical": "🔴", "warning": "🟡", "error": "🟠"}.get(i.get("severity"), "⚪")
            lines.append(f"- {tag} [{i['kind']}] {i['msg']}")
        lines.append("")
    # Dispatch chain health (notify-auto-audit.yml on each watched PWA)
    dch = report["cross_cutting"].get("dispatch_chain", [])
    if dch:
        worst = "🔴" if any(i.get("severity") == "critical" for i in dch) else "🟡"
        lines.append(f"## {worst} Cross-cutting: post-merge dispatch chain")
        for i in dch:
            tag = {"critical": "🔴", "warning": "🟡", "error": "🟠"}.get(i.get("severity"), "⚪")
            lines.append(f"- {tag} [{i['kind']}] {i['msg']}")
        lines.append("")
    # ward_helper_pull_by_username RPC smoke (cross-device restore path)
    whp = report["cross_cutting"].get("ward_helper_pull_rpc", [])
    if whp:
        worst = "🔴" if any(i.get("severity") == "critical" for i in whp) else "🟡"
        lines.append(f"## {worst} Cross-cutting: ward_helper pull-by-username RPC")
        for i in whp:
            tag = {"critical": "🔴", "warning": "🟡", "error": "🟠"}.get(i.get("severity"), "⚪")
            lines.append(f"- {tag} [{i['kind']}] {i['msg']}")
        lines.append("")
    # Scheduler-health self-probe (catches GHA cron drift before it bites us).
    sched = report["cross_cutting"].get("scheduler_health", [])
    if sched:
        lines.append("## 🟡 Cross-cutting: GHA scheduler drift")
        for i in sched:
            lines.append(f"- [{i['kind']}] {i['msg']}")
        lines.append("")
    return "\n".join(lines)


def file_issue(repo: str, title: str, body: str, labels: list[str]) -> Optional[int]:
    """Open a GH issue. Idempotent-by-title within last 14 days."""
    # Search for an open issue with same title
    q = f'repo:{OWNER}/{repo} is:issue is:open in:title "{title}"'
    status, data = gh(f"/search/issues?q={urllib.request.quote(q)}")
    if status == 200 and isinstance(data, dict) and data.get("total_count", 0) > 0:
        existing = data["items"][0]
        sys.stderr.write(f"[issue] reusing #{existing['number']} in {repo}\n")
        return existing["number"]
    # Ensure labels exist (best-effort, ignore failure)
    for lbl in labels:
        gh(f"/repos/{OWNER}/{repo}/labels", method="POST",
           body={"name": lbl, "color": "ededed"})
    status, data = gh(
        f"/repos/{OWNER}/{repo}/issues", method="POST",
        body={"title": title, "body": body, "labels": labels},
    )
    if status == 201 and isinstance(data, dict):
        sys.stderr.write(f"[issue] created #{data['number']} in {repo}\n")
        return data["number"]
    sys.stderr.write(f"[issue] failed to create in {repo}: HTTP {status} {data}\n")
    return None


def main() -> int:
    if not GH_TOKEN:
        sys.stderr.write("FATAL: GH_TOKEN not set\n")
        return 2

    report = run()
    md = render_md(report)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = report["generated_at"].replace(":", "-").replace("+00:00", "")
    md_path = REPORT_DIR / f"{stamp}.md"
    json_path = REPORT_DIR / f"{stamp}.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    sys.stderr.write(f"[report] wrote {md_path} + {json_path}\n")
    print(md)

    # Per-repo issue creation
    dispatched: list[tuple[str, str, int, bool]] = []  # (repo, template, issue#, ok)
    if not DRY_RUN:
        for repo, r in report["repos"].items():
            # Special handling for call-count-delta alarms (both warning and critical)
            # These open dedicated issues separate from the general critical-findings issue
            call_count_issues = [i for i in r["issues"]
                                if i.get("kind") in ("call_count_runaway_loop", "call_count_elevated")]
            if call_count_issues:
                for issue in call_count_issues:
                    delta = issue.get("delta", 0)
                    severity = issue.get("severity", "warning")
                    title_prefix = "CRITICAL" if severity == "critical" else "WARNING"
                    title = f"[call-count-alarm] {title_prefix}: {delta} calls in 30min — {report['generated_at'][:10]}"

                    body_lines = [
                        f"_Auto-generated by `Eiasash/auto-audit` call-count-delta probe at {report['generated_at']}._",
                        "",
                        "## Alert",
                        "",
                        f"- {issue['msg']}",
                        "",
                        "## Context",
                        "",
                        f"- **Delta**: {delta} calls in ~30 minutes",
                        f"- **Rate**: ~{delta/30:.1f} calls/minute",
                        f"- **Threshold**: {'CRIT' if severity == 'critical' else 'WARN'} at {CALL_COUNT_CRIT_DELTA if severity == 'critical' else CALL_COUNT_WARN_DELTA} calls/30min",
                        "",
                        "## Possible causes",
                        "",
                        "- **Runaway loop**: Auth-failure retry storm, malformed-JSON re-prompt loop",
                        "- **Bulk-gen event**: Legitimate distractor regeneration (check recent commits to PWA repos)",
                        "- **Spike in legitimate usage**: Multiple users hitting the proxy simultaneously",
                        "",
                        "## Investigate",
                        "",
                        "- [ ] Check `/api/self-audit` for recent error patterns",
                        "- [ ] Check Anthropic console for abuse/rate-limit warnings",
                        "- [ ] Review recent commits to PWA repos for bulk-gen triggers",
                        "- [ ] If legitimate bulk-gen, set `BULK_GEN_ACTIVE=1` repo variable to suppress future alarms",
                        "- [ ] If confirmed runaway, investigate and fix the loop; consider rotating proxy secret",
                        "",
                        "## Suppression",
                        "",
                        "To suppress this alarm during legitimate bulk-gen events, set the `BULK_GEN_ACTIVE` "
                        "repository variable to `1` at https://github.com/Eiasash/auto-audit/settings/variables/actions",
                    ]

                    labels = ["auto-audit", "call-count-alarm"]
                    if severity == "critical":
                        labels.extend(["auto-fix-eligible", "priority/high"])

                    file_issue(repo, title, "\n".join(body_lines), labels)

            # Standard critical issue handling
            crits = [i for i in r["issues"] if i["severity"] == "critical"
                     and i.get("kind") not in ("call_count_runaway_loop", "call_count_elevated")]
            if not crits:
                continue
            title = f"[auto-audit] {len(crits)} critical issue(s) — {report['generated_at'][:10]}"
            body_lines = [
                f"_Auto-generated by `Eiasash/auto-audit` Tier 1 monitor at {report['generated_at']}._",
                "",
                "## Critical findings",
                "",
            ]
            auto_fixable = False
            for i in crits:
                body_lines.append(f"- **{i['kind']}** — {i['msg']}")
                if i.get("auto_fix"):
                    body_lines.append(f"  - auto-fix candidate: `{i['auto_fix']}`")
                    auto_fixable = True
                if i.get("url"):
                    body_lines.append(f"  - {i['url']}")
            body_lines += [
                "",
                "## Full repo snapshot",
                "```json",
                json.dumps(r["raw"], indent=2, default=str)[:3000],
                "```",
                "",
                "## What happens next",
                "",
                "* If the `auto-fix-eligible` label is present, the Tier 2 workflow in `Eiasash/auto-audit` "
                "will pick this up and open a PR with a proposed fix.",
                "* Tier 2 never pushes to `main` directly — every fix is a reviewable PR.",
                "* Close this issue once the fix lands; the next probe will confirm green.",
            ]
            labels = ["auto-audit"]
            if auto_fixable:
                labels.append("auto-fix-eligible")
            issue_num = file_issue(repo, title, "\n".join(body_lines), labels)

            # Auto-dispatch known auto-fix templates.
            # Only templates listed in AUTO_DISPATCH_TEMPLATES are eligible —
            # anything else stays manual until it's earned trust.
            # One dispatch per probe cycle per repo (the workflow itself is
            # idempotent re: duplicate runs via auto_audit_workflow_running).
            if issue_num is not None and not AUTO_DISPATCH_DISABLED:
                for crit in crits:
                    template = crit.get("auto_fix")
                    if template not in AUTO_DISPATCH_TEMPLATES:
                        continue
                    wf_file, wf_ref = AUTO_DISPATCH_TEMPLATES[template]
                    if auto_audit_workflow_running(wf_file):
                        sys.stderr.write(
                            f"[auto-dispatch] {wf_file} already running; "
                            f"skipping for {repo}#{issue_num}\n"
                        )
                        # Leave a comment so the issue thread reflects the
                        # decision (no spam — file_issue is idempotent).
                        gh(
                            f"/repos/{OWNER}/{repo}/issues/{issue_num}/comments",
                            method="POST",
                            body={
                                "body": (
                                    f"⏳ Auto-dispatch skipped for `{template}`: "
                                    f"workflow `{wf_file}` is already running on "
                                    f"`Eiasash/auto-audit`. The earlier run will "
                                    f"close this. (Set `AUTO_DISPATCH_DISABLED=1` "
                                    f"in the cron env to revert to manual.)"
                                )
                            },
                        )
                        dispatched.append((repo, template, issue_num, False))
                        break
                    ok = dispatch_auto_audit_workflow(
                        wf_file,
                        inputs={"issue_number": str(issue_num)},
                        ref=wf_ref,
                    )
                    sys.stderr.write(
                        f"[auto-dispatch] {wf_file} dispatched={ok} "
                        f"for {repo}#{issue_num} (template={template})\n"
                    )
                    dispatched.append((repo, template, issue_num, ok))
                    if ok:
                        gh(
                            f"/repos/{OWNER}/{repo}/issues/{issue_num}/comments",
                            method="POST",
                            body={
                                "body": (
                                    f"🤖 Auto-dispatched `{template}` "
                                    f"(`Eiasash/auto-audit/.github/workflows/{wf_file}`).\n\n"
                                    f"The workflow will open a PR back to this repo "
                                    f"in 30–60 min. Track it at "
                                    f"https://github.com/{OWNER}/auto-audit/actions/"
                                    f"workflows/{wf_file}.\n\n"
                                    f"Set `AUTO_DISPATCH_DISABLED=1` in the cron env "
                                    f"to revert to manual click-to-fix."
                                )
                            },
                        )
                    else:
                        gh(
                            f"/repos/{OWNER}/{repo}/issues/{issue_num}/comments",
                            method="POST",
                            body={
                                "body": (
                                    f"⚠️ Auto-dispatch FAILED for `{template}` → "
                                    f"`{wf_file}`. The PAT may be missing "
                                    f"`Actions: Read & write` on `Eiasash/auto-audit`, "
                                    f"or the workflow file is missing. Run it "
                                    f"manually: https://github.com/{OWNER}/auto-audit/"
                                    f"actions/workflows/{wf_file}"
                                )
                            },
                        )
                    break  # one auto-dispatch per repo per cycle is plenty

    # Surface dispatch decisions in the run log so the GH summary shows them.
    if dispatched:
        sys.stderr.write("[auto-dispatch] summary:\n")
        for repo, template, num, ok in dispatched:
            mark = "✓" if ok else "✗"
            sys.stderr.write(f"  {mark} {repo}#{num} → {template}\n")

    # Cross-cutting critical findings → file ONE issue in auto-audit itself,
    # since these issues span multiple repos (e.g. server-side RPC whitelist
    # drift hits all 3 medical PWAs at once). Filing N copies in N repos
    # would just confuse the cleanup.
    cc_critical: list[dict[str, Any]] = []
    for section_name, items in report["cross_cutting"].items():
        for i in items:
            if isinstance(i, dict) and i.get("severity") == "critical":
                cc_critical.append({"section": section_name, **i})

    if cc_critical and not DRY_RUN:
        title = (
            f"[auto-audit] {len(cc_critical)} cross-cutting critical issue(s) — "
            f"{report['generated_at'][:10]}"
        )
        body_lines = [
            f"_Auto-generated by `Eiasash/auto-audit` Tier 1 monitor at "
            f"{report['generated_at']}._",
            "",
            "## Cross-cutting critical findings",
            "",
            "These findings affect shared infrastructure (Supabase RPCs, "
            "sibling engine, syllabus parity) — fix once, all apps recover.",
            "",
        ]
        for i in cc_critical:
            body_lines.append(f"- **[{i['section']}] {i['kind']}** — {i['msg']}")
        body_lines += [
            "",
            "## What happens next",
            "",
            "* No auto-fix template is wired for cross-cutting issues yet — "
            "this is a manual fix.",
            "* For `study_plan_rpc_whitelist_drift`: check the latest "
            "migration on `public.study_plan_get` / `study_plan_upsert` in "
            "Supabase project `krmlzwwelqvlfslwltol`. The whitelist must "
            "match `STUDY_PLAN_RPC_APPS` in `scripts/probe.py`.",
            "* For `backup_get_rpc_*`: read path for the Phase 2 backups "
            "RLS tightening. Check `public.backup_get(p_app, p_id)` in "
            "Supabase project `krmlzwwelqvlfslwltol`. Whitelist must match "
            "`BACKUPS_RPC_APPS` (`mishpacha`, `pnimit`, `geri`, `samega`); "
            "GRANT EXECUTE must include anon. If `_server_error`, the "
            "function body is broken — most likely the dynamic table-name "
            "lookup tried to read a non-existent table (e.g. `geri_backups` "
            "instead of `samega_backups`). If `_whitelist_bypassed`, the "
            "`IF p_app NOT IN (...)` guard was removed and ANY app string "
            "is now passed through to the lookup — fix immediately.",
            "* For `dispatch_chain_run_failed`: the post-merge "
            "repository_dispatch chain is broken. The 30-min cron failsafe "
            "still runs, but sub-minute push-to-probe SLA is lost until the "
            "PAT is rotated. Run `python scripts/rotate_dispatch_pat.py` "
            "with a fresh fine-grained PAT (Contents:read + Actions:write "
            "on Eiasash/auto-audit). See `scripts/DISPATCH_PAT_ROTATION.md`.",
            "* For `dispatch_chain_workflow_missing`: the affected watched "
            "repo lost `.github/workflows/notify-auto-audit.yml`. Restore "
            "it from any sibling watched repo — the file is identical "
            "across all four.",
            "* For `ward_helper_pull_rpc_*`: the cross-device restore path "
            "for ward-helper (option 2 hybrid bridge, 2026-04-29). Check "
            "`public.ward_helper_pull_by_username(p_username)` in Supabase "
            "project `krmlzwwelqvlfslwltol`. If `_server_error`, the "
            "function body's WHERE clause references a column that drifted "
            "(most likely the `username` column on ward_helper_backup "
            "was dropped or renamed). If `_permission_drift`, GRANT EXECUTE "
            "was revoked on anon — re-grant with `GRANT EXECUTE ON FUNCTION "
            "public.ward_helper_pull_by_username(text) TO anon, authenticated;`. "
            "If `_sentinel_polluted` AND the sentinel id matches the dunder, "
            "delete via SQL (table has no anon DELETE policy).",
            "* Close this issue once the next probe (≤30 min) reports green.",
        ]
        file_issue("auto-audit", title, "\n".join(body_lines), ["auto-audit", "cross-cutting"])

    # Decide exit code based on severity (non-zero so the workflow run is RED visibly)
    any_critical = (
        any(i["severity"] == "critical" for r in report["repos"].values() for i in r["issues"])
        or len(cc_critical) > 0
    )
    return 1 if any_critical else 0


if __name__ == "__main__":
    sys.exit(main())
