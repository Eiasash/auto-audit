# Tier 3 — Weekly synthesis · 2026-07-05

_Window: last 7 days · 181 health reports parsed · generated 2026-07-05 07:14Z_

_Prior week: https://github.com/Eiasash/auto-audit/issues/71_

## Action needed

**Warning** (4)
- (probe-recurring) Probe `feedback_queue` fired in 181 reports this window. Last: 2026-07-05T06:19:36.589530+00:00.
- (probe-recurring) Probe `scheduler_health` fired in 70 reports this window. Last: 2026-07-05T06:19:36.589530+00:00.
- (target-issue-aging) `Eiasash/FamilyMedicine` auto-audit finding [#170](https://github.com/Eiasash/FamilyMedicine/issues/170) open 18 days: [auto-audit] 1 critical issue(s) — 2026-06-16
- (secret-rotation) `AUTO_AUDIT_DISPATCH_PAT` will hit the 90-day rotation deadline in 23 days. Plan: create a fine-grained PAT scoped to auto-audit + run `scripts/rotate_dispatch_pat.py`.

## Narrative

Toranot is emitting 183 issues — more than all other repos combined — while showing zero version bumps and no live software. This combination suggests the audit/emit pipeline is running against a repo that isn't being actively maintained or deployed, which raises a signal-to-noise question: those issues are inflating aggregate counts without any corresponding development activity to resolve them.

The two persistently firing probes (`feedback_queue` at 181 hits, `scheduler_health` at 70) share the same last-fired timestamp (`2026-07-05T06:19:36`), indicating they fired together in the most recent report window rather than independently over time. This co-firing pattern suggests a single upstream condition — likely a scheduler or queue processing failure — is triggering both probes simultaneously rather than two separate degradation paths.

The `FamilyMedicine` aging audit finding (#170, 18 days open) and the `AUTO_AUDIT_DISPATCH_PAT` rotation deadline (23 days out) are converging on roughly the same timeframe. If the PAT rotates before that finding is resolved and the rotation introduces any disruption to the dispatch workflow, auto-audit coverage could lapse precisely while a known critical issue remains unaddressed.

`ward-helper` is the only repo with CI failures this week (2), and it also has the highest emitted-issue count among active repos (45). The CI failures and issue volume together suggest this repo is under more active churn than its single version bump implies.

## Cross-cutting probe activity

- `feedback_queue` — fired in **181** reports (last: 2026-07-05T06:19:36.589530+00:00)
  - {"severity": "warning", "kind": "feedback_queue_fetch_error", "msg": "feedback_queue: failed to query mishpacha_feedback (HTTP 400)"}
- `scheduler_health` — fired in **70** reports (last: 2026-07-05T06:19:36.589530+00:00)
  - {"severity": "warning", "kind": "scheduler-drift", "msg": "GHA scheduler dropped ticks: previous Tier 1 schedule run was 91 min ago (expected \u2264 30). Repository_dispatch path (issue #14) is the durable fix \u2014 verify AUTO_AUDIT_DISPA

## Spend trajectory

- Earliest snapshot (2026-06-28): MTD **$90.50**, 16,460 calls
- Latest snapshot (2026-07-05): MTD **$0.06**, 13 calls
- Projected end-of-month: **$0.37**

## Per-repo activity

### Geriatrics
- live SW: `10.64.186` · version bumps this week: **5** · workflow failures (distinct SHAs): **0** · commits to main: **5** · merged PRs: **5**
  - Recent merged PRs:
    - [#406](https://github.com/Eiasash/Geriatrics/pull/406) data(3C A-tier): 4 source-cited corrections + patient-safety (v10.64.186)
    - [#405](https://github.com/Eiasash/Geriatrics/pull/405) chore: refresh CLAUDE.md currency drift
    - [#404](https://github.com/Eiasash/Geriatrics/pull/404) data(3C tranche-2): source-cited answer-key/stem corrections (v10.64.185)
    - [#402](https://github.com/Eiasash/Geriatrics/pull/402) data(3C-batch-1): SZMC-Rescue content-derived refs + 4 keep-key polish edits (v10.64.184)
    - [#401](https://github.com/Eiasash/Geriatrics/pull/401) fix(refs): 3B citation hygiene — 27 organ-system corrections + 6 malformed ref fixes (v10.64.183)

### InternalMedicine
- live SW: `10.4.57` · version bumps this week: **1** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

### FamilyMedicine
- live SW: `1.26.17` · version bumps this week: **1** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

### ward-helper
- live SW: `1.46.31` · version bumps this week: **1** · workflow failures (distinct SHAs): **2** · commits to main: **1** · merged PRs: **1**
  - `CI` (2): [`40683d7`](https://github.com/Eiasash/ward-helper/actions/runs/28388070233), [`e6ab8ce`](https://github.com/Eiasash/ward-helper/actions/runs/28390168472)
  - Recent merged PRs:
    - [#266](https://github.com/Eiasash/ward-helper/pull/266) fix(phi-gate): allowlist de-identified archetype labels (keep all detectors)

### Toranot
- live SW: `?` · version bumps this week: **0** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

### watch-advisor2
- live SW: `?` · version bumps this week: **0** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

## Open issues

**auto-audit self (2)**
- `auto-audit`: 1 open
  - [#71](https://github.com/Eiasash/auto-audit/issues/71) [Tier 3] Weekly synthesis · 2026-06-21 — 3 warn
- `rotation-reminder`: 1 open
  - [#72](https://github.com/Eiasash/auto-audit/issues/72) [reminder] Proxy secret rotation due

**Target repos (12)**
- `Eiasash/Geriatrics`: 2 open with `auto-audit` label
  - [#407](https://github.com/Eiasash/Geriatrics/issues/407) [auto-audit] 1 critical issue(s) — 2026-07-01
  - [#403](https://github.com/Eiasash/Geriatrics/issues/403) [auto-audit] 1 critical issue(s) — 2026-06-30
- `Eiasash/InternalMedicine`: 1 open with `auto-audit` label
  - [#193](https://github.com/Eiasash/InternalMedicine/issues/193) [auto-audit] Gate FAIL + 1 high npm vuln — 2026-07-01
- `Eiasash/FamilyMedicine`: 1 open with `auto-audit` label
  - [#170](https://github.com/Eiasash/FamilyMedicine/issues/170) [auto-audit] 1 critical issue(s) — 2026-06-16
- `Eiasash/ward-helper`: 5 open with `auto-audit` label
  - [#264](https://github.com/Eiasash/ward-helper/issues/264) [auto-audit] 1 critical issue(s) — 2026-07-01
  - [#263](https://github.com/Eiasash/ward-helper/issues/263) [auto-audit] 1 critical issue(s) — 2026-06-30
  - [#262](https://github.com/Eiasash/ward-helper/issues/262) [auto-audit] 1 critical issue(s) — 2026-06-29
- `Eiasash/Toranot`: 1 open with `auto-audit` label
  - [#125](https://github.com/Eiasash/Toranot/issues/125) [auto-audit] 1 high npm vulnerability — 2026-07-01
- `Eiasash/watch-advisor2`: 2 open with `auto-audit` label
  - [#279](https://github.com/Eiasash/watch-advisor2/issues/279) [auto-audit] 1 critical issue(s) — 2026-07-02
  - [#277](https://github.com/Eiasash/watch-advisor2/issues/277) [auto-audit] 1 critical issue(s) — 2026-06-30

---

_Auto-generated by `scripts/tier3_synthesis.py` ([source](https://github.com/Eiasash/auto-audit/blob/main/scripts/tier3_synthesis.py))._