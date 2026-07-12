# Tier 3 — Weekly synthesis · 2026-07-12

_Window: last 7 days · 180 health reports parsed · generated 2026-07-12 07:00Z_

_Prior week: https://github.com/Eiasash/auto-audit/issues/71_

## Action needed

**Warning** (7)
- (probe-recurring) Probe `feedback_queue` fired in 180 reports this window. Last: 2026-07-12T06:02:04.358996+00:00.
- (probe-recurring) Probe `scheduler_health` fired in 66 reports this window. Last: 2026-07-12T06:02:04.358996+00:00.
- (issue-aging) `auto-audit` issue [#71](https://github.com/Eiasash/auto-audit/issues/71) open for 20 days: [Tier 3] Weekly synthesis · 2026-06-21 — 3 warn
- (target-issue-aging) `Eiasash/FamilyMedicine` auto-audit finding [#170](https://github.com/Eiasash/FamilyMedicine/issues/170) open 25 days: [auto-audit] 1 critical issue(s) — 2026-06-16
- (target-issue-aging) `Eiasash/ward-helper` auto-audit finding [#260](https://github.com/Eiasash/ward-helper/issues/260) open 18 days: [auto-audit] 1 critical issue(s) — 2026-06-24
- (target-issue-aging) `Eiasash/ward-helper` auto-audit finding [#253](https://github.com/Eiasash/ward-helper/issues/253) open 18 days: [auto-audit] 1 critical issue(s) — 2026-06-23
- (secret-rotation) `AUTO_AUDIT_DISPATCH_PAT` will hit the 90-day rotation deadline in 16 days. Plan: create a fine-grained PAT scoped to auto-audit + run `scripts/rotate_dispatch_pat.py`.

## Narrative

Toranot's 180 emitted issues this week account for the entirety of the `feedback_queue` probe firings (180 exact match), and Toranot has no live software version and no bumps — meaning a non-deployed, likely infrastructure-adjacent repo is the sole driver of the system's loudest recurring probe. The `scheduler_health` probe's 66 firings don't map cleanly to any single repo's issue count, suggesting a separate degraded subsystem running independently of the target repos.

Three unresolved critical auto-audit findings are aging simultaneously across two target repos (FamilyMedicine #170 at 25 days, ward-helper #260 and #253 both at 18 days), while FamilyMedicine also has the only workflow failure this week. That combination — active workflow breakage plus an unactioned critical finding — represents the one repo where two independent signals are co-occurring.

The `AUTO_AUDIT_DISPATCH_PAT` rotation deadline lands in 16 days. If it lapses, the dispatch mechanism that feeds auto-audit findings into target repos would break, which would make the aging-issue pattern invisible going forward rather than resolved — the existing backlog of unactioned criticals would simply stop growing visibly, not get addressed.

## Cross-cutting probe activity

- `feedback_queue` — fired in **180** reports (last: 2026-07-12T06:02:04.358996+00:00)
  - {"severity": "warning", "kind": "feedback_queue_fetch_error", "msg": "feedback_queue: failed to query mishpacha_feedback (HTTP 400)"}
- `scheduler_health` — fired in **66** reports (last: 2026-07-12T06:02:04.358996+00:00)
  - {"severity": "warning", "kind": "scheduler-drift", "msg": "GHA scheduler dropped ticks: previous Tier 1 schedule run was 84 min ago (expected \u2264 30). Repository_dispatch path (issue #14) is the durable fix \u2014 verify AUTO_AUDIT_DISPA

## Spend trajectory

- Earliest snapshot (2026-07-05): MTD **$0.06**, 13 calls
- Latest snapshot (2026-07-12): MTD **$0.10**, 20 calls
- Window delta: **+$0.04**
- Projected end-of-month: **$0.26**

## Per-repo activity

### Geriatrics
- live SW: `10.64.186` · version bumps this week: **1** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

### InternalMedicine
- live SW: `10.4.57` · version bumps this week: **1** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

### FamilyMedicine
- live SW: `1.26.17` · version bumps this week: **1** · workflow failures (distinct SHAs): **1** · commits to main: **0** · merged PRs: **0**
  - `Distractor Autopsy Generator` (1): [`42f3111`](https://github.com/Eiasash/FamilyMedicine/actions/runs/29019328821)

### ward-helper
- live SW: `1.46.31` · version bumps this week: **1** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

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

**Target repos (14)**
- `Eiasash/Geriatrics`: 2 open with `auto-audit` label
  - [#407](https://github.com/Eiasash/Geriatrics/issues/407) [auto-audit] 1 critical issue(s) — 2026-07-01
  - [#403](https://github.com/Eiasash/Geriatrics/issues/403) [auto-audit] 1 critical issue(s) — 2026-06-30
- `Eiasash/InternalMedicine`: 3 open with `auto-audit` label
  - [#195](https://github.com/Eiasash/InternalMedicine/issues/195) [auto-audit] 1 critical issue(s) — 2026-07-08
  - [#194](https://github.com/Eiasash/InternalMedicine/issues/194) [auto-audit] 1 critical issue(s) — 2026-07-06
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