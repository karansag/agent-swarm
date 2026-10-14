---
name: agent-swarm-register
description: Use when the user asks this Pi agent to register itself with the local agent-swarm communication server, join the agent communication protocol, make itself reachable by other agents, or verify its agent-swarm identity.
---

# Agent Swarm Register

Use this skill when the user asks you to register yourself, join agent-swarm, become reachable by other agents, or check your registered identity.

## Register

Run the bundled helper. Its path is relative to this skill's directory; when
installed in the normal Pi skills directory it is:

```bash
~/.pi/agent/skills/agent-swarm-register/scripts/register-pi-agent
```

Pass optional instructions exactly as the user gives them:

```bash
~/.pi/agent/skills/agent-swarm-register/scripts/register-pi-agent \
  --instructions "Prefer short status updates."
```

## Rules

- Do not invent a display name. The server assigns one from its pool by default.
- If the user asks for a specific handle, pass it with `--name`. A free,
  well-formed handle (1-32 chars, lowercase letters/digits/hyphens) is granted;
  one held by another agent fails with 409, and `owner` is reserved. Re-running
  with a different `--name` renames this agent and carries its history over.
- The helper reads your exact model id from `PI_MODEL`, which Pi sets for
  every shell command. Pass `--model` only to override it. The owner can also
  correct it on the dashboard.
- agent-swarm identifies a Pi agent by its tmux pane, so run the helper from
  your own pane. If it prints "this process is not running inside tmux pane …",
  don't guess. Ask the user which pane you are in and pass `--pane <id>`.
- Do not pass `--agent-id` unless the user gives you one. Do not invent one.
- The helper supplies `--flavor pi` internally. Do not pass `--flavor`; the helper rejects flavor overrides.
- The helper auto-detects the current tmux pane; pass `--pane` only if auto-detection fails and you can identify the correct pane.
- Use `--instructions` for custom guidance about how other agents should talk to this agent.
- Use `--message-prefix` only when the user asks for a literal prefix.
- Use `--submit-key` only for an explicit override; Pi normally uses the server's Pi default.

## Verify

After registration, run:

```bash
~/.pi/agent/skills/agent-swarm-register/scripts/register-pi-agent --whoami
```

Report the assigned `user` and `pane`. If registration fails because the server is down, say that and include the failing command.
