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


def test_model_line_prefers_named_lines_over_family():
    # "opus" beats the redundant "claude" family name.
    assert tmux.model_line("claude-opus-4-7") == "opus"
    assert tmux.model_line("claude-sonnet-5") == "sonnet"
    assert tmux.model_line("claude-3-5-haiku-20241022") == "haiku"
    assert tmux.model_line("claude-fable-5-1") == "fable"


def test_model_line_recognizes_codex_model_codenames():
    assert tmux.model_line("gpt-5.6-sol") == "sol"
    assert tmux.model_line("gpt-5.6-terra") == "terra"
    assert tmux.model_line("gpt-5.6-luna") == "luna"


def test_model_line_keeps_major_version_for_unnamed_lines():
    # Version stays so a later generation is a different tag.
    assert tmux.model_line("gpt-5-codex") == "gpt5"
    assert tmux.model_line("gpt-6-codex") == "gpt6"
    assert tmux.model_line("claude-code") == "claude"
    assert tmux.model_line("totally-made-up") == "totally"


def test_model_line_handles_missing_model():
    assert tmux.model_line(None) is None
    assert tmux.model_line("") is None


def test_handle_tag_leads_with_harness_then_model_line():
    assert tmux.handle_tag("claude", "claude-opus-4-7") == "claude-opus"
    assert tmux.handle_tag("codex", "gpt-5.6-terra") == "codex-terra"
    assert tmux.handle_tag("codex", "gpt-5-codex") == "codex-gpt5"


def test_handle_tag_drops_a_model_line_that_only_repeats_the_harness():
    # "claude-code" tells us nothing "claude" did not already say.
    assert tmux.handle_tag("claude", "claude-code") == "claude"
    assert tmux.handle_tag("hermes", "hermes-2") == "hermes"


def test_handle_tag_falls_back_to_whichever_half_is_known():
    assert tmux.handle_tag("generic", None) == "generic"
    assert tmux.handle_tag(None, "claude-opus-4-7") == "opus"
    assert tmux.handle_tag(None, None) is None


def test_handle_tag_trails_the_host_when_one_is_reported():
    assert (
        tmux.handle_tag("claude", "claude-opus-4-7", "karans-linux")
        == "claude-opus-karanslinux"
    )
    assert tmux.handle_tag("codex", "gpt-5-codex", "karans-linux") == "codex-gpt5-karanslinux"
    # No host reported: the handle is exactly what it was before.
    assert tmux.handle_tag("claude", "claude-code") == "claude"
    assert tmux.handle_tag(None, None, "karans-linux") == "karanslinux"


def test_host_tag_keeps_handles_parseable():
    # Only the first DNS label, and no hyphens of its own: the handle already
    # uses hyphens to separate animal, harness, model and host.
    assert tmux.host_tag("karans-linux.local") == "karanslinux"
    assert tmux.host_tag("Karans-MacBook-Pro") == "karansmacboo"  # capped at 12
    assert tmux.host_tag("  box01  ") == "box01"
    assert tmux.host_tag(None) is None
    assert tmux.host_tag("---") is None


def test_local_host_prefers_the_node_override(monkeypatch):
    monkeypatch.setenv("AGENT_SWARM_NODE", "hub")
    assert tmux.local_host() == "hub"
    monkeypatch.delenv("AGENT_SWARM_NODE")
    monkeypatch.setattr(tmux.socket, "gethostname", lambda: "karans-linux.local")
    assert tmux.local_host() == "karans-linux"
