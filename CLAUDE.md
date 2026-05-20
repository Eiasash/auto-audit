## Operating model — single lane (from 2026-05-19)

Development on this repo is done by Claude Code directly — design,
implementation, testing, and shipping all in one session. This **supersedes**
every "two-lane", "web-lane", or "terminal-lane" instruction in older docs and
skills (audit-fix-deploy and the per-repo skills included): there is no second
Claude lane, and no `claude/web-` vs `claude/term-` branch split.

Workflow: branch `claude/<slug>` -> PR -> CI green + Codex review -> Claude Code
self-merges -> post-merge `verify-deploy`. Codex is the independent automated
reviewer. Codex green + CI green is sufficient self-merge authority. Eias sign-off is required only for: (a) PRs touching patient-data paths (ward-helper PHI crypto, IDB roster schema, rounds-data persistence — enumerated in ward-helper codeowners, queued as follow-up PR), and (b) per-PR gate docs that explicitly carry a "NO self-merge" clause (audit-8 R1.5 / R1.6 and subsequent R1.x gates). Claude Code never self-certifies its own audit — independence comes from cross-model review (Codex), not from human-vs-AI gates. All release,
version-trinity, and verification rules in the repo's skill still apply
unchanged.
