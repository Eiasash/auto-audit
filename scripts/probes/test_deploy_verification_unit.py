#!/usr/bin/env python3
"""
test_deploy_verification_unit.py — pre-merge unit gate for the
deploy-verification probe. NO NETWORK.

Companion to test_deploy_verification_dispatch.py (which is the live
integration snapshot test). This file freezes two structural decisions
that are easy to "simplify" in a refactor and silently break:

1. **IM `+.0` version-source routing** — IM's deployed APP_VERSION is
   3-part (`10.4.4`) while package.json is 4-part (`10.4.4.0`,
   enforced by regressionGuards.test.js:436). The probe MUST read
   from src/core/constants.js. If a refactor switches it to
   package.json (the easy/uniform default), live grep will fail
   silently because the bundle ships the 3-part form.

2. **Canonical schema dispatch** — IM canonical files are shaped
   `{"questions": {...}, "stats": ...}` (dict-keyed by question
   number) but the probe also tolerates `{"questions": [...]}` and
   plain top-level lists. If a refactor narrows the schema handling,
   future canonical-store format changes break the probe silently.

Run manually before pushing probe changes:

    python scripts/probes/test_deploy_verification_unit.py

Cost: zero network. <100ms.
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import patch

import probe_deploy_verification as probe_mod
from probe_deploy_verification import (
    CANONICAL_SESSION_TAGS,
    DEPLOY_CONFIG,
    NON_CANONICAL_TAGS,
    _expected_version,
    _load_canonical_stems,
    check_pnimit_canonical_sample,
)


def _fail(msg: str) -> None:
    sys.stderr.write(f"FAIL: {msg}\n")
    sys.exit(1)


# ─────────────────────────── test 1: IM version-source freeze ───────────────────────────

def test_im_version_source_routes_to_constants_not_package_json() -> None:
    """IM probe MUST read APP_VERSION from src/core/constants.js (3-part),
    never from package.json (4-part `+.0`). Freezes the routing decision
    against future "let's just use package.json uniformly" refactors.

    Why this matters: live deploy ships the 3-part form. If the probe
    started reading the 4-part form from package.json, every check
    against the live bundle would silently fail because `10.4.4.0`
    doesn't appear there — only `10.4.4` does.
    """
    cfg = DEPLOY_CONFIG.get("InternalMedicine")
    if cfg is None:
        _fail("DEPLOY_CONFIG missing 'InternalMedicine' entry")

    src_path, src_re = cfg["version_source"]
    if src_path != "src/core/constants.js":
        _fail(
            f"IM version_source path is {src_path!r}, expected "
            f"'src/core/constants.js'. The +.0 suffix on package.json "
            f"is intentional (regressionGuards.test.js:436); the probe "
            f"must read APP_VERSION from constants.js to match the "
            f"3-part literal that ships in the live bundle."
        )

    # Behavioural check: feed the function realistic file contents and
    # confirm it returns the 3-part form, not the 4-part.
    fake_constants_js = (
        "// src/core/constants.js\n"
        "export const APP_VERSION = '10.4.4';\n"
        "export const BUILD_HASH = 'q-v10.4.4';\n"
    )
    fake_package_json = '{"name": "pnimit-mega", "version": "10.4.4.0"}'

    def _fake_fetch(repo: str, branch: str, path: str) -> str:
        if path == "src/core/constants.js":
            return fake_constants_js
        if path == "package.json":
            return fake_package_json
        raise AssertionError(f"unexpected fetch: {repo} {branch} {path}")

    with patch.object(probe_mod, "_fetch_repo_file", side_effect=_fake_fetch):
        v = _expected_version("InternalMedicine", cfg, "main")

    if v != "10.4.4":
        _fail(
            f"_expected_version('InternalMedicine', ...) returned {v!r}, "
            f"expected '10.4.4' (3-part from constants.js). If you got "
            f"'10.4.4.0', the routing flipped to package.json — that "
            f"breaks live verification because the deployed bundle "
            f"contains the 3-part form only."
        )

    print("PASS: IM version-source routes to constants.js, returns 3-part")


# ─────────────────────────── test 2: canonical schema dispatch ───────────────────────────

def test_canonical_loader_handles_all_three_shapes() -> None:
    """The Pnimit canonical store currently uses `{"questions": {...}, "stats": ...}`
    (dict-keyed). The probe also tolerates `{"questions": [...]}` (list under
    "questions") and plain top-level `[...]` (no wrapper). If a refactor
    narrows the schema handling, future store format changes break silently.
    """
    fake_files = {
        "scripts/exam_audit/canonical/dict_form.json": {
            "questions": {
                "1": {"q": "stem-A", "o": ["a", "b"], "c": 0},
                "2": {"q": "stem-B  ", "o": ["x", "y"], "c": 1},  # trailing ws
            },
            "stats": {"total": 2},
        },
        "scripts/exam_audit/canonical/list_under_questions.json": {
            "questions": [
                {"q": "stem-C", "o": ["a"], "c": 0},
            ],
        },
        "scripts/exam_audit/canonical/top_level_list.json": [
            {"q": "stem-D", "o": ["a"], "c": 0},
        ],
        # Sanity: a malformed file should be skipped gracefully, not crash.
        "scripts/exam_audit/canonical/malformed.json": "not a list or dict",
    }

    def _fake_listing(repo: str, branch: str, path: str) -> list[str]:
        return list(fake_files.keys())

    def _fake_json(url: str) -> Any:
        # url shape: https://raw.githubusercontent.com/<repo>/<branch>/<path>
        for path, payload in fake_files.items():
            if url.endswith(path):
                return payload
        raise AssertionError(f"unexpected fetch: {url}")

    with patch.object(probe_mod, "_fetch_repo_dir_listing", side_effect=_fake_listing), \
         patch.object(probe_mod, "_fetch_json", side_effect=_fake_json):
        stems, file_count = _load_canonical_stems("main")

    if file_count != len(fake_files):
        _fail(
            f"_load_canonical_stems reported file_count={file_count}, "
            f"expected {len(fake_files)}. Listing dispatch broken."
        )

    expected_stems = {"stem-A", "stem-B", "stem-C", "stem-D"}
    missing = expected_stems - stems
    if missing:
        _fail(
            f"_load_canonical_stems missed {sorted(missing)} from "
            f"the mock corpus. Schema dispatch lost a shape branch. "
            f"Expected all three shapes (dict-keyed, list-under-questions, "
            f"top-level-list) to yield stems."
        )

    extra = stems - expected_stems
    if extra:
        _fail(
            f"_load_canonical_stems produced unexpected stems {sorted(extra)}. "
            f"Either the malformed file leaked, or a fake stem appeared."
        )

    # Trailing-whitespace absorption check (stem-B in dict_form had "  " at end).
    if "stem-B" not in stems:
        _fail(
            "stem-B (with trailing whitespace) was not normalized — the "
            ".strip() call at canonical-load time is missing."
        )

    print("PASS: canonical loader handles dict, list-under-questions, and top-level list shapes")


# ─────────────────────────── test 3: Phase 2 tag-routing freezers ───────────────────────────

def _run_sampler_with_mocks(deployed: list, canonical_stems: set) -> list:
    """Helper: run check_pnimit_canonical_sample with mocked network calls."""
    def _fake_fetch_json(url: str) -> Any:
        if "questions.json" in url:
            return deployed
        # Treat any other URL as a canonical file fetch the loader does
        # internally — we bypass that path by also patching _load_canonical_stems.
        raise AssertionError(f"unexpected fetch_json: {url}")

    def _fake_load_canonical(branch: str) -> tuple:
        return (canonical_stems, len(canonical_stems))

    with patch.object(probe_mod, "_fetch_json", side_effect=_fake_fetch_json), \
         patch.object(probe_mod, "_load_canonical_stems", side_effect=_fake_load_canonical):
        return check_pnimit_canonical_sample(branch="main", sample_size=5, seed=42)


def test_t_routing_skips_non_canonical_tags() -> None:
    """Freezer: questions tagged `t='Harrison'` or `t='Exam'` MUST be skipped
    by the canonical-match assertion. This was the entire point of Phase 2 —
    Phase 1 sampled them uniformly and produced 100% false-positive findings
    (3 of 3 in dry-run: Pnimit indices 1439, 1115, 1415, all `t: 'Harrison'`,
    all medically valid).

    If a refactor accidentally widens the eligible set back to the whole
    corpus, this test fires.
    """
    # All-Harrison deployed corpus + a populated canonical (content irrelevant —
    # we just need _load_canonical_stems to return something so the early
    # "no stems loaded" guard doesn't short-circuit before Phase 2 routing).
    # Phase 1 would have flagged every sample as a fabrication. Phase 2 must
    # skip them all and return at most an empty-eligible WARN.
    deployed = [
        {"q": f"harrison-stem-{i}", "o": ["a", "b"], "c": 0, "t": "Harrison"}
        for i in range(20)
    ]
    findings = _run_sampler_with_mocks(
        deployed, canonical_stems={"unrelated-canonical-stem"}
    )

    # Must NOT include any CRITICAL fabrication finding.
    crits = [f for f in findings if f.get("severity") == "CRITICAL"]
    if crits:
        _fail(
            f"Sampler emitted {len(crits)} CRITICAL finding(s) on an all-`Harrison` "
            f"corpus — Phase 1 false-positive class is back. Tag routing is "
            f"either disabled or Harrison fell off NON_CANONICAL_TAGS. "
            f"First finding title: {crits[0].get('title')!r}"
        )

    # SHOULD include a WARN about empty-eligible (no canonical-tagged questions).
    warns = [f for f in findings if f.get("severity") == "WARN"]
    if not any("no canonical-eligible" in w.get("title", "") for w in warns):
        _fail(
            f"All-`Harrison` corpus should produce a 'no canonical-eligible' WARN "
            f"so the maintainer notices a degenerate sample state. Got "
            f"{[w.get('title') for w in warns]!r} instead."
        )

    print("PASS: tag routing skips Harrison/Exam (no false-positive fabrication finding)")


def test_t_routing_catches_session_tagged_fabrication() -> None:
    """Freezer: when a question with a CANONICAL session tag has a stem that
    doesn't appear in canonical, the CRITICAL fabrication finding MUST fire.
    This is the v9.81 idx 510 detection case — the whole reason the probe
    exists. If Phase 2's tag routing accidentally suppresses canonical-tagged
    samples too, this test catches it.
    """
    # 5 session-tagged questions; one ('FABRICATED') is missing from canonical.
    deployed = [
        {"q": "real-stem-A", "o": ["a"], "c": 0, "t": "2025-Jun"},
        {"q": "real-stem-B", "o": ["a"], "c": 0, "t": "2024-May"},
        {"q": "real-stem-C", "o": ["a"], "c": 0, "t": "2023-Jun"},
        {"q": "FABRICATED-stem", "o": ["a"], "c": 0, "t": "2025-Jun"},
        {"q": "real-stem-E", "o": ["a"], "c": 0, "t": "2022-Jun"},
    ]
    canonical = {"real-stem-A", "real-stem-B", "real-stem-C", "real-stem-E"}
    findings = _run_sampler_with_mocks(deployed, canonical_stems=canonical)

    crits = [f for f in findings if f.get("severity") == "CRITICAL"]
    if not crits:
        _fail(
            "Sampler did NOT emit a CRITICAL finding on a deployed corpus "
            "containing a session-tagged stem absent from canonical. "
            "Phase 2's tag routing has gone too far and is suppressing the "
            "v9.81 detection case. Findings: "
            f"{[f.get('title') for f in findings]!r}"
        )

    # The FABRICATED stem should appear in the diverging-samples block.
    body = crits[0].get("body", "")
    if "FABRICATED-stem" not in body:
        _fail(
            "CRITICAL finding fired but the FABRICATED stem isn't in its "
            "body. Either the diverging-samples block is broken or the stem "
            "snippet length capped it out (it's < 240 chars, so that's not it)."
        )

    print("PASS: tag routing catches session-tagged fabrication (v9.81-class detection)")


def test_unknown_tag_emits_warn() -> None:
    """Freezer: a `t` value that isn't in either CANONICAL_SESSION_TAGS or
    NON_CANONICAL_TAGS must emit a WARN finding. This is the maintenance
    hook — when a 2026 exam ships with `t='2026-Mar'`, the probe nudges the
    maintainer to declare it explicitly instead of silently miscategorising
    the questions.
    """
    deployed = [
        {"q": "stem-1", "o": ["a"], "c": 0, "t": "2025-Jun"},
        {"q": "stem-2", "o": ["a"], "c": 0, "t": "2026-Mar"},  # NOVEL tag
        {"q": "stem-3", "o": ["a"], "c": 0, "t": "Harrison"},
    ]
    canonical = {"stem-1"}
    findings = _run_sampler_with_mocks(deployed, canonical_stems=canonical)

    warns = [f for f in findings if f.get("severity") == "WARN"]
    novel_warns = [w for w in warns if "2026-Mar" in w.get("title", "")]
    if not novel_warns:
        _fail(
            "Sampler did NOT emit a WARN for the novel tag `2026-Mar`. "
            "When a new exam session ships, the probe must surface its tag "
            "so the maintainer adds it to CANONICAL_SESSION_TAGS + creates "
            "the canonical file. Findings: "
            f"{[(f.get('severity'), f.get('title')) for f in findings]!r}"
        )

    print("PASS: unknown tag emits WARN finding (maintenance nudge)")


# ─────────────────────────── orchestration ───────────────────────────

def main() -> int:
    print("=== deploy-verification probe — unit tests (no network) ===")
    test_im_version_source_routes_to_constants_not_package_json()
    test_canonical_loader_handles_all_three_shapes()
    test_t_routing_skips_non_canonical_tags()
    test_t_routing_catches_session_tagged_fabrication()
    test_unknown_tag_emits_warn()
    print("\nAll unit tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
