# Phase 2: In-app Study Plan Feature

This directory contains all Phase 2 deliverables for implementing the Study Plan feature in the Geri, Pnimit, and Mishpacha medical PWAs.

## 📦 What's Included

### SQL Migrations (`sql/`)
- **001_create_study_plans.sql** — Database table, RPCs, and RLS policies
- **002_add_syllabus_to_app_config.sql** — Load syllabus data into app_config

### TypeScript Port (`typescript/`)
- **types.ts** — Type definitions for study plan data structures
- **studyPlan.ts** — Core algorithm (Python → TypeScript port)
- **icsExport.ts** — Calendar export utility (.ics generation)
- **test-study-plan.ts** — Test suite to verify implementation
- **package.json** / **tsconfig.json** — TypeScript configuration

### Documentation (`docs/`)
- **INTEGRATION.md** — Complete integration guide for PWA developers

## 🎯 Phase 2 Goals (from Issue #1)

✅ **Backend (one-time, shared)**
- Create `study_plans` table with RLS + RPCs
- Bake `syllabus_data.json` into `app_config`

✅ **Algorithm Port**
- Port Python `allocate_hours()`, `schedule()`, `render_md()` to TypeScript
- Lives in `phase2/typescript/` (copy to PWA repos as needed)

🔲 **Per-app Frontend** (3x — to be implemented in PWA repos)
- Settings → Study Plan tab
- Form: exam date, hours/week, ramp weeks
- Display: weekly schedule, topic table, calendar export button

## 🚀 Quick Start

### 1. Database Setup (One-time)

```bash
# Run SQL migrations in Supabase SQL Editor
# See: sql/001_create_study_plans.sql and sql/002_add_syllabus_to_app_config.sql
```

### 2. Test TypeScript Implementation

```bash
cd phase2/typescript/
npm install
npm run test
```

This will:
- Generate study plans for all 3 apps
- Export markdown and .ics files
- Verify algorithm correctness

### 3. Integrate into PWAs

Follow the detailed guide in `docs/INTEGRATION.md`.

## 📊 Implementation Status

| Task | Status |
|------|--------|
| SQL table + RPCs | ✅ Done |
| Syllabus data in app_config | ✅ Done |
| TypeScript algorithm port | ✅ Done |
| Type definitions | ✅ Done |
| ICS export utility | ✅ Done |
| Integration docs | ✅ Done |
| Test suite | ✅ Done |
| PWA UI (Mishpacha) | 🔲 TODO |
| PWA UI (Pnimit) | 🔲 TODO |
| PWA UI (Geri) | 🔲 TODO |

## 🔍 Algorithm Overview

The study plan algorithm (ported from `scripts/generate_study_plan.py`):

1. **Allocate hours** to topics based on empirical question frequency
   - Floor: 0.5h per topic (ensure coverage)
   - Ceiling: 6h per topic (avoid over-investment)

2. **Schedule topics** week-by-week using greedy allocation
   - High-frequency topics first
   - Fill weeks up to 70% of weekly budget
   - Remaining 30% reserved for Q-bank (20%) + misc (10%)

3. **Add ramp weeks** for pre-exam mock exams
   - Default: 3 weeks before exam
   - Mock #1 → review misses + hot review
   - Mock #2 → compare progress
   - Mock #3 → final simulation

4. **Generate calendar** export
   - Weekly topic study blocks
   - Daily Q-bank sessions
   - Mock exam events
   - Final exam day

## 📝 Example Usage

```typescript
import { generateStudyPlan } from './typescript/studyPlan';
import { generateICS, downloadICS } from './typescript/icsExport';

// Load syllabus data from Supabase
const { data: syllabusData } = await supabase.rpc('app_config_get_syllabus');

// Generate plan
const plan = generateStudyPlan(syllabusData, {
  app: 'mishpacha',
  examDate: '2026-12-01',
  hoursPerWeek: 10,
  rampWeeks: 3,
});

// Save to database
await supabase.rpc('study_plan_upsert', {
  p_app: 'mishpacha',
  p_exam_date: plan.examDate,
  p_hours_per_week: plan.hoursPerWeek,
  p_ramp_weeks: plan.rampWeeks,
  p_plan_json: plan,
});

// Export to calendar
const icsContent = generateICS(plan);
downloadICS(icsContent, 'study-plan-mishpacha.ics');
```

## 🧪 Testing

### Run automated tests:
```bash
cd typescript/
npm run test
```

### Compare with Python reference:
```bash
# Python version
python ../scripts/generate_study_plan.py \
  --app mishpacha \
  --exam-date 2026-12-01 \
  --start-date 2026-09-01 \
  --hours-per-week 10

# TypeScript version
npm run test  # Generates test-output-mishpacha.md

# Compare the two outputs
diff study_plan_mishpacha_2026-12-01.md typescript/test-output-mishpacha.md
```

### Validate .ics file:
```bash
# Import generated .ics file to Google Calendar
# File: typescript/test-output-mishpacha.ics
```

## 📖 Data Sources

**Syllabus Data** (`scripts/syllabus_data.json`):
- **Geri**: 3,833 questions, 46 topics
- **Pnimit**: 1,556 questions, 24 topics
- **Mishpacha**: 1,061 questions, 27 topics

Refreshed periodically via `scripts/refresh_syllabus_data.py`.

## 🔐 Security

- Study plans table uses **RLS** (Row Level Security)
- No direct table access — all operations via **SECURITY DEFINER** RPCs
- Users can only read/write their own plans
- RPC functions validate authentication via `auth.uid()`

## 🚧 Out of Scope (Phase 3)

These features are **NOT** part of Phase 2:
- Daily reminders / push notifications
- Streak tracking
- Plan migration (just regenerate on change)
- Mobile native app (PWA only)

## 📚 References

- **Issue**: [#1 Phase 2: in-app Study Plan feature](https://github.com/Eiasash/auto-audit/issues/1)
- **Python reference**: `scripts/generate_study_plan.py`
- **Data source**: `scripts/syllabus_data.json`
- **Integration guide**: `docs/INTEGRATION.md`

## 🤝 Contributing

When implementing in PWA repos:
1. Start with **Mishpacha** (cleanest topic names)
2. Verify everything works end-to-end
3. Mirror to **Pnimit** and **Geri**
4. Follow the "version trinity" rule:
   - Bump `package.json` version
   - Update `APP_VERSION` in constants
   - Update `CACHE` in service worker

## ✅ Done

Phase 2 deliverables in this repo are **complete**. The next step is to integrate the TypeScript modules into the actual PWA repositories (Geriatrics, InternalMedicine, FamilyMedicine) following the guide in `docs/INTEGRATION.md`.

---

**Questions?** Check [Issue #1](https://github.com/Eiasash/auto-audit/issues/1) or the integration docs.
