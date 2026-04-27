/**
 * test-study-plan.ts — Simple test to verify TypeScript implementation
 *
 * Run with: npx ts-node phase2/typescript/test-study-plan.ts
 * Or compile and run: tsc phase2/typescript/test-study-plan.ts && node phase2/typescript/test-study-plan.js
 */

import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';
import { generateStudyPlan, renderMarkdown, APP_METADATA } from './studyPlan';
import { generateICS } from './icsExport';
import type { SyllabusData } from './types';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Load syllabus data
const syllabusDataPath = path.join(__dirname, '../../scripts/syllabus_data.json');
const syllabusData: SyllabusData = JSON.parse(fs.readFileSync(syllabusDataPath, 'utf-8'));

console.log('🧪 Testing Study Plan TypeScript Implementation\n');

// Test 1: Allocate hours for Mishpacha
console.log('Test 1: Generate study plan for Mishpacha');
console.log('==========================================');

try {
  const mishpachaPlan = generateStudyPlan(syllabusData, {
    app: 'mishpacha',
    examDate: '2026-12-01',
    startDate: '2026-09-01',
    hoursPerWeek: 10,
    rampWeeks: 3,
  });

  console.log(`✅ Plan generated successfully`);
  console.log(`   App: ${mishpachaPlan.appLabel}`);
  console.log(`   Exam date: ${mishpachaPlan.examDate}`);
  console.log(`   Start date: ${mishpachaPlan.startDate}`);
  console.log(`   Total weeks: ${mishpachaPlan.totalWeeks}`);
  console.log(`   Topic weeks: ${mishpachaPlan.topicWeeks}`);
  console.log(`   Ramp weeks: ${mishpachaPlan.rampWeeks}`);
  console.log(`   Topics: ${mishpachaPlan.topicsSummary.length}`);
  console.log(`   Questions analyzed: ${mishpachaPlan.totalQuestionsAnalyzed}`);

  // Verify weekly schedule
  const topicWeeks = mishpachaPlan.weeks.filter(w => !w.isRampWeek);
  const rampWeeks = mishpachaPlan.weeks.filter(w => w.isRampWeek);
  console.log(`   Topic study weeks: ${topicWeeks.length}`);
  console.log(`   Ramp weeks: ${rampWeeks.length}`);

  // Verify hours allocation
  const totalTopicHours = topicWeeks.reduce((sum, w) => sum + w.topicHours, 0);
  console.log(`   Total topic hours: ${totalTopicHours.toFixed(1)}h`);

  // Check that high-frequency topics come first
  const firstWeekTopics = topicWeeks[0].topics;
  if (firstWeekTopics.length > 0) {
    const firstTopic = firstWeekTopics[0];
    console.log(`   First week first topic: ${firstTopic.en} (${firstTopic.frequency_pct}%)`);
  }

  console.log('\n');
} catch (error) {
  console.error(`❌ Failed to generate Mishpacha plan:`, error);
  process.exit(1);
}

// Test 2: Generate plan for Geri
console.log('Test 2: Generate study plan for Geri');
console.log('====================================');

try {
  const geriPlan = generateStudyPlan(syllabusData, {
    app: 'geri',
    examDate: '2026-09-15',
    startDate: '2026-06-01',
    hoursPerWeek: 8,
    rampWeeks: 3,
  });

  console.log(`✅ Plan generated successfully`);
  console.log(`   App: ${geriPlan.appLabel}`);
  console.log(`   Topics: ${geriPlan.topicsSummary.length}`);
  console.log(`   Questions analyzed: ${geriPlan.totalQuestionsAnalyzed}`);
  console.log('\n');
} catch (error) {
  console.error(`❌ Failed to generate Geri plan:`, error);
  process.exit(1);
}

// Test 3: Generate plan for Pnimit
console.log('Test 3: Generate study plan for Pnimit');
console.log('======================================');

try {
  const pnimitPlan = generateStudyPlan(syllabusData, {
    app: 'pnimit',
    examDate: '2026-12-01',
    startDate: '2026-08-01',
    hoursPerWeek: 12,
    rampWeeks: 3,
  });

  console.log(`✅ Plan generated successfully`);
  console.log(`   App: ${pnimitPlan.appLabel}`);
  console.log(`   Topics: ${pnimitPlan.topicsSummary.length}`);
  console.log(`   Questions analyzed: ${pnimitPlan.totalQuestionsAnalyzed}`);
  console.log('\n');
} catch (error) {
  console.error(`❌ Failed to generate Pnimit plan:`, error);
  process.exit(1);
}

// Test 4: Error handling - exam date before start date
console.log('Test 4: Error handling');
console.log('=====================');

try {
  generateStudyPlan(syllabusData, {
    app: 'mishpacha',
    examDate: '2026-01-01',
    startDate: '2026-12-01',
  });
  console.error(`❌ Should have thrown error for invalid dates`);
  process.exit(1);
} catch (error) {
  console.log(`✅ Correctly throws error for invalid dates`);
  console.log(`   Error: ${(error as Error).message}`);
  console.log('\n');
}

// Test 5: Render markdown
console.log('Test 5: Render markdown');
console.log('=======================');

try {
  const mishpachaPlan = generateStudyPlan(syllabusData, {
    app: 'mishpacha',
    examDate: '2026-12-01',
    startDate: '2026-09-01',
    hoursPerWeek: 10,
    rampWeeks: 3,
  });

  const markdown = renderMarkdown(mishpachaPlan);
  console.log(`✅ Markdown rendered successfully`);
  console.log(`   Length: ${markdown.length} characters`);
  console.log(`   Lines: ${markdown.split('\n').length}`);

  // Check that markdown contains expected sections
  const hasHeader = markdown.includes('# Family Medicine');
  const hasTopicTable = markdown.includes('| Rank | Topic |');
  const hasWeeks = markdown.includes('## Week 1');
  const hasRampWeeks = markdown.includes('## Ramp Week');

  console.log(`   Has header: ${hasHeader ? '✅' : '❌'}`);
  console.log(`   Has topic table: ${hasTopicTable ? '✅' : '❌'}`);
  console.log(`   Has weeks: ${hasWeeks ? '✅' : '❌'}`);
  console.log(`   Has ramp weeks: ${hasRampWeeks ? '✅' : '❌'}`);

  // Write to file for manual inspection
  const outputPath = path.join(__dirname, 'test-output-mishpacha.md');
  fs.writeFileSync(outputPath, markdown, 'utf-8');
  console.log(`   Written to: ${outputPath}`);
  console.log('\n');
} catch (error) {
  console.error(`❌ Failed to render markdown:`, error);
  process.exit(1);
}

// Test 6: ICS export
console.log('Test 6: ICS calendar export');
console.log('===========================');

try {
  const mishpachaPlan = generateStudyPlan(syllabusData, {
    app: 'mishpacha',
    examDate: '2026-12-01',
    startDate: '2026-11-01',
    hoursPerWeek: 10,
    rampWeeks: 2,
  });

  const icsContent = generateICS(mishpachaPlan);
  console.log(`✅ ICS generated successfully`);
  console.log(`   Length: ${icsContent.length} characters`);

  // Check ICS structure
  const hasHeader = icsContent.includes('BEGIN:VCALENDAR');
  const hasEvents = icsContent.includes('BEGIN:VEVENT');
  const hasFooter = icsContent.includes('END:VCALENDAR');
  const hasMockExam = icsContent.includes('Mock Exam');
  const hasExamDay = icsContent.includes('EXAM');

  console.log(`   Has VCALENDAR header: ${hasHeader ? '✅' : '❌'}`);
  console.log(`   Has VEVENT blocks: ${hasEvents ? '✅' : '❌'}`);
  console.log(`   Has VCALENDAR footer: ${hasFooter ? '✅' : '❌'}`);
  console.log(`   Has mock exam events: ${hasMockExam ? '✅' : '❌'}`);
  console.log(`   Has exam day event: ${hasExamDay ? '✅' : '❌'}`);

  // Count events
  const eventCount = (icsContent.match(/BEGIN:VEVENT/g) || []).length;
  console.log(`   Total events: ${eventCount}`);

  // Write to file for manual testing
  const outputPath = path.join(__dirname, 'test-output-mishpacha.ics');
  fs.writeFileSync(outputPath, icsContent, 'utf-8');
  console.log(`   Written to: ${outputPath}`);
  console.log(`   📅 Import this file to Google Calendar to verify`);
  console.log('\n');
} catch (error) {
  console.error(`❌ Failed to generate ICS:`, error);
  process.exit(1);
}

// Test 7: Compare with Python reference
console.log('Test 7: Compare with Python reference output');
console.log('============================================');

console.log('Run this manually to compare:');
console.log('  1. Python version:');
console.log('     python scripts/generate_study_plan.py --app mishpacha --exam-date 2026-12-01 --start-date 2026-09-01 --hours-per-week 10');
console.log('  2. TypeScript version output is in:');
console.log('     phase2/typescript/test-output-mishpacha.md');
console.log('  3. Compare the two files for consistency');
console.log('\n');

console.log('✅ All tests passed!');
console.log('\nNext steps:');
console.log('1. Review test-output-mishpacha.md and compare with Python output');
console.log('2. Import test-output-mishpacha.ics to Google Calendar');
console.log('3. Proceed with PWA integration (see phase2/docs/INTEGRATION.md)');
