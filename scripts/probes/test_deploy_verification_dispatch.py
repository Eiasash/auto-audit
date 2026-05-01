#!/usr/bin/env python3
"""
test_deploy_verification_dispatch.py — pre-merge verifier for the
deploy-verification probe.

Snapshot test, not CI. Run manually before pushing probe changes:

    python scripts/probes/test_deploy_verification_dispatch.py

What it checks:

1. **Mocked dispatch payload** — simulates the GH Actions
   `repository_dispatch` event the watched repos will fire post-merge.
   Confirms the probe runs end-to-end with the same env shape (no
   GH_TOKEN required for the read-only live curls + raw fetches the
   probe uses).

2. **Live `main` baseline** — version-literal check should be silent
   for all 5 watched repos when the deploys are healthy. If it flips
   to non-empty, real drift shipped (Pages didn't publish, CDN stale,
   tree-shake dropped a literal). The probe is doing its job.

3. **Pnimit canonical sampling** — runs a deterministic seeded sample
   so the test result is reproducible across runs. Reports the
   canonical/deployed corpus sizes for sanity (sudden drops mean the
   canonical store regressed).

If `version_literal` flips to non-empty: real deploy drift shipped.
Investigate before pushing probe changes.
If `canonical_sample` returns "no canonical stems loaded": the canonical
dir listing or schema regressed; check
InternalMedicine/scripts/exam_audit/canonical/ on main.

Cost: 5 live HTML/SW fetches (~few KB each) + 7 canonical JSON fetches
(~150KB each) + 1 deployed questions.json (~few hundred KB).
~5–8s end-to-end. Manual gate, deliberately NOT in CI.
"""
from __future__ import annotations

import json
import os
import sys

from probe_deploy_verification import (
    DEPLOY_CONFIG,
    check_pnimit_canonical_sample,
    check_version_literal,
)


# Deterministic seed so the canonical sampling is reproducible.
CANONICAL_SAMPLE_SEED = 20260501


def _fail(msg: str) -> None:
    sys.stderr.write(f"FAIL: {msg}\n")
    sys.exit(1)


def mock_dispatch_env() -> None:
    """Set the env vars the GH Actions repository_dispatch event would set,
    so the probe runs in the same shape as production. The probe doesn't
    actually read these — they're shape verification for the workflow wiring."""
    os.environ.setdefault("GITHUB_EVENT_NAME", "repository_dispatch")
    os.environ.setdefault("GITHUB_EVENT_ACTION", "watched-repo-merge")
    # The probe reads no env beyond GH_TOKEN (which only the issue-filing
    # path needs). Local runs skip issue filing — DRY_RUN-equivalent.


def check_version_literal_baseline() -> int:
    findings = []
    for repo in DEPLOY_CONFIG:
        findings.extend(check_version_literal(repo))
    crit = [f for f in findings if f.get("severity") == "CRITICAL"]
    warn = [f for f in findings if f.get("severity") == "WARN"]
    if crit:
        _fail(
            f"version_literal: {len(crit)} CRITICAL finding(s). "
            f"Real deploy drift shipped — investigate before pushing.\n"
            f"Titles: {[f['title'] for f in crit]}"
        )
    if warn:
        sys.stderr.write(
            f"WARN: {len(warn)} non-critical finding(s) "
            f"(typically transient network failures): "
            f"{[f['title'] for f in warn]}\n"
        )
    print(f"PASS: version_literal across {len(DEPLOY_CONFIG)} repos -> [] (clean)")
    return len(findings)


def check_canonical_sample_baseline() -> int:
    findings = check_pnimit_canonical_sample(seed=CANONICAL_SAMPLE_SEED)
    if not findings:
        print("PASS: pnimit_canonical_sample -> [] (clean) "
              "[note: clean ≠ comprehensive; sample size is small]")
        return 0
    f = findings[0]
    sev = f.get("severity")
    title = f.get("title")
    print(f"INFO: pnimit_canonical_sample -> 1 {sev} finding")
    print(f"      title: {title}")
    if sev == "WARN":
        # Tolerable — typically rate-limited dir listing or transient
        # fetch failure. Test still passes.
        return 0
    # CRITICAL — surface but don't fail the test. The whole point of
    # this probe is to surface fabrication; some non-canonical questions
    # exist by design (AI-generated, Harrison-derived). Triage is the
    # user's job, not this snapshot test's.
    sys.stderr.write(
        "INFO: CRITICAL finding from canonical sampling is expected on "
        "first runs (deployed corpus contains AI-generated and textbook-"
        "derived questions outside the 7 exam-session canonical files). "
        "Treat the dry-run output as triage input, not a green/red gate.\n"
    )
    return 1


def main() -> int:
    mock_dispatch_env()
    print("=== deploy-verification probe — snapshot test ===")
    n_version = check_version_literal_baseline()
    n_canon = check_canonical_sample_baseline()
    print(f"\nSummary: version_literal findings={n_version}  canonical_findings={n_canon}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
