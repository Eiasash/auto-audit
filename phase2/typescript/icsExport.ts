/**
 * icsExport.ts — Generate ICS calendar files for study plan export
 *
 * Generates downloadable .ics files that users can import into Google Calendar,
 * Apple Calendar, Outlook, etc.
 *
 * Usage:
 *   const icsContent = generateICS(studyPlan);
 *   downloadICS(icsContent, `study-plan-${studyPlan.app}.ics`);
 */

import type { StudyPlan, ICSEvent } from './types';

/**
 * Format date as ICS datetime string (YYYYMMDDTHHMMSSZ)
 */
function formatICSDateTime(date: Date): string {
  return date.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';
}

/**
 * Format date as ICS date string (YYYYMMDD)
 */
function formatICSDate(date: Date): string {
  return date.toISOString().split('T')[0].replace(/-/g, '');
}

/**
 * Escape special characters for ICS format
 */
function escapeICS(text: string): string {
  return text
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\n/g, '\\n');
}

/**
 * Fold long lines to 75 characters (ICS spec requirement)
 */
function foldLine(line: string): string {
  if (line.length <= 75) {
    return line;
  }

  const folded: string[] = [];
  let remaining = line;

  while (remaining.length > 75) {
    folded.push(remaining.substring(0, 75));
    remaining = ' ' + remaining.substring(75); // Continuation lines start with space
  }

  folded.push(remaining);
  return folded.join('\r\n');
}

/**
 * Generate a unique ID for ICS events
 */
function generateUID(): string {
  const timestamp = Date.now();
  const random = Math.random().toString(36).substring(2, 15);
  return `${timestamp}-${random}@study-plan.eiasash.github.io`;
}

/**
 * Create an ICS event block
 */
function createICSEvent(event: ICSEvent): string {
  const lines: string[] = [];

  lines.push('BEGIN:VEVENT');
  lines.push(`UID:${generateUID()}`);
  lines.push(`DTSTAMP:${formatICSDateTime(new Date())}`);
  lines.push(`DTSTART:${formatICSDateTime(event.start)}`);
  lines.push(`DTEND:${formatICSDateTime(event.end)}`);
  lines.push(`SUMMARY:${escapeICS(event.summary)}`);

  if (event.description) {
    lines.push(`DESCRIPTION:${escapeICS(event.description)}`);
  }

  if (event.location) {
    lines.push(`LOCATION:${escapeICS(event.location)}`);
  }

  lines.push('STATUS:CONFIRMED');
  lines.push('SEQUENCE:0');
  lines.push('END:VEVENT');

  // Fold long lines
  return lines.map(foldLine).join('\r\n');
}

/**
 * Generate ICS calendar file content from study plan
 *
 * Creates events for:
 * - Weekly topic study blocks
 * - Mock exam sessions (ramp weeks)
 * - Final exam day
 *
 * @param plan - Study plan object
 * @returns ICS file content as string
 */
export function generateICS(plan: StudyPlan): string {
  const events: ICSEvent[] = [];

  // Add events for each week
  for (const week of plan.weeks) {
    const weekStart = new Date(week.startDate);
    const weekEnd = new Date(week.endDate);

    if (week.isRampWeek) {
      // Mock exam event (3-hour block at start of week)
      const mockStart = new Date(weekStart);
      mockStart.setHours(9, 0, 0, 0); // 9 AM
      const mockEnd = new Date(mockStart);
      mockEnd.setHours(12, 0, 0, 0); // 12 PM

      let mockDescription = '';
      if (week.rampWeekNumber === 1) {
        mockDescription =
          'Full timed mock exam. Review every miss and mark for spaced repetition. ' +
          'Hot review: weakest 5 topics from this mock (typically top-frequency topics you scored < 70%).';
      } else if (week.rampWeekNumber === 2) {
        mockDescription =
          'Fresh full set timed. Compare to mock #1: which topics improved, which didn\'t. ' +
          'Drill highest-frequency topics that scored < 70%.';
      } else {
        mockDescription =
          'Full timed simulation under exam conditions. ' +
          'Light review only the day before exam. 8h sleep, no new material in last 48h.';
      }

      events.push({
        summary: `${plan.appLabel}: Mock Exam #${week.rampWeekNumber}`,
        description: mockDescription,
        start: mockStart,
        end: mockEnd,
        location: plan.deployUrl,
      });

      // Review session (2 hours, day after mock)
      const reviewStart = new Date(mockStart);
      reviewStart.setDate(reviewStart.getDate() + 1);
      const reviewEnd = new Date(reviewStart);
      reviewEnd.setHours(reviewStart.getHours() + 2);

      events.push({
        summary: `${plan.appLabel}: Mock Review & Drill`,
        description: `Review mock exam #${week.rampWeekNumber} results and drill weak areas.`,
        start: reviewStart,
        end: reviewEnd,
        location: plan.deployUrl,
      });
    } else {
      // Topic study week - create events for each topic
      for (const topic of week.topics) {
        // Spread topic hours across the week (e.g., 2h topic = Mon+Wed 1h each)
        const sessionsNeeded = Math.ceil(topic.hours / 2); // Max 2h per session
        const hoursPerSession = topic.hours / sessionsNeeded;

        for (let session = 0; session < sessionsNeeded; session++) {
          const sessionStart = new Date(weekStart);
          sessionStart.setDate(sessionStart.getDate() + session * Math.floor(7 / sessionsNeeded));
          sessionStart.setHours(14, 0, 0, 0); // 2 PM default

          const sessionEnd = new Date(sessionStart);
          sessionEnd.setHours(sessionStart.getHours() + hoursPerSession);

          const topicDisplay = topic.he ? `${topic.en} / ${topic.he}` : topic.en;
          const description =
            `Study session: ${topicDisplay}\n` +
            `Frequency: ${topic.frequency_pct}% of past exam questions\n` +
            `Keywords: ${(topic.keywords || []).slice(0, 8).join(', ')}`;

          events.push({
            summary: `${plan.appLabel}: ${topic.en}`,
            description,
            start: sessionStart,
            end: sessionEnd,
            location: plan.deployUrl,
          });
        }
      }

      // Daily Q-bank practice (30 min blocks, Mon-Fri)
      for (let day = 0; day < 5; day++) {
        const qbankStart = new Date(weekStart);
        qbankStart.setDate(qbankStart.getDate() + day);
        qbankStart.setHours(19, 0, 0, 0); // 7 PM default

        const qbankEnd = new Date(qbankStart);
        qbankEnd.setMinutes(qbankStart.getMinutes() + 30);

        events.push({
          summary: `${plan.appLabel}: Daily Q-bank (${plan.dailyQuestionsTarget} Qs)`,
          description: `Practice ${plan.dailyQuestionsTarget} questions with FSRS spaced repetition.`,
          start: qbankStart,
          end: qbankEnd,
          location: plan.deployUrl,
        });
      }
    }
  }

  // Add final exam event
  const examStart = new Date(plan.examDate);
  examStart.setHours(8, 0, 0, 0);
  const examEnd = new Date(examStart);
  examEnd.setHours(12, 0, 0, 0);

  events.push({
    summary: `🎯 ${plan.appLabel} EXAM`,
    description: 'Good luck! You\'ve prepared well with this frequency-weighted study plan.',
    start: examStart,
    end: examEnd,
  });

  // Build ICS file
  const lines: string[] = [];

  lines.push('BEGIN:VCALENDAR');
  lines.push('VERSION:2.0');
  lines.push('PRODID:-//Eias Medical PWAs//Study Plan//EN');
  lines.push('CALSCALE:GREGORIAN');
  lines.push('METHOD:PUBLISH');
  lines.push(`X-WR-CALNAME:${plan.appLabel} Study Plan`);
  lines.push(
    `X-WR-CALDESC:Frequency-weighted study plan for ${plan.appLabel} (${plan.examDate})`
  );
  lines.push('X-WR-TIMEZONE:UTC');

  // Add all events
  for (const event of events) {
    lines.push(createICSEvent(event));
  }

  lines.push('END:VCALENDAR');

  return lines.join('\r\n');
}

/**
 * Trigger download of ICS file in the browser
 *
 * @param icsContent - ICS file content string
 * @param filename - Suggested filename (default: study-plan.ics)
 */
export function downloadICS(icsContent: string, filename = 'study-plan.ics'): void {
  const blob = new Blob([icsContent], { type: 'text/calendar;charset=utf-8' });
  const url = URL.createObjectURL(blob);

  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.style.display = 'none';

  document.body.appendChild(link);
  link.click();

  // Cleanup
  setTimeout(() => {
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, 100);
}

/**
 * Generate Google Calendar URL for adding study plan
 *
 * Note: Google Calendar URL import has limits. For full plan, use downloadICS instead.
 * This is useful for adding individual events.
 *
 * @param event - Single ICS event
 * @returns Google Calendar URL
 */
export function generateGoogleCalendarURL(event: ICSEvent): string {
  const params = new URLSearchParams({
    action: 'TEMPLATE',
    text: event.summary,
    details: event.description || '',
    dates: `${formatICSDateTime(event.start)}/${formatICSDateTime(event.end)}`,
  });

  if (event.location) {
    params.set('location', event.location);
  }

  return `https://calendar.google.com/calendar/render?${params.toString()}`;
}
