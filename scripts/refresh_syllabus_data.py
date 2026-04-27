#!/usr/bin/env python3
"""
refresh_syllabus_data.py — pull topics + questions + display names from all
3 PWAs and rebuild syllabus_data.json with clean en/he labels.

DISPLAY NAME SOURCES (verified 2026-04-27):
    Geri      → Eiasash/Geriatrics/shlav-a-mega.html  →  const TOPICS=[...]
    Pnimit    → Eiasash/InternalMedicine/src/core/constants.js  →  export const TOPICS=[...]
    Mishpacha → Eiasash/FamilyMedicine/data/topics.json  →  [{en, he}]

Hebrew names for Geri are bundled in this script (curated against the keyword
arrays in data/topics.json, lined up by index). Edit GERI_HE if you want to
adjust them. For Pnimit, Hebrew is left blank — if you want Hebrew for Pnimit
later, add a similar PNIMIT_HE list.

Env:
    GITHUB_PAT — read access to all 3 repos
"""

from __future__ import annotations
import json, os, re, sys, urllib.request
from collections import Counter

GH_API = "https://api.github.com"
DATA_FILE = os.path.join(os.path.dirname(__file__), "syllabus_data.json")

# ── Curated Hebrew names for Geri (46) ────────────────────────────────────
GERI_HE = [
    "ביולוגיה של ההזדקנות", "דמוגרפיה", "הערכה גריאטרית כוללת", "שבריריות",
    "נפילות", "דליריום", "דמנציה", "דיכאון", "ריבוי תרופות", "תזונה",
    "פצעי לחץ", "אי-נקיטה", "עצירות", "שינה", "כאב", "אוסטאופורוזיס",
    "אוסטאוארטריטיס", "מחלות לב וכלי דם", "אי ספיקת לב", "יתר לחץ דם",
    "שבץ מוחי", "מחלת ריאות חסימתית כרונית", "סוכרת", "בלוטת התריס",
    "אי-ספיקת כליות כרונית", "אנמיה", "סרטן", "זיהומים", "טיפול פליאטיבי",
    "אתיקה", "התעללות בקשישים", "נהיגה", "אפוטרופסות וייפוי כוח",
    "זכויות החולה", "הנחיות מקדימות", "קהילה וטיפול ארוך-טווח", "שיקום",
    "ראייה ושמיעה", "טיפול פריאופרטיבי", "רפואה דחופה גריאטרית",
    "מחלת פרקינסון", "הפרעות קצב", "הפרעות בליעה", "אנדרופאוזה",
    "מניעה וקידום בריאות", "טיפול בין-תחומי",
]


def gh_raw(repo: str, path: str, pat: str) -> bytes:
    req = urllib.request.Request(
        f"{GH_API}/repos/Eiasash/{repo}/contents/{path}",
        headers={"Authorization": f"Bearer {pat}",
                 "Accept": "application/vnd.github.v3.raw"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def extract_geri_topics(pat):
    html = gh_raw("Geriatrics", "shlav-a-mega.html", pat).decode()
    m = re.search(r'const TOPICS=(\[[^\]]+\]);', html)
    if not m:
        raise RuntimeError("Geri TOPICS const not found in shlav-a-mega.html")
    return json.loads(m.group(1))


def extract_pnimit_topics(pat):
    src = gh_raw("InternalMedicine", "src/core/constants.js", pat).decode()
    m = re.search(r"export const TOPICS\s*=\s*(\[[^\]]+\]);", src)
    if not m:
        raise RuntimeError("Pnimit TOPICS export not found in src/core/constants.js")
    return json.loads(m.group(1).replace("'", '"'))


def build_records(en_names, he_names, keyword_arrays, questions):
    counter = Counter(q.get("ti") for q in questions if "ti" in q)
    records = []
    for i, en in enumerate(en_names):
        kws = keyword_arrays[i] if i < len(keyword_arrays) else []
        if isinstance(kws, dict):
            kws = []
        n = counter.get(i, 0)
        records.append({
            "id": i,
            "en": en,
            "he": he_names[i] if i < len(he_names) else "",
            "keywords": kws if isinstance(kws, list) else [],
            "n_questions": n,
        })
    total = sum(r["n_questions"] for r in records) or 1
    for r in records:
        r["frequency_pct"] = round(r["n_questions"] / total * 100, 1)
        r["weight"] = round(r["n_questions"] / (total / len(records)), 2)
    records.sort(key=lambda r: -r["n_questions"])
    return records


def main():
    pat = os.environ.get("GITHUB_PAT")
    if not pat:
        sys.exit("GITHUB_PAT env var required (read access to Eiasash repos)")

    out = {}

    # ── GERI ──────────────────────────────────────────────────────────
    print("  fetching Geriatrics …")
    geri_keywords = json.loads(gh_raw("Geriatrics", "data/topics.json", pat))
    geri_questions = json.loads(gh_raw("Geriatrics", "data/questions.json", pat))
    geri_en = extract_geri_topics(pat)
    if len(geri_en) != len(geri_keywords):
        print(f"  ⚠ Geri: TOPICS const has {len(geri_en)} but data/topics.json has {len(geri_keywords)} — using HTML count")
    he = GERI_HE if len(GERI_HE) == len(geri_en) else [""] * len(geri_en)
    out["Geri"] = {
        "repo": "Eiasash/Geriatrics",
        "total_questions_analyzed": len(geri_questions),
        "total_topics": len(geri_en),
        "topics": build_records(geri_en, he, geri_keywords, geri_questions),
    }
    print(f"    -> {len(geri_questions)} Qs, {len(geri_en)} topics")

    # ── PNIMIT ────────────────────────────────────────────────────────
    print("  fetching InternalMedicine …")
    pnimit_keywords = json.loads(gh_raw("InternalMedicine", "data/topics.json", pat))
    pnimit_questions = json.loads(gh_raw("InternalMedicine", "data/questions.json", pat))
    pnimit_en = extract_pnimit_topics(pat)
    out["Pnimit"] = {
        "repo": "Eiasash/InternalMedicine",
        "total_questions_analyzed": len(pnimit_questions),
        "total_topics": len(pnimit_en),
        "topics": build_records(pnimit_en, [""] * len(pnimit_en), pnimit_keywords, pnimit_questions),
    }
    print(f"    -> {len(pnimit_questions)} Qs, {len(pnimit_en)} topics")

    # ── MISHPACHA ─────────────────────────────────────────────────────
    print("  fetching FamilyMedicine …")
    misha_topics = json.loads(gh_raw("FamilyMedicine", "data/topics.json", pat))
    misha_questions = json.loads(gh_raw("FamilyMedicine", "data/questions.json", pat))
    misha_en = [t.get("en", "") for t in misha_topics]
    misha_he = [t.get("he", "") for t in misha_topics]
    out["Mishpacha"] = {
        "repo": "Eiasash/FamilyMedicine",
        "total_questions_analyzed": len(misha_questions),
        "total_topics": len(misha_en),
        "topics": build_records(misha_en, misha_he, [[]] * len(misha_en), misha_questions),
    }
    print(f"    -> {len(misha_questions)} Qs, {len(misha_en)} topics")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {DATA_FILE} ({os.path.getsize(DATA_FILE):,} bytes)")


if __name__ == "__main__":
    main()
