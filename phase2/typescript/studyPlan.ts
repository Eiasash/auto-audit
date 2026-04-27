/**
 * studyPlan.ts — TypeScript port of generate_study_plan.py
 *
 * Generates frequency-weighted study plans for Israeli medical exams
 * (Geriatrics / Internal Medicine / Family Medicine).
 *
 * Algorithm:
 * 1. Allocate hours to topics based on empirical question frequency
 * 2. Schedule topics week-by-week (greedy: high-frequency first)
 * 3. Reserve 70% time for topics, 20% for Q-bank, 10% misc
 * 4. Add pre-exam ramp weeks for mock exams
 *
 * Data source: syllabus_data.json (via app_config in Supabase)
 */

import type {
  AppKey,
  AppLabel,
  AppMetadata,
  TopicData,
  TopicWithHours,
  AppSyllabusData,
  SyllabusData,
  WeekSchedule,
  StudyPlan,
  StudyPlanParams,
} from './types';

/**
 * App metadata constants (matches Python APP_META)
 */
export const APP_METADATA: Record<AppKey, AppMetadata> = {
  geri: {
    label: 'Geriatrics (Stage A — P005-2026)',
    deployUrl: 'https://eiasash.github.io/Geriatrics/',
    nQuestionsTargetPerDay: 25,
  },
  pnimit: {
    label: 'Internal Medicine (Stage A — P0064-2025)',
    deployUrl: 'https://eiasash.github.io/InternalMedicine/',
    nQuestionsTargetPerDay: 30,
  },
  mishpacha: {
    label: 'Family Medicine (Stage A — P0062-2025)',
    deployUrl: 'https://eiasash.github.io/FamilyMedicine/',
    nQuestionsTargetPerDay: 25,
  },
};

/**
 * App key to label mapping (matches Python APP_TO_KEY)
 */
export const APP_TO_LABEL: Record<AppKey, AppLabel> = {
  geri: 'Geri',
  pnimit: 'Pnimit',
  mishpacha: 'Mishpacha',
};

/**
 * Convert string date to Date object
 */
function parseDate(date: string | Date): Date {
  return typeof date === 'string' ? new Date(date) : date;
}

/**
 * Format Date as ISO 8601 date string (YYYY-MM-DD)
 */
function formatDate(date: Date): string {
  return date.toISOString().split('T')[0];
}

/**
 * Add days to a date
 */
function addDays(date: Date, days: number): Date {
  const result = new Date(date);
  result.setDate(result.getDate() + days);
  return result;
}

/**
 * Calculate number of weeks between two dates
 */
function weeksBetween(start: Date, end: Date): number {
  const diffMs = end.getTime() - start.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  return Math.floor(diffDays / 7);
}

/**
 * Allocate hours to each topic based on frequency_pct
 *
 * Floor: 0.5h per topic (ensure every topic gets some time)
 * Ceiling: 6h per topic (avoid degenerate distributions)
 *
 * @param topics - Array of topics from syllabus data
 * @param totalHours - Total hours available for topic study
 * @returns Array of topics with allocated hours
 */
export function allocateHours(
  topics: TopicData[],
  totalHours: number
): TopicWithHours[] {
  const totalFreq = topics.reduce((sum, t) => sum + t.frequency_pct, 0) || 100;

  return topics.map((t) => {
    const share = t.frequency_pct / totalFreq;
    const hours = Math.max(0.5, Math.min(6.0, share * totalHours));
    const roundedHours = Math.round(hours * 10) / 10; // Round to 1 decimal

    return {
      ...t,
      hours: roundedHours,
    };
  });
}

/**
 * Schedule topics into weeks using greedy allocation
 *
 * Strategy: Place high-frequency topics first, fill week up to 70% of weekly budget
 * (remaining 30% reserved for Q-bank work and misc)
 *
 * @param topics - Array of topics with allocated hours
 * @param hoursPerWeek - Total study hours per week
 * @param weeks - Number of weeks available for topic study
 * @returns Array of weekly schedules and hours used per week
 */
export function schedule(
  topics: TopicWithHours[],
  hoursPerWeek: number,
  weeks: number
): { weeks: TopicWithHours[][]; used: number[] } {
  const weeklyBudget = hoursPerWeek * 0.7;

  // Sort topics by frequency (high to low)
  const sortedTopics = [...topics].sort((a, b) => b.frequency_pct - a.frequency_pct);

  // Initialize weeks and usage tracking
  const weeksArr: TopicWithHours[][] = Array.from({ length: weeks }, () => []);
  const used: number[] = Array(weeks).fill(0);

  // Greedy allocation: place each topic in first week with capacity
  for (const topic of sortedTopics) {
    let placed = false;

    // Try to place in first available week
    for (let i = 0; i < weeks; i++) {
      if (used[i] + topic.hours <= weeklyBudget + 0.5) {
        weeksArr[i].push(topic);
        used[i] += topic.hours;
        placed = true;
        break;
      }
    }

    // If no week has capacity, place in week with least usage
    if (!placed) {
      const minWeek = used.indexOf(Math.min(...used));
      weeksArr[minWeek].push(topic);
      used[minWeek] += topic.hours;
    }
  }

  return { weeks: weeksArr, used };
}

/**
 * Generate a complete study plan
 *
 * @param syllabusData - Syllabus data for all apps (from app_config)
 * @param params - Study plan parameters
 * @returns Complete study plan object
 */
export function generateStudyPlan(
  syllabusData: SyllabusData,
  params: StudyPlanParams
): StudyPlan {
  // Parse and validate parameters
  const {
    app,
    hoursPerWeek = 8,
    rampWeeks = 3,
  } = params;

  const startDate = parseDate(params.startDate || new Date());
  const examDate = parseDate(params.examDate);

  // Validate dates
  if (examDate <= startDate) {
    throw new Error('exam_date must be after start_date');
  }

  // Calculate weeks
  const totalWeeks = weeksBetween(startDate, examDate);
  if (totalWeeks < rampWeeks + 4) {
    throw new Error(
      `Only ${totalWeeks} weeks until exam — need at least ${rampWeeks + 4}`
    );
  }

  const topicWeeks = totalWeeks - rampWeeks;
  const totalTopicHours = topicWeeks * hoursPerWeek * 0.7;

  // Get app-specific data
  const appLabel = APP_TO_LABEL[app];
  const appData = syllabusData[appLabel];
  const appMeta = APP_METADATA[app];

  if (!appData) {
    throw new Error(`App ${app} not found in syllabus data`);
  }

  // Allocate hours and schedule topics
  const topicsWithHours = allocateHours(appData.topics, totalTopicHours);
  const { weeks: weeklyTopics, used: weeklyUsed } = schedule(
    topicsWithHours,
    hoursPerWeek,
    topicWeeks
  );

  // Build week schedules
  const weeks: WeekSchedule[] = [];

  // Topic study weeks
  for (let i = 0; i < topicWeeks; i++) {
    const weekStart = addDays(startDate, i * 7);
    const weekEnd = addDays(weekStart, 6);

    weeks.push({
      weekNumber: i + 1,
      startDate: formatDate(weekStart),
      endDate: formatDate(weekEnd),
      topics: weeklyTopics[i],
      topicHours: Math.round(weeklyUsed[i] * 10) / 10,
      qBankHours: Math.round(hoursPerWeek * 0.2 * 10) / 10,
      miscHours: Math.round(hoursPerWeek * 0.1 * 10) / 10,
    });
  }

  // Ramp weeks (mock exams)
  for (let j = 0; j < rampWeeks; j++) {
    const weekStart = addDays(startDate, (topicWeeks + j) * 7);
    const weekEnd = addDays(weekStart, 6);

    weeks.push({
      weekNumber: topicWeeks + j + 1,
      startDate: formatDate(weekStart),
      endDate: formatDate(weekEnd),
      topics: [],
      topicHours: 0,
      qBankHours: Math.round(hoursPerWeek * 0.8 * 10) / 10,
      miscHours: Math.round(hoursPerWeek * 0.2 * 10) / 10,
      isRampWeek: true,
      rampWeekNumber: j + 1,
    });
  }

  // Assemble complete plan
  return {
    app,
    appLabel: appMeta.label,
    examDate: formatDate(examDate),
    startDate: formatDate(startDate),
    totalWeeks,
    topicWeeks,
    rampWeeks,
    hoursPerWeek,
    topicHoursPerWeek: Math.round(hoursPerWeek * 0.7 * 10) / 10,
    qBankHoursPerWeek: Math.round(hoursPerWeek * 0.2 * 10) / 10,
    miscHoursPerWeek: Math.round(hoursPerWeek * 0.1 * 10) / 10,
    dailyQuestionsTarget: appMeta.nQuestionsTargetPerDay,
    deployUrl: appMeta.deployUrl,
    totalQuestionsAnalyzed: appData.total_questions_analyzed,
    weeks,
    topicsSummary: topicsWithHours.sort((a, b) => b.frequency_pct - a.frequency_pct),
  };
}

/**
 * Render study plan as markdown (for debugging/export)
 *
 * @param plan - Study plan object
 * @returns Markdown string
 */
export function renderMarkdown(plan: StudyPlan): string {
  const lines: string[] = [];

  lines.push(`# ${plan.appLabel} — Study Plan`);
  lines.push('');
  lines.push(`- **Exam date**: ${plan.examDate}`);
  lines.push(`- **Start date**: ${plan.startDate}`);
  lines.push(`- **Total weeks**: ${plan.totalWeeks}`);
  lines.push(`- **Topic study weeks**: ${plan.topicWeeks}`);
  lines.push(`- **Pre-exam ramp**: ${plan.rampWeeks} weeks (mocks + hot review)`);
  lines.push(
    `- **Hours per week**: ${plan.hoursPerWeek} (≈ ${plan.topicHoursPerWeek}h topics, ${plan.qBankHoursPerWeek}h Q-bank, ${plan.miscHoursPerWeek}h misc)`
  );
  lines.push(
    `- **Daily Q-bank target**: ${plan.dailyQuestionsTarget} questions on [${plan.deployUrl}](${plan.deployUrl})`
  );
  lines.push('');

  lines.push(
    `## Topic distribution (empirical, n=${plan.totalQuestionsAnalyzed.toLocaleString()} past-exam questions analyzed)`
  );
  lines.push('');
  lines.push('| Rank | Topic | % of past Qs | Hours allocated |');
  lines.push('|---|---|---|---|');

  plan.topicsSummary.forEach((t, i) => {
    lines.push(`| ${i + 1} | ${t.en} | ${t.frequency_pct}% | ${t.hours}h |`);
  });
  lines.push('');

  // Week-by-week schedule
  for (const week of plan.weeks) {
    if (week.isRampWeek) {
      lines.push(`## Ramp Week ${week.rampWeekNumber} — ${week.startDate} → ${week.endDate}`);
      lines.push('');

      if (week.rampWeekNumber === 1) {
        lines.push(`- **Mock exam #1** — full timed at [${plan.deployUrl}](${plan.deployUrl})`);
        lines.push('- Review every miss, mark for spaced repetition');
        lines.push(
          '- Hot review: weakest 5 topics from mock #1 (typically the top-frequency ones you scored < 70%)'
        );
      } else if (week.rampWeekNumber === 2) {
        lines.push('- **Mock exam #2** — fresh full set timed');
        lines.push('- Compare to mock #1: which topics improved, which didn\'t');
        lines.push('- Drill highest-frequency topics that scored < 70%');
      } else {
        lines.push('- **Mock exam #3** — full timed simulation under exam conditions');
        lines.push('- Light review only the day before exam');
        lines.push('- 8h sleep, no new material in last 48h');
      }
      lines.push('');
    } else {
      lines.push(`## Week ${week.weekNumber} — ${week.startDate} → ${week.endDate}`);
      lines.push('');
      lines.push(
        `_Topic budget: ${week.topicHours}h • Q-bank: ${plan.dailyQuestionsTarget}/day_`
      );
      lines.push('');

      for (const topic of week.topics) {
        const he = topic.he ? ` / ${topic.he}` : '';
        lines.push(
          `### ${topic.en}${he} — ${topic.hours}h (${topic.frequency_pct}% of past exams)`
        );

        if (topic.keywords && topic.keywords.length > 0) {
          const keywords = topic.keywords.slice(0, 8).join(', ');
          lines.push(`- Keywords: _${keywords}_`);
        }
        lines.push('');
      }
    }
  }

  lines.push('## Notes');
  lines.push('');
  lines.push(
    '- Topic ordering reflects **actual past-exam frequency** from your question bank (not Claude\'s guess).'
  );
  lines.push('- Frequency-weighted hours protect against over-investing time in low-yield topics.');
  lines.push('- Use FSRS in the PWA for spaced-repetition Q review.');
  lines.push('- Re-run with different `hoursPerWeek` if your schedule changes.');
  lines.push('');
  lines.push(
    '_Generated by Study Plan algorithm (TypeScript port of scripts/generate_study_plan.py)._'
  );

  return lines.join('\n');
}
