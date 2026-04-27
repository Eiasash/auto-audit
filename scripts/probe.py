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
REPORT_DIR = Path(os.environ.get("REPORT_DIR", "health-reports"))

USER_AGENT = "Eiasash-auto-audit/1.0"


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


def probe_deploy_drift(repo: str, cfg: dict[str, Any], versions: dict[str, str | None],
                       live_ver: str | None) -> list[dict[str, Any]]:
    """If we have a live SW version AND a repo version, they must match."""
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
        issues.append({
            "severity": "critical",
            "kind": "deploy_live_drift",
            "msg": f"Live SW serves v{live_ver} but main has v{sorted(repo_vers)}",
            "auto_fix": "investigate_deploy_pipeline",
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


# ─────────────────────────── orchestration ────────────────────────────

def run() -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "generated_at": started.isoformat(),
        "tool": "auto-audit Tier 1 monitor",
        "repos": {},
        "cross_cutting": {"sibling_drift": []},
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

        report["repos"][repo] = repo_report

    sys.stderr.write("[probe] sibling drift\n")
    report["cross_cutting"]["sibling_drift"] = probe_sibling_drift()

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
    if not DRY_RUN:
        for repo, r in report["repos"].items():
            crits = [i for i in r["issues"] if i["severity"] == "critical"]
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
            file_issue(repo, title, "\n".join(body_lines), labels)

    # Decide exit code based on severity (non-zero so the workflow run is RED visibly)
    any_critical = any(i["severity"] == "critical" for r in report["repos"].values() for i in r["issues"])
    return 1 if any_critical else 0


if __name__ == "__main__":
    sys.exit(main())
