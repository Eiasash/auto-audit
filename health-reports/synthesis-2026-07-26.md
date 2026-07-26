# Tier 3 — Weekly synthesis · 2026-07-26

_Window: last 7 days · 201 health reports parsed · generated 2026-07-26 07:01Z_

_Prior week: https://github.com/Eiasash/auto-audit/issues/71_

## Action needed

**Critical** (1)
- (issue-aging) `auto-audit` issue [#71](https://github.com/Eiasash/auto-audit/issues/71) open for 34 days: [Tier 3] Weekly synthesis · 2026-06-21 — 3 warn

**Warning** (17)
- (probe-recurring) Probe `study_plan_parity` fired in 201 reports this window. Last: 2026-07-26T06:02:25.414395+00:00.
- (probe-recurring) Probe `dispatch_chain` fired in 201 reports this window. Last: 2026-07-26T06:02:25.414395+00:00.
- (probe-recurring) Probe `dispatch_pat_freshness` fired in 201 reports this window. Last: 2026-07-26T06:02:25.414395+00:00.
- (probe-recurring) Probe `scheduler_health` fired in 57 reports this window. Last: 2026-07-26T06:02:25.414395+00:00.
- (workflow-streak) `Geriatrics` / `Notify auto-audit` failed across 8 distinct SHAs this window.
- (workflow-streak) `InternalMedicine` / `Notify auto-audit` failed across 5 distinct SHAs this window.
- (workflow-streak) `FamilyMedicine` / `Notify auto-audit` failed across 6 distinct SHAs this window.
- (issue-aging) `rotation-reminder` issue [#72](https://github.com/Eiasash/auto-audit/issues/72) open for 24 days: [reminder] Proxy secret rotation due
- (target-issue-aging) `Eiasash/ward-helper` auto-audit finding [#264](https://github.com/Eiasash/ward-helper/issues/264) open 25 days: [auto-audit] 1 critical issue(s) — 2026-07-01
- (target-issue-aging) `Eiasash/ward-helper` auto-audit finding [#263](https://github.com/Eiasash/ward-helper/issues/263) open 26 days: [auto-audit] 1 critical issue(s) — 2026-06-30
- (target-issue-aging) `Eiasash/ward-helper` auto-audit finding [#262](https://github.com/Eiasash/ward-helper/issues/262) open 26 days: [auto-audit] 1 critical issue(s) — 2026-06-29
- (target-issue-aging) `Eiasash/ward-helper` auto-audit finding [#260](https://github.com/Eiasash/ward-helper/issues/260) open 32 days: [auto-audit] 1 critical issue(s) — 2026-06-24
- (target-issue-aging) `Eiasash/ward-helper` auto-audit finding [#253](https://github.com/Eiasash/ward-helper/issues/253) open 32 days: [auto-audit] 1 critical issue(s) — 2026-06-23
- (target-issue-aging) `Eiasash/Toranot` auto-audit finding [#125](https://github.com/Eiasash/Toranot/issues/125) open 25 days: [auto-audit] 1 high npm vulnerability — 2026-07-01
- (target-issue-aging) `Eiasash/watch-advisor2` auto-audit finding [#279](https://github.com/Eiasash/watch-advisor2/issues/279) open 24 days: [auto-audit] 1 critical issue(s) — 2026-07-02
- (target-issue-aging) `Eiasash/watch-advisor2` auto-audit finding [#277](https://github.com/Eiasash/watch-advisor2/issues/277) open 25 days: [auto-audit] 1 critical issue(s) — 2026-06-30
- (secret-rotation) `AUTO_AUDIT_DISPATCH_PAT` will hit the 90-day rotation deadline in 2 days. Plan: create a fine-grained PAT scoped to auto-audit + run `scripts/rotate_dispatch_pat.py`.

## Narrative

The three probes firing at identical counts (201 each) across `dispatch_chain`, `dispatch_pat_freshness`, and `study_plan_parity` are almost certainly coupled to a single root cause rather than three independent issues. The `AUTO_AUDIT_DISPATCH_PAT` expiring in 2 days is the most likely driver: a degraded or near-expired PAT would simultaneously break dispatch chain integrity, trigger freshness warnings, and prevent downstream study plan synchronization. The `Notify auto-audit` workflow failures spanning 8, 5, and 6 distinct SHAs across Geriatrics, InternalMedicine, and FamilyMedicine reinforce this — these failures persist through code changes, pointing to an infrastructure credential problem rather than anything repo-specific.

The aging finding clusters tell a compounding story: auto-audit is successfully emitting issues (201–402 per repo) but the notification/dispatch layer is broken, so those findings are silently accumulating unacknowledged. Ward-helper has 5 critical findings open 23–32 days; watch-advisor2 has 2 critical findings open 24–25 days. The 34-day-old issue #71 (Tier 3 weekly synthesis) suggests the synthesis pipeline has been degraded at least since late June — predating the current PAT expiry window, which means the dispatch breakage may have an earlier origin than the rotation deadline alone.

`scheduler_health` firing at 57 (vs. 201 for the others) is a partial overlap, suggesting it's affected by but not solely caused by the same PAT issue — something in the scheduler was already degraded before the dispatch layer fully broke.

## Cross-cutting probe activity

- `study_plan_parity` — fired in **201** reports (last: 2026-07-26T06:02:25.414395+00:00)
  - {"severity": "warning", "kind": "study_plan_syllabus_drift", "msg": "syllabus_data.json differs across the three medical PWAs: {'FamilyMedicine': '2b295d1317ad', 'InternalMedicine': '2b295d1317ad', 'Geriatrics': '8165cacec81b'}", "auto_fix"
- `dispatch_chain` — fired in **201** reports (last: 2026-07-26T06:02:25.414395+00:00)
  - {"severity": "critical", "kind": "dispatch_chain_run_failed", "msg": "Geriatrics: most recent notify-auto-audit run FAILED (sha 637ade7c, 2026-07-19T21:28:52Z). Most likely cause: AUTO_AUDIT_DISPATCH_PAT expired, was revoked, or lost the Ac
  - {"severity": "critical", "kind": "dispatch_chain_run_failed", "msg": "InternalMedicine: most recent notify-auto-audit run FAILED (sha 3f0126aa, 2026-07-19T21:24:22Z). Most likely cause: AUTO_AUDIT_DISPATCH_PAT expired, was revoked, or lost
- `dispatch_pat_freshness` — fired in **201** reports (last: 2026-07-26T06:02:25.414395+00:00)
  - {"severity": "warning", "kind": "dispatch_pat_aging", "msg": "Geriatrics: AUTO_AUDIT_DISPATCH_PAT last rotated 87 days ago (2026-04-29T09:09:39Z). Approaching the 90-day rotation cadence \u2014 plan to rotate within 3 days per scripts/DISPA
  - {"severity": "warning", "kind": "dispatch_pat_aging", "msg": "InternalMedicine: AUTO_AUDIT_DISPATCH_PAT last rotated 87 days ago (2026-04-29T09:09:39Z). Approaching the 90-day rotation cadence \u2014 plan to rotate within 3 days per scripts
- `scheduler_health` — fired in **57** reports (last: 2026-07-26T06:02:25.414395+00:00)
  - {"severity": "warning", "kind": "scheduler-drift", "msg": "GHA scheduler dropped ticks: previous Tier 1 schedule run was 84 min ago (expected \u2264 30). Repository_dispatch path (issue #14) is the durable fix \u2014 verify AUTO_AUDIT_DISPA

## Spend trajectory

- Earliest snapshot (2026-07-19): MTD **$0.11**, 36 calls
- Latest snapshot (2026-07-26): MTD **$0.12**, 42 calls
- Window delta: **+$0.01**
- Projected end-of-month: **$0.14**

## Per-repo activity

### Geriatrics
- live SW: `10.64.195` · version bumps this week: **5** · workflow failures (distinct SHAs): **9** · commits to main: **8** · merged PRs: **4**
  - `Notify auto-audit` (8): [`96d5497`](https://github.com/Eiasash/Geriatrics/actions/runs/29662977704), [`f97fd3b`](https://github.com/Eiasash/Geriatrics/actions/runs/29679323738), [`7c02417`](https://github.com/Eiasash/Geriatrics/actions/runs/29685472401), [`63afc7d`](https://github.com/Eiasash/Geriatrics/actions/runs/29701244336), [`81325b8`](https://github.com/Eiasash/Geriatrics/actions/runs/29702097185)
  - `Weekly Audit` (1): [`96d5497`](https://github.com/Eiasash/Geriatrics/actions/runs/29677008265)
  - Recent merged PRs:
    - [#423](https://github.com/Eiasash/Geriatrics/pull/423) fix(content): 10 hand-adjudicated Tier-B answer-key corrections
    - [#422](https://github.com/Eiasash/Geriatrics/pull/422) fix(content): realign 42 desynced answer keys to their explanations
    - [#421](https://github.com/Eiasash/Geriatrics/pull/421) Retire dead proxy secrets + re-arm gitleaks
    - [#420](https://github.com/Eiasash/Geriatrics/pull/420) G5: keyword-anchored explanation-letter remap (zero medical-token corruption) + tidy

### InternalMedicine
- live SW: `10.4.61` · version bumps this week: **3** · workflow failures (distinct SHAs): **5** · commits to main: **4** · merged PRs: **2**
  - `Notify auto-audit` (5): [`2891c9c`](https://github.com/Eiasash/InternalMedicine/actions/runs/29663080308), [`a8e96ea`](https://github.com/Eiasash/InternalMedicine/actions/runs/29679393465), [`716dad9`](https://github.com/Eiasash/InternalMedicine/actions/runs/29685466419), [`b3c5450`](https://github.com/Eiasash/InternalMedicine/actions/runs/29703465831), [`3f0126a`](https://github.com/Eiasash/InternalMedicine/actions/runs/29704299712)
  - Recent merged PRs:
    - [#209](https://github.com/Eiasash/InternalMedicine/pull/209) Retire dead proxy secrets + re-arm gitleaks
    - [#208](https://github.com/Eiasash/InternalMedicine/pull/208) G5: keyword-anchored remap (zero medical corruption) + read-compatible local streak

### FamilyMedicine
- live SW: `1.26.22` · version bumps this week: **4** · workflow failures (distinct SHAs): **6** · commits to main: **5** · merged PRs: **2**
  - `Notify auto-audit` (6): [`1fbf79d`](https://github.com/Eiasash/FamilyMedicine/actions/runs/29663196548), [`2ec1565`](https://github.com/Eiasash/FamilyMedicine/actions/runs/29679458400), [`0ddf8ba`](https://github.com/Eiasash/FamilyMedicine/actions/runs/29685470293), [`1e2684a`](https://github.com/Eiasash/FamilyMedicine/actions/runs/29703133850), [`9f39495`](https://github.com/Eiasash/FamilyMedicine/actions/runs/29703550961)
  - Recent merged PRs:
    - [#187](https://github.com/Eiasash/FamilyMedicine/pull/187) Retire dead proxy secrets + re-arm gitleaks
    - [#186](https://github.com/Eiasash/FamilyMedicine/pull/186) G5: keyword-anchored explanation-letter remap (zero medical-token corruption)

### ward-helper
- live SW: `1.46.32` · version bumps this week: **1** · workflow failures (distinct SHAs): **2** · commits to main: **1** · merged PRs: **1**
  - `Notify auto-audit` (2): [`d8b5bf0`](https://github.com/Eiasash/ward-helper/actions/runs/29422833627), [`740332c`](https://github.com/Eiasash/ward-helper/actions/runs/29685473563)
  - Recent merged PRs:
    - [#276](https://github.com/Eiasash/ward-helper/pull/276) Retire dead proxy secrets + re-arm gitleaks

### Toranot
- live SW: `?` · version bumps this week: **0** · workflow failures (distinct SHAs): **1** · commits to main: **1** · merged PRs: **1**
  - `CI / Deploy` (1): [`f57ce93`](https://github.com/Eiasash/Toranot/actions/runs/29685468759)
  - Recent merged PRs:
    - [#133](https://github.com/Eiasash/Toranot/pull/133) Retire dead proxy secrets + re-arm gitleaks

### watch-advisor2
- live SW: `?` · version bumps this week: **0** · workflow failures (distinct SHAs): **0** · commits to main: **4** · merged PRs: **4**
  - Recent merged PRs:
    - [#286](https://github.com/Eiasash/watch-advisor2/pull/286) chore(deps-dev): bump postcss from 8.5.15 to 8.5.23
    - [#287](https://github.com/Eiasash/watch-advisor2/pull/287) chore(deps-dev): bump js-yaml from 4.2.0 to 4.3.0
    - [#285](https://github.com/Eiasash/watch-advisor2/pull/285) chore(deps-dev): bump sharp from 0.34.5 to 0.35.0
    - [#283](https://github.com/Eiasash/watch-advisor2/pull/283) Retire dead proxy secrets + re-arm gitleaks

## Open issues

**auto-audit self (19)**
- `auto-audit`: 18 open
  - [#90](https://github.com/Eiasash/auto-audit/issues/90) [auto-audit] 4 cross-cutting critical issue(s) — 2026-07-26
  - [#89](https://github.com/Eiasash/auto-audit/issues/89) [auto-audit] 4 cross-cutting critical issue(s) — 2026-07-25
  - [#88](https://github.com/Eiasash/auto-audit/issues/88) [auto-audit] 4 cross-cutting critical issue(s) — 2026-07-24
- `rotation-reminder`: 1 open
  - [#72](https://github.com/Eiasash/auto-audit/issues/72) [reminder] Proxy secret rotation due

**Target repos (18)**
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
- `Eiasash/watch-advisor2`: 4 open with `auto-audit` label
  - [#288](https://github.com/Eiasash/watch-advisor2/issues/288) [auto-audit] 1 critical issue(s) — 2026-07-25
  - [#284](https://github.com/Eiasash/watch-advisor2/issues/284) [auto-audit] 1 critical issue(s) — 2026-07-20
  - [#279](https://github.com/Eiasash/watch-advisor2/issues/279) [auto-audit] 1 critical issue(s) — 2026-07-02

---

_Auto-generated by `scripts/tier3_synthesis.py` ([source](https://github.com/Eiasash/auto-audit/blob/main/scripts/tier3_synthesis.py))._