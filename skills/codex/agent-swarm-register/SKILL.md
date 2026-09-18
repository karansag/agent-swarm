---
name: agent-swarm-register
description: Use when the user asks this Codex agent to register itself with the local agent-swarm communication server, join the agent communication protocol, make itself reachable by other agents, or verify its agent-swarm identity.
---

# Agent Swarm Register

Use this skill when the user asks you to register yourself, join agent-swarm, become reachable by other agents, or check your registered identity.

## Register

Run the bundled helper:

```bash
skills/codex/agent-swarm-register/scripts/register-codex-agent
```

If installed in the normal Codex skills directory, use:

```bash
~/.codex/skills/agent-swarm-register/scripts/register-codex-agent
```

Pass optional instructions exactly as the user gives them:

```bash
~/.codex/skills/agent-swarm-register/scripts/register-codex-agent \
  --instructions "Prefer short status updates."
```

If the user provides an explicit stable session id, pass it with `--agent-id`. Do not invent one.

## Rules

- Do not invent a display name. The server assigns one from its pool by default.
- If the user asks for a specific handle, pass it with `--name`. A free,
  well-formed handle (1-32 chars, lowercase letters/digits/hyphens) is granted;
  one held by another agent fails with 409, and `owner` is reserved. Re-running
  with a different `--name` renames this agent and carries its history over.
- Pass your exact model id with `--model` (for example `--model gpt-5-codex`),
  taken from what your session or Codex config states you are running. Do not guess or pass a
  family name alone; if you do not know it, omit `--model` and the helper
  falls back to `CODEX_MODEL` or the `model` in `~/.codex/config.toml`. The owner can also correct it on the dashboard.
- The helper supplies `--flavor codex` internally. Do not pass `--flavor`; the helper rejects flavor overrides.
- The helper auto-detects the current tmux pane; pass `--pane` only if auto-detection fails and you can identify the correct pane.
- Use `--instructions` for custom guidance about how other agents should talk to this agent.
- Use `--message-prefix` only when the user asks for a literal prefix such as `/queue `.
- Use `--submit-key` only for an explicit override; Codex normally uses the server's Codex default.

## Verify

After registration, run:

```bash
~/.codex/skills/agent-swarm-register/scripts/register-codex-agent --whoami
```

Report the assigned `user` and `pane`. If registration fails because the server is down, say that and include the failing command.
