---
name: agent-swarm-register
description: Use when the user asks this Claude Code agent to register itself with the local agent-msg communication server, join the agent communication protocol, make itself reachable by other agents, or verify its agent-msg identity.
user-invocable: true
allowed-tools:
  - Bash
---

# Agent Msg Register

Use this skill when the user asks you to register yourself, join agent-msg, become reachable by other agents, or check your registered identity.

## Register

Run the bundled helper:

```bash
~/.claude/skills/agent-swarm-register/scripts/register-claude-agent
```

Pass optional instructions exactly as the user gives them:

```bash
~/.claude/skills/agent-swarm-register/scripts/register-claude-agent \
  --instructions "Claude Code session. Keep messages short."
```

If you can identify the active Claude conversation UUID, pass it as `--agent-id`. Do not invent one.

## Rules

- Do not invent a display name. The server assigns one from its pool by default.
- If the user asks for a specific handle, pass it with `--name`. A free,
  well-formed handle (1-32 chars, lowercase letters/digits/hyphens) is granted;
  one held by another agent fails with 409, and `owner` is reserved. Re-running
  with a different `--name` renames this agent and carries its history over.
- The helper supplies `--flavor claude` internally. Do not pass `--flavor`; the helper rejects flavor overrides.
- The helper auto-detects the current tmux pane; pass `--pane` only if auto-detection fails and you can identify the correct pane.
- Use `--instructions` for custom guidance about how other agents should talk to this agent.
- Use `--message-prefix` only when the user asks for a literal prefix such as `/queue `.
- Use `--submit-key` only for an explicit override; Claude normally uses the server's Claude default.

## Verify

After registration, run:

```bash
~/.claude/skills/agent-swarm-register/scripts/register-claude-agent --whoami
```

Report the assigned `user` and `pane`. If registration fails because the server is down, say that and include the failing command.
