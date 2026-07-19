# Tier 3 — Weekly synthesis · 2026-07-19

_Window: last 7 days · 216 health reports parsed · generated 2026-07-19 06:57Z_

_Prior week: https://github.com/Eiasash/auto-audit/issues/71_

## Action needed

**Warning** (20)
- (probe-recurring) Probe `feedback_queue` fired in 36 reports this window. Last: 2026-07-13T09:08:17.874751+00:00.
- (probe-recurring) Probe `scheduler_health` fired in 49 reports this window. Last: 2026-07-19T06:01:28.467318+00:00.
- (probe-recurring) Probe `dispatch_chain` fired in 182 reports this window. Last: 2026-07-19T06:01:28.467318+00:00.
- (probe-recurring) Probe `dispatch_pat_freshness` fired in 181 reports this window. Last: 2026-07-19T06:01:28.467318+00:00.
- (probe-recurring) Probe `study_plan_parity` fired in 179 reports this window. Last: 2026-07-19T06:01:28.467318+00:00.
- (workflow-streak) `Geriatrics` / `Notify auto-audit` failed across 7 distinct SHAs this window.
- (workflow-streak) `InternalMedicine` / `Notify auto-audit` failed across 7 distinct SHAs this window.
- (workflow-streak) `FamilyMedicine` / `Notify auto-audit` failed across 8 distinct SHAs this window.
- (workflow-streak) `ward-helper` / `Notify auto-audit` failed across 5 distinct SHAs this window.
- (issue-aging) `auto-audit` issue [#71](https://github.com/Eiasash/auto-audit/issues/71) open for 27 days: [Tier 3] Weekly synthesis · 2026-06-21 — 3 warn
- (issue-aging) `rotation-reminder` issue [#72](https://github.com/Eiasash/auto-audit/issues/72) open for 17 days: [reminder] Proxy secret rotation due
- (target-issue-aging) `Eiasash/ward-helper` auto-audit finding [#264](https://github.com/Eiasash/ward-helper/issues/264) open 18 days: [auto-audit] 1 critical issue(s) — 2026-07-01
- (target-issue-aging) `Eiasash/ward-helper` auto-audit finding [#263](https://github.com/Eiasash/ward-helper/issues/263) open 19 days: [auto-audit] 1 critical issue(s) — 2026-06-30
- (target-issue-aging) `Eiasash/ward-helper` auto-audit finding [#262](https://github.com/Eiasash/ward-helper/issues/262) open 19 days: [auto-audit] 1 critical issue(s) — 2026-06-29
- (target-issue-aging) `Eiasash/ward-helper` auto-audit finding [#260](https://github.com/Eiasash/ward-helper/issues/260) open 25 days: [auto-audit] 1 critical issue(s) — 2026-06-24
- (target-issue-aging) `Eiasash/ward-helper` auto-audit finding [#253](https://github.com/Eiasash/ward-helper/issues/253) open 25 days: [auto-audit] 1 critical issue(s) — 2026-06-23
- (target-issue-aging) `Eiasash/Toranot` auto-audit finding [#125](https://github.com/Eiasash/Toranot/issues/125) open 18 days: [auto-audit] 1 high npm vulnerability — 2026-07-01
- (target-issue-aging) `Eiasash/watch-advisor2` auto-audit finding [#279](https://github.com/Eiasash/watch-advisor2/issues/279) open 17 days: [auto-audit] 1 critical issue(s) — 2026-07-02
- (target-issue-aging) `Eiasash/watch-advisor2` auto-audit finding [#277](https://github.com/Eiasash/watch-advisor2/issues/277) open 18 days: [auto-audit] 1 critical issue(s) — 2026-06-30
- (secret-rotation) `AUTO_AUDIT_DISPATCH_PAT` will hit the 90-day rotation deadline in 9 days. Plan: create a fine-grained PAT scoped to auto-audit + run `scripts/rotate_dispatch_pat.py`.

## Narrative

The most coherent pattern this week is a **dispatch loop that has effectively stopped working**. `dispatch_chain` and `dispatch_pat_freshness` fired ~181–182 times — nearly every report in the window — and the `AUTO_AUDIT_DISPATCH_PAT` expires in 9 days. The "Notify auto-audit" workflow failing across 5–8 distinct SHAs in every active repo isn't a per-repo problem; it's the same broken dispatch path expressing itself everywhere. The streak counts spanning multiple SHAs confirm this predates any single deploy.

This breakdown has a downstream consequence on the audit finding backlog. Auto-audit is still *emitting* issues (Geriatrics: 182, InternalMedicine: 393, FamilyMedicine: 220, ward-helper: 154, Toranot: 219) but notifications aren't landing, which likely explains why critical findings across ward-helper (#253, #260, #262, #263, #264) and watch-advisor2 (#277, #279) have aged 17–25 days without apparent triage. The system is generating signal; the delivery layer is suppressing it.

`scheduler_health` (49 firings) and `feedback_queue` (36 firings, last seen July 13 — six days ago) represent a second cluster. The feedback queue going silent while the scheduler continues to fire suggests the queue consumer stalled independently of the dispatch issue, compounding the blind spots in what actually reaches attention.

Spend is negligible and not a factor this week.

## Cross-cutting probe activity

- `dispatch_chain` — fired in **182** reports (last: 2026-07-19T06:01:28.467318+00:00)
  - {"severity": "critical", "kind": "dispatch_chain_run_failed", "msg": "Geriatrics: most recent notify-auto-audit run FAILED (sha 96d54972, 2026-07-18T22:10:59Z). Most likely cause: AUTO_AUDIT_DISPATCH_PAT expired, was revoked, or lost the Ac
  - {"severity": "critical", "kind": "dispatch_chain_run_failed", "msg": "InternalMedicine: most recent notify-auto-audit run FAILED (sha 2891c9c3, 2026-07-18T22:14:25Z). Most likely cause: AUTO_AUDIT_DISPATCH_PAT expired, was revoked, or lost
- `dispatch_pat_freshness` — fired in **181** reports (last: 2026-07-19T06:01:28.467318+00:00)
  - {"severity": "warning", "kind": "dispatch_pat_aging", "msg": "Geriatrics: AUTO_AUDIT_DISPATCH_PAT last rotated 80 days ago (2026-04-29T09:09:39Z). Approaching the 90-day rotation cadence \u2014 plan to rotate within 10 days per scripts/DISP
  - {"severity": "warning", "kind": "dispatch_pat_aging", "msg": "InternalMedicine: AUTO_AUDIT_DISPATCH_PAT last rotated 80 days ago (2026-04-29T09:09:39Z). Approaching the 90-day rotation cadence \u2014 plan to rotate within 10 days per script
- `study_plan_parity` — fired in **179** reports (last: 2026-07-19T06:01:28.467318+00:00)
  - {"severity": "warning", "kind": "study_plan_syllabus_drift", "msg": "syllabus_data.json differs across the three medical PWAs: {'FamilyMedicine': '2b295d1317ad', 'InternalMedicine': '2b295d1317ad', 'Geriatrics': '8165cacec81b'}", "auto_fix"
- `scheduler_health` — fired in **49** reports (last: 2026-07-19T06:01:28.467318+00:00)
  - {"severity": "warning", "kind": "scheduler-drift", "msg": "GHA scheduler dropped ticks: previous Tier 1 schedule run was 84 min ago (expected \u2264 30). Repository_dispatch path (issue #14) is the durable fix \u2014 verify AUTO_AUDIT_DISPA
- `feedback_queue` — fired in **36** reports (last: 2026-07-13T09:08:17.874751+00:00)
  - {"severity": "warning", "kind": "feedback_queue_item", "msg": "feedback/mishpacha#6 (bug) \u2192 needs_review. FamilyMedicine#174", "row_id": 6, "verdict": "needs_review", "issue_num": 174, "repo": "FamilyMedicine"}

## Spend trajectory

- Earliest snapshot (2026-07-12): MTD **$0.10**, 20 calls
- Latest snapshot (2026-07-19): MTD **$0.11**, 36 calls
- Window delta: **+$0.01**
- Projected end-of-month: **$0.18**

## Per-repo activity

### Geriatrics
- live SW: `10.64.191` · version bumps this week: **5** · workflow failures (distinct SHAs): **8** · commits to main: **10** · merged PRs: **9**
  - `Notify auto-audit` (7): [`d479ed3`](https://github.com/Eiasash/Geriatrics/actions/runs/29230745474), [`8dc7a7d`](https://github.com/Eiasash/Geriatrics/actions/runs/29246984299), [`20cb3ea`](https://github.com/Eiasash/Geriatrics/actions/runs/29260529255), [`5dea4db`](https://github.com/Eiasash/Geriatrics/actions/runs/29364279582), [`b04ff61`](https://github.com/Eiasash/Geriatrics/actions/runs/29424710997)
  - `Weekly Audit` (1): [`ea3ed5f`](https://github.com/Eiasash/Geriatrics/actions/runs/29183240253)
  - Recent merged PRs:
    - [#419](https://github.com/Eiasash/Geriatrics/pull/419) Round-2: FSRS anchor reschedule + streak/autopsy/proxy-401 (G5 held)
    - [#418](https://github.com/Eiasash/Geriatrics/pull/418) Audit fixes: mock crash, boot resilience, exam-mode AI gating (G1-G4)
    - [#414](https://github.com/Eiasash/Geriatrics/pull/414) DRAFT - DO NOT MERGE until Netlify API_SECRET dual-accept + UPSTASH set (P0 proxy JWT cutover)
    - [#413](https://github.com/Eiasash/Geriatrics/pull/413) ci(gitleaks): harden install step (authenticate release fetch)
    - [#411](https://github.com/Eiasash/Geriatrics/pull/411) v10.64.190: cache-bump for syllabus sync + weekly-audit judge timeout + gitleaks

### InternalMedicine
- live SW: `10.4.59` · version bumps this week: **3** · workflow failures (distinct SHAs): **8** · commits to main: **9** · merged PRs: **7**
  - `Notify auto-audit` (7): [`59551e4`](https://github.com/Eiasash/InternalMedicine/actions/runs/29230770231), [`f846476`](https://github.com/Eiasash/InternalMedicine/actions/runs/29236466996), [`c4cae41`](https://github.com/Eiasash/InternalMedicine/actions/runs/29259826747), [`fec33c5`](https://github.com/Eiasash/InternalMedicine/actions/runs/29364287028), [`a91b20a`](https://github.com/Eiasash/InternalMedicine/actions/runs/29423568040)
  - `CI` (1): [`c4cae41`](https://github.com/Eiasash/InternalMedicine/actions/runs/29259826381)
  - Recent merged PRs:
    - [#207](https://github.com/Eiasash/InternalMedicine/pull/207) Round-2: FSRS anchor reschedule + proxy-auth timeout + streak gate
    - [#206](https://github.com/Eiasash/InternalMedicine/pull/206) Audit fixes: scoring/leaderboard, SRS, quiz-flow, XSS hardening (IM-1..9)
    - [#203](https://github.com/Eiasash/InternalMedicine/pull/203) DRAFT - DO NOT MERGE until Netlify API_SECRET dual-accept + UPSTASH set (P0 proxy JWT cutover)
    - [#202](https://github.com/Eiasash/InternalMedicine/pull/202) ci(gitleaks): harden install step (authenticate release fetch)
    - [#201](https://github.com/Eiasash/InternalMedicine/pull/201) chore(lockfile): refresh stale version metadata

### FamilyMedicine
- live SW: `1.26.19` · version bumps this week: **3** · workflow failures (distinct SHAs): **9** · commits to main: **10** · merged PRs: **8**
  - `Notify auto-audit` (8): [`8e2537d`](https://github.com/Eiasash/FamilyMedicine/actions/runs/29230772215), [`bcb3b25`](https://github.com/Eiasash/FamilyMedicine/actions/runs/29236652870), [`48a56b9`](https://github.com/Eiasash/FamilyMedicine/actions/runs/29260053619), [`18015a3`](https://github.com/Eiasash/FamilyMedicine/actions/runs/29360639178), [`b2e7cdb`](https://github.com/Eiasash/FamilyMedicine/actions/runs/29364247765)
  - `CI` (1): [`48a56b9`](https://github.com/Eiasash/FamilyMedicine/actions/runs/29260053793)
  - Recent merged PRs:
    - [#185](https://github.com/Eiasash/FamilyMedicine/pull/185) Round-2: FSRS anchor reschedule + streak gate + dead-tagger removal + proxy-auth timeout
    - [#184](https://github.com/Eiasash/FamilyMedicine/pull/184) Audit fixes: chat-key guard, quiz reveal, SRS, XSS, prompt (FM-2..8 + siblings)
    - [#180](https://github.com/Eiasash/FamilyMedicine/pull/180) DRAFT - DO NOT MERGE until Netlify API_SECRET dual-accept + UPSTASH set (P0 proxy JWT cutover)
    - [#179](https://github.com/Eiasash/FamilyMedicine/pull/179) ci(gitleaks): harden install step (authenticate release fetch)
    - [#178](https://github.com/Eiasash/FamilyMedicine/pull/178) chore(lockfile): refresh stale version metadata

### ward-helper
- live SW: `1.46.32` · version bumps this week: **2** · workflow failures (distinct SHAs): **5** · commits to main: **7** · merged PRs: **7**
  - `Notify auto-audit` (5): [`02067a2`](https://github.com/Eiasash/ward-helper/actions/runs/29233817105), [`85cf42c`](https://github.com/Eiasash/ward-helper/actions/runs/29274951669), [`b513efb`](https://github.com/Eiasash/ward-helper/actions/runs/29334478684), [`6a89904`](https://github.com/Eiasash/ward-helper/actions/runs/29364298118), [`d8b5bf0`](https://github.com/Eiasash/ward-helper/actions/runs/29422833627)
  - Recent merged PRs:
    - [#272](https://github.com/Eiasash/ward-helper/pull/272) DRAFT - DO NOT MERGE until Netlify API_SECRET dual-accept + UPSTASH set (P0 proxy JWT cutover)
    - [#271](https://github.com/Eiasash/ward-helper/pull/271) ci(gitleaks): harden install step (authenticate release fetch)
    - [#270](https://github.com/Eiasash/ward-helper/pull/270) chore(lockfile): refresh stale version metadata
    - [#269](https://github.com/Eiasash/ward-helper/pull/269) P0 security: untrack .env.production + gitleaks CI
    - [#268](https://github.com/Eiasash/ward-helper/pull/268) Claude/web emailto localstorage hygiene

### Toranot
- live SW: `?` · version bumps this week: **0** · workflow failures (distinct SHAs): **0** · commits to main: **7** · merged PRs: **6**
  - Recent merged PRs:
    - [#130](https://github.com/Eiasash/Toranot/pull/130) fix(proxy): key rate limiter on Edge context.ip (was global :unknown)
    - [#129](https://github.com/Eiasash/Toranot/pull/129) Supabase-backed proxy rate limiter (replace unconfigured Upstash)
    - [#128](https://github.com/Eiasash/Toranot/pull/128) ci(gitleaks): harden install step (authenticate release fetch)
    - [#127](https://github.com/Eiasash/Toranot/pull/127) P0 security: proxy rate-limit hardening + gitleaks CI
    - [#124](https://github.com/Eiasash/Toranot/pull/124) chore: refresh CLAUDE.md currency drift

### watch-advisor2
- live SW: `?` · version bumps this week: **0** · workflow failures (distinct SHAs): **0** · commits to main: **4** · merged PRs: **4**
  - Recent merged PRs:
    - [#282](https://github.com/Eiasash/watch-advisor2/pull/282) ci(gitleaks): harden install step (authenticate release fetch)
    - [#281](https://github.com/Eiasash/watch-advisor2/pull/281) P0 security: gitleaks secret-scanning CI
    - [#278](https://github.com/Eiasash/watch-advisor2/pull/278) chore: refresh CLAUDE.md currency drift
    - [#280](https://github.com/Eiasash/watch-advisor2/pull/280) security(rls): scope permissive app_settings/push_subscriptions policies

## Open issues

**auto-audit self (12)**
- `auto-audit`: 11 open
  - [#83](https://github.com/Eiasash/auto-audit/issues/83) [auto-audit] 4 cross-cutting critical issue(s) — 2026-07-19
  - [#82](https://github.com/Eiasash/auto-audit/issues/82) [auto-audit] 4 cross-cutting critical issue(s) — 2026-07-18
  - [#81](https://github.com/Eiasash/auto-audit/issues/81) [auto-audit] 4 cross-cutting critical issue(s) — 2026-07-17
- `rotation-reminder`: 1 open
  - [#72](https://github.com/Eiasash/auto-audit/issues/72) [reminder] Proxy secret rotation due

**Target repos (16)**
- `Eiasash/InternalMedicine`: 3 open with `auto-audit` label
  - [#205](https://github.com/Eiasash/InternalMedicine/issues/205) [auto-audit] 1 critical issue(s) — 2026-07-18
  - [#199](https://github.com/Eiasash/InternalMedicine/issues/199) [auto-audit] 1 critical issue(s) — 2026-07-14
  - [#198](https://github.com/Eiasash/InternalMedicine/issues/198) [auto-audit] 1 critical issue(s) — 2026-07-13
- `Eiasash/FamilyMedicine`: 4 open with `auto-audit` label
  - [#183](https://github.com/Eiasash/FamilyMedicine/issues/183) [auto-audit] 1 critical issue(s) — 2026-07-18
  - [#176](https://github.com/Eiasash/FamilyMedicine/issues/176) [auto-audit] 1 critical issue(s) — 2026-07-14
  - [#175](https://github.com/Eiasash/FamilyMedicine/issues/175) [auto-audit] 1 critical issue(s) — 2026-07-13
- `Eiasash/ward-helper`: 6 open with `auto-audit` label
  - [#275](https://github.com/Eiasash/ward-helper/issues/275) [auto-audit] 1 critical issue(s) — 2026-07-18
  - [#264](https://github.com/Eiasash/ward-helper/issues/264) [auto-audit] 1 critical issue(s) — 2026-07-01
  - [#263](https://github.com/Eiasash/ward-helper/issues/263) [auto-audit] 1 critical issue(s) — 2026-06-30
- `Eiasash/Toranot`: 1 open with `auto-audit` label
  - [#125](https://github.com/Eiasash/Toranot/issues/125) [auto-audit] 1 high npm vulnerability — 2026-07-01
- `Eiasash/watch-advisor2`: 2 open with `auto-audit` label
  - [#279](https://github.com/Eiasash/watch-advisor2/issues/279) [auto-audit] 1 critical issue(s) — 2026-07-02
  - [#277](https://github.com/Eiasash/watch-advisor2/issues/277) [auto-audit] 1 critical issue(s) — 2026-06-30

---

_Auto-generated by `scripts/tier3_synthesis.py` ([source](https://github.com/Eiasash/auto-audit/blob/main/scripts/tier3_synthesis.py))._