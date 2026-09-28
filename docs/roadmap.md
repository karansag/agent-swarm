# Dashboard roadmap and working notes

Agent-agnostic notes for whoever continues this work (human, Claude,
Codex, or otherwise). Last updated 2026-07-13.

## Deferred features

- **`agent-swarm status "one-liner"` self-reports.** Agents summarize
  what they are doing via a CLI command that stores a status line per
  agent. This feeds the visualization above and the roster sublines. No
  separate LLM harness is needed; the agents are LLMs and can
  self-report.
- **Owner login.** Nodes authenticate with tokens and everything else is
  loopback-only, so a dashboard served through a reverse proxy
  (`AGENT_SWARM_TRUST_LOOPBACK=0`) currently has no way in. Add a login
  page that sets an HttpOnly cookie from an owner token, with Origin
  checks on mutating requests.
- **Importing open tasks** from a machine that ran its own agent-swarm
  (`agent-swarm import-tasks`, see docs/cross-machine-design.md) is
  described but not built; re-file them by hand for now.

## Conventions for this repo

- Commit messages: plain, no AI attribution footers.
- Prose (docs, UI copy, commits): no "no x, no y, just z"
  constructions, minimal emdashes, plain functional naming ("agent
  dashboard", "agents"), no whimsical section names, no KPI stat-tile
  strips.
- The dashboard's authored Preact/HTM modules and CSS live under `web/`.
  Run `npm ci` and `npm run build` after editing them, and commit the generated
  `agent_swarm/portal.html` and `agent_swarm/static/` assets so the Python runtime
  does not need Node. Keep lists keyed; no manual DOM manipulation.
- Verify changes end to end against a scratch server
  (`AGENT_SWARM_DB=/tmp/x.sqlite AGENT_SWARM_PORT=8799`), never against
  the production server on 8765 (real DB at ~/.agent-swarm/db.sqlite).
  Playwright with system Chrome (`channel="chrome"`) works for browser
  checks. Restarting the production server is safe; all state is in
  SQLite.
