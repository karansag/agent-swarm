import pytest

from agent_swarm import tmux


@pytest.fixture(autouse=True)
def _no_optional_harness_flags(monkeypatch):
    """Spawn commands must not depend on which harness versions this machine
    has installed; tests that care opt in by patching harness_accepts."""
    monkeypatch.setattr(tmux, "harness_accepts", lambda binary, flag: False)
"""Keep tests away from this machine's real settings and hub."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_SWARM_CONFIG", str(tmp_path / "no-such-node.toml"))
    for var in ("AGENT_SWARM_URL", "AGENT_MSG_URL", "AGENT_SWARM_TOKEN", "AGENT_SWARM_NODE"):
        monkeypatch.delenv(var, raising=False)
