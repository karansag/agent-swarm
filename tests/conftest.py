"""Fixtures every test gets: no real settings or hub, and spawn commands
that don't depend on which harness versions this machine has installed."""

import pytest

from agent_swarm import tmux


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_SWARM_CONFIG", str(tmp_path / "no-such-node.toml"))
    # The harness session ids too: tests run inside Claude Code or Codex.
    for var in ("AGENT_SWARM_URL", "AGENT_MSG_URL", "AGENT_SWARM_TOKEN", "AGENT_SWARM_NODE",
                "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID",
                "CLAUDE_MODEL", "ANTHROPIC_MODEL", "CODEX_MODEL", "PI_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex-home"))
    # And the process tree: `register` reads its harness from the ancestry.
    monkeypatch.setattr(tmux, "ancestors", lambda pid=None: [])


@pytest.fixture(autouse=True)
def _no_optional_harness_flags(monkeypatch):
    """Tests that care about optional harness flags opt in by patching harness_accepts."""
    monkeypatch.setattr(tmux, "harness_accepts", lambda binary, flag: False)
