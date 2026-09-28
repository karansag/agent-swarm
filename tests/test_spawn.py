"""Pure tests for the harness spawn command builder."""

from agent_swarm import tmux


AUTO_CLAUDE = "claude --permission-mode bypassPermissions"
CODEX_STARTUP = "codex -c check_for_update_on_startup=false"
AUTO_CODEX = f"{CODEX_STARTUP} --ask-for-approval never --sandbox workspace-write"


def test_default_autonomy_is_auto():
    assert tmux.spawn_launch_command("claude") == AUTO_CLAUDE
    assert tmux.spawn_launch_command("codex") == AUTO_CODEX
    # pi has no approval gating, so auto needs no extra flags
    assert tmux.spawn_launch_command("pi") == "pi"
    assert tmux.spawn_launch_command("hermes") == "hermes --yolo --accept-hooks"


def test_supervised_keeps_ask_first_behavior():
    assert tmux.spawn_launch_command("claude", autonomy="supervised") == "claude"
    # startup blockers are removed even when supervised: the codex update
    # prompt stalls a fresh pane before the agent is usable at all
    assert tmux.spawn_launch_command("codex", autonomy="supervised") == CODEX_STARTUP
    assert tmux.spawn_launch_command("pi", autonomy="supervised") == "pi"
    assert tmux.spawn_launch_command("hermes", autonomy="supervised") == "hermes"


def test_known_model_appends_harness_flag():
    assert (
        tmux.spawn_launch_command("claude", "opus")
        == "claude --model opus --permission-mode bypassPermissions"
    )
    assert (
        tmux.spawn_launch_command("claude", "opus", autonomy="supervised")
        == "claude --model opus"
    )
    assert (
        tmux.spawn_launch_command("codex", "gpt-5.6-terra")
        == f"{CODEX_STARTUP} --model gpt-5.6-terra --ask-for-approval never --sandbox workspace-write"
    )
    # hermes uses -m rather than --model.
    tmux.HARNESS_SPAWN["hermes"].models.append("_probe")
    try:
        assert (
            tmux.spawn_launch_command("hermes", "_probe", autonomy="supervised")
            == "hermes -m _probe"
        )
    finally:
        tmux.HARNESS_SPAWN["hermes"].models.remove("_probe")


def test_pi_pattern_is_shell_quoted():
    # Leading ~ must be quoted so the shell does not tilde-expand it.
    cmd = tmux.spawn_launch_command("pi", "~anthropic/claude-opus-latest")
    assert cmd == "pi --model '~anthropic/claude-opus-latest'"


def test_unknown_model_falls_back_to_bare_binary():
    assert tmux.spawn_launch_command("claude", "not-a-real-model") == AUTO_CLAUDE
    assert tmux.spawn_launch_command("claude", "") == AUTO_CLAUDE


def test_unspawnable_flavor_returns_none():
    assert tmux.spawn_launch_command("generic") is None
    assert tmux.spawn_launch_command("nonsense") is None


def test_spawn_options_shape():
    opts = {o["flavor"]: o["models"] for o in tmux.spawn_options()}
    assert set(opts) == {"claude", "codex", "pi", "hermes"}
    assert opts["claude"] == ["opus", "sonnet", "haiku"]
    assert opts["codex"] == ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]


def test_local_node_prefers_the_node_override(monkeypatch):
    monkeypatch.setenv("AGENT_SWARM_NODE", "hub")
    assert tmux.local_node() == "hub"
    monkeypatch.delenv("AGENT_SWARM_NODE")
    monkeypatch.setattr(tmux.socket, "gethostname", lambda: "karans-linux.local")
    assert tmux.local_node() == "karans-linux"


def test_codex_spawn_skips_the_shared_daemon_when_codex_supports_it(monkeypatch):
    monkeypatch.setattr(tmux, "harness_accepts", lambda binary, flag: (binary, flag) == ("codex", "--no-daemon"))
    assert tmux.spawn_launch_command("codex").endswith(" --no-daemon")
    assert "--no-daemon" not in tmux.spawn_launch_command("claude")


def test_codex_spawn_leaves_out_flags_an_older_codex_rejects():
    # The autouse fixture reports every optional flag as unsupported.
    assert "--no-daemon" not in tmux.spawn_launch_command("codex")


def test_harness_accepts_probes_the_binary(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        return type("R", (), {"returncode": 0 if cmd[1] == "--new" else 2})()

    monkeypatch.undo()  # drop the autouse stub; test the real probe
    monkeypatch.setattr(tmux.subprocess, "run", fake_run)
    tmux.harness_accepts.cache_clear()
    assert tmux.harness_accepts("fakeharness", "--new") is True
    assert tmux.harness_accepts("fakeharness", "--old") is False
    assert tmux.harness_accepts("fakeharness", "--new") is True  # cached
    assert calls == [["fakeharness", "--new", "--help"], ["fakeharness", "--old", "--help"]]
    tmux.harness_accepts.cache_clear()


def _run_sequence(monkeypatch, outcomes):
    """Fake subprocess.run for tmux.deliver: one outcome per tmux call, in order."""
    import subprocess

    calls = []
    outcomes = iter(outcomes)

    def run(cmd, **kw):
        calls.append(cmd[1])
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tmux.subprocess, "run", run)
    monkeypatch.setattr(tmux.time, "sleep", lambda s: None)
    monkeypatch.setattr(tmux, "_await_submit", lambda pane, timeout: True)
    return calls


def test_deliver_is_failed_only_while_nothing_reached_the_pane(monkeypatch):
    import subprocess

    calls = _run_sequence(monkeypatch, [subprocess.CalledProcessError(1, "tmux", stderr="no server")])
    assert tmux.deliver("%1", "hi") == (False, "no server")
    assert calls == ["load-buffer"]
    calls = _run_sequence(monkeypatch, [None, subprocess.CalledProcessError(1, "tmux", stderr="can't find pane")])
    assert tmux.deliver("%1", "hi") == (False, "can't find pane")
    assert calls == ["load-buffer", "paste-buffer"]


def test_deliver_is_uncertain_once_the_paste_may_have_landed(monkeypatch):
    import subprocess

    import pytest

    _run_sequence(monkeypatch, [None, subprocess.TimeoutExpired("tmux", 5)])
    with pytest.raises(tmux.Uncertain, match="paste did not report back"):
        tmux.deliver("%1", "hi")
    _run_sequence(monkeypatch, [None, None, subprocess.TimeoutExpired("tmux", 5)])
    with pytest.raises(tmux.Uncertain, match="submit key failed"):
        tmux.deliver("%1", "hi")
    calls = _run_sequence(monkeypatch, [None, None, None])
    assert tmux.deliver("%1", "hi") == (True, None)
    assert calls == ["load-buffer", "paste-buffer", "send-keys"]


def test_spawn_window_is_uncertain_when_tmux_does_not_report_back(monkeypatch):
    import subprocess

    import pytest

    outcomes = iter([
        subprocess.CompletedProcess([], 0, "", ""),  # has-session
        subprocess.CompletedProcess([], 0, "%7\n", ""),  # new-window
        subprocess.TimeoutExpired("tmux", 5),  # send-keys
    ])
    monkeypatch.setattr(tmux.subprocess, "run", lambda cmd, **kw: _raise_or(next(outcomes)))
    with pytest.raises(tmux.Uncertain) as info:
        tmux.spawn_window(command="claude")
    assert info.value.pane == "%7"
    outcomes = iter([
        subprocess.CompletedProcess([], 0, "", ""),
        subprocess.CalledProcessError(1, "tmux", stderr="no space"),
    ])
    assert tmux.spawn_window(command="claude") == (None, "no space")


def _raise_or(outcome):
    if isinstance(outcome, Exception):
        raise outcome
    return outcome
