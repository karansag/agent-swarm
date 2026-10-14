"""`agent-swarm autoregister`: registering from a harness startup hook."""

from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from agent_swarm import client, tmux

PANE_SHELL = 100


def _tree(monkeypatch, *chain, pane_pid=PANE_SHELL):
    """This process's ancestry, nearest first, as (pid, command) pairs."""
    monkeypatch.setattr(tmux, "ancestors", lambda pid=None: [(9, "python agent-swarm"), (8, "/bin/sh -c x"), *chain])
    monkeypatch.setattr(tmux, "pane_process", lambda pane: pane_pid)


def test_harness_straight_in_its_pane_shell_is_its_own(monkeypatch):
    _tree(monkeypatch, (7, "claude --model opus"), (PANE_SHELL, "-zsh"), (1, "tmux"))
    assert client.own_pane_harness("%5") == ("claude", "")


def test_npm_codex_with_its_node_launcher_is_its_own(monkeypatch):
    _tree(monkeypatch, (7, "/n/lib/node_modules/@openai/codex/vendor/bin/codex --yolo --no-daemon"),
          (6, "node /n/bin/codex --yolo --no-daemon"), (PANE_SHELL, "bash"))
    assert client.own_pane_harness("%5") == ("codex", "")


def test_harness_launched_as_the_pane_process_is_its_own(monkeypatch):
    _tree(monkeypatch, (PANE_SHELL, "pi"), (1, "tmux"))
    assert client.own_pane_harness("%5") == ("pi", "")


def test_harness_inside_an_editor_is_not(monkeypatch):
    _tree(monkeypatch, (7, "claude"), (6, "/bin/bash"), (5, "emacs -nw"), (PANE_SHELL, "zsh"))
    harness, why = client.own_pane_harness("%5")
    assert harness is None and "emacs" in why


def test_harness_nested_in_another_agent_is_not(monkeypatch):
    # A codex started from a shell command of a codex agent shares its pane.
    _tree(monkeypatch, (7, "/x/codex/bin/codex --yolo"), (6, "/bin/bash -c codex"),
          (5, "/x/codex/bin/codex --yolo"), (PANE_SHELL, "zsh"))
    harness, why = client.own_pane_harness("%5")
    assert harness is None and "inside codex" in why


def test_one_shot_runs_are_not(monkeypatch):
    for command in ("claude -p hello", "claude --print x", "/x/codex/bin/codex exec hi",
                    "node /n/bin/codex exec hi"):
        _tree(monkeypatch, (7, command), (PANE_SHELL, "zsh"))
        harness, why = client.own_pane_harness("%5")
        assert harness is None and "one-shot" in why, command


def test_harness_outside_this_pane_is_not(monkeypatch):
    # A stale TMUX_PANE inherited from elsewhere: the pane's shell is no ancestor.
    _tree(monkeypatch, (7, "claude"), (6, "zsh"), (1, "systemd"), pane_pid=4242)
    assert client.own_pane_harness("%5")[0] is None


def _hub(monkeypatch, brief="You are registered as 'otter'.\nCurrently registered peers:\n  - a (x)\n  - b (y)\nPeers tagged OFFLINE are ...\nEnd."):
    posts = []

    def post(url, json, headers, timeout):
        posts.append(json)
        return SimpleNamespace(is_success=True, status_code=200, text="", json=lambda: {"protocol_brief": brief})

    monkeypatch.setattr(client.httpx, "post", post)
    monkeypatch.setattr(client, "local_node", lambda: "laptop")
    return posts


def _run(monkeypatch, capsys, hook: dict | None):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(hook) if hook is not None else ""))
    args = ["autoregister", "--verbose"] + (["--hook"] if hook is not None else [])
    assert client.main(args) == 0
    return capsys.readouterr()


def test_hook_registers_with_the_hooks_session_and_model(monkeypatch, capsys):
    # The env holds an outer session's id; the hook input names the new one.
    monkeypatch.setenv("TMUX_PANE", "%5")
    monkeypatch.setenv("CODEX_THREAD_ID", "outer-thread")
    _tree(monkeypatch, (7, "/x/codex/bin/codex"), (PANE_SHELL, "zsh"))
    posts = _hub(monkeypatch)
    out = _run(monkeypatch, capsys, {"session_id": "new-thread", "model": "gpt-6-sol"})
    assert posts == [{"tmux_pane": "%5", "node": "laptop", "flavor": "codex",
                      "agent_id": "new-thread", "model": "gpt-6-sol"}]
    context = json.loads(out.out)["hookSpecificOutput"]["additionalContext"]
    # The roster stays out of every session's context.
    assert "  - a" not in context and "(2 registered;" in context and "OFFLINE" not in context


def test_env_session_of_another_harness_is_not_used(monkeypatch, capsys):
    monkeypatch.setenv("TMUX_PANE", "%5")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "the-claude-that-made-the-pane")
    monkeypatch.setenv("PI_MODEL", "m-1")
    _tree(monkeypatch, (PANE_SHELL, "pi"))
    posts = _hub(monkeypatch)
    _run(monkeypatch, capsys, None)
    assert posts[0]["flavor"] == "pi" and "agent_id" not in posts[0] and posts[0]["model"] == "m-1"


def test_skips_quietly_outside_tmux_or_when_turned_off(monkeypatch, capsys):
    posts = _hub(monkeypatch)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    assert "not inside tmux" in _run(monkeypatch, capsys, {}).err
    monkeypatch.setenv("TMUX_PANE", "%5")
    monkeypatch.setenv("AGENT_SWARM_AUTOREGISTER", "0")
    assert "AGENT_SWARM_AUTOREGISTER=0" in _run(monkeypatch, capsys, {}).err
    assert posts == []


def test_hub_down_never_fails_the_harness(monkeypatch, capsys):
    monkeypatch.setenv("TMUX_PANE", "%5")
    _tree(monkeypatch, (7, "claude"), (PANE_SHELL, "zsh"))

    def post(*a, **k):
        raise client.httpx.ConnectError("refused")

    monkeypatch.setattr(client.httpx, "post", post)
    out = _run(monkeypatch, capsys, {"session_id": "s"})
    assert out.out == "" and "hub unreachable" in out.err


INSTALL = Path(__file__).parents[1] / "hooks/install"


def _install(home: Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("CODEX_HOME", "PI_CODING_AGENT_DIR")}
    subprocess.run([str(INSTALL), *args], check=True, capture_output=True, env=env | {"HOME": str(home)})


def test_install_adds_each_hook_once_and_remove_undoes_it(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"model": "opus", "hooks": {"Stop": [{"hooks": [{"command": "x"}]}]}}))
    _install(tmp_path)
    _install(tmp_path)
    claude = json.loads(settings.read_text())
    assert claude["model"] == "opus" and claude["hooks"]["Stop"]
    assert [h["command"] for g in claude["hooks"]["SessionStart"] for h in g["hooks"]] == [
        "agent-swarm autoregister --hook"]
    codex = json.loads((tmp_path / ".codex/hooks.json").read_text())
    assert len(codex["hooks"]["SessionStart"]) == 1
    ext = tmp_path / ".pi/agent/extensions/agent-swarm"
    assert ext.is_symlink() and (ext / "index.ts").exists()
    assert list(tmp_path.glob(".claude/settings.json.bak-*"))
    _install(tmp_path, "--remove")
    assert json.loads(settings.read_text()) == {"model": "opus", "hooks": {"Stop": [{"hooks": [{"command": "x"}]}]}}
    assert not ext.exists() and not ext.is_symlink()
