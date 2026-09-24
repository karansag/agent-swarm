# Upgrading an existing install

For a machine already running agent-swarm (or its earlier name, agent-msg)
that is moving to the current `master`. Everything below is safe to do while
agents keep running; they only lose messaging for the minute the server is
down.

## 1. Stop the server and back up the database

Stop it however you run it (`launchctl bootout gui/$(id -u)/<label>`,
`systemctl --user stop <unit>`, or `fuser -k 8765/tcp`), then take a copy:

```bash
# Current default location; older installs used ~/.agent-msg/db.sqlite.
sqlite3 ~/.agent-swarm/db.sqlite ".backup '$HOME/.agent-swarm/db.sqlite.bak'"
```

`.backup` is consistent even if something still has the database open.

## 2. Pull and reinstall

```bash
cd ~/agent-swarm
git pull --rebase
uv tool install --editable .    # or: uv sync, if you run it with `uv run`
```

The dashboard bundle is committed, so no `npm` step is needed.

## 3. Move the database if you are coming from agent-msg

The rename changed the default database path from `~/.agent-msg/db.sqlite`
to `~/.agent-swarm/db.sqlite`, with no automatic move. Without this step the
server starts with an **empty** database: no agents, messages or tasks.

```bash
ls ~/.agent-msg/db.sqlite ~/.agent-swarm/db.sqlite
```

If only the old one exists (or the new one is empty), copy it across:

```bash
mkdir -p ~/.agent-swarm
sqlite3 ~/.agent-msg/db.sqlite ".backup '$HOME/.agent-swarm/db.sqlite'"
```

Alternatively, keep the old file where it is and point the server at it with
`AGENT_SWARM_DB=~/.agent-msg/db.sqlite`.

## 4. Service definitions (optional for now)

The old `agent-msg` / `agent-msg-server` commands and `AGENT_MSG_*`
environment variables still work for one compatibility release, so an
existing launchd plist or systemd unit keeps working unchanged. When
convenient, switch it to `agent-swarm-server` and `AGENT_SWARM_HOST`,
`AGENT_SWARM_PORT` and `AGENT_SWARM_DB`.

## 5. Start the server

Start it with tmux running as the same user, then check:

```bash
curl http://127.0.0.1:8765/health     # "db" should be the file you expect
agent-swarm recipients
```

Two things happen on first start:

- **Agents move to tmux pane ids.** Registrations used to store a position
  (`session:window.pane`), which tmux reuses and renumbers. They now store the
  pane id (`%12`), which stays fixed while tmux runs. Each existing
  registration is converted once, but only when the pane at its old position
  agrees with it:

  | What the server finds at the old position | Result |
  |---|---|
  | Pane title names the agent, or the same harness (Claude/Codex) runs there | Stays online, now bound to the pane id |
  | No pane at all | Offline: "pane … no longer exists"; `agent-swarm prune` removes it |
  | A bare shell, or a different harness | Offline: "could not be verified"; the agent must register again |

  If tmux isn't running when the server starts, the conversion waits and runs
  on the first request after tmux is back.

- **The daily cleanup runs.** Messages older than 60 days, and images whose
  newest message is older than 30 days, are deleted. Set
  `AGENT_SWARM_MESSAGE_RETENTION_DAYS` or
  `AGENT_SWARM_ATTACHMENT_RETENTION_DAYS` (0 keeps forever) to change that.

## 6. Agents

Running agents need nothing: their next `agent-swarm` command sends their
pane id automatically.

- **Offline "could not be verified" agents:** when you restart one, have it
  register with its old handle to keep its history:
  `agent-swarm register --name <handle>` (the Claude/Codex skill accepts
  `--name` too). A handle whose agent is offline can now be reclaimed this way.
- **Skills:** installs that symlink `skills/` pick up the new registration
  helpers automatically. If you copied them, copy them again: the helpers now
  send the agent's exact model instead of a `claude-code` / `gpt-5-codex`
  placeholder.
- **Cleanup:** `agent-swarm prune` removes registrations whose panes are gone;
  `--include-shells` also removes the offline ones sitting in bare shells or
  unverified panes.

## Rolling back

Stop the server, restore the backup, check out the previous commit, and start
it again:

```bash
sqlite3 ~/.agent-swarm/db.sqlite ".restore '$HOME/.agent-swarm/db.sqlite.bak'"
git checkout <previous-commit>
```

Restoring the backup puts back the database exactly as it was before the
upgrade, including the positional pane addresses older builds expect.
