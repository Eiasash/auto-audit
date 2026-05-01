"""
probe_deploy_verification.py — auto-audit Tier 1 probe addition (Phase 1)

Two checks, one module:

1. **Version-literal check** (all 5 watched PWA repos) — replicates the
   logic of each repo's `scripts/verify-deploy.sh`: curls the live URL,
   asserts the new version literal actually appears in deployed assets.
   Catches "Pages publish silently failed", "CDN serves stale", and
   "Vite tree-shake dropped a define'd literal" failure modes that
   existing probe_live_sw / probe_deploy_drift don't see (they only
   check sw.js — not HTML inline markers, not hashed bundles, and
   they skip watch-advisor2 entirely).

   Mismatch → CRITICAL, labels: auto-audit + auto-fix-eligible.
   The fix template is `version_trinity` (existing) — a stale live
   deploy is almost always a stuck Pages workflow or trinity drift.

2. **Pnimit canonical sampling** — Pnimit-only this phase. Fetches
   `data/questions.json` from the deployed site, picks 5 random
   questions, and asserts each `q` stem appears verbatim somewhere in
   `scripts/exam_audit/canonical/*.json` on main. Catches the v9.81
   idx 510 fabrication class — option text/explanations are easier
   to fabricate than question stems, but a fabricated stem means the
   whole record is suspect.

   Mismatch → CRITICAL, label: auto-audit only.
   NO `auto-fix-eligible` — fabrication is not mechanically reversible;
   needs a human re-extract from source PDF.

   **Phase 2 (tag-routed sampling):** Sampling pre-filters to
   `t in CANONICAL_SESSION_TAGS` — the exam-session tags whose
   questions are canonical-grounded under `scripts/exam_audit/canonical/`.
   `t: 'Harrison'` (~589 q) and `t: 'Exam'` (~20 q) are skipped:
   they're deliberately not canonical-mirrored, and Phase 1's uniform
   sampling produced false positives on every non-canonical draw.
   New `t` values surface as a WARN finding so the maintainer can
   decide handling (add to CANONICAL_SESSION_TAGS + create canonical
   file, or add to NON_CANONICAL_TAGS to skip).
   Future Phase 3: per-tag verification via an optional `source`
   field (Harrison chapter/page, AI model+date) — not yet wired.

Drop into: scripts/probes/probe_deploy_verification.py

Wire into probe.py orchestration (after the distractor-alignment block):

    from probes.probe_deploy_verification import (
        check_version_literal,
        check_pnimit_canonical_sample,
    )
    for r, dcfg in DEPLOY_CONFIG.items():
        for f in check_version_literal(r):
            ... convert to issue dict ...
    if repo == "InternalMedicine":
        for f in check_pnimit_canonical_sample():
            ... convert to issue dict ...

Pnimit version-source gotcha: package.json carries a 4-part `+.0`
suffix enforced by tests/regressionGuards.test.js:436. Live ships
the 3-part APP_VERSION from src/core/constants.js. This probe reads
constants.js for IM, NOT package.json. Don't normalize the .0
elsewhere — it's deliberate.

No GH token needed for the live curls (raw.githubusercontent +
github.io + netlify.app are all public).
"""
from __future__ import annotations

import json
import random
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

RAW_BASE = "https://raw.githubusercontent.com"
USER_AGENT = "auto-audit-probe-deploy-verification"
HTTP_TIMEOUT = 30

# Per-repo deploy verification config. Mirrors each repo's
# scripts/verify-deploy.sh. Adding watch-advisor2 here does NOT add it
# to the global REPO_CONFIG (that would cascade scope to every other
# probe); Phase 1 keeps watch-advisor2 in deploy-verification only.
DEPLOY_CONFIG: Dict[str, Dict[str, Any]] = {
    "Geriatrics": {
        "live_html": "https://eiasash.github.io/Geriatrics/shlav-a-mega.html",
        "live_sw":   "https://eiasash.github.io/Geriatrics/sw.js",
        "html_re":   r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]",
        "sw_re":     r"CACHE\s*=\s*['\"]shlav-a-v([^'\"]+)['\"]",
        "version_source": ("package.json", r'"version"\s*:\s*"([^"]+)"'),
    },
    "InternalMedicine": {
        "live_html":  "https://eiasash.github.io/InternalMedicine/pnimit-mega.html",
        "live_sw":    "https://eiasash.github.io/InternalMedicine/sw.js",
        # HTML is a thin shell; APP_VERSION is bundled into a hashed asset.
        "bundle_path_re": r"/InternalMedicine/assets/pnimit-mega-[A-Za-z0-9_-]+\.js",
        "bundle_match":   '"{version}"',
        "sw_re":          r"CACHE\s*=\s*['\"]pnimit-v([^'\"]+)['\"]",
        # IM-specific: read APP_VERSION from constants.js, NOT package.json.
        # See top-of-file docstring for the +.0 gotcha.
        "version_source": ("src/core/constants.js", r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]"),
    },
    "FamilyMedicine": {
        "live_html": "https://eiasash.github.io/FamilyMedicine/mishpacha-mega.html",
        "live_sw":   "https://eiasash.github.io/FamilyMedicine/sw.js",
        "bundle_path_re": r"/FamilyMedicine/assets/mishpacha-mega-[A-Za-z0-9_-]+\.js",
        "bundle_match":   "q-v{version}",   # BUILD_HASH suffix from constants.js
        "sw_re":          r"CACHE\s*=\s*['\"]mishpacha-v([^'\"]+)['\"]",
        "version_source": ("package.json", r'"version"\s*:\s*"([^"]+)"'),
    },
    "ward-helper": {
        # No HTML inline marker — index.html is a thin shell. sw.js is the witness.
        "live_sw": "https://eiasash.github.io/ward-helper/sw.js",
        "sw_re":   r"VERSION\s*=\s*['\"]ward-v([^'\"]+)['\"]",
        "version_source": ("package.json", r'"version"\s*:\s*"([^"]+)"'),
    },
    "watch-advisor2": {
        "live_html":      "https://watch-advisor2.netlify.app/",
        "bundle_path_re": r"/assets/index-[A-Za-z0-9_-]+\.js",
        "bundle_match":   '"{version}"',  # __BUILD_NUMBER__ injected via Vite define
        # SW key (wa2-shell-v13) is hardcoded and decoupled from version, so
        # it cannot witness deploys. Bundle literal is the only marker.
        "version_source": ("package.json", r'"version"\s*:\s*"([^"]+)"'),
    },
}

# Pnimit canonical sampling
CANONICAL_DIR = "scripts/exam_audit/canonical"
DEPLOYED_QUESTIONS_URL = "https://eiasash.github.io/InternalMedicine/data/questions.json"
PNIMIT_REPO = "Eiasash/InternalMedicine"

# Phase 2 tag routing: only questions whose `t` field is one of these tags
# are canonical-grounded under scripts/exam_audit/canonical/. The sampler
# pre-filters to these before doing the canonical-match assertion.
#
# Maintenance: when a new exam session ships, add its tag here AND create
# the matching canonical file under InternalMedicine/scripts/exam_audit/
# canonical/. The probe's "unknown tag" WARN finding nudges the maintainer
# if a tag appears in the deployed bundle but isn't declared here.
#
# Sourced from the 2026-05-01 deployed Pnimit corpus tally (1556 q).
CANONICAL_SESSION_TAGS: frozenset = frozenset({
    "2020", "2021-Jun", "2022-Jun", "2023-Jun",
    "2024-May", "2024-Oct", "2025-Jun",
})

# Tags whose questions are deliberately NOT canonical-grounded — Harrison-
# derived, AI-generated, or imported from other non-IMA sources. Phase 2
# skips these in canonical sampling. Phase 3 (not yet implemented) will
# verify them per-tag via an optional `source` field on each question.
NON_CANONICAL_TAGS: frozenset = frozenset({
    "Harrison", "Exam",
})


# ─────────────────────────── helpers ───────────────────────────

def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def _fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read())


def _fetch_repo_file(repo: str, branch: str, path: str) -> str:
    return _fetch_text(f"{RAW_BASE}/{repo}/{branch}/{path}")


def _fetch_repo_dir_listing(repo: str, branch: str, path: str) -> List[str]:
    """Use the GitHub contents API (anonymous, public-repo only) to list files in a dir."""
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    try:
        data = _fetch_json(api_url)
    except urllib.error.HTTPError:
        return []
    if not isinstance(data, list):
        return []
    return [item["path"] for item in data if item.get("type") == "file" and item.get("name", "").endswith(".json")]


# ─────────────────────────── version-literal check ───────────────────────────

def _expected_version(repo: str, cfg: Dict[str, Any], branch: str) -> Optional[str]:
    """Read the source-of-truth version from main."""
    src_path, src_re = cfg["version_source"]
    try:
        text = _fetch_repo_file(f"Eiasash/{repo}", branch, src_path)
    except urllib.error.HTTPError:
        return None
    m = re.search(src_re, text)
    return m.group(1) if m else None


def check_version_literal(
    repo: str, branch: str = "main"
) -> List[Dict[str, Any]]:
    """
    Replicates scripts/verify-deploy.sh from the auto-audit side.
    Returns at most one finding per repo (mismatch is binary).

    Per-repo asset shapes:
        Geriatrics       — HTML APP_VERSION + sw.js shlav-a-v
        InternalMedicine — bundle literal + sw.js pnimit-v
        FamilyMedicine   — bundle q-v + sw.js mishpacha-v
        ward-helper      — sw.js ward-v
        watch-advisor2   — bundle literal (no SW marker)
    """
    cfg = DEPLOY_CONFIG.get(repo)
    if not cfg:
        return []

    expected = _expected_version(repo, cfg, branch)
    if not expected:
        return [{
            "severity": "WARN",
            "repo": repo,
            "title": f"Deploy verification: cannot read source version for {repo}",
            "body": f"Could not fetch or parse `{cfg['version_source'][0]}` on `{branch}`.",
            "labels": ["auto-audit"],
            "template": None,
            "template_args": {},
        }]

    failures: List[str] = []

    # 1. HTML inline marker (Geriatrics only — others have a thin shell)
    if cfg.get("html_re") and cfg.get("live_html"):
        try:
            html = _fetch_text(f"{cfg['live_html']}?cb={random.randint(1, 1_000_000)}")
            m = re.search(cfg["html_re"], html)
            live_html_ver = m.group(1) if m else None
            if live_html_ver != expected:
                failures.append(
                    f"HTML inline `APP_VERSION` is `{live_html_ver}` (expected `{expected}`)"
                )
        except urllib.error.URLError as e:
            failures.append(f"HTML unreachable: {e}")

    # 2. Hashed bundle literal (Vite-built repos)
    if cfg.get("bundle_path_re") and cfg.get("live_html"):
        try:
            html = _fetch_text(f"{cfg['live_html']}?cb={random.randint(1, 1_000_000)}")
            bm = re.search(cfg["bundle_path_re"], html)
            if not bm:
                failures.append(
                    f"Bundle path regex `{cfg['bundle_path_re']}` matched nothing in live HTML"
                )
            else:
                # bundle_path_re yields a path beginning with '/...'; resolve against site origin.
                bundle_path = bm.group(0)
                origin = re.match(r"^https?://[^/]+", cfg["live_html"]).group(0)
                bundle_url = origin + bundle_path
                bundle_body = _fetch_text(bundle_url)
                needle = cfg["bundle_match"].format(version=expected)
                if needle not in bundle_body:
                    failures.append(
                        f"Bundle `{bundle_path}` is missing literal `{needle}` "
                        f"(possibly tree-shaken or stale)"
                    )
        except urllib.error.URLError as e:
            failures.append(f"Bundle fetch failed: {e}")

    # 3. sw.js cache marker
    if cfg.get("sw_re") and cfg.get("live_sw"):
        try:
            sw_body = _fetch_text(f"{cfg['live_sw']}?cb={random.randint(1, 1_000_000)}")
            sm = re.search(cfg["sw_re"], sw_body)
            live_sw_ver = sm.group(1) if sm else None
            if live_sw_ver != expected:
                failures.append(
                    f"sw.js marker is `{live_sw_ver}` (expected `{expected}`)"
                )
        except urllib.error.URLError as e:
            failures.append(f"sw.js unreachable: {e}")

    if not failures:
        return []

    body_lines = [
        f"**Live deploy doesn't match `{cfg['version_source'][0]}` on `{branch}` (expected v{expected}).**",
        "",
        "Failed assertions:",
    ]
    body_lines.extend(f"- {f}" for f in failures)
    body_lines += [
        "",
        "**What this means:** local trinity may be aligned but the deploy didn't actually publish, "
        "or the CDN is serving a stale asset, or a Vite plugin tree-shook the version literal "
        "out of the bundle. Either way, users aren't getting the version `package.json` claims.",
        "",
        "**Auto-fix:** the `version_trinity` template will re-validate local sources and "
        "re-trigger the deploy workflow. If failures persist after the workflow re-runs, "
        "the issue is upstream of the version files (Pages config, CDN, or build plugin).",
        "",
        f"Verify locally with: `bash scripts/verify-deploy.sh` (in the {repo} working tree).",
    ]

    return [{
        "severity": "CRITICAL",
        "repo": repo,
        "title": f"Deploy live-witness mismatch: {repo} expected v{expected}",
        "body": "\n".join(body_lines),
        "labels": ["auto-audit", "auto-fix-eligible", "deploy-drift"],
        "template": "version_trinity",
        "template_args": {
            "branch": branch,
            "expected_version": expected,
            "failure_count": len(failures),
        },
    }]


# ─────────────────────────── Pnimit canonical sampling ───────────────────────────

def _load_canonical_stems(branch: str) -> Tuple[set, int]:
    """Load every `q` field from every canonical file. Returns (stems, file_count).

    Canonical files are shaped `{"questions": {...|[...]}, "stats": ...}` —
    `questions` may be a dict keyed by question number or a list. Stems are
    stripped to absorb trailing-whitespace drift between exports.
    """
    stems: set = set()
    files = _fetch_repo_dir_listing(PNIMIT_REPO, branch, CANONICAL_DIR)
    for path in files:
        try:
            data = _fetch_json(f"{RAW_BASE}/{PNIMIT_REPO}/{branch}/{path}")
        except urllib.error.HTTPError:
            continue
        # Drill into the questions container if present.
        if isinstance(data, dict) and "questions" in data:
            container = data["questions"]
        else:
            container = data
        if isinstance(container, dict):
            iterable = container.values()
        elif isinstance(container, list):
            iterable = container
        else:
            continue
        for q in iterable:
            if isinstance(q, dict) and isinstance(q.get("q"), str):
                stems.add(q["q"].strip())
    return stems, len(files)


def check_pnimit_canonical_sample(
    branch: str = "main", sample_size: int = 5, seed: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Sample N questions from the deployed bundle and assert each `q` stem
    appears verbatim somewhere in scripts/exam_audit/canonical/*.json.

    Returns at most one finding (corruption is binary in spirit, even
    though we sample stochastically).

    Cost: 1 fetch of deployed questions.json (~few hundred KB) + 7 fetches
    of canonical/*.json. ~3-5s end-to-end.
    """
    rng = random.Random(seed)
    try:
        deployed = _fetch_json(DEPLOYED_QUESTIONS_URL)
    except urllib.error.URLError as e:
        return [{
            "severity": "WARN",
            "repo": "InternalMedicine",
            "title": "Canonical sampling: cannot fetch deployed questions.json",
            "body": f"Live URL unreachable: {e}",
            "labels": ["auto-audit"],
            "template": None,
            "template_args": {},
        }]

    if not isinstance(deployed, list) or not deployed:
        return [{
            "severity": "WARN",
            "repo": "InternalMedicine",
            "title": "Canonical sampling: deployed questions.json has unexpected shape",
            "body": f"Expected non-empty list; got {type(deployed).__name__} (len={len(deployed) if hasattr(deployed, '__len__') else 'n/a'}).",
            "labels": ["auto-audit"],
            "template": None,
            "template_args": {},
        }]

    canonical_stems, canon_files = _load_canonical_stems(branch)
    if not canonical_stems:
        return [{
            "severity": "WARN",
            "repo": "InternalMedicine",
            "title": "Canonical sampling: no canonical stems loaded",
            "body": (
                f"Could not load any canonical questions from `{CANONICAL_DIR}/*.json` "
                f"on `{branch}` (found {canon_files} files). The probe cannot validate "
                "deployed questions without a canonical reference."
            ),
            "labels": ["auto-audit"],
            "template": None,
            "template_args": {},
        }]

    # Phase 2 tag routing: pre-filter to canonical-eligible indices and
    # surface any unrecognized tags as a separate WARN finding so they
    # don't accumulate silently when a new exam session lands.
    known_tags = CANONICAL_SESSION_TAGS | NON_CANONICAL_TAGS
    all_tags_seen: set = set()
    eligible: List[int] = []
    for i, q in enumerate(deployed):
        if not isinstance(q, dict):
            continue
        t = q.get("t")
        if t is not None:
            all_tags_seen.add(t)
        if t in CANONICAL_SESSION_TAGS:
            eligible.append(i)

    findings: List[Dict[str, Any]] = []

    unknown_tags = all_tags_seen - known_tags
    if unknown_tags:
        findings.append({
            "severity": "WARN",
            "repo": "InternalMedicine",
            "title": (
                f"Pnimit deployed bundle has unrecognized `t` value(s): "
                f"{sorted(unknown_tags)}"
            ),
            "body": (
                f"`data/questions.json` on the live deploy contains "
                f"{len(unknown_tags)} `t` value(s) not declared in this probe's "
                f"`CANONICAL_SESSION_TAGS` or `NON_CANONICAL_TAGS`: "
                f"{sorted(unknown_tags)}.\n\n"
                f"Decide handling before this accumulates silently:\n"
                f"- New exam session → add tag to `CANONICAL_SESSION_TAGS` AND "
                f"create the matching canonical file under `{CANONICAL_DIR}/`.\n"
                f"- New non-canonical source (textbook, AI model, etc.) → add "
                f"to `NON_CANONICAL_TAGS` so the sampler skips it correctly.\n\n"
                f"Sample-eligible this run: {len(eligible)}/{len(deployed)} "
                f"questions. Unknown-tag questions are excluded from sampling."
            ),
            "labels": ["auto-audit"],
            "template": None,
            "template_args": {},
        })

    if not eligible:
        findings.append({
            "severity": "WARN",
            "repo": "InternalMedicine",
            "title": (
                "Pnimit canonical sampling: no canonical-eligible questions "
                "in deployed corpus"
            ),
            "body": (
                f"Of {len(deployed)} deployed questions, none have `t` in "
                f"`CANONICAL_SESSION_TAGS` ({sorted(CANONICAL_SESSION_TAGS)}). "
                f"The probe cannot canonical-match anything — either every "
                f"canonical-tagged exam was retired, or the deployed corpus "
                f"shape changed, or all sessions were re-tagged."
            ),
            "labels": ["auto-audit"],
            "template": None,
            "template_args": {},
        })
        return findings

    # Sample N canonical-eligible indices without replacement
    n = min(sample_size, len(eligible))
    indices = rng.sample(eligible, n)
    mismatches: List[Dict[str, Any]] = []
    for idx in indices:
        q = deployed[idx]
        stem = q.get("q")
        if not isinstance(stem, str):
            continue
        if stem.strip() not in canonical_stems:
            mismatches.append({
                "idx": idx,
                "t": q.get("t"),
                "deployed_q": stem[:240],
                "stem_len": len(stem),
            })

    if not mismatches:
        return findings  # may contain the unknown-tags WARN above

    body_lines = [
        f"**{len(mismatches)} of {n} sampled questions have stems that do NOT appear "
        f"in any canonical file under `{CANONICAL_DIR}/` on `{branch}`.**",
        "",
        f"Canonical corpus: {len(canonical_stems)} unique stems across {canon_files} session files.",
        f"Deployed corpus: {len(deployed)} questions.",
        "",
        "**What this means:** the deployed bundle contains question text that doesn't "
        "match any source-of-truth canonical record. This is the v9.81 idx 510 "
        "fabrication class — option text and explanations can be fabricated, but a "
        "fabricated *stem* means the whole record is suspect.",
        "",
        "**This is NOT auto-fixable.** Fabrication requires a human re-extract from the "
        "source PDF; mechanical regeneration cannot restore truth that was never there. "
        "The fix path: locate the original exam-session PDF, re-run "
        "`scripts/exam_audit/parse_questions.py` for that session, diff against the "
        "deployed copy, and reconcile in a human-reviewed PR.",
        "",
        "**Diverging samples:**",
        "```json",
        json.dumps(mismatches, indent=2, ensure_ascii=False),
        "```",
    ]

    findings.append({
        "severity": "CRITICAL",
        "repo": "InternalMedicine",
        "title": (
            f"Pnimit canonical fabrication: {len(mismatches)}/{n} sampled "
            "deployed questions have no canonical match"
        ),
        "body": "\n".join(body_lines),
        # NO auto-fix-eligible — fabrication isn't mechanically reversible.
        "labels": ["auto-audit", "content-fabrication"],
        "template": None,
        "template_args": {},
    })
    return findings


# ─────────────────────────── CLI ───────────────────────────

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    findings: List[Dict[str, Any]] = []
    if mode in ("all", "version"):
        for repo_name in DEPLOY_CONFIG:
            findings.extend(check_version_literal(repo_name))
    if mode in ("all", "canonical"):
        findings.extend(check_pnimit_canonical_sample())
    print(json.dumps(findings, indent=2, ensure_ascii=False))
    sys.exit(1 if any(f.get("severity") == "CRITICAL" for f in findings) else 0)
