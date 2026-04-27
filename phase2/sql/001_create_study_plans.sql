-- Migration: Create study_plans table and RPC functions for Phase 2
-- Target: Supabase PostgreSQL database shared by Geri, Pnimit, Mishpacha PWAs
-- Run this once in the Supabase SQL editor or via migration tool

-- ============================================================================
-- 1. Create the study_plans table
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.study_plans (
  username text NOT NULL,
  app text NOT NULL CHECK (app IN ('geri','pnimit','mishpacha')),
  exam_date date NOT NULL,
  hours_per_week numeric NOT NULL DEFAULT 8
    CHECK (hours_per_week BETWEEN 1 AND 40),
  ramp_weeks int NOT NULL DEFAULT 3
    CHECK (ramp_weeks BETWEEN 1 AND 6),
  plan_json jsonb,
  generated_at timestamptz DEFAULT now(),
  PRIMARY KEY (username, app),
  CONSTRAINT fk_study_plans_user
    FOREIGN KEY (username)
    REFERENCES public.app_users(username)
    ON DELETE CASCADE
);

-- Add index on generated_at for analytics queries
CREATE INDEX IF NOT EXISTS idx_study_plans_generated_at
  ON public.study_plans(generated_at);

-- Add index on exam_date for filtering upcoming exams
CREATE INDEX IF NOT EXISTS idx_study_plans_exam_date
  ON public.study_plans(exam_date);

-- Enable Row Level Security (deny-all by default)
ALTER TABLE public.study_plans ENABLE ROW LEVEL SECURITY;

-- No RLS policies defined = deny all direct access
-- All access must go through SECURITY DEFINER RPCs below


-- ============================================================================
-- 2. Create RPC: study_plan_upsert
-- ============================================================================
-- Insert or update a study plan for the current authenticated user

CREATE OR REPLACE FUNCTION public.study_plan_upsert(
  p_app text,
  p_exam_date date,
  p_hours_per_week numeric,
  p_ramp_weeks int,
  p_plan_json jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_username text;
  v_result jsonb;
BEGIN
  -- Get the authenticated user's username from JWT claims
  -- Assumes auth.uid() -> app_users.id mapping exists
  -- Adjust this query based on your actual auth schema
  SELECT username INTO v_username
  FROM public.app_users
  WHERE id = auth.uid();

  IF v_username IS NULL THEN
    RAISE EXCEPTION 'User not authenticated or not found in app_users';
  END IF;

  -- Validate app parameter
  IF p_app NOT IN ('geri', 'pnimit', 'mishpacha') THEN
    RAISE EXCEPTION 'Invalid app: must be geri, pnimit, or mishpacha';
  END IF;

  -- Validate hours_per_week
  IF p_hours_per_week < 1 OR p_hours_per_week > 40 THEN
    RAISE EXCEPTION 'hours_per_week must be between 1 and 40';
  END IF;

  -- Validate ramp_weeks
  IF p_ramp_weeks < 1 OR p_ramp_weeks > 6 THEN
    RAISE EXCEPTION 'ramp_weeks must be between 1 and 6';
  END IF;

  -- Validate exam_date is in the future
  IF p_exam_date <= CURRENT_DATE THEN
    RAISE EXCEPTION 'exam_date must be in the future';
  END IF;

  -- Insert or update the study plan
  INSERT INTO public.study_plans (
    username,
    app,
    exam_date,
    hours_per_week,
    ramp_weeks,
    plan_json,
    generated_at
  )
  VALUES (
    v_username,
    p_app,
    p_exam_date,
    p_hours_per_week,
    p_ramp_weeks,
    p_plan_json,
    now()
  )
  ON CONFLICT (username, app)
  DO UPDATE SET
    exam_date = EXCLUDED.exam_date,
    hours_per_week = EXCLUDED.hours_per_week,
    ramp_weeks = EXCLUDED.ramp_weeks,
    plan_json = EXCLUDED.plan_json,
    generated_at = now()
  RETURNING
    jsonb_build_object(
      'username', username,
      'app', app,
      'exam_date', exam_date,
      'hours_per_week', hours_per_week,
      'ramp_weeks', ramp_weeks,
      'generated_at', generated_at
    ) INTO v_result;

  RETURN v_result;
END;
$$;

-- Grant execute permission to authenticated users only
GRANT EXECUTE ON FUNCTION public.study_plan_upsert TO authenticated;


-- ============================================================================
-- 3. Create RPC: study_plan_get
-- ============================================================================
-- Retrieve study plan for the current authenticated user and specified app

CREATE OR REPLACE FUNCTION public.study_plan_get(
  p_app text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_username text;
  v_result jsonb;
BEGIN
  -- Get the authenticated user's username
  SELECT username INTO v_username
  FROM public.app_users
  WHERE id = auth.uid();

  IF v_username IS NULL THEN
    RAISE EXCEPTION 'User not authenticated or not found in app_users';
  END IF;

  -- Validate app parameter
  IF p_app NOT IN ('geri', 'pnimit', 'mishpacha') THEN
    RAISE EXCEPTION 'Invalid app: must be geri, pnimit, or mishpacha';
  END IF;

  -- Retrieve the study plan
  SELECT jsonb_build_object(
    'username', username,
    'app', app,
    'exam_date', exam_date,
    'hours_per_week', hours_per_week,
    'ramp_weeks', ramp_weeks,
    'plan_json', plan_json,
    'generated_at', generated_at
  ) INTO v_result
  FROM public.study_plans
  WHERE username = v_username
    AND app = p_app;

  -- Return NULL if no plan exists (not an error)
  RETURN v_result;
END;
$$;

-- Grant execute permission to authenticated users only
GRANT EXECUTE ON FUNCTION public.study_plan_get TO authenticated;


-- ============================================================================
-- 4. Create RPC: study_plan_delete
-- ============================================================================
-- Delete study plan for the current authenticated user and specified app

CREATE OR REPLACE FUNCTION public.study_plan_delete(
  p_app text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_username text;
  v_deleted boolean;
BEGIN
  -- Get the authenticated user's username
  SELECT username INTO v_username
  FROM public.app_users
  WHERE id = auth.uid();

  IF v_username IS NULL THEN
    RAISE EXCEPTION 'User not authenticated or not found in app_users';
  END IF;

  -- Validate app parameter
  IF p_app NOT IN ('geri', 'pnimit', 'mishpacha') THEN
    RAISE EXCEPTION 'Invalid app: must be geri, pnimit, or mishpacha';
  END IF;

  -- Delete the study plan
  DELETE FROM public.study_plans
  WHERE username = v_username
    AND app = p_app;

  -- Return true if a row was deleted
  GET DIAGNOSTICS v_deleted = ROW_COUNT;
  RETURN v_deleted > 0;
END;
$$;

-- Grant execute permission to authenticated users only
GRANT EXECUTE ON FUNCTION public.study_plan_delete TO authenticated;


-- ============================================================================
-- 5. Comments for documentation
-- ============================================================================

COMMENT ON TABLE public.study_plans IS
  'Stores personalized study plans for medical exam preparation across Geri, Pnimit, Mishpacha apps. One plan per user per app.';

COMMENT ON COLUMN public.study_plans.username IS
  'Username from app_users table (FK with CASCADE delete)';

COMMENT ON COLUMN public.study_plans.app IS
  'App identifier: geri (Geriatrics), pnimit (Internal Medicine), mishpacha (Family Medicine)';

COMMENT ON COLUMN public.study_plans.exam_date IS
  'Target exam date entered by user';

COMMENT ON COLUMN public.study_plans.hours_per_week IS
  'Study hours per week (1-40), used for plan generation';

COMMENT ON COLUMN public.study_plans.ramp_weeks IS
  'Number of pre-exam mock exam weeks (1-6)';

COMMENT ON COLUMN public.study_plans.plan_json IS
  'Generated study plan as JSON: {weeks: [{topics: [...], hours: N}], metadata: {...}}';

COMMENT ON COLUMN public.study_plans.generated_at IS
  'Timestamp when plan was last generated/updated';

COMMENT ON FUNCTION public.study_plan_upsert IS
  'Upsert study plan for authenticated user. Returns plan metadata on success.';

COMMENT ON FUNCTION public.study_plan_get IS
  'Get study plan for authenticated user. Returns NULL if no plan exists.';

COMMENT ON FUNCTION public.study_plan_delete IS
  'Delete study plan for authenticated user. Returns true if deleted, false if not found.';
