# Tier 3 — Weekly synthesis · 2026-06-21

_Window: last 7 days · 116 health reports parsed · generated 2026-06-21 07:49Z_

## Action needed

**Warning** (3)
- (probe-recurring) Probe `study_plan_parity` fired in 11 reports this window. Last: 2026-06-16T05:48:03.913960+00:00.
- (probe-recurring) Probe `feedback_queue` fired in 116 reports this window. Last: 2026-06-21T07:42:32.353023+00:00.
- (probe-recurring) Probe `scheduler_health` fired in 68 reports this window. Last: 2026-06-21T07:42:32.353023+00:00.

## Narrative

`feedback_queue` (116 firings) and `scheduler_health` (68 firings) are both running hot and share an identical last-fired timestamp, which means they are co-occurring — likely the same underlying condition triggering both probes simultaneously rather than two independent problems. The volume ratio (roughly 2:1 across the window) suggests `scheduler_health` may be a downstream consequence of `feedback_queue` saturation, not a separate fault.

Toranot is the dominant noise source: 232 emitted issues from a repo with no live software version and zero bumps. That combination — high issue emission, no deployable artifact, no version progression — means the issue signal from that repo is structurally decoupled from any release activity. Its issues are not correlating with anything actionable in the deploy cycle this week.

`study_plan_parity` stopped firing after June 16 while the other two probes continued through June 21. That gap is a concrete signal: whatever condition drove `study_plan_parity` either resolved or the data feeding it changed mid-window. Worth noting it's not simply quieter — it's absent for the final five days while system activity continued.

## Cross-cutting probe activity

- `feedback_queue` — fired in **116** reports (last: 2026-06-21T07:42:32.353023+00:00)
  - {"severity": "warning", "kind": "feedback_queue_fetch_error", "msg": "feedback_queue: failed to query mishpacha_feedback (HTTP 400)"}
- `scheduler_health` — fired in **68** reports (last: 2026-06-21T07:42:32.353023+00:00)
  - {"severity": "warning", "kind": "scheduler-drift", "msg": "GHA scheduler dropped ticks: previous Tier 1 schedule run was 123 min ago (expected \u2264 30). Repository_dispatch path (issue #14) is the durable fix \u2014 verify AUTO_AUDIT_DISP
- `study_plan_parity` — fired in **11** reports (last: 2026-06-16T05:48:03.913960+00:00)
  - {"severity": "warning", "kind": "study_plan_syllabus_drift", "msg": "syllabus_data.json differs across the three medical PWAs: {'FamilyMedicine': 'b4e835651206', 'InternalMedicine': '2b295d1317ad', 'Geriatrics': '2b295d1317ad'}", "auto_fix"

## Spend trajectory

- Earliest snapshot (2026-06-16): MTD **$89.77**, 16,367 calls
- Latest snapshot (2026-06-21): MTD **$90.44**, 16,452 calls
- Window delta: **+$0.67**
- Projected end-of-month: **$129.20**

## Per-repo activity

### Geriatrics
- live SW: `10.64.182` · version bumps this week: **2** · workflow failures (distinct SHAs): **2** · commits to main: **7** · merged PRs: **7**
  - `Weekly Audit` (1): [`f5b9675`](https://github.com/Eiasash/Geriatrics/actions/runs/27557144392)
  - `CI` (1): [`f5b9675`](https://github.com/Eiasash/Geriatrics/actions/runs/27557125311)
  - Recent merged PRs:
    - [#399](https://github.com/Eiasash/Geriatrics/pull/399) fix(app-logic): four defensive guards (wrong-review crash, boot, chat, leaderboard) — v10.64.182
    - [#398](https://github.com/Eiasash/Geriatrics/pull/398) fix: restore live-judge-gate + make the chaos bot exit cleanly in CI (reverses #397)
    - [#397](https://github.com/Eiasash/Geriatrics/pull/397) ci(weekly-audit): drop live-judge-gate job (manual R3 pre-flight only)
    - [#396](https://github.com/Eiasash/Geriatrics/pull/396) fix(tests): isolate tagger idempotency test to temp file (kill CI flake)
    - [#394](https://github.com/Eiasash/Geriatrics/pull/394) fix(weekly-audit): exempt SZMC-Rescue Qs from ref requirement

### InternalMedicine
- live SW: `10.4.57` · version bumps this week: **3** · workflow failures (distinct SHAs): **0** · commits to main: **6** · merged PRs: **6**
  - Recent merged PRs:
    - [#191](https://github.com/Eiasash/InternalMedicine/pull/191) fix(ai): specific callAI errors + clear stale API key on 401/403 (v10.4.57)
    - [#189](https://github.com/Eiasash/InternalMedicine/pull/189) fix(exam-audit): un-merge canonical Q#45 to the restored colorectal Q50 (IM #185 final)
    - [#188](https://github.com/Eiasash/InternalMedicine/pull/188) content(2020): restore missing colorectal-screening Q50 at idx 44 (v10.4.56)
    - [#187](https://github.com/Eiasash/InternalMedicine/pull/187) fix(exam-audit): re-baseline 25 canonical q-stems to current questions.json (IM #185)
    - [#186](https://github.com/Eiasash/InternalMedicine/pull/186) fix(study-plan): resync syllabus_data.json to shared canonical

### FamilyMedicine
- live SW: `1.26.17` · version bumps this week: **2** · workflow failures (distinct SHAs): **0** · commits to main: **4** · merged PRs: **4**
  - Recent merged PRs:
    - [#169](https://github.com/Eiasash/FamilyMedicine/pull/169) fix(ai)+a11y: tolerate bare-string explain cache; amber-600→amber-800 (v1.26.17)
    - [#168](https://github.com/Eiasash/FamilyMedicine/pull/168) fix(study-plan): resync syllabus_data.json to shared canonical
    - [#167](https://github.com/Eiasash/FamilyMedicine/pull/167) ci(weekly-audit): fix false conflicting-duplicate on a one-hyphen variance (Q528/Q783)
    - [#166](https://github.com/Eiasash/FamilyMedicine/pull/166) fix(fm): finish touch target cleanup

### ward-helper
- live SW: `1.46.25` · version bumps this week: **3** · workflow failures (distinct SHAs): **0** · commits to main: **4** · merged PRs: **4**
  - Recent merged PRs:
    - [#251](https://github.com/Eiasash/ward-helper/pull/251) fix(skills): bundle szmc-clinical-notes sibling files into the build mirror
    - [#250](https://github.com/Eiasash/ward-helper/pull/250) docs(migration): mark 0009 as APPLIED
    - [#249](https://github.com/Eiasash/ward-helper/pull/249) fix(phi): delete cloud backup row when a note is deleted (orphaned-PHI gap)
    - [#247](https://github.com/Eiasash/ward-helper/pull/247) fix(a11y): SOAP note-type button passes WCAG AA contrast

### Toranot
- live SW: `?` · version bumps this week: **0** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

### watch-advisor2
- live SW: `?` · version bumps this week: **0** · workflow failures (distinct SHAs): **0** · commits to main: **2** · merged PRs: **2**
  - Recent merged PRs:
    - [#276](https://github.com/Eiasash/watch-advisor2/pull/276) chore(deps-dev): bump undici from 7.27.2 to 7.28.0
    - [#275](https://github.com/Eiasash/watch-advisor2/pull/275) fix(robustness): authedFetch on 3 call sites + getConfiguredModel cache + ClaudePick res.ok guard

## Open issues


**Target repos (2)**
- `Eiasash/Geriatrics`: 1 open with `auto-audit` label
  - [#400](https://github.com/Eiasash/Geriatrics/issues/400) [auto-audit] 1 critical issue(s) — 2026-06-16
- `Eiasash/FamilyMedicine`: 1 open with `auto-audit` label
  - [#170](https://github.com/Eiasash/FamilyMedicine/issues/170) [auto-audit] 1 critical issue(s) — 2026-06-16

---

_Auto-generated by `scripts/tier3_synthesis.py` ([source](https://github.com/Eiasash/auto-audit/blob/main/scripts/tier3_synthesis.py))._