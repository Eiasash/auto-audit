# Session learnings — 2026-04-28 overnight job

## What shipped

Three PRs open by end of session, none merged (per stop-condition: Eias does final review):

| Repo | PR | Title | Status |
|---|---|---|---|
| `Eiasash/auto-audit` | [#3](https://github.com/Eiasash/auto-audit/pull/3) | Tier 1 auto-dispatch for known-safe fix templates | OPEN, MERGEABLE — was already pushed before this session opened (Step 0 of the overnight plan was a no-op for me) |
| `Eiasash/InternalMedicine` | [#48](https://github.com/Eiasash/InternalMedicine/pull/48) | v9.86.0 — Study Plan generator (mirror of Mishpacha v1.9.1) | OPEN, all 563 tests passing, build green |
| `Eiasash/Geriatrics` | [#96](https://github.com/Eiasash/Geriatrics/pull/96) | v10.46.0 — Study Plan generator (mirror of Mishpacha v1.9.1 + Pnimit v9.86.0) | OPEN, all 859 tests passing |

Manual follow-ups Eias still needs to do:
- **Upgrade `MONITOR_PAT` scope** per `auto-audit/PROBE_PAT_UPGRADE.md` — add `Actions: Read & write` on `Eiasash/auto-audit` (token VALUE doesn't change, just scopes). Without this, Tier 1 auto-dispatch will post a "FAILED" comment on the issue (informative, not destructive). Required for PR #3 to be functionally complete.
- **Review + merge** the two study-plan PRs (#48, #96) and the auto-dispatch PR (#3) in any order.
- The shared Supabase migration (`public.study_plans` table + RPCs) was already applied by FM v1.9.0 — Pnimit + Geri PRs need NO database work.

## Reality vs the overnight job description

- **FM was already shipped at v1.9.1**, not "1.9.1+ on a feature branch" — local clones were stale; `git fetch --all` resolved.
- **Pnimit was at v9.85.0, not v9.84.1** — same staleness issue. The job's prescribed bump (9.85.0 → 9.86.0) was correct after fetching.
- **auto-audit Step 0 was a no-op** — the patch (`auto-dispatch-known-fixes.patch`) had already been applied and pushed as branch `feature/auto-dispatch-known-fixes` and PR #3 was already open before this session. Verified PR #3 mergeable + correct file diff, then moved on to the primary mission.

## Gotchas hit

### 1. `npm run verify` Windows env-var prefix

Geri's `verify` script chains `HARRISON_HEBREW_BASELINE=0 node scripts/...` which breaks on Windows cmd.exe (the npm-script shell). Already documented in user CLAUDE.md as a known git-bash gotcha. Workaround: ran the steps individually in bash. Pipeline content all green; the failure was purely shell syntax. Suggested fix for the future: `cross-env HARRISON_HEBREW_BASELINE=0 ...` in the verify script (or run just `npx vitest run` and let the harness env handle it).

### 2. JS↔Python schedule divergence on Geri's 46-topic slice

Surfaced (not silently fixed) per the job's stop condition:

- FM's `algorithm.js` uses `+ 1e-9` float tolerance in the weekly capacity check.
- `auto-audit/scripts/generate_study_plan.py` uses strict `<= weekly_budget + 0.5`.
- For Geri's 46-topic input, `5.2 + 0.9` floats up to `6.1000000000000005` in Python, so Python rejects placement at the 6.1 boundary; JS admits it. ONE 0.9h topic ends up in week 8 in JS, week 14 in Python.
- Identical topic SET, identical total study hours (88.4) — only one week-index shifts.
- FM (27 topics) and Pnimit (24 topics) don't trigger the boundary; their fixtures pass JS↔Python byte-identical.
- Geri's test asserts the JS vector and includes both vectors inline as a comment. PR #96 body has the full discussion.

**Open follow-up question** for Eias: align JS to Python (touch FM's algorithm.js, re-baseline FM fixture) OR loosen Python (re-baseline auto-audit reference) OR leave as-is. Not blocking — clinically equivalent plans either way.

### 3. Untracked workspace files

- Geri repo had pre-existing untracked `scripts/auto_fix/` and `scripts/probes/` (unrelated to study plan, leftover from earlier sessions). Stayed out of my commits.
- Pnimit repo had pre-existing `data/questions.json.bak` (stayed out of commit).

## Stretch goal — done

[`auto-audit` PR #4](https://github.com/Eiasash/auto-audit/pull/4) — Tier 1 `study_plan_view` parity probe.

What it does: fetches `syllabus_data.json` from all 3 apps via the GitHub Contents API, hashes them, flags drift if they ever diverge. Slight reframe from the literal job description ("via the live RPCs") — the RPCs only round-trip stored plans, they don't recompute, so a parity check via RPCs would either need a synthetic test user (writes cruft every 30 min) or compare-on-shape (low signal). The static `syllabus_data.json` parity check is higher-signal: any drift in the topic data immediately desyncs the three apps' generated plans, and it costs zero writes.

Pre-merge gracefully degrades: Pnimit + Geri haven't merged their syllabus files to main yet, so the probe currently skips with a stderr note. Activates automatically once both PRs merge — no follow-up code needed.

The algorithm-primitive parity (allocateHours / schedule / render) is already guarded by each repo's own `tests/studyPlanAlgorithm.test.js` cross-language fixture pinned against `scripts/generate_study_plan.py`, so the auto-audit probe doesn't need to duplicate that.

## What I didn't do

- **No auto-merge** of any PR (per explicit job constraint).
- **No `main` push** in any repo (per branch policy).
- **No changes to `shared/fsrs.js` / `harrison_chapters.json` / `drugs.json`** (lane discipline).

## Architecture note for future ports between the three apps

The three apps' study-plan implementations now form a useful template:

| App | Pattern | Loadable via | Tested via |
|---|---|---|---|
| FamilyMedicine v1.9.1 | ES modules under `src/features/study_plan/` | Vite bundler | `import` in vitest |
| Pnimit v9.86.0 (PR #48) | ES modules under `src/features/study_plan/` (mirror of FM) | Vite bundler | `import` in vitest |
| Geriatrics v10.46.0 (PR #96) | Plain JS scripts at `src/study_plan_algorithm.js` + `src/study_plan.js` | `<script src=…>` in single-file HTML | `vm.runInContext` (mirrors `flashcardFsrs.test.js`) |

The algorithm primitives are byte-identical across all three; only the *packaging* differs (modular Vite vs single-file). When porting other features:
- Vite siblings (FM ↔ Pnimit) — direct file copy + `APP_KEY` swap + UI hookup.
- Geri sibling — split into a vm-loadable algorithm script + an IIFE UI script + add to `JSON_DATA_URLS` / `HTML_URLS` in `sw.js` if new data files.

Hebrew strings can be copied 1:1 between Mishpacha and Pnimit; Geri sometimes needs subtle tweaks (the Pnimit string "1,556 שאלות, 24 נושאים" became "3,833 שאלות, 46 נושאים" + a different exam-day pin label `🎯 בחינת שלב א' גריאטריה (P005-2026)`).
