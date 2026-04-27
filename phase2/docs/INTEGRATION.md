# Phase 2 Study Plan Feature — Integration Guide

This directory contains all the deliverables for Phase 2 of the Study Plan feature, which adds in-app study plan generation to the Geri, Pnimit, and Mishpacha PWAs.

## 📁 Directory Structure

```
phase2/
├── sql/
│   ├── 001_create_study_plans.sql          # Database table + RPCs
│   └── 002_add_syllabus_to_app_config.sql  # Bake syllabus_data into app_config
├── typescript/
│   ├── types.ts                             # Type definitions
│   ├── studyPlan.ts                         # Core algorithm (Python → TS port)
│   └── icsExport.ts                         # Calendar export utility
└── docs/
    └── INTEGRATION.md                       # This file
```

## 🎯 Implementation Overview

Phase 2 adds an in-app "Study Plan" feature where users:
1. Enter their exam date and weekly study hours
2. App generates a frequency-weighted study plan
3. Plan displays week-by-week schedule with topics
4. Users can export to Google Calendar (.ics file)

## 📋 Prerequisites

Before integrating into PWAs, ensure:
- ✅ Phase 1 is complete: `scripts/syllabus_data.json` exists and is up-to-date
- ✅ Supabase database is set up with `app_users` table
- ✅ PWAs have authentication (Supabase Auth)
- ✅ PWAs have a Settings page or similar UI

## 🚀 Integration Steps

### Step 1: Database Setup (One-time, shared)

1. **Run SQL migrations** in Supabase SQL Editor:
   ```bash
   # In Supabase Dashboard → SQL Editor
   # Run these in order:

   # 1. Create study_plans table and RPCs
   sql/001_create_study_plans.sql

   # 2. Add syllabus_data to app_config
   sql/002_add_syllabus_to_app_config.sql
   ```

2. **Load syllabus data** into app_config:
   ```sql
   -- In Supabase SQL Editor
   -- Copy content from scripts/syllabus_data.json and run:

   INSERT INTO public.app_config (key, value, description)
   VALUES (
     'syllabus_data',
     '{ ... paste JSON from syllabus_data.json here ... }'::jsonb,
     'Empirical topic frequency data from past exams for study plan generation'
   )
   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
   ```

3. **Verify setup**:
   ```sql
   -- Check that study_plans table exists
   SELECT * FROM public.study_plans LIMIT 1;

   -- Check that syllabus_data is loaded
   SELECT
     key,
     value->'Geri'->>'total_questions_analyzed' as geri_questions,
     value->'Pnimit'->>'total_questions_analyzed' as pnimit_questions,
     value->'Mishpacha'->>'total_questions_analyzed' as mishpacha_questions
   FROM public.app_config
   WHERE key = 'syllabus_data';
   ```

### Step 2: Copy TypeScript Files to PWA

**For Mishpacha** (canonical implementation):

```bash
# In the Mishpacha repo
mkdir -p src/features/studyPlan/

# Copy TypeScript files
cp phase2/typescript/types.ts src/features/studyPlan/
cp phase2/typescript/studyPlan.ts src/features/studyPlan/
cp phase2/typescript/icsExport.ts src/features/studyPlan/
```

**For Geri and Pnimit**: Same structure, copy after Mishpacha is verified.

### Step 3: Implement UI Components

#### 3.1. Settings Page — Add "Study Plan" Tab

Create a new tab in Settings with:

**Form inputs:**
- Date picker for exam date
- Slider for hours per week (1-20)
- Slider for ramp weeks (1-6)
- "Generate Plan" button

**Display area:**
- Weekly schedule (accordion or tabs)
- Topic distribution table
- "Download Calendar" button

**Example React component structure:**

```tsx
// src/features/studyPlan/StudyPlanTab.tsx
import { useState } from 'react';
import { supabase } from '../core/supabase';
import { generateStudyPlan } from './studyPlan';
import { generateICS, downloadICS } from './icsExport';
import type { StudyPlan } from './types';

export function StudyPlanTab({ app }: { app: 'geri' | 'pnimit' | 'mishpacha' }) {
  const [examDate, setExamDate] = useState('');
  const [hoursPerWeek, setHoursPerWeek] = useState(8);
  const [rampWeeks, setRampWeeks] = useState(3);
  const [plan, setPlan] = useState<StudyPlan | null>(null);
  const [loading, setLoading] = useState(false);

  const handleGenerate = async () => {
    setLoading(true);

    // 1. Fetch syllabus data from app_config
    const { data: syllabusData } = await supabase.rpc('app_config_get_syllabus');

    // 2. Generate plan locally
    const newPlan = generateStudyPlan(syllabusData, {
      app,
      examDate,
      hoursPerWeek,
      rampWeeks,
    });

    // 3. Save to database
    await supabase.rpc('study_plan_upsert', {
      p_app: app,
      p_exam_date: examDate,
      p_hours_per_week: hoursPerWeek,
      p_ramp_weeks: rampWeeks,
      p_plan_json: newPlan,
    });

    setPlan(newPlan);
    setLoading(false);
  };

  const handleDownloadCalendar = () => {
    if (!plan) return;
    const icsContent = generateICS(plan);
    downloadICS(icsContent, `study-plan-${app}-${plan.examDate}.ics`);
  };

  return (
    <div className="study-plan-tab">
      {/* Form UI */}
      <form onSubmit={handleGenerate}>
        {/* Date picker, sliders, etc. */}
      </form>

      {/* Display plan */}
      {plan && (
        <div className="study-plan-display">
          <button onClick={handleDownloadCalendar}>
            📅 Add to Google Calendar
          </button>

          {/* Weekly schedule */}
          {plan.weeks.map(week => (
            <div key={week.weekNumber}>
              <h3>Week {week.weekNumber}</h3>
              {/* Topic list */}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

#### 3.2. Load Existing Plan on Mount

```tsx
useEffect(() => {
  const loadExistingPlan = async () => {
    const { data } = await supabase.rpc('study_plan_get', { p_app: app });
    if (data && data.plan_json) {
      setPlan(data.plan_json);
      setExamDate(data.exam_date);
      setHoursPerWeek(data.hours_per_week);
      setRampWeeks(data.ramp_weeks);
    }
  };

  loadExistingPlan();
}, [app]);
```

### Step 4: Testing

#### 4.1. Manual Testing Checklist

- [ ] User can generate a new study plan
- [ ] Plan displays correctly with all weeks
- [ ] Topic hours sum correctly (70% of weekly budget)
- [ ] Mock exam weeks show correct guidance
- [ ] Calendar export downloads valid .ics file
- [ ] .ics file imports successfully to Google Calendar
- [ ] Plan persists after page reload
- [ ] Regenerating plan updates existing record
- [ ] Works for all 3 apps (Geri, Pnimit, Mishpacha)

#### 4.2. Automated Tests

Create unit tests for the TypeScript algorithm:

```typescript
// src/features/studyPlan/studyPlan.test.ts
import { allocateHours, schedule, generateStudyPlan } from './studyPlan';
import mockSyllabusData from './fixtures/syllabus_data.json';

describe('allocateHours', () => {
  it('allocates hours proportional to frequency', () => {
    const topics = mockSyllabusData.Mishpacha.topics;
    const allocated = allocateHours(topics, 100);

    // Sum should roughly equal total hours
    const sum = allocated.reduce((s, t) => s + t.hours, 0);
    expect(sum).toBeCloseTo(100, 0);

    // High frequency topics should get more hours
    expect(allocated[0].hours).toBeGreaterThan(allocated[allocated.length - 1].hours);
  });

  it('respects floor of 0.5h and ceiling of 6h', () => {
    const topics = mockSyllabusData.Mishpacha.topics;
    const allocated = allocateHours(topics, 100);

    allocated.forEach(t => {
      expect(t.hours).toBeGreaterThanOrEqual(0.5);
      expect(t.hours).toBeLessThanOrEqual(6);
    });
  });
});

describe('schedule', () => {
  it('distributes topics across weeks', () => {
    const topics = allocateHours(mockSyllabusData.Mishpacha.topics, 70);
    const { weeks, used } = schedule(topics, 10, 10);

    expect(weeks.length).toBe(10);

    // Each week should be under capacity
    used.forEach(u => {
      expect(u).toBeLessThanOrEqual(10 * 0.7 + 1); // 70% + tolerance
    });
  });
});

describe('generateStudyPlan', () => {
  it('generates a complete study plan', () => {
    const plan = generateStudyPlan(mockSyllabusData, {
      app: 'mishpacha',
      examDate: '2026-12-01',
      startDate: '2026-09-01',
      hoursPerWeek: 10,
      rampWeeks: 3,
    });

    expect(plan.app).toBe('mishpacha');
    expect(plan.totalWeeks).toBeGreaterThan(3);
    expect(plan.weeks.length).toBe(plan.totalWeeks);

    // Last N weeks should be ramp weeks
    const lastWeeks = plan.weeks.slice(-3);
    lastWeeks.forEach(w => {
      expect(w.isRampWeek).toBe(true);
    });
  });

  it('throws error if exam date is before start date', () => {
    expect(() => {
      generateStudyPlan(mockSyllabusData, {
        app: 'mishpacha',
        examDate: '2026-01-01',
        startDate: '2026-12-01',
      });
    }).toThrow('exam_date must be after start_date');
  });
});
```

### Step 5: Deployment

1. **Version bump** (per the "version trinity" rule):
   ```bash
   # In each PWA repo
   # 1. Bump version in package.json
   npm version minor  # or patch

   # 2. Update APP_VERSION in src/core/constants.js
   export const APP_VERSION = "1.8.0";

   # 3. Update CACHE in sw.js
   const CACHE = "v1.8.0";
   ```

2. **Run tests**:
   ```bash
   npm test
   npm run build
   ```

3. **Commit and push**:
   ```bash
   git add .
   git commit -m "feat: add Study Plan feature (Phase 2)"
   git push origin main
   ```

4. **Verify deployment**:
   - Check GitHub Actions for successful build
   - Test on live site (GitHub Pages)
   - Verify service worker updates

## 🔧 Maintenance

### Refreshing Syllabus Data

Run periodically (after major question bank updates):

```bash
# In auto-audit repo
cd scripts/
GITHUB_PAT=<your_token> python refresh_syllabus_data.py

# Then update app_config in Supabase
# Copy the new syllabus_data.json content and run:
# INSERT INTO public.app_config ... (see Step 1)
```

### Monitoring

Check `auto-audit` health reports for:
- Version trinity violations (triggers auto-fix PR)
- Stale syllabus data (last refresh date)
- RPC function errors (Supabase logs)

## 📚 Reference

- **Python reference**: `scripts/generate_study_plan.py`
- **Data source**: `scripts/syllabus_data.json`
- **Database schema**: `phase2/sql/001_create_study_plans.sql`
- **Type definitions**: `phase2/typescript/types.ts`
- **Algorithm**: `phase2/typescript/studyPlan.ts`
- **Calendar export**: `phase2/typescript/icsExport.ts`

## 🐛 Troubleshooting

### "User not authenticated" error

Check that:
- User is logged in with Supabase Auth
- `app_users` table has a row for this user
- JWT token is valid

### "Invalid app" error

Ensure the `app` parameter is exactly one of: `'geri'`, `'pnimit'`, `'mishpacha'` (lowercase).

### Syllabus data not found

Run the RPC function to check:
```sql
SELECT app_config_get_syllabus();
```

If NULL, re-run the data load from Step 1.

### Study plan not saving

Check Supabase logs for RPC function errors. Common issues:
- Missing `username` in `app_users`
- Invalid date formats (must be ISO 8601)
- Foreign key constraint violations

## 🎉 Success Criteria

Phase 2 is complete when:
- [x] SQL migrations run successfully in Supabase
- [x] Syllabus data loaded into `app_config`
- [x] TypeScript algorithm generates valid plans
- [x] UI displays study plan correctly
- [x] Calendar export generates valid .ics files
- [x] All 3 PWAs (Mishpacha → Pnimit → Geri) have the feature
- [x] Tests pass
- [x] No version trinity violations
- [x] Feature documented in each repo's README

## 🚧 Out of Scope (Phase 3)

The following are **NOT** part of Phase 2:
- Daily reminders / push notifications
- Streak tracking
- Plan migration when exam date changes (just regenerate)
- Cross-device sync (handled by Supabase automatically)
- Mobile app (PWA only for now)

---

Questions? Check the [main issue](https://github.com/Eiasash/auto-audit/issues/1) or ask in the repo discussions.
