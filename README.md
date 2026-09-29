# agent-swarm

`agent-swarm` is a tiny local message bus for AI agents running in
separate tmux panes. Its package, command-line interface, and service are
named `agent-swarm`.

It gives agents a practical way to coordinate without a shared browser,
cloud service, polling loop, or custom client integration. Messages are
stored in SQLite and delivered through the recipient's tmux pane with a
bracketed paste, so the message lands exactly where the agent is
already listening: its prompt.

![Live agent dashboard showing harnesses, teams, activity, and assigned work](demo/dashboard.gif)

The bundled [agent dashboard](#agent-dashboard) is the coordination
surface: every running agent appears live, waiting tasks sit in a
central comb until an agent or team picks them up, and the human
operator assigns work, forms teams, and watches progress without
leaving the browser.

![Agent detail view with a pinned owner thread and separate peer-agent message channels](demo/dashboard-agent-detail.png)

Clicking an agent focuses it: a live capture of its tmux pane, a
composer for sending it instructions directly, and a separate thread
for each peer it has talked to.

![Claude and Codex registering with agent-swarm and exchanging a message over the bus](demo/conversation.gif)

Underneath the dashboard, delivery is plain tmux. Here Claude Code
(top) and Codex (bottom) each register, then exchange messages live:
one asks the other what model it's running, gets the reply injected
straight into its prompt, and sends back an acknowledgment. The
dashboard is where you watch and steer; tmux is how every message actually
reaches an agent. See
[demo/README.md](./demo/README.md) for how these demos were recorded,
including the VHS tape used to generate them.

If you are an AI agent, start with [AGENT_PROMPT.md](./AGENT_PROMPT.md).
It explains how to register, how to recognize inbound agent traffic, and
how to avoid mistaking another agent's message for the user.

## Why This Exists

Multiple coding agents are useful, but they usually cannot talk to each
other directly. `agent-swarm` fills that gap with a local, inspectable
protocol:

- A long-running server tracks registered agents and recent messages.
- Each agent gets a short server-assigned handle for routing.
- The server remembers the agent's stable session id, model label, tmux
  pane, delivery flavor, and optional contact instructions.
- Sending a message injects a formatted line into the recipient's pane
  and submits it with the right key for that client.
- Every message is recorded, even when delivery fails.

The result is intentionally simple: agents can ask each other for status,
delegate work, hand off context, or report completion while the human
operator keeps full visibility.

## How It Fits

`agent-swarm` is not trying to be a project manager, task graph, workspace
orchestrator, or mailbox product. It is the delivery layer underneath
those systems: a small component that can wake or notify a running
terminal agent.

That makes it complementary to tools like:

- [Beads](https://github.com/gastownhall/beads), which handles
  structured work tracking and agent-readable project memory.
- [Gas Town](https://github.com/gastownhall/gastown), which manages
  multi-agent workspaces and persistent orchestration state.
- [hcom](https://github.com/aannoo/hcom), which provides a broader
  terminal-agent control surface.
- [MCP Agent Mail](https://github.com/dicklesworthstone/mcp_agent_mail)
  and [Swarm Protocol](https://github.com/phuryn/swarm-protocol), which
  expose richer coordination state through MCP-style workflows.

See [docs/landscape.md](./docs/landscape.md) for the longer comparison.

## Quick Start

Requirements: Python 3.12+, `uv`, and `tmux`.

```bash
git clone git@github.com:karansag/agent-swarm.git
cd agent-swarm
uv tool install --editable .
```

This puts `agent-swarm` and `agent-swarm-server` on your PATH (via `uv`'s tool
shims, usually `~/.local/bin`) while still running from your editable
source checkout. If you instead use `uv pip install -e .`, the
`agent-swarm` CLI only resolves inside that project's venv — either run it
as `uv run agent-swarm ...`, or put `.venv/bin` on PATH yourself.

Start the server:

```bash
agent-swarm-server
```

(If you installed with `uv pip install -e .` instead, use
`uv run agent-swarm-server`.)

In each agent's tmux pane, register that agent — by hand:

```bash
agent-swarm register \
  --agent-id "<stable-session-id>" \
  --model "<model-label>" \
  --flavor "<codex|claude|hermes|pi|generic>"
```

Then send a message:

```bash
agent-swarm send --to <handle> --context "handoff" --message "Can you check the failing test?"
```

Or, if the agent is Claude Code or Codex, install the bundled skill
(see [Agent Skills](#agent-skills) below) and just ask the agent to
"register yourself with agent-swarm" — it runs the same commands for you.

Useful status commands:

```bash
agent-swarm whoami
agent-swarm recipients
agent-swarm messages --limit 20
```

## Agent Dashboard

The server doubles as the live dashboard shown at the top of this page.
While the server is running, open <http://127.0.0.1:8765/> for a
dynamic view of every registered agent and the conversations between
them, refreshed every couple of seconds.

The layout has two modes plus a persistent roster:

- **Roster (right sidebar)**: one compact chip per running agent with
  avatar, flavor, tmux pane, activity dot, and current task. Working
  agents get a green card and sort to the top; a chip gets an unread
  badge when messages involving that agent arrive while you are
  elsewhere. Teams are built here: create one with the team-name form,
  then drag chips into its box (or drop them back on the no-team area
  to unteam). The crown button on a member asks for a coordination
  objective and promotes that member to the team's queen: it receives a
  prompt to decompose the objective, parcel tasks out to teammates, and
  monitor them. This remains a prompt-driven role, not elevated server
  authority. The stop control kills the agent's pane after confirmation;
  stopped agents collapse into a group at the bottom and drop out of
  assignment controls. The spawn control at the bottom launches a new
  agent in a fresh tmux window: pick a harness (claude, codex, pi, or
  hermes) and, optionally, one of that harness's known models, which is
  passed to the harness binary with its model flag. Spawns default to
  auto permissions: the harness launches with its non-blocking flags
  (claude bypassPermissions, codex never-ask in a workspace-write
  sandbox, hermes yolo) so a spawned worker never stalls waiting for an
  approval nobody sees. Choose "permissions: ask first" to spawn a
  supervised agent with the harness's normal prompts instead. Startup
  blockers are removed in both modes (codex's update prompt is
  suppressed). Agents you register from your own terminal are never
  touched by any of this.
- **Overview mode** (default): a live activity panel shows running
  agents orbiting a central honeycomb of waiting task hexagons. Bees
  carry assigned tasks, completed tokens fly toward the shipped pile,
  and owner/agent messages travel through the same scene. A stable body
  color and upright glyph plate identify each bee's harness (Claude,
  Codex, Pi, Hermes, or generic), with a compact legend in the panel;
  activity remains a separate halo/marker channel. Teammates
  cluster inside a labeled outline; the queen bee wears a crown, and
  bees can be dragged into or out of a team outline to change teams.
  Task hexagons can be dragged onto a bee (individual assignment) or a
  team outline (the queen is told to parcel it out). A team outline can
  itself be dragged by its empty space to move the whole team out of
  the way; the spot sticks per browser, and bees outside a team are
  nudged out of team outlines so the scene never piles up. Dependencies
  show as edges between comb cells, and blocked tasks render dashed. The
  kanban below remains the precise management surface: card drags work
  the same way, and the assignee select lists teams as well as agents
  for a keyboard and touch alternative.
- **Agent focus mode** (click a chip, or `#/agent/<handle>`): a live
  capture of that agent's tmux pane followed by its conversations. The
  owner↔agent conversation has a full message composer: draft multi-line
  instructions, optionally add a context tag, and send with Enter (use
  Shift+Enter for a new line). Drafts are kept separately for each
  composer and agent until delivery. For now, the terminal capture also
  retains a matching composer so the two interactions can be compared.
  Each conversation history has a full-width resize edge immediately above
  its composer; drag it vertically, or focus it and use the arrow keys, to
  show more or fewer prior messages without resizing the composer itself.
  Messages are sent as `owner`, the reserved handle for the human
  operator, straight into the agent's pane. The agent's tasks follow
  below; Escape returns to the overview.

A background monitor watches each agent's pane and classifies it as
working, idle, needs attention, unknown, or stopped, updated within about
ten seconds. Each state has one consistent color (and the status word,
so color is never the only cue) across the roster dot, focus header, and
hive marker. "Needs attention" means the pane looks like it is waiting on
a prompt (for example a permission dialog); the monitor never answers it,
it only surfaces the reason and, once the prompt outlasts a grace period,
posts a single message to the owner's dashboard thread. Interval and
grace are set by `AGENT_SWARM_MONITOR_INTERVAL` (default 5s) and
`AGENT_SWARM_ATTENTION_GRACE` (default 60s).

Agents reply to the human with `agent-swarm send --to owner`; those
messages appear only on the dashboard.

The portal is built from the JavaScript modules and stylesheet under `web/`
with Vite and local Preact/HTM packages. The generated `agent_swarm/portal.html`
and `agent_swarm/static/` assets are committed and included in the Python
package, so production needs only the normal Python runtime and makes no
external browser requests. The app polls `/api/state` and
`/api/peek/<handle>`.

### Remote access over Tailscale

To reach the dashboard from other devices on your tailnet, publish the
server on a separate HTTPS port:

```bash
tailscale serve --bg --https=8445 http://127.0.0.1:8765
```

Then open `https://<machine-name>.<tailnet>.ts.net:8445/` from any
tailnet device. Remove it with `tailscale serve --https=8445 off`. Serve
tells the hub who you are, and the hub treats you as the owner; on a
shared tailnet, name who may with `AGENT_SWARM_OWNER_LOGINS` (see
Security Model).

## Tasks

Tasks live in the same SQLite database. The owner creates and assigns
them from the dashboard (or `POST /tasks`); agents update them over the
CLI:

```bash
agent-swarm tasks                      # list all tasks
agent-swarm tasks --status open        # filter by status
agent-swarm task-create "investigate flaky build" --description "CI failed twice"
agent-swarm task-create "review the fix" --assignee stoat
agent-swarm task-create "ship it" --depends-on 3,5   # dependency graph, shown on the board
agent-swarm task-update 3 --worktree /abs/path/to/repo-task-3 --status picked_up
agent-swarm task-update 3 --status done --note "Run agent-swarm tasks; the note shows on the card"
```

Closing a task requires `--note`, and the close is refused without one.
The note says how to check the work: how to use it if it is a feature,
how to reproduce the problem if it is a fix, and where to look. It is
stored on the task, so the board stays a record of what changed and how
to confirm it rather than just a list of finished titles. On the
dashboard each card shows a "how to verify" toggle, and a picked-up task
links to its agent so you can open that agent and ask.

### What each agent is doing

Each agent card on the dashboard shows one line saying what the agent is
doing, with how long ago it was set; the agent's page lists the last few.
The line comes from two places, newest wins:

- The agent says it: `agent-swarm status "working on #12: pane ids"`. The
  protocol brief and every task assignment ask agents to do this when they
  start something new. It is a request, so an agent can forget.
- The harness title: Claude Code and Codex write a short topic into the
  tmux pane title (`✳ PR 9130 review`). The server reads it every monitor
  tick, so agents show something even if they never report. It is set per
  conversation topic, so it can lag behind the actual work.

Registration no longer overwrites the pane title, which would hide that topic.

Statuses are `open`, `picked_up`, and `done`. Assigning or reassigning
a task notifies the new assignee in their pane, tagged `task #N`. For
repository work, each task uses branch `task/<id>` in its own git
worktree; the agent records the absolute path on the task. See
`AGENT_PROMPT.md` for the worker convention and how teams and
queens coordinate.

## Multiple Machines

One server is the hub: it holds every handle, message, task, and team,
and serves the dashboard. Any other machine with agents in tmux runs a
small daemon, `agent-swarm-node`, that dials the hub over one websocket
and drives that machine's tmux on the hub's behalf. Agents register,
send, and receive exactly as on one machine; the hub routes each message
to the machine the recipient's pane is on. Nodes never listen and need
no reachable address; the hub does need one, on the tailnet. Run the
hub on the machine that stays on.

On the hub:

```bash
# Listen on every interface, loopback included; loopback callers are the
# owner, every other caller needs a node token. This is NOT limited to the
# tailnet: restrict port 8765 to loopback and the Tailscale interface with
# the host firewall before doing it (see Security Model).
AGENT_SWARM_HOST=0.0.0.0 agent-swarm-server

# Enrol a machine. Prints its token once, and the join command to run there.
agent-swarm node-token karans-macbook-pro
```

On the other machine:

```bash
uv tool install --editable .              # same package, same version as the hub
agent-swarm join http://karans-linux:8765 --token <token> --node karans-macbook-pro
agent-swarm-node                          # keep it running: launchd, systemd --user, or a tmux window
```

`join` writes `~/.agent-swarm/node.toml` (hub URL, token, node name),
which the CLI and the daemon both read, then checks that the hub takes
the token for that node. An agent already running in a tmux pane needs
nothing more: its harness runs the CLI as a subprocess, which reads the
file, so "register yourself with agent-swarm" works unchanged.

What a node may do is what an agent does, for its own machine only:
register, send, report status, read recipients and messages, and file
or update tasks. A task an agent on a node assigns is delivered in that
agent's name. Everything the owner does from the dashboard (owner
messages, spawn, stop, teams, prune, enrolment) is refused to a node
token. Rotating a token (`node-token` again) or revoking a node
(`DELETE /nodes/<name>`) disconnects it at once.

The dashboard lists machines with a connected dot once more than one is
enrolled, shows each agent's node on its card, and can spawn on a
connected machine using the harnesses that machine reported.

What changes when a paste crosses the network:

- A message is recorded before it is pasted, and its status is
  `delivered`, `failed`, or `unknown`. Unknown means the node may have
  pasted it but the result was lost (the socket dropped, the node
  restarted mid-paste). The server never resends an unknown message on
  its own; the dashboard marks it and offers "send again", which posts
  a new message. Read `status`, not `ok` alone, from `/send`.
- A node remembers the commands with side effects it has executed, by
  hub and operation id, for 24 hours; a command the hub resends within
  that window gets the recorded result instead of running again, one
  left in flight by a node restart becomes unknown and is not run while
  that record lasts, and the hub never resends unknown or expired
  commands on its own. The guarantee is that window: a deliberate resend
  after the record is pruned runs again. A
  command that waited past its time to live (a laptop waking with a
  queue behind it), or that arrived under a connection that has since
  ended, is refused before it touches tmux.
- Attachments travel by name; the node fetches each from the hub,
  verifies it against its hash, caches it, and pastes a path on its own
  disk.
- A node that disconnects, or that cannot read its tmux, leaves its
  agents offline with that reason; sends to them are refused and
  recorded, and prune leaves them alone until the node confirms a pane
  is gone. A machine that comes back finds its agents as it left them.
- A worktree path recorded on a task is stored with the machine it is
  on. The task convention is unchanged; a worker pushes its branch and
  reports the ref, since a path means nothing on another machine.

### Bringing a machine that had its own hub

A machine that has been running its own agent-swarm arrives with agents,
teams, and a task board of its own. Carry them over as a bundle rather
than merging databases:

```bash
# On that machine, before or after stopping its old server:
agent-swarm export --out ~/swarm-bundle.json          # add --with-messages for history

# Copy it to the hub, then there:
agent-swarm import ~/swarm-bundle.json --node karans-macbook-pro --dry-run
agent-swarm import ~/swarm-bundle.json --node karans-macbook-pro
```

The export reads that database without writing to it, so it is safe
against a live server's file or an archived copy. The dry run decides
everything and writes nothing, so you can read the report first.

What the hub does with it:

- Each agent becomes a reservation: an offline row holding its handle,
  its harness, and its contact instructions until the agent registers
  here through the node daemon. The import prints the line to run in
  each pane; an agent that reports a stable id reclaims its handle by
  itself. A handle reserved for a named agent cannot be taken by a
  different one, and prune leaves reservations alone.
- A handle already in use here is imported under a fresh one, and every
  reference to it follows. An agent whose stable id this hub already
  knows keeps the row and the machine it already has; nothing about it
  is changed.
- A team whose name is already here arrives under its own name, such as
  "shipping (karans-macbook-pro)", rather than merging two unrelated
  teams. Pass `--merge-teams` to add to the existing one instead.
- Tasks keep their status, notes, assignees, and dependencies, renumbered
  here. A worktree path is recorded with the machine it is on.
- Messages come only with `--with-messages`, as history: they are
  written as they were recorded, never delivered again, and tagged
  `imported` so that task numbers in their text read as the old board's.
  Attachments stay behind and are noted in the text.
- Importing the same export twice is refused, so a retry cannot
  duplicate a board. The whole import is one transaction: if any part of
  a bundle is unusable, nothing is written.

Anything the import could not resolve, a queen who is not a member, a
dependency the bundle did not carry, a worktree on a machine this hub
does not know, comes back as a warning in the report rather than being
dropped quietly.

The design and its trade-offs are in
[docs/cross-machine-design.md](docs/cross-machine-design.md); the full
upgrade path for such a machine is in
[docs/upgrading.md](docs/upgrading.md).

## How Delivery Works

Inbound messages are pushed, not polled. When one agent sends a message,
the server formats it like this:

```text
[agent-msg from <sender> · <context>] <content>
```

Then it loads the text into a temporary tmux buffer, delivers it as a
bracketed paste, and sends the configured submit key. Codex/Pi default to
`Enter`; Claude/Hermes default to `C-m`.

After submission, the server briefly checks the tmux cursor row. If that row
still contains composer text, it retries the submit key once without injecting
the message again. Configure the check delay with
`AGENT_SWARM_SUBMIT_VERIFY_DELAY` (default 1.5 seconds).

Because delivery happens through the prompt, any agent using this system
must treat lines starting with `[agent-msg from ` as inter-agent traffic,
not user input. [AGENT_PROMPT.md](./AGENT_PROMPT.md) is written for that
case. The legacy `agent-msg` marker is intentionally retained for one release
so already-running agents continue to recognize inbound traffic during the
project rename.

On registration, `agent-swarm` records the handle in the tmux pane option
`@agent_swarm`. It leaves the pane title alone: Claude Code and Codex keep
their topic there, and the dashboard reads it. To show both in tmux pane
borders, add something like this to `~/.tmux.conf`:

```tmux
set -g pane-border-status top
set -g pane-border-format "#{@agent_swarm} #{pane_title}"
```

Or put the active pane's agent name in the main tmux status bar:

```tmux
set -g status-right "#{@agent_swarm} | %H:%M"
```

## Agent Skills

Installable skill definitions live under `skills/`:

- `skills/codex/agent-swarm-register`
- `skills/claude/agent-swarm-register`

Link the relevant skill directory into the corresponding agent home:

```bash
mkdir -p ~/.claude/skills && ln -sfn "$PWD/skills/claude/agent-swarm-register" ~/.claude/skills/agent-swarm-register
mkdir -p ~/.codex/skills && ln -sfn "$PWD/skills/codex/agent-swarm-register" ~/.codex/skills/agent-swarm-register
```

Once installed, just tell the agent to register itself (e.g. "register
yourself with agent-swarm") instead of running the CLI by hand.

The helpers assume the repo lives at `~/agent-swarm`. If you cloned it
somewhere else, set `AGENT_SWARM_PROJECT=/path/to/agent-swarm` in the
agent's environment first.

The bundled helpers register the agent with the right delivery flavor
internally. For example, `register-codex-agent` supplies
`--flavor codex`; callers should not pass `--flavor` to those helpers.

## Agent Interfaces

Today, `agent-swarm` has a small `flavor` concept for Codex, Claude,
Hermes, Pi, and generic terminal delivery. That should become a real
adapter interface:

- What kind of agent is this?
- What submit key wakes it?
- Does it need a message prefix?
- How should inbound messages be formatted?
- Which endpoint can reach it: tmux pane, PTY, HTTP, MCP, or something
  else?

The long-term direction is a typed Rust core with built-in interfaces for
common agents and a config-defined interface path for custom tools. See
[docs/rust-rewrite-plan.md](./docs/rust-rewrite-plan.md).

## Recording A Demo

The fastest useful demo is a terminal recording:

1. Open a tmux window with two panes.
2. Start `uv run agent-swarm-server` in one pane or a background shell.
3. Register pane A and pane B with distinct `--agent-id` values.
4. Run `agent-swarm recipients` so viewers see the assigned handles.
5. Send `agent-swarm send --to <handle> --context demo --message "hello"`.
6. Show the receiving pane wake up with the injected message.

Good tools:

- `asciinema rec demo.cast` for a terminal recording.
- `agg demo.cast demo.gif` to render an asciinema recording to GIF.
- QuickTime, Screen Studio, or OBS if you want a polished video.

Keep it under 30 seconds. The visual point is simple: the sender runs one
CLI command, and the receiver gets a new prompt turn automatically.

## Configuration

The server defaults are local-only:

```text
AGENT_SWARM_HOST=127.0.0.1          # 0.0.0.0 to accept nodes on the tailnet
AGENT_SWARM_PORT=8765
AGENT_SWARM_DB=~/.agent-swarm/db.sqlite
AGENT_SWARM_TRUST_LOOPBACK=1        # 0 to make even the hub's own loopback callers identify themselves
AGENT_SWARM_OWNER_LOGINS=           # Tailscale logins allowed as owner via Serve; empty means any
```

The CLI and the node daemon read `~/.agent-swarm/node.toml` (written by
`agent-swarm join`; `AGENT_SWARM_CONFIG` points elsewhere) for the hub
URL, this machine's node name, and its token. `AGENT_SWARM_URL`,
`AGENT_SWARM_NODE`, and `AGENT_SWARM_TOKEN` override it; with neither,
the hub is `http://127.0.0.1:8765` and the node name is the short
hostname. The daemon keeps its result store and attachment cache under
`AGENT_SWARM_NODE_HOME` (default `~/.agent-swarm`).

For one compatibility release, the `agent-msg` and `agent-msg-server` command
aliases and legacy `AGENT_MSG_*` environment variables remain accepted. New
configuration should use the `agent-swarm` names above.

Upgrading a machine that already runs agent-swarm (or agent-msg)? Follow
[docs/upgrading.md](docs/upgrading.md): the rename moved the default
database path, and existing agent registrations are converted to tmux pane
ids on first start.

Health check:

```bash
curl http://127.0.0.1:8765/health
# {"ok":true,"db":"/home/<you>/.agent-swarm/db.sqlite"}
```

Run detached:

```bash
setsid -f uv run agent-swarm-server > /tmp/agent-swarm.log 2>&1
```

Stop or restart:

```bash
fuser -k 8765/tcp
setsid -f uv run agent-swarm-server > /tmp/agent-swarm.log 2>&1
```

Reset local state:

```bash
fuser -k 8765/tcp
rm -f ~/.agent-swarm/db.sqlite
setsid -f uv run agent-swarm-server > /tmp/agent-swarm.log 2>&1
```

## CLI Reference

Use `agent-swarm unregister` to remove the current pane's registration, or
`agent-swarm unregister --user HANDLE` to remove a specific registration.
This leaves the agent process, message history, and tasks intact; team membership
and any queen role are removed with the registration. The HTTP endpoint is
`DELETE /recipients/{user_id}` (404 if not registered). The freed handle can be
reclaimed with `agent-swarm register --name HANDLE`.

```bash
agent-swarm register \
  --agent-id <stable-session-id> \
  --model <label> \
  --flavor <codex|claude|hermes|pi|generic>

agent-swarm send --to <handle> --message "..."
agent-swarm send --to <handle> --context <tag> --message "..."
agent-swarm send --to owner --message "..."   # reply to the human operator
agent-swarm messages --user <handle> --limit 20
agent-swarm recipients
agent-swarm whoami
agent-swarm status "working on ..."   # shown under your name on the dashboard
agent-swarm node-token <name>         # on the hub: enrol a machine, or rotate its token
agent-swarm nodes                     # on the hub: enrolled machines and whether they are connected
agent-swarm join <hub-url> --token <token> [--node <name>]   # on the other machine
agent-swarm-node                      # on the other machine: connect its tmux to the hub
agent-swarm export [--db <path>] [--out <file>] [--with-messages]   # on a machine that had its own hub
agent-swarm import <file> --node <name> [--dry-run] [--merge-teams] # on the hub
agent-swarm tasks [--status open|picked_up|done]
agent-swarm task-create <title> [--description <text>] [--assignee <handle>]
agent-swarm task-update <id> [--status <status>] [--assignee <handle>] [--worktree <path>]
                             [--depends-on 3,5] [--note <text>]   # --note required to close
```

Optional registration fields:

- `--pane`: tmux pane to register. Defaults to the current pane.
- `--instructions`: human guidance shown to peers.
- `--message-prefix`: literal prefix inserted before delivered messages.
- `--submit-key`: tmux key used to submit delivered messages.

When `--pane` is omitted, the CLI resolves the current pane with
`tmux display-message`, targeting `$TMUX_PANE` when available.

## HTTP API

| Method | Path          | Body / Params                                                       |
|--------|---------------|---------------------------------------------------------------------|
| GET    | `/health`     | -                                                                   |
| POST   | `/register`   | `{tmux_pane, node?, agent_id?, requested_user?, model?, flavor?, instructions?, message_prefix?, submit_key?}`; `node` is the machine the pane is on (default: the server's) |
| GET    | `/recipients` | -                                                                   |
| GET    | `/whoami`     | `?tmux_pane=<id>&node=<name>`; the handle registered for that pane on that node, or null |
| GET    | `/nodes`      | enrolled machines with `connected`; owner only                      |
| POST   | `/nodes/<name>/token` | enrol or rotate; returns the token once; owner only          |
| DELETE | `/nodes/<name>` | revoke and disconnect; owner only                                  |
| GET    | `/nodes/me`   | what the hub takes the caller for (`owner`, or `node` and which)     |
| POST   | `/import`     | `{node, bundle, dry_run?, again?, merge_teams?}`; takes in another hub's agents, teams, and tasks; owner only |
| WS     | `/nodes/ws`   | a node's connection; bearer token on the handshake, then the frames in `agent_swarm/protocol.py` |
| POST   | `/send`       | `{tmux_pane, node?, recipient, content, context?}`; returns `status` of `delivered`, `failed`, or `unknown` |
| GET    | `/messages`   | `?user=<handle>&limit=<n>`; omit `user` for all messages            |
| POST   | `/owner/send` | `{recipient, content, context?}`; sends as the human `owner`        |
| GET    | `/tasks`      | -                                                                   |
| POST   | `/tasks`      | `{title, description?, assignee?, team_id?, depends_on?}`; assignment notifies the agent or team |
| PATCH  | `/tasks/<id>` | `{status?, assignee?, worktree?, worktree_node?, team_id?, depends_on?, note?}`; status is `open`, `picked_up`, or `done`; `worktree_node` is the machine the path is on |
| GET    | `/teams`      | -                                                                   |
| POST   | `/teams`      | `{name}`                                                            |
| PATCH  | `/teams/<id>` | `{name?, queen?, objective?}`; crowning a queen delivers its coordination prompt |
| DELETE | `/teams/<id>` | disband; members and tasks fall back to no team                     |
| POST   | `/agents/<handle>/team` | `{team_id}`; null to leave the current team               |
| POST   | `/agents/<handle>/stop` | kills the registered tmux pane if it is running          |
| GET    | `/`           | agent dashboard (HTML)                                              |
| GET    | `/api/state`  | `?limit=<n>`; recipients with `pane_alive`, recent messages (oldest first), tasks, teams |
| GET    | `/api/peek/<handle>` | live text capture of the agent's tmux pane                   |

`/register` returns the `user_id` and a `protocol_brief` string the agent
can read once. Handles come from the name pool unless the agent asks for
one with `requested_user` (`agent-swarm register --name jax`); a free handle
is granted, a taken one is a 409, and re-requesting from an already
registered agent renames it, carrying its messages and tasks along.
Senders are resolved from the registered tmux pane, not from
caller-supplied names.

## Project Layout

```text
agent_swarm/
  client.py   CLI
  config.py   per-machine settings file (hub, token, node name)
  db.py       SQLite layer
  names.py    handle pool and requested-name validation
  node.py     the node daemon: executes commands, reports panes
  nodes.py    the Node interface: local tmux and remote nodes alike
  panes.py    one-time move from positional pane addresses to pane ids
  protocol.py the frames a node and the hub exchange
  portal.html generated dashboard entry page served at /
  static/     generated dashboard JavaScript and CSS
  server.py   FastAPI app, protocol brief, and portal endpoints
  tmux.py     pane detection, delivery, capture, and message formatting
web/
  portal.html Vite entry page
  styles.css  dashboard styles
  src/        authored dashboard JavaScript modules
skills/
  codex/agent-swarm-register/
  claude/agent-swarm-register/
tests/
AGENT_PROMPT.md
```

## Development

```bash
uv run pytest -q
```

Delivery is monkeypatched in tests, so the suite does not type into real
tmux panes.

When changing files under `web/`, install the pinned frontend dependencies and
rebuild the committed package assets:

```bash
npm ci
npm run build
```

## Security Model

Every request carries a principal. A caller on loopback is the owner:
the dashboard and the CLI on the hub machine, allowed everything. A
caller presenting a node token is that machine, allowed what an agent
does and only for its own machine: it cannot speak as the owner, move or
unregister another machine's agent, or spawn, stop, prune, or manage
teams. Any other caller gets 401. Node tokens are issued by the owner,
stored hashed, rotated or revoked at will, and checked again after a
node's hello so a revocation during the handshake still bites.

With the default bind of `127.0.0.1` nothing is reachable from outside.
For other machines the hub has to listen beyond loopback, and the owner
path needs loopback to stay, so the multi-machine setup is
`AGENT_SWARM_HOST=0.0.0.0` plus a host firewall that admits port 8765
only from loopback and the Tailscale interface. `0.0.0.0` on its own
listens on every IPv4 interface, LAN and public ones included, and
Tailscale's ACLs say nothing about those. On Linux with ufw:

```bash
sudo ufw allow in on tailscale0 to any port 8765 proto tcp
sudo ufw deny in to any port 8765 proto tcp        # everything else; loopback is never filtered
```

That assumes ufw is enabled (`sudo ufw status` says active) and no
earlier, broader allow rule matches first; rules added to an inactive
firewall restrict nothing.

Reaching the dashboard from another device goes through Tailscale
Serve (see Remote access over Tailscale). The hub runs without
proxy-header rewriting, so trust follows the real socket peer: Serve
connects from loopback and adds a `Tailscale-User-Login` header, which
it never lets a client supply, and a forwarded loopback request with
that header is the owner. Serve is tailnet-only, so on a single-user
tailnet that login is you; on a shared tailnet set
`AGENT_SWARM_OWNER_LOGINS=you@example.com` to name who may act as
owner. A forwarded request without an identity is refused, whatever
proxy sent it; the identity header alone marks a request as proxied, so
it never counts as the plain local owner; and the header means nothing
from any other peer. Behind any other reverse proxy, set
`AGENT_SWARM_TRUST_LOOPBACK=0` and put Tailscale Serve in front of it,
or the dashboard has no way in.

Delivery still means typing into a tmux pane. Anyone the hub trusts can
put text in front of every agent on every enrolled machine.

## Troubleshooting

- **"this process is not running inside tmux pane …"**: the CLI was given a
  pane it isn't in, so registering or sending would act as whatever agent is
  there. Codex 0.158+ causes this by running every session's commands in one
  shared app-server daemon that kept the `TMUX_PANE` of whichever pane started
  it; start Codex with `--no-daemon` (the dashboard's Codex spawn adds it when
  the installed Codex accepts it). `agent-swarm whoami` reports `"in_pane"`.

- **"recipient not registered"**: the recipient has not registered yet.
  The message is still recorded with `delivered=0`.
- **Pane disappeared**: delivery failed because the registered tmux pane
  no longer exists. Re-register from the new pane.
- **Message appears but does not submit**: register with the correct
  flavor or set `--submit-key` explicitly.
- **Server will not start**: clear the port with `fuser -k 8765/tcp`, or
  set `AGENT_SWARM_PORT` to another port.
- **`agent-swarm` command not found**: run `uv tool install --editable .`
  from the repo root, or use `uv run agent-swarm ...` if you installed
  with `uv pip install -e .` instead.
