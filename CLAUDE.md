## Operating model — single lane (from 2026-05-19)

Development on this repo is done by Claude Code directly — design,
implementation, testing, and shipping all in one session. This **supersedes**
every "two-lane", "web-lane", or "terminal-lane" instruction in older docs and
skills (audit-fix-deploy and the per-repo skills included): there is no second
Claude lane, and no `claude/web-` vs `claude/term-` branch split.

Workflow: branch `claude/<slug>` -> PR -> CI green + Codex review -> Eias
merges -> post-merge `verify-deploy`. Codex is the independent automated
reviewer. Eias is the sole merge authority — no self-merge. All release,
version-trinity, and verification rules in the repo's skill still apply
unchanged.
