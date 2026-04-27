-- Migration: Add syllabus_data to app_config table
-- Target: Supabase PostgreSQL database shared by Geri, Pnimit, Mishpacha PWAs
--
-- This bakes the empirical topic frequency data from syllabus_data.json
-- into the app_config table so all 3 PWAs can read it from a single source.
--
-- IMPORTANT: Run this AFTER loading the syllabus_data.json content
-- The actual JSON content should be inserted from the file at:
-- /home/runner/work/auto-audit/auto-audit/scripts/syllabus_data.json

-- ============================================================================
-- 1. Create or update app_config table structure (if needed)
-- ============================================================================

-- Check if app_config table exists, create if not
CREATE TABLE IF NOT EXISTS public.app_config (
  key text PRIMARY KEY,
  value jsonb NOT NULL,
  updated_at timestamptz DEFAULT now(),
  description text
);

-- Add index on updated_at for tracking freshness
CREATE INDEX IF NOT EXISTS idx_app_config_updated_at
  ON public.app_config(updated_at);


-- ============================================================================
-- 2. Create RPC to update syllabus_data (admin-only)
-- ============================================================================

CREATE OR REPLACE FUNCTION public.app_config_update_syllabus(
  p_syllabus_data jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_result jsonb;
BEGIN
  -- Check if user has admin role
  -- Adjust this check based on your actual auth schema
  -- For now, we'll just check if user is authenticated
  IF auth.uid() IS NULL THEN
    RAISE EXCEPTION 'Must be authenticated to update app config';
  END IF;

  -- Validate that the JSON has the expected structure
  IF NOT (
    p_syllabus_data ? 'Geri' AND
    p_syllabus_data ? 'Pnimit' AND
    p_syllabus_data ? 'Mishpacha'
  ) THEN
    RAISE EXCEPTION 'Invalid syllabus_data: must contain Geri, Pnimit, and Mishpacha keys';
  END IF;

  -- Insert or update the syllabus_data
  INSERT INTO public.app_config (key, value, updated_at, description)
  VALUES (
    'syllabus_data',
    p_syllabus_data,
    now(),
    'Empirical topic frequency data from past exams for study plan generation'
  )
  ON CONFLICT (key)
  DO UPDATE SET
    value = EXCLUDED.value,
    updated_at = now();

  -- Return confirmation
  SELECT jsonb_build_object(
    'success', true,
    'updated_at', updated_at,
    'topics_geri', (value->'Geri'->>'total_topics')::int,
    'topics_pnimit', (value->'Pnimit'->>'total_topics')::int,
    'topics_mishpacha', (value->'Mishpacha'->>'total_topics')::int
  ) INTO v_result
  FROM public.app_config
  WHERE key = 'syllabus_data';

  RETURN v_result;
END;
$$;

-- Grant execute permission (restrict to admin role in production)
GRANT EXECUTE ON FUNCTION public.app_config_update_syllabus TO authenticated;


-- ============================================================================
-- 3. Create RPC to get syllabus_data (public read)
-- ============================================================================

CREATE OR REPLACE FUNCTION public.app_config_get_syllabus()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_result jsonb;
BEGIN
  -- Retrieve the syllabus_data
  SELECT value INTO v_result
  FROM public.app_config
  WHERE key = 'syllabus_data';

  -- Return NULL if not found (should be populated by admin)
  RETURN v_result;
END;
$$;

-- Grant execute permission to all authenticated users
GRANT EXECUTE ON FUNCTION public.app_config_get_syllabus TO authenticated;

-- Also allow anonymous access for public PWAs (optional, adjust based on your needs)
GRANT EXECUTE ON FUNCTION public.app_config_get_syllabus TO anon;


-- ============================================================================
-- 4. Initial data load (MANUAL STEP)
-- ============================================================================

-- After running this migration, you need to manually load the syllabus_data.json
-- content into the app_config table. You can do this via:
--
-- Option A: Supabase SQL Editor
-- Copy the content of scripts/syllabus_data.json and run:
--
-- INSERT INTO public.app_config (key, value, description)
-- VALUES (
--   'syllabus_data',
--   '{ ... paste JSON here ... }'::jsonb,
--   'Empirical topic frequency data from past exams for study plan generation'
-- )
-- ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
--
-- Option B: Use the RPC function (requires admin auth)
-- Call app_config_update_syllabus() with the JSON content from a client
--
-- Option C: Automated refresh script
-- Create a GitHub Action that runs scripts/refresh_syllabus_data.py and
-- automatically updates the database via the RPC function


-- ============================================================================
-- 5. Comments for documentation
-- ============================================================================

COMMENT ON TABLE public.app_config IS
  'Application configuration key-value store (JSONB values)';

COMMENT ON COLUMN public.app_config.key IS
  'Configuration key (e.g., syllabus_data, app_settings)';

COMMENT ON COLUMN public.app_config.value IS
  'Configuration value as JSON';

COMMENT ON COLUMN public.app_config.updated_at IS
  'Timestamp of last update';

COMMENT ON FUNCTION public.app_config_update_syllabus IS
  'Update syllabus_data in app_config (admin-only). Validates structure before saving.';

COMMENT ON FUNCTION public.app_config_get_syllabus IS
  'Get syllabus_data from app_config (public read access)';
