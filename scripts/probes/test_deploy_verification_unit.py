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
    DEPLOY_CONFIG,
    _expected_version,
    _load_canonical_stems,
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


# ─────────────────────────── orchestration ───────────────────────────

def main() -> int:
    print("=== deploy-verification probe — unit tests (no network) ===")
    test_im_version_source_routes_to_constants_not_package_json()
    test_canonical_loader_handles_all_three_shapes()
    print("\nAll unit tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
