# Tier 3 — Weekly synthesis · 2026-06-28

_Window: last 7 days · 160 health reports parsed · generated 2026-06-28 07:31Z_

_Prior week: https://github.com/Eiasash/auto-audit/issues/71_

## Action needed

**Warning** (3)
- (probe-recurring) Probe `feedback_queue` fired in 160 reports this window. Last: 2026-06-28T06:49:18.253235+00:00.
- (probe-recurring) Probe `scheduler_health` fired in 75 reports this window. Last: 2026-06-28T06:49:18.253235+00:00.
- (secret-rotation) `AUTO_AUDIT_DISPATCH_PAT` will hit the 90-day rotation deadline in 30 days. Plan: create a fine-grained PAT scoped to auto-audit + run `scripts/rotate_dispatch_pat.py`.

## Narrative

The `feedback_queue` (160 firings) and `scheduler_health` (75 firings) probes are both firing persistently and share an identical last-fired timestamp, suggesting they're either triggered by the same underlying condition or evaluated in the same health-check pass. Their co-occurrence warrants attention as a coupled failure rather than two independent issues.

Toranot stands out structurally: zero bumps, no live software version, yet 214 emitted issues — by far the highest issue volume in the fleet. This is the inverse of the normal pattern where active repos with frequent bumps generate issues. Something in Toranot is generating signal without any corresponding deploy activity, which is a different failure mode than what the other repos exhibit.

`ward-helper` shows the week's highest bump count (6) with zero workflow failures and 10 emitted issues — a relatively clean deploy cadence. No correlation between its activity and the probe firings is visible in this data, but its bump rate is an outlier worth monitoring if spend or probe load increases.

The PAT rotation deadline in 30 days is currently isolated, but if `AUTO_AUDIT_DISPATCH_PAT` expires without rotation, any auto-audit workflows across the fleet would silently break dispatch — a cross-repo blast radius that makes the countdown more consequential than a single-repo secret.

## Cross-cutting probe activity

- `feedback_queue` — fired in **160** reports (last: 2026-06-28T06:49:18.253235+00:00)
  - {"severity": "warning", "kind": "feedback_queue_fetch_error", "msg": "feedback_queue: failed to query mishpacha_feedback (HTTP 400)"}
- `scheduler_health` — fired in **75** reports (last: 2026-06-28T06:49:18.253235+00:00)
  - {"severity": "warning", "kind": "scheduler-drift", "msg": "GHA scheduler dropped ticks: previous Tier 1 schedule run was 108 min ago (expected \u2264 30). Repository_dispatch path (issue #14) is the durable fix \u2014 verify AUTO_AUDIT_DISP

## Spend trajectory

- Earliest snapshot (2026-06-21): MTD **$90.44**, 16,452 calls
- Latest snapshot (2026-06-28): MTD **$90.50**, 16,460 calls
- Window delta: **+$0.06**
- Projected end-of-month: **$96.96**

## Per-repo activity

### Geriatrics
- live SW: `10.64.182` · version bumps this week: **1** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

### InternalMedicine
- live SW: `10.4.57` · version bumps this week: **1** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

### FamilyMedicine
- live SW: `1.26.17` · version bumps this week: **1** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

### ward-helper
- live SW: `1.46.31` · version bumps this week: **6** · workflow failures (distinct SHAs): **0** · commits to main: **10** · merged PRs: **6**
  - Recent merged PRs:
    - [#261](https://github.com/Eiasash/ward-helper/pull/261) v1.46.31 security: de-identify clinical-notes + azma-ui in public mirror + CI PHI gate
    - [#259](https://github.com/Eiasash/ward-helper/pull/259) v1.46.30: sync azma-ui skill to v4.1.0 (reconciled icon semantics + PHI scrub)
    - [#255](https://github.com/Eiasash/ward-helper/pull/255) feat(skills): runtime conditional-load gate for REHAB_NOTES.md [DO NOT MERGE — Eias review]
    - [#256](https://github.com/Eiasash/ward-helper/pull/256) docs(skills): capture Claude.ai .skill handoff hygiene rules
    - [#254](https://github.com/Eiasash/ward-helper/pull/254) fix(skill): szmc-clinical-notes rehab consistency follow-up (3 stale-line alignments)

### Toranot
- live SW: `?` · version bumps this week: **0** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

### watch-advisor2
- live SW: `?` · version bumps this week: **0** · workflow failures (distinct SHAs): **0** · commits to main: **0** · merged PRs: **0**

## Open issues

**auto-audit self (1)**
- `auto-audit`: 1 open
  - [#71](https://github.com/Eiasash/auto-audit/issues/71) [Tier 3] Weekly synthesis · 2026-06-21 — 3 warn

**Target repos (3)**
- `Eiasash/FamilyMedicine`: 1 open with `auto-audit` label
  - [#170](https://github.com/Eiasash/FamilyMedicine/issues/170) [auto-audit] 1 critical issue(s) — 2026-06-16
- `Eiasash/ward-helper`: 2 open with `auto-audit` label
  - [#260](https://github.com/Eiasash/ward-helper/issues/260) [auto-audit] 1 critical issue(s) — 2026-06-24
  - [#253](https://github.com/Eiasash/ward-helper/issues/253) [auto-audit] 1 critical issue(s) — 2026-06-23

---

_Auto-generated by `scripts/tier3_synthesis.py` ([source](https://github.com/Eiasash/auto-audit/blob/main/scripts/tier3_synthesis.py))._