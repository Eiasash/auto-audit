#!/usr/bin/env python3
"""
generate_study_plan.py — Israeli Geriatrics Board exam (Stage A, P005-2026)
study plan generator.

Inputs:
    --exam-date YYYY-MM-DD       (required)
    --hours-per-week N           (default 8)
    --start-date YYYY-MM-DD      (default today)
    --output FILE                (default ./study_plan.md)

Generates a markdown plan that:
    1. Distributes 42 syllabus topics across the available weeks, weighted by
       tier (high/medium/low yield) — Tier 1 gets 3x the time of Tier 3.
    2. Reserves the final 3 weeks for mock exams + hot review.
    3. Inserts a daily question-bank target (Geri PWA at eiasash.github.io/Geriatrics/).
    4. Annotates Hazzard / GRS / Harrison reading anchors per topic.

Tier classification reflects exam emphasis based on past Israeli geriatrics
boards + clinical importance. Adjust TIER_OVERRIDE if you disagree.

Usage:
    python generate_study_plan.py --exam-date 2026-09-01 --hours-per-week 10
"""

from __future__ import annotations
import argparse, math
from dataclasses import dataclass
from datetime import date, timedelta

# --------------------------------------------------------------------------- #
# 42 syllabus topics, with tier and source anchors
# --------------------------------------------------------------------------- #

@dataclass
class Topic:
    name: str
    tier: int  # 1=high, 2=medium, 3=low
    hazzard: str = ""    # rough Hazzard 8e chapter pointer
    grs: str = ""        # GRS section pointer
    notes: str = ""

TOPICS = [
    Topic("Alzheimer and other Dementias", 1, "Hazzard ch. Cognitive Impairment", "GRS Dementia", "Overlap with #11"),
    Topic("Andropausa", 3, "Hazzard ch. Endocrine"),
    Topic("Anemias", 2, "Hazzard ch. Hematology"),
    Topic("Arrhythmia", 2, "Hazzard ch. Arrhythmias", "GRS Cardiology"),
    Topic("Auditory and visual issues", 2, "Hazzard ch. Sensory", "GRS Sensory"),
    Topic("Biology of aging", 3, "Hazzard ch. Biology of aging", "GRS Aging biology"),
    Topic("Confusional states / Delirium", 1, "Hazzard ch. Delirium", "GRS Delirium", "HIGH YIELD — mechanism, CAM, management"),
    Topic("Congestive heart failure", 1, "Hazzard CHF + Harrison CHF", "GRS HF", "HFpEF emphasis"),
    Topic("Constipation", 2, "Hazzard ch. GI", "GRS GI"),
    Topic("Comprehensive geriatric assessment", 1, "Hazzard ch. CGA", "GRS CGA", "Israel-specific overlay (FIM)"),
    Topic("Dementia and cognitive impairment", 1, "Hazzard ch. Dementia", "GRS Dementia", "Overlap with #1"),
    Topic("Demography of aging", 3, "Hazzard ch. Demography", "Brookdale 2024 stats"),
    Topic("Depression", 2, "Hazzard ch. Mood"),
    Topic("Diabetes", 1, "Hazzard DM + Harrison DM", "GRS Diabetes", "Hypoglycemia risk, A1c targets in frail"),
    Topic("Dysphagia", 2, "Hazzard ch. Swallowing"),
    Topic("End of life care", 1, "Hazzard ch. Palliative", "GRS EOL", "Israeli law + ייפוי כוח context"),
    Topic("Ethics", 1, "Hazzard ch. Ethics", "GRS Ethics", "Capacity, AOA, surrogate decision-makers"),
    Topic("Falls", 1, "Hazzard ch. Falls", "GRS Falls", "Multifactorial assessment + Tinetti/POMA"),
    Topic("Fractures", 2, "Hazzard ch. Hip fracture"),
    Topic("Frailty", 1, "Hazzard ch. Frailty", "GRS Frailty", "Fried + CFS scales"),
    Topic("Geriatrics in Israel — local aspects", 1, "(no Hazzard equivalent)", "(none)",
          "MANDATORY: ייפוי כוח מתמשך, מקבל החלטות זמני, סיעוד מורכב, נהיגה (חוזר 6/2023)"),
    Topic("Hypertension", 1, "Hazzard HTN + Harrison HTN", "GRS HTN", "SPRINT in elderly, orthostasis"),
    Topic("Hypothermia", 3, "Hazzard ch. Thermoregulation"),
    Topic("Incontinence — urinary and fecal", 1, "Hazzard ch. Incontinence", "GRS Incontinence"),
    Topic("Infections in the elderly", 2, "Hazzard ch. Infections", "GRS Infections", "DAG SZMC"),
    Topic("Ischemic heart disease — peripheral vascular disease", 2, "Hazzard ch. CAD"),
    Topic("Nutrition and enteral feeding", 2, "Hazzard ch. Nutrition", "GRS Nutrition", "PEG ethics"),
    Topic("Osteoarthritis, Osteoporosis", 2, "Hazzard ch. Bone", "GRS Bone"),
    Topic("Parkinson's disease and Extrapyramidal syndrome", 2, "Hazzard ch. PD"),
    Topic("Physical activity and exercise", 3, "Hazzard ch. Exercise"),
    Topic("Postural instability", 2, "Hazzard ch. Gait/Balance"),
    Topic("Pressure sores", 1, "Hazzard ch. Skin", "GRS Skin", "Staging + prevention"),
    Topic("Prevention and health promotion", 3, "Hazzard ch. Prevention"),
    Topic("Problems of polypharmacy", 1, "Hazzard ch. Pharmacology", "GRS Pharm", "Beers + STOPP/START + ACB"),
    Topic("Pulmonary embolism", 3, "Hazzard ch. PE"),
    Topic("Quality of life", 3, "Hazzard ch. QOL"),
    Topic("Rehabilitation", 2, "Hazzard ch. Rehab", "GRS Rehab"),
    Topic("Sarcopenia", 2, "Hazzard ch. Sarcopenia"),
    Topic("Sensory deprivation", 3, "Hazzard ch. Sensory"),
    Topic("Stroke and related disorders", 1, "Hazzard CVD + Harrison Stroke", "GRS Stroke"),
    Topic("The geriatric team — team-work", 2, "Hazzard ch. Team", "GRS Team"),
    Topic("Urinary tract infection — renal failure", 2, "Hazzard ch. UTI/Renal", "DAG SZMC"),
]

assert len(TOPICS) == 42, f"expected 42 topics, got {len(TOPICS)}"

TIER_WEIGHT = {1: 1.5, 2: 1.0, 3: 0.5}


# --------------------------------------------------------------------------- #
# Plan construction
# --------------------------------------------------------------------------- #

def allocate_hours(total_topic_hours: float) -> dict[str, float]:
    total_share = sum(TIER_WEIGHT[t.tier] for t in TOPICS)
    out = {}
    for t in TOPICS:
        share = TIER_WEIGHT[t.tier] / total_share
        out[t.name] = round(share * total_topic_hours, 1)
    return out


def schedule_topics(topic_hours: dict[str, float], hours_per_week: float, topic_weeks: int):
    """Greedy: assign topics to weeks, fitting up to 0.7*hours_per_week into a week
       (rest reserved for question-bank ongoing work). Tier-1 first."""
    weekly_topic_budget = hours_per_week * 0.7
    sorted_topics = sorted(TOPICS, key=lambda t: (t.tier, -topic_hours[t.name]))

    weeks = [[] for _ in range(topic_weeks)]
    week_used = [0.0] * topic_weeks

    for t in sorted_topics:
        h = topic_hours[t.name]
        # find first week with capacity
        placed = False
        for i in range(topic_weeks):
            if week_used[i] + h <= weekly_topic_budget + 0.5:  # allow tiny overflow
                weeks[i].append((t, h))
                week_used[i] += h
                placed = True
                break
        if not placed:
            # spill into the least-loaded week
            i = min(range(topic_weeks), key=lambda j: week_used[j])
            weeks[i].append((t, h))
            week_used[i] += h
    return weeks, week_used


# --------------------------------------------------------------------------- #
# Markdown rendering
# --------------------------------------------------------------------------- #

def render_md(start: date, exam: date, hpw: float, weeks, week_used, topic_hours):
    total_weeks = (exam - start).days // 7
    topic_weeks = len(weeks)
    ramp_weeks = total_weeks - topic_weeks
    daily_q_target = max(15, round(hpw * 60 / 7 / 3))  # ~1Q/3min on study days

    lines = []
    lines.append(f"# Geriatrics Board Study Plan")
    lines.append("")
    lines.append(f"- **Exam date**: {exam.isoformat()}")
    lines.append(f"- **Start date**: {start.isoformat()}")
    lines.append(f"- **Total weeks**: {total_weeks}")
    lines.append(f"- **Topic study weeks**: {topic_weeks}")
    lines.append(f"- **Pre-exam ramp**: {ramp_weeks} weeks (mocks + hot review)")
    lines.append(f"- **Hours per week**: {hpw} (≈ {round(hpw*0.7,1)}h topics, {round(hpw*0.2,1)}h Q-bank, {round(hpw*0.1,1)}h misc)")
    lines.append(f"- **Daily Q-bank target**: {daily_q_target} questions (Geri PWA)")
    lines.append("")
    lines.append("## Topic distribution")
    lines.append("")
    lines.append("| Tier | Count | Hours each | Total hours |")
    lines.append("|---|---|---|---|")
    for tier in (1, 2, 3):
        tier_topics = [t for t in TOPICS if t.tier == tier]
        if not tier_topics:
            continue
        avg = sum(topic_hours[t.name] for t in tier_topics) / len(tier_topics)
        total = sum(topic_hours[t.name] for t in tier_topics)
        label = {1: "1 (high-yield)", 2: "2 (medium)", 3: "3 (low-yield)"}[tier]
        lines.append(f"| {label} | {len(tier_topics)} | {avg:.1f}h | {total:.1f}h |")
    lines.append("")

    for i, week in enumerate(weeks):
        wk_start = start + timedelta(days=i * 7)
        wk_end = wk_start + timedelta(days=6)
        lines.append(f"## Week {i+1} — {wk_start.isoformat()} → {wk_end.isoformat()}")
        lines.append("")
        lines.append(f"_Topic budget: {week_used[i]:.1f}h • Q-bank: {daily_q_target}/day_")
        lines.append("")
        for t, h in week:
            tier_tag = {1: "🔴 T1", 2: "🟡 T2", 3: "🟢 T3"}[t.tier]
            lines.append(f"### {tier_tag} {t.name} — {h}h")
            anchors = []
            if t.hazzard:
                anchors.append(f"📕 {t.hazzard}")
            if t.grs:
                anchors.append(f"📗 {t.grs}")
            if anchors:
                lines.append("- " + " · ".join(anchors))
            if t.notes:
                lines.append(f"- _{t.notes}_")
            lines.append("")

    # Pre-exam ramp
    if ramp_weeks > 0:
        for j in range(ramp_weeks):
            wk_start = start + timedelta(days=(topic_weeks + j) * 7)
            wk_end = wk_start + timedelta(days=6)
            lines.append(f"## Ramp Week {j+1} — {wk_start.isoformat()} → {wk_end.isoformat()}")
            lines.append("")
            if j == 0:
                lines.append("- **Mock exam #1** — full 100Q timed in Geri PWA (P005-2026 mode)")
                lines.append("- Review every miss, mark for spaced repetition")
                lines.append("- Hot review: weakest 5 topics from mock #1")
            elif j == 1:
                lines.append("- **Mock exam #2** — fresh 100Q timed")
                lines.append("- Compare to mock #1: which topics improved, which didn't")
                lines.append("- Drill Tier 1 topics that scored < 70%")
                lines.append("- Re-read **Geriatrics in Israel** materials end-to-end (it's mandatory and easy points)")
            else:
                lines.append("- **Mock exam #3** — full timed simulation under exam conditions")
                lines.append("- Light review only the day before exam")
                lines.append("- 8h sleep, no new material in last 48h")
            lines.append("")

    lines.append("## Notes on this plan")
    lines.append("")
    lines.append("- Tier weights are clinical-importance heuristics; Israeli boards historically emphasize delirium, falls, polypharmacy, dementia, EOL/ethics, and Israel-specific law.")
    lines.append("- The Q-bank target is parallel to topic study, not replacement. Use spaced repetition (FSRS in Geri PWA).")
    lines.append(f"- Generated by `scripts/generate_study_plan.py` — adjust hours-per-week and re-run if your schedule changes.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--exam-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--hours-per-week", type=float, default=8)
    p.add_argument("--start-date", default=date.today().isoformat())
    p.add_argument("--output", default="./study_plan.md")
    p.add_argument("--ramp-weeks", type=int, default=3)
    args = p.parse_args()

    start = date.fromisoformat(args.start_date)
    exam = date.fromisoformat(args.exam_date)
    if exam <= start:
        raise SystemExit("exam-date must be after start-date")

    total_weeks = (exam - start).days // 7
    if total_weeks < args.ramp_weeks + 4:
        raise SystemExit(f"only {total_weeks} weeks until exam — need at least {args.ramp_weeks + 4}")

    topic_weeks = total_weeks - args.ramp_weeks
    total_topic_hours = topic_weeks * args.hours_per_week * 0.7

    topic_hours = allocate_hours(total_topic_hours)
    weeks, week_used = schedule_topics(topic_hours, args.hours_per_week, topic_weeks)

    md = render_md(start, exam, args.hours_per_week, weeks, week_used, topic_hours)
    with open(args.output, "w") as f:
        f.write(md)
    print(f"Wrote {args.output} — {total_weeks} weeks, {len(TOPICS)} topics, "
          f"{total_topic_hours:.0f}h topic study")
    print(f"\nTier 1 hours/topic: {topic_hours[next(t.name for t in TOPICS if t.tier==1)]:.1f}h")
    print(f"Tier 3 hours/topic: {topic_hours[next(t.name for t in TOPICS if t.tier==3)]:.1f}h")


if __name__ == "__main__":
    main()
