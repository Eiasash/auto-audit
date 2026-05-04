# Tier 3 — Weekly synthesis · 2026-05-03

_Window: last 7 days · 240 health reports parsed · generated 2026-05-03 07:00Z_

## Action needed

**Warning** (6)
- (probe-recurring) Probe `scheduler_health` fired in 19 reports this window. Last: 2026-05-03T06:01:32.426561+00:00.
- (probe-recurring) Probe `feedback_queue` fired in 18 reports this window. Last: 2026-05-03T06:01:32.426561+00:00.
- (workflow-streak) `Geriatrics` / `Distractor Autopsy Generator` failed across 4 distinct SHAs this window.
- (workflow-streak) `Geriatrics` / `CI` failed across 4 distinct SHAs this window.
- (workflow-streak) `InternalMedicine` / `Distractor Autopsy Generator` failed across 3 distinct SHAs this window.
- (workflow-streak) `InternalMedicine` / `Integrity Guard` failed across 4 distinct SHAs this window.

## Narrative

The most striking pattern is the pairing of `scheduler_health` (19 firings) and `feedback_queue` (18 firings) — near-identical cadences firing together suggest a common upstream cause rather than two independent issues. Given that both probes fired at the same timestamp in their most recent reports, these are likely co-symptomatic of the same subsystem degradation rather than separate problems.

The workflow failure streaks cut across repos in a revealing way: `Distractor Autopsy Generator` is failing in Geriatrics (4 SHAs), InternalMedicine (3 SHAs), and FamilyMedicine (1 SHA) — this is a shared workflow degrading across the estate, not a repo-specific issue. Separately, Geriatrics `CI` and InternalMedicine `Integrity Guard` are each failing across 4 distinct SHAs, meaning these repos have been shipping broken commits continuously without resolution. The high bump counts (37 and 30 respectively) combined with persistent 4-SHA streaks indicate active development is outpacing the broken state — changes are accumulating on a foundation that hasn't cleared.

Geriatrics is the heaviest signal concentration: highest bumps, highest emitted issues (53), and two independent 4-SHA failure streaks. The gap between Geriatrics (53 issues) and InternalMedicine (29) despite comparable activity levels may reflect that CI failures there are blocking remediation feedback loops rather than just generating noise.

## Cross-cutting probe activity

- `scheduler_health` — fired in **19** reports (last: 2026-05-03T06:01:32.426561+00:00)
  - {"severity": "warning", "kind": "scheduler-drift", "msg": "GHA scheduler dropped ticks: previous Tier 1 schedule run was 77 min ago (expected \u2264 30). Repository_dispatch path (issue #14) is the durable fix \u2014 verify AUTO_AUDIT_DISPA
- `feedback_queue` — fired in **18** reports (last: 2026-05-03T06:01:32.426561+00:00)
  - {"severity": "warning", "kind": "feedback_queue_fetch_error", "msg": "feedback_queue: failed to query mishpacha_feedback (HTTP 400)"}
  - {"severity": "warning", "kind": "feedback_queue_fetch_error", "msg": "feedback_queue: failed to query pnimit_feedback (HTTP 400)"}
- `dispatch_pat_freshness` — fired in **1** reports (last: 2026-04-30T20:54:16.393053+00:00)
  - {"severity": "warning", "kind": "dispatch_pat_probe_unauthorized", "msg": "Geriatrics: GET secret metadata returned 403 \u2014 the GH_TOKEN used by this probe lacks secrets:read on Geriatrics. Grant the scope or accept that this probe will
  - {"severity": "warning", "kind": "dispatch_pat_probe_unauthorized", "msg": "InternalMedicine: GET secret metadata returned 403 \u2014 the GH_TOKEN used by this probe lacks secrets:read on InternalMedicine. Grant the scope or accept that this

## Spend trajectory

- Earliest snapshot (2026-04-28): MTD **$197.03**, 29,142 calls
- Latest snapshot (2026-05-03): MTD **$3.68**, 525 calls
- Projected end-of-month: **$38.03**

## Per-repo activity

### Geriatrics
- live SW: `10.64.16` · version bumps this week: **37** · workflow failures (distinct SHAs): **9** · commits to main: **87** · merged PRs: **39**
  - `Distractor Autopsy Generator` (4): [`dbdaad5`](https://github.com/Eiasash/Geriatrics/actions/runs/25001641348), [`151ab40`](https://github.com/Eiasash/Geriatrics/actions/runs/25035028606), [`aae0dea`](https://github.com/Eiasash/Geriatrics/actions/runs/25060050296), [`0e9e6ec`](https://github.com/Eiasash/Geriatrics/actions/runs/25256209613)
  - `CI` (4): [`6be2f44`](https://github.com/Eiasash/Geriatrics/actions/runs/25183229824), [`4c22083`](https://github.com/Eiasash/Geriatrics/actions/runs/25257736411), [`3fc83db`](https://github.com/Eiasash/Geriatrics/actions/runs/25259015370), [`9e81aad`](https://github.com/Eiasash/Geriatrics/actions/runs/25259758081)
  - `Notify auto-audit` (1): [`f4e2d8e`](https://github.com/Eiasash/Geriatrics/actions/runs/25095839459)
  - Recent merged PRs:
    - [#138](https://github.com/Eiasash/Geriatrics/pull/138) v10.64.16: ref beautification finishing pass (91 of 93)
    - [#137](https://github.com/Eiasash/Geriatrics/pull/137) v10.64.15: beautify 391 pipe-delimited canonical refs
    - [#136](https://github.com/Eiasash/Geriatrics/pull/136) v10.64.14: Q-bleed ref cleanup + v3 mapping augmentation
    - [#135](https://github.com/Eiasash/Geriatrics/pull/135) v10.64.13: revert 15 ambiguous refs + close 94 c_wrong audit
    - [#134](https://github.com/Eiasash/Geriatrics/pull/134) v10.64.12: 501 canonical IMA refs (page-specific)

### InternalMedicine
- live SW: `10.4.7` · version bumps this week: **30** · workflow failures (distinct SHAs): **8** · commits to main: **54** · merged PRs: **33**
  - `Integrity Guard` (4): [`13a0703`](https://github.com/Eiasash/InternalMedicine/actions/runs/25129829885), [`102a51d`](https://github.com/Eiasash/InternalMedicine/actions/runs/25130092937), [`e314441`](https://github.com/Eiasash/InternalMedicine/actions/runs/25130257527), [`8a40243`](https://github.com/Eiasash/InternalMedicine/actions/runs/25130432431)
  - `Distractor Autopsy Generator` (3): [`7d6298f`](https://github.com/Eiasash/InternalMedicine/actions/runs/25001858564), [`fe560bc`](https://github.com/Eiasash/InternalMedicine/actions/runs/25031850844), [`48303bb`](https://github.com/Eiasash/InternalMedicine/actions/runs/25060286449)
  - `Notify auto-audit` (1): [`536a2c1`](https://github.com/Eiasash/InternalMedicine/actions/runs/25095843364)
  - Recent merged PRs:
    - [#81](https://github.com/Eiasash/InternalMedicine/pull/81) fix(content): 4 SEVERE fixes + v10.4.5
    - [#80](https://github.com/Eiasash/InternalMedicine/pull/80) ci: add verify-deploy.sh + normalize package.json version
    - [#78](https://github.com/Eiasash/InternalMedicine/pull/78) v10.3.0: settings consolidation — stages 4-5 of 5
    - [#77](https://github.com/Eiasash/InternalMedicine/pull/77) WIP v10.3.0 settings consolidation — stages 1-3 of 5
    - [#76](https://github.com/Eiasash/InternalMedicine/pull/76) fix CRLF tolerance in honestStats source guard

### FamilyMedicine
- live SW: `1.21.6` · version bumps this week: **17** · workflow failures (distinct SHAs): **2** · commits to main: **36** · merged PRs: **12**
  - `Distractor Autopsy Generator` (1): [`fd16567`](https://github.com/Eiasash/FamilyMedicine/actions/runs/25060042609)
  - `Notify auto-audit` (1): [`f38be83`](https://github.com/Eiasash/FamilyMedicine/actions/runs/25095847137)
  - Recent merged PRs:
    - [#27](https://github.com/Eiasash/FamilyMedicine/pull/27) fix(library): AFP markdown links + AI Summary button (both broken in reader)
    - [#24](https://github.com/Eiasash/FamilyMedicine/pull/24) fix(content): 7 SEVERE/WARNING fixes + v1.21.3
    - [#22](https://github.com/Eiasash/FamilyMedicine/pull/22) ci: add verify-deploy.sh post-deploy live verification
    - [#20](https://github.com/Eiasash/FamilyMedicine/pull/20) chore: annotate heDir innerHTML pieces with safe-innerhtml comments
    - [#19](https://github.com/Eiasash/FamilyMedicine/pull/19) ci: notify auto-audit on push-to-main (closes Eiasash/auto-audit#14)

### ward-helper
- live SW: `1.32.0` · version bumps this week: **8** · workflow failures (distinct SHAs): **1** · commits to main: **40** · merged PRs: **32**
  - `Notify auto-audit` (1): [`1290891`](https://github.com/Eiasash/ward-helper/actions/runs/25095851038)
  - Recent merged PRs:
    - [#48](https://github.com/Eiasash/ward-helper/pull/48) feat(skills): bundle azma-ui R4 + geriatrics-knowledge for richer prompts
    - [#47](https://github.com/Eiasash/ward-helper/pull/47) feat(editor): section-cards copy view + warm slate-navy theme
    - [#46](https://github.com/Eiasash/ward-helper/pull/46) fix(auth): normalize flat RPC shape — root cause of every silent 'שגיאה'
    - [#45](https://github.com/Eiasash/ward-helper/pull/45) fix(auth): defer setAuthSession until email step finishes on register
    - [#44](https://github.com/Eiasash/ward-helper/pull/44) feat(auth): optional email field on register form, chains authSetEmail

### Toranot
- live SW: `?` · version bumps this week: **0** · workflow failures (distinct SHAs): **1** · commits to main: **21** · merged PRs: **10**
  - `Toranot Weekly Audit` (1) _(known flap)_: [`36d8238`](https://github.com/Eiasash/Toranot/actions/runs/24979180381)
  - Recent merged PRs:
    - [#89](https://github.com/Eiasash/Toranot/pull/89) fix(simulator): allow 3-6 option counts (was hardcoded === 4)
    - [#88](https://github.com/Eiasash/Toranot/pull/88) feat(scripts): cross-repo PWA runtime simulator (jsdom)
    - [#87](https://github.com/Eiasash/Toranot/pull/87) chore(rls-audit): bump BASELINE 21 → 18 (Phase 2 backups RLS shipped 2026-04-29)
    - [#86](https://github.com/Eiasash/Toranot/pull/86) fix(rls-audit): upload snapshot as artifact (branch protection blocks bot push)
    - [#85](https://github.com/Eiasash/Toranot/pull/85) fix(rls-audit): Q1 allow-list public-schema only (drops false positives on supabase_migrations + topology)

### watch-advisor2
- live SW: `?` · version bumps this week: **0** · workflow failures (distinct SHAs): **1** · commits to main: **21** · merged PRs: **9**
  - `Weekly Autonomous Audit` (1) _(known flap)_: [`d12f5c7`](https://github.com/Eiasash/watch-advisor2/actions/runs/24980775021)
  - Recent merged PRs:
    - [#123](https://github.com/Eiasash/watch-advisor2/pull/123) test: hoist vi.mock() calls to top level in audit expansion suites
    - [#122](https://github.com/Eiasash/watch-advisor2/pull/122) feat(ai): Opus 4.7 + adaptive thinking + retroactive feedback loop + tz fix
    - [#121](https://github.com/Eiasash/watch-advisor2/pull/121) feat(outfit): sweater threshold 22°C → 14°C + per-slot remove fix
    - [#120](https://github.com/Eiasash/watch-advisor2/pull/120) ci(weekly-audit): add mode: agent for schedule events
    - [#119](https://github.com/Eiasash/watch-advisor2/pull/119) ci: add verify-deploy.sh post-deploy live verification

## Open issues

**auto-audit self (1)**
- `auto-audit`: 1 open
  - [#20](https://github.com/Eiasash/auto-audit/issues/20) Tier 2 health check

---

_Auto-generated by `scripts/tier3_synthesis.py` ([source](https://github.com/Eiasash/auto-audit/blob/main/scripts/tier3_synthesis.py))._