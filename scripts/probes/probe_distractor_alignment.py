"""
probe_distractor_alignment.py — auto-audit Tier 1 probe addition

Detects content-misalignment between data/distractors.json and
data/questions.json in the Geriatrics repo (Shlav A Mega). The existing
distractorsDrift.test.js only checks structural invariants (key types,
array lengths) — it does NOT catch the case where every entry has the
right shape but points at the wrong question's options. This probe
fills that gap from the production side.

Real-world precedent: caught 2,729 of 3,795 entries (72%) silently
misaligned in v10.44.x after the v9.58 answer-key sweep + question
insertions. By design, this probe will fire on the SAME corruption
again.

Drop into: scripts/probes/probe_distractor_alignment.py

Wire into probe.py (Geri-specific check):

    from probes.probe_distractor_alignment import check_distractor_alignment
    if repo == "Eiasash/Geriatrics":
        findings.extend(check_distractor_alignment(repo))

No GH token needed — pulls from raw.githubusercontent.

Threshold: any misalignment is CRITICAL. The generator invariant is
absolute — empty slot in DIS[k] MUST equal Q[k].c. There is no
tolerable rate of drift.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List

RAW_BASE = "https://raw.githubusercontent.com"


def _fetch_json(repo: str, branch: str, path: str) -> Any:
    url = f"{RAW_BASE}/{repo}/{branch}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "auto-audit-probe"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def check_distractor_alignment(
    repo: str = "Eiasash/Geriatrics", branch: str = "main"
) -> List[Dict[str, Any]]:
    """
    Returns at most one finding (the corruption is binary: clean or rotten).

    The check:
        For every key k in DIS, the empty slot in DIS[k] must equal Q[k].c.
        This is the generator's output invariant. If it breaks, the UI
        shows "Wrong because:" rationales on the correct answer.

    Performance: fetches ~6.8MB + ~2MB once per probe run. ~3s.
    Acceptable for a 30-min cron.
    """
    try:
        Q = _fetch_json(repo, branch, "data/questions.json")
        D = _fetch_json(repo, branch, "data/distractors.json")
    except urllib.error.HTTPError as e:
        return [{
            "severity": "WARN",
            "repo": repo,
            "title": "Cannot fetch questions/distractors for alignment probe",
            "body": f"HTTP {e.code} fetching from {branch}.",
            "labels": ["auto-audit"],
            "template": None,
            "template_args": {},
        }]

    aligned = 0
    misaligned = 0
    no_empty = 0
    samples: List[Dict[str, Any]] = []

    for k, v in D.items():
        try:
            i = int(k)
        except (TypeError, ValueError):
            continue
        if not (0 <= i < len(Q)):
            continue
        q = Q[i]
        if not isinstance(q, dict):
            continue
        opts = q.get("o")
        c = q.get("c")
        if not isinstance(opts, list) or not isinstance(c, int):
            continue
        if not isinstance(v, list) or len(v) != len(opts):
            continue
        empty_idx = next(
            (j for j, s in enumerate(v) if not s or not str(s).strip()), -1
        )
        if empty_idx == -1:
            no_empty += 1
            continue
        if empty_idx == c:
            aligned += 1
        else:
            misaligned += 1
            if len(samples) < 5:
                stem = (q.get("q") or "")[:80].replace("\n", " ")
                samples.append({
                    "qIdx": i,
                    "qC": c,
                    "emptyIdx": empty_idx,
                    "stem": stem,
                })

    total = aligned + misaligned + no_empty
    if total == 0:
        return [{
            "severity": "WARN",
            "repo": repo,
            "title": "Distractor alignment probe: no data to check",
            "body": "Both files loaded but no comparable entries were found.",
            "labels": ["auto-audit"],
            "template": None,
            "template_args": {},
        }]

    if misaligned == 0 and no_empty == 0:
        # Healthy. Don't emit a finding.
        return []

    pct = (misaligned / total) * 100.0 if total else 0.0
    body_lines = [
        f"**{misaligned} of {total} entries misaligned** ({pct:.1f}%).",
        "",
        f"- aligned (empty slot == q.c): {aligned}",
        f"- misaligned (empty slot != q.c): {misaligned}",
        f"- no empty slot at all: {no_empty}",
        "",
        "**What this means:** the UI renders 'Wrong because:' rationales on "
        "the correct (green ✓) answer, and silently swallows real "
        "wrong-option rationales. Users see distractor explanations that "
        "don't match the question.",
        "",
        "**Auto-fix:** run the `regenerate_misaligned_distractors` template — "
        "it drops misaligned entries, regenerates via the Toranot proxy, and "
        "opens a PR with a version-trinity bump.",
        "",
        "**Sample misaligned entries:**",
        "```json",
        json.dumps(samples, indent=2, ensure_ascii=False),
        "```",
    ]

    return [{
        "severity": "CRITICAL",
        "repo": repo,
        "title": (
            f"Distractor autopsy data corruption: "
            f"{misaligned}/{total} entries misaligned ({pct:.0f}%)"
        ),
        "body": "\n".join(body_lines),
        "labels": ["auto-audit", "auto-fix-eligible", "data-corruption"],
        "template": "regenerate_misaligned_distractors",
        "template_args": {
            "branch": branch,
            "misaligned_count": misaligned,
            "total": total,
        },
    }]


if __name__ == "__main__":
    import sys
    repo = sys.argv[1] if len(sys.argv) > 1 else "Eiasash/Geriatrics"
    branch = sys.argv[2] if len(sys.argv) > 2 else "main"
    print(json.dumps(check_distractor_alignment(repo, branch), indent=2))
