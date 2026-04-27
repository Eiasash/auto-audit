#!/usr/bin/env python3
"""
generate_study_plan.py v2 — IMA exam study plan generator.

Generates a frequency-weighted study plan for one of three Israeli medical
exams (Geriatrics / Internal Medicine / Family Medicine), using empirical
question-frequency data from past exams (extracted from the live PWA
question banks) rather than hand-curated tier guesses.

DATA SOURCE
-----------
`syllabus_data.json` (sibling file) is built from:
  - Eiasash/Geriatrics/data/topics.json + questions.json     (3833 Qs, 46 topics)
  - Eiasash/InternalMedicine/data/topics.json + questions.json  (1556 Qs, 24 topics)
  - Eiasash/FamilyMedicine/data/topics.json + questions.json    (1061 Qs, 27 topics)

To refresh the data: re-run `scripts/refresh_syllabus_data.py` (TODO).

USAGE
-----
    python generate_study_plan.py --app geri --exam-date 2026-09-15 --hours-per-week 8
    python generate_study_plan.py --app pnimit --exam-date 2026-12-01 --hours-per-week 12
    python generate_study_plan.py --app mishpacha --exam-date 2026-10-15
"""

from __future__ import annotations
import argparse, json, os
from datetime import date, timedelta

DATA_FILE = os.path.join(os.path.dirname(__file__), "syllabus_data.json")

APP_META = {
    "geri":      {"label": "Geriatrics (Stage A — P005-2026)",
                  "deploy_url": "https://eiasash.github.io/Geriatrics/",
                  "n_questions_target_per_day": 25},
    "pnimit":    {"label": "Internal Medicine (Stage A — P0064-2025)",
                  "deploy_url": "https://eiasash.github.io/InternalMedicine/",
                  "n_questions_target_per_day": 30},
    "mishpacha": {"label": "Family Medicine (Stage A — P0062-2025)",
                  "deploy_url": "https://eiasash.github.io/FamilyMedicine/",
                  "n_questions_target_per_day": 25},
}

APP_TO_KEY = {"geri": "Geri", "pnimit": "Pnimit", "mishpacha": "Mishpacha"}


def allocate_hours(topics: list[dict], total_hours: float) -> list[dict]:
    """Assign hours to each topic by frequency_pct, with floor of 0.5h
       and ceiling of 6h per topic to avoid degenerate distributions."""
    out = []
    total_freq = sum(t["frequency_pct"] for t in topics) or 100.0
    for t in topics:
        share = t["frequency_pct"] / total_freq
        h = round(max(0.5, min(6.0, share * total_hours)), 1)
        out.append({**t, "hours": h})
    return out


def schedule(topics: list[dict], hours_per_week: float, weeks: int) -> list[list[dict]]:
    """Greedy weekly allocation: high-frequency topics first, fill week up to
       0.7 * hours_per_week (rest reserved for Q-bank work)."""
    weekly_budget = hours_per_week * 0.7
    sorted_topics = sorted(topics, key=lambda t: -t["frequency_pct"])
    weeks_arr = [[] for _ in range(weeks)]
    used = [0.0] * weeks
    for t in sorted_topics:
        # find first week with capacity
        placed = False
        for i in range(weeks):
            if used[i] + t["hours"] <= weekly_budget + 0.5:
                weeks_arr[i].append(t)
                used[i] += t["hours"]
                placed = True
                break
        if not placed:
            i = min(range(weeks), key=lambda j: used[j])
            weeks_arr[i].append(t)
            used[i] += t["hours"]
    return weeks_arr, used


def render_md(app_key, app_meta, start, exam, hpw, weeks_arr, used, topics, ramp_weeks):
    total_weeks = (exam - start).days // 7
    topic_weeks = len(weeks_arr)
    daily_q = app_meta["n_questions_target_per_day"]
    L = []
    L.append(f"# {app_meta['label']} — Study Plan")
    L.append("")
    L.append(f"- **Exam date**: {exam.isoformat()}")
    L.append(f"- **Start date**: {start.isoformat()}")
    L.append(f"- **Total weeks**: {total_weeks}")
    L.append(f"- **Topic study weeks**: {topic_weeks}")
    L.append(f"- **Pre-exam ramp**: {ramp_weeks} weeks (mocks + hot review)")
    L.append(f"- **Hours per week**: {hpw} (≈ {round(hpw*0.7,1)}h topics, {round(hpw*0.2,1)}h Q-bank, {round(hpw*0.1,1)}h misc)")
    L.append(f"- **Daily Q-bank target**: {daily_q} questions on [{app_meta['deploy_url']}]({app_meta['deploy_url']})")
    L.append("")
    L.append(f"## Topic distribution (empirical, n={sum(t['n_questions'] for t in topics):,} past-exam questions analyzed)")
    L.append("")
    L.append("| Rank | Topic | % of past Qs | Hours allocated |")
    L.append("|---|---|---|---|")
    for rank, t in enumerate(topics, 1):
        L.append(f"| {rank} | {t['en']} | {t['frequency_pct']}% | {t['hours']}h |")
    L.append("")
    for i, week in enumerate(weeks_arr):
        wk_start = start + timedelta(days=i*7)
        wk_end = wk_start + timedelta(days=6)
        L.append(f"## Week {i+1} — {wk_start.isoformat()} → {wk_end.isoformat()}")
        L.append("")
        L.append(f"_Topic budget: {used[i]:.1f}h • Q-bank: {daily_q}/day_")
        L.append("")
        for t in week:
            he = f" / {t['he']}" if t.get("he") else ""
            L.append(f"### {t['en']}{he} — {t['hours']}h ({t['frequency_pct']}% of past exams)")
            if t.get("keywords"):
                kw = ", ".join(t["keywords"][:8])
                L.append(f"- Keywords: _{kw}_")
            L.append("")
    if ramp_weeks > 0:
        for j in range(ramp_weeks):
            wk_start = start + timedelta(days=(topic_weeks+j)*7)
            wk_end = wk_start + timedelta(days=6)
            L.append(f"## Ramp Week {j+1} — {wk_start.isoformat()} → {wk_end.isoformat()}")
            L.append("")
            if j == 0:
                L.append(f"- **Mock exam #1** — full timed at [{app_meta['deploy_url']}]({app_meta['deploy_url']})")
                L.append("- Review every miss, mark for spaced repetition")
                L.append(f"- Hot review: weakest 5 topics from mock #1 (typically the top-frequency ones you scored < 70%)")
            elif j == 1:
                L.append("- **Mock exam #2** — fresh full set timed")
                L.append("- Compare to mock #1: which topics improved, which didn't")
                L.append("- Drill highest-frequency topics that scored < 70%")
            else:
                L.append("- **Mock exam #3** — full timed simulation under exam conditions")
                L.append("- Light review only the day before exam")
                L.append("- 8h sleep, no new material in last 48h")
            L.append("")
    L.append("## Notes")
    L.append("")
    L.append("- Topic ordering reflects **actual past-exam frequency** from your question bank (not Claude's guess).")
    L.append("- Frequency-weighted hours protect against over-investing time in low-yield topics.")
    L.append("- Use FSRS in the PWA for spaced-repetition Q review.")
    L.append("- Re-run with different `--hours-per-week` if your schedule changes.")
    L.append("")
    L.append(f"_Generated by `scripts/generate_study_plan.py` from `syllabus_data.json` (refresh by re-running `scripts/refresh_syllabus_data.py`)._")
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--app", choices=list(APP_META.keys()), required=True)
    p.add_argument("--exam-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--hours-per-week", type=float, default=8)
    p.add_argument("--start-date", default=date.today().isoformat())
    p.add_argument("--output", default=None)
    p.add_argument("--ramp-weeks", type=int, default=3)
    args = p.parse_args()

    if not os.path.exists(DATA_FILE):
        raise SystemExit(f"missing {DATA_FILE} — run scripts/refresh_syllabus_data.py first")
    data = json.load(open(DATA_FILE, encoding='utf-8'))

    key = APP_TO_KEY[args.app]
    if key not in data:
        raise SystemExit(f"app {args.app} not in syllabus_data.json (have: {list(data.keys())})")

    start = date.fromisoformat(args.start_date)
    exam = date.fromisoformat(args.exam_date)
    if exam <= start:
        raise SystemExit("exam-date must be after start-date")
    total_weeks = (exam - start).days // 7
    if total_weeks < args.ramp_weeks + 4:
        raise SystemExit(f"only {total_weeks} weeks until exam — need at least {args.ramp_weeks + 4}")
    topic_weeks = total_weeks - args.ramp_weeks
    total_topic_hours = topic_weeks * args.hours_per_week * 0.7

    topics = allocate_hours(data[key]["topics"], total_topic_hours)
    weeks_arr, used = schedule(topics, args.hours_per_week, topic_weeks)

    md = render_md(key, APP_META[args.app], start, exam, args.hours_per_week,
                   weeks_arr, used, topics, args.ramp_weeks)
    out = args.output or f"./study_plan_{args.app}_{exam.isoformat()}.md"
    with open(out, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"Wrote {out}")
    print(f"  app: {args.app}")
    print(f"  total weeks: {total_weeks}, topic weeks: {topic_weeks}, ramp weeks: {args.ramp_weeks}")
    print(f"  topics: {len(topics)}, hours/topic range: {min(t['hours'] for t in topics)}–{max(t['hours'] for t in topics)}h")


if __name__ == "__main__":
    main()
