import pytest

from agent_swarm import tmux


@pytest.fixture(autouse=True)
def _no_optional_harness_flags(monkeypatch):
    """Spawn commands must not depend on which harness versions this machine
    has installed; tests that care opt in by patching harness_accepts."""
    monkeypatch.setattr(tmux, "harness_accepts", lambda binary, flag: False)
