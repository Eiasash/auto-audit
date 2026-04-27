#!/usr/bin/env python3
"""
test_alignment_dispatch.py — pre-merge verifier for the distractor-alignment probe.

Snapshot test, not CI. Run manually before pushing probe changes:

    python scripts/probes/test_alignment_dispatch.py

Exits 0 if both reference points still behave as expected:

    main          -> no findings (post-v10.45.0, 100% aligned)
    7e893eb       -> 1 CRITICAL finding (~72% misaligned, ~2729/3795)
                    with template "regenerate_misaligned_distractors"

If `main` flips to non-empty: real corruption shipped — investigate before
pushing probe changes (the probe is doing its job).
If `7e893eb` flips to empty: the known-bad SHA was force-pushed away;
update KNOWN_BAD_REF below to a fresh pre-fix commit, OR retire this test.

Cost: two raw.githubusercontent fetches per ref (~6.8MB + ~2MB each = ~17MB),
~6s end-to-end. Acceptable for a manual gate, deliberately NOT in CI.
"""
from __future__ import annotations

import sys

from probe_distractor_alignment import check_distractor_alignment

REPO = "Eiasash/Geriatrics"
KNOWN_GOOD_REF = "main"
KNOWN_BAD_REF = "7e893eb"   # TIS-reclassify commit, pre-v10.45.0

# Tolerance for the known-bad ref: the precise count was 2729/3795, but if a
# rebuild ever changes the exact numbers slightly we still want the test to
# pass as long as the misalignment is materially present.
MIN_MISALIGNED_ON_BAD = 1000


def _fail(msg: str) -> None:
    sys.stderr.write(f"FAIL: {msg}\n")
    sys.exit(1)


def check_good() -> None:
    findings = check_distractor_alignment(REPO, KNOWN_GOOD_REF)
    if findings:
        _fail(
            f"{KNOWN_GOOD_REF} should return [] (clean). Got "
            f"{len(findings)} finding(s): {[f.get('title') for f in findings]}"
        )
    print(f"PASS: {REPO}@{KNOWN_GOOD_REF} -> [] (clean)")


def check_bad() -> None:
    findings = check_distractor_alignment(REPO, KNOWN_BAD_REF)
    if not findings:
        _fail(
            f"{KNOWN_BAD_REF} should return a CRITICAL finding (pre-fix snapshot). "
            f"Got []. The known-bad SHA may have been force-pushed away — "
            f"update KNOWN_BAD_REF or retire this test."
        )
    if len(findings) != 1:
        _fail(f"{KNOWN_BAD_REF} should return exactly 1 finding, got {len(findings)}")
    f = findings[0]
    if f.get("severity") != "CRITICAL":
        _fail(f"expected severity CRITICAL, got {f.get('severity')!r}")
    if f.get("template") != "regenerate_misaligned_distractors":
        _fail(f"expected template regenerate_misaligned_distractors, got {f.get('template')!r}")
    args = f.get("template_args") or {}
    misaligned = args.get("misaligned_count", 0)
    total = args.get("total", 0)
    if misaligned < MIN_MISALIGNED_ON_BAD:
        _fail(
            f"{KNOWN_BAD_REF} reports only {misaligned} misaligned "
            f"(expected >= {MIN_MISALIGNED_ON_BAD}). Did you point at the wrong SHA?"
        )
    if "auto-fix-eligible" not in (f.get("labels") or []):
        _fail(f"expected auto-fix-eligible label, got {f.get('labels')!r}")
    print(
        f"PASS: {REPO}@{KNOWN_BAD_REF} -> CRITICAL "
        f"({misaligned}/{total} misaligned, template={f.get('template')!r})"
    )


if __name__ == "__main__":
    check_good()
    check_bad()
    print("\nOK — probe verified end-to-end. Safe to push.")
    sys.exit(0)
