#!/usr/bin/env python3
"""
refresh_syllabus_data.py — pull topics.json + questions.json from all 3 PWAs,
merge with the topic_names.json overlay (clean en/he names for Geri/Pnimit
that the PWA repos themselves don't carry), compute per-topic empirical
frequency, write syllabus_data.json.

Run periodically (after big question additions, or after curating new
topic names in topic_names.json) to keep the study plan generator's
weights and display names current.

Env:
    GITHUB_PAT — read access to Eiasash/{Geriatrics, InternalMedicine, FamilyMedicine}

Output:
    syllabus_data.json (sibling of generate_study_plan.py)

Overlay file:
    topic_names.json (sibling) — see its _README for rationale.
    Mishpacha is skipped — its data/topics.json already has {en, he}.
    For Geri and Pnimit, overlay names take priority over the keyword-derived
    fallback. Missing entries fall back to keyword-derived "title-cased first stem".
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
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "syllabus_data.json")
OVERLAY_FILE = os.path.join(SCRIPT_DIR, "topic_names.json")


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


def load_overlay():
    if not os.path.exists(OVERLAY_FILE):
        return {}
    with open(OVERLAY_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for app, entries in raw.items():
        if app.startswith("_"):
            continue
        idx = {}
        for e in entries:
            idx[e["id"]] = {"en": e.get("en", ""), "he": e.get("he", "")}
        out[app] = idx
    return out


def build_topic_records(label, topics_raw, questions_raw, overlay):
    topics = json.loads(topics_raw)
    qs = json.loads(questions_raw)
    counter = Counter(q.get("ti") for q in qs if "ti" in q)
    app_overlay = overlay.get(label, {})

    records = []
    for i, t in enumerate(topics):
        # Source 1: native repo dict (Mishpacha pattern)
        if isinstance(t, dict):
            name_en = t.get("en") or f"Topic {t.get('id', i)}"
            name_he = t.get("he", "")
            keywords = []
        else:
            # Source 2: overlay (Geri/Pnimit clean names)
            ov = app_overlay.get(i)
            if ov and ov.get("en"):
                name_en = ov["en"]
                name_he = ov.get("he", "")
            else:
                # Source 3: fallback — title-case the first keyword stem
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
            r["frequency_pct"] = round(100 / len(records), 1)
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

    overlay = load_overlay()
    if overlay:
        print(f"  loaded overlay: {sum(len(v) for v in overlay.values())} curated names "
              f"across {list(overlay.keys())}")
    else:
        print("  no overlay file — Geri/Pnimit will use keyword-derived fallback names")

    out = {}
    for label, repo in APPS.items():
        print(f"  fetching {repo}/data/topics.json + questions.json …")
        topics_raw = gh_raw(repo, "data/topics.json", pat)
        questions_raw = gh_raw(repo, "data/questions.json", pat)
        records, n_qs = build_topic_records(label, topics_raw, questions_raw, overlay)
        out[label] = {
            "repo": f"Eiasash/{repo}",
            "total_questions_analyzed": n_qs,
            "total_topics": len(records),
            "topics": records,
        }
        unnamed = [r for r in records if not r["en"] or r["en"].startswith("Topic ")]
        marker = "✓" if not unnamed else f"⚠ {len(unnamed)} unnamed"
        print(f"    -> {n_qs} questions, {len(records)} topics {marker}")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {DATA_FILE} ({os.path.getsize(DATA_FILE):,} bytes)")


if __name__ == "__main__":
    main()
