/**
 * Type definitions for the Study Plan feature (Phase 2)
 *
 * These types correspond to the Python implementation in scripts/generate_study_plan.py
 * and the database schema in phase2/sql/001_create_study_plans.sql
 */

/**
 * App identifier for the three medical PWAs
 */
export type AppKey = 'geri' | 'pnimit' | 'mishpacha';

/**
 * Full app label mapping (for display)
 */
export type AppLabel = 'Geri' | 'Pnimit' | 'Mishpacha';

/**
 * Metadata about each app
 */
export interface AppMetadata {
  label: string;
  deployUrl: string;
  nQuestionsTargetPerDay: number;
}

/**
 * Topic data structure from syllabus_data.json
 */
export interface TopicData {
  id: number;
  en: string;
  he?: string;
  keywords?: string[];
  n_questions: number;
  frequency_pct: number;
  weight: number;
}

/**
 * Topic data with allocated hours
 */
export interface TopicWithHours extends TopicData {
  hours: number;
}

/**
 * Syllabus data for one app
 */
export interface AppSyllabusData {
  repo: string;
  total_questions_analyzed: number;
  total_topics: number;
  topics: TopicData[];
}

/**
 * Complete syllabus data structure (from syllabus_data.json or app_config)
 */
export interface SyllabusData {
  Geri: AppSyllabusData;
  Pnimit: AppSyllabusData;
  Mishpacha: AppSyllabusData;
}

/**
 * Weekly schedule item (one week in the study plan)
 */
export interface WeekSchedule {
  weekNumber: number;
  startDate: string; // ISO 8601 date string
  endDate: string;   // ISO 8601 date string
  topics: TopicWithHours[];
  topicHours: number;
  qBankHours: number;
  miscHours: number;
  isRampWeek?: boolean;
  rampWeekNumber?: number;
}

/**
 * Complete study plan structure
 */
export interface StudyPlan {
  app: AppKey;
  appLabel: string;
  examDate: string;      // ISO 8601 date string
  startDate: string;     // ISO 8601 date string
  totalWeeks: number;
  topicWeeks: number;
  rampWeeks: number;
  hoursPerWeek: number;
  topicHoursPerWeek: number;
  qBankHoursPerWeek: number;
  miscHoursPerWeek: number;
  dailyQuestionsTarget: number;
  deployUrl: string;
  totalQuestionsAnalyzed: number;
  weeks: WeekSchedule[];
  topicsSummary: TopicWithHours[];
}

/**
 * Parameters for generating a study plan
 */
export interface StudyPlanParams {
  app: AppKey;
  examDate: string | Date;  // ISO 8601 date string or Date object
  hoursPerWeek?: number;     // Default: 8
  startDate?: string | Date; // Default: today
  rampWeeks?: number;        // Default: 3
}

/**
 * Database row structure for study_plans table
 */
export interface StudyPlanRow {
  username: string;
  app: AppKey;
  exam_date: string;
  hours_per_week: number;
  ramp_weeks: number;
  plan_json: StudyPlan | null;
  generated_at: string;
}

/**
 * RPC function parameters for study_plan_upsert
 */
export interface StudyPlanUpsertParams {
  p_app: AppKey;
  p_exam_date: string;
  p_hours_per_week: number;
  p_ramp_weeks: number;
  p_plan_json: StudyPlan;
}

/**
 * RPC function result from study_plan_upsert
 */
export interface StudyPlanUpsertResult {
  username: string;
  app: AppKey;
  exam_date: string;
  hours_per_week: number;
  ramp_weeks: number;
  generated_at: string;
}

/**
 * RPC function result from study_plan_get
 */
export interface StudyPlanGetResult {
  username: string;
  app: AppKey;
  exam_date: string;
  hours_per_week: number;
  ramp_weeks: number;
  plan_json: StudyPlan | null;
  generated_at: string;
}

/**
 * ICS calendar event for study plan export
 */
export interface ICSEvent {
  summary: string;
  description: string;
  start: Date;
  end: Date;
  location?: string;
}
