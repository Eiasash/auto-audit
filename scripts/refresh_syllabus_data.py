#!/usr/bin/env python3
"""
refresh_syllabus_data.py — pull topics.json + questions.json from all 3 PWAs,
compute per-topic empirical frequency, write syllabus_data.json.

Run periodically (after big question additions) to keep the study plan
generator's weights up to date.

Env:
    GITHUB_PAT — PAT with read access to Eiasash/{Geriatrics, InternalMedicine, FamilyMedicine}

Output:
    syllabus_data.json (sibling of generate_study_plan.py)
"""

from __future__ import annotations
import json, os, sys, urllib.request
from collections import Counter

GH_API = "https://api.github.com"
APPS = {
    "Geri":      "Geriatrics",
    "Pnimit":    "InternalMedicine",
    "Mishpacha": "FamilyMedicine",
}
DATA_FILE = os.path.join(os.path.dirname(__file__), "syllabus_data.json")


def gh_raw(repo: str, path: str, pat: str) -> bytes:
    req = urllib.request.Request(
        f"{GH_API}/repos/Eiasash/{repo}/contents/{path}",
        headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github.v3.raw",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def build_topic_records(topics_raw, questions_raw):
    topics = json.loads(topics_raw)
    qs = json.loads(questions_raw)
    counter = Counter(q.get("ti") for q in qs if "ti" in q)
    records = []
    for i, t in enumerate(topics):
        if isinstance(t, dict):
            name_en = t.get("en") or f"Topic {t.get('id', i)}"
            name_he = t.get("he", "")
            keywords = []
        else:
            name_en = (t[0] if t else f"Topic {i}").title()
            name_he = ""
            keywords = list(t)
        n = counter.get(i, 0)
        records.append({
            "id": i, "en": name_en, "he": name_he,
            "keywords": keywords, "n_questions": n,
        })
    total = sum(r["n_questions"] for r in records)
    if total == 0:
        for r in records:
            r["frequency_pct"] = round(100/len(records), 1)
            r["weight"] = 1.0
    else:
        for r in records:
            pct = r["n_questions"] / total * 100
            r["frequency_pct"] = round(pct, 1)
            r["weight"] = round(r["n_questions"] / (total / len(records)), 2)
    records.sort(key=lambda r: -r["n_questions"])
    return records, len(qs)


def main():
    pat = os.environ.get("GITHUB_PAT")
    if not pat:
        sys.exit("GITHUB_PAT env var required (read access to Eiasash repos)")
    out = {}
    for label, repo in APPS.items():
        print(f"  fetching {repo}/data/topics.json + questions.json …")
        topics_raw = gh_raw(repo, "data/topics.json", pat)
        questions_raw = gh_raw(repo, "data/questions.json", pat)
        records, n_qs = build_topic_records(topics_raw, questions_raw)
        out[label] = {
            "repo": f"Eiasash/{repo}",
            "total_questions_analyzed": n_qs,
            "total_topics": len(records),
            "topics": records,
        }
        print(f"    -> {n_qs} questions, {len(records)} topics")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {DATA_FILE} ({os.path.getsize(DATA_FILE):,} bytes)")


if __name__ == "__main__":
    main()
