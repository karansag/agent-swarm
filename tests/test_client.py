from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace

import pytest

from agent_swarm import client, tmux


def test_unregister_defaults_to_current_pane(monkeypatch):
    calls = []
    monkeypatch.setattr(client, "current_pane", lambda: "marin:1.2")
    monkeypatch.setattr(client, "registered_user", lambda pane: "marten" if pane == "marin:1.2" else None)
    monkeypatch.setattr(client, "base_url", lambda: "http://localhost:8765")

    def delete(url, timeout):
        calls.append((url, timeout))
        return SimpleNamespace(text='{"ok":true}', is_success=True)

    monkeypatch.setattr(client.httpx, "delete", delete)
    assert client.main(["unregister"]) == 0
    assert calls == [("http://localhost:8765/recipients/marten", 5)]


def test_unregister_explicit_handle_propagates_failure(monkeypatch):
    monkeypatch.setattr(client, "current_pane", lambda: None)
    monkeypatch.setattr(client.httpx, "delete", lambda url, timeout: SimpleNamespace(text="not registered", is_success=False))
    assert client.main(["unregister", "--user", "marten"]) == 1


def test_unregister_without_identity_does_not_delete(monkeypatch, capsys):
    monkeypatch.setattr(client, "current_pane", lambda: None)
    assert client.main(["unregister"]) == 2
    assert "pass --user HANDLE" in capsys.readouterr().err


def test_current_pane_targets_tmux_pane_env(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check, timeout):
        calls.append(cmd)
        return SimpleNamespace(stdout="%177\n")

    monkeypatch.setenv("TMUX_PANE", "%177")
    monkeypatch.setattr(tmux.subprocess, "run", fake_run)

    # The stable pane id, not the positional session:window.pane.
    assert tmux.current_pane() == "%177"
    assert calls == [
        ["tmux", "display-message", "-p", "-t", "%177", "#{pane_id}"]
    ]


def test_current_pane_without_tmux_pane_env_uses_tmux_current_target(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check, timeout):
        calls.append(cmd)
        return SimpleNamespace(stdout="%5\n")

    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(tmux.subprocess, "run", fake_run)

    assert tmux.current_pane() == "%5"
    assert calls == [["tmux", "display-message", "-p", "#{pane_id}"]]


def test_flavor_defaults_cover_pi_and_hermes():
    assert tmux.submit_key_for_flavor("pi") == "Enter"
    assert tmux.submit_key_for_flavor("hermes") == "C-m"
    assert tmux.infer_flavor("pi") == "pi"
    assert tmux.infer_flavor("pi-coding-agent") == "pi"
    assert tmux.infer_flavor("hermes-agent") == "hermes"
    assert tmux.infer_flavor("github-copilot/gpt-5.5") == "generic"


def _paste_calls(pane, text):
    return [
        ["tmux", "load-buffer", "-b", ANY_BUF, "-"],
        ["tmux", "paste-buffer", "-p", "-d", "-b", ANY_BUF, "-t", pane],
    ]


class _AnyBuf(str):
    def __eq__(self, other):
        return isinstance(other, str) and other.startswith("agent-swarm-")


ANY_BUF = _AnyBuf()


def _fake_run(calls):
    def fake_run(cmd, capture_output, text, check, timeout, input=None):
        calls.append(cmd)
        return SimpleNamespace(stdout="")
    return fake_run


def test_deliver_pastes_then_submits_with_configured_key(monkeypatch):
    calls = []
    monkeypatch.setattr(tmux.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(tmux, "_composer_holds_text", lambda pane: False)
    monkeypatch.setattr(tmux.time, "sleep", lambda seconds: None)

    assert tmux.deliver("session-a:9.0", "hello", submit_key="Enter", flavor="pi") == (
        True,
        None,
    )
    assert calls == _paste_calls("session-a:9.0", "hello") + [
        ["tmux", "send-keys", "-t", "session-a:9.0", "Enter"],
    ]


def test_deliver_retries_submit_once_when_composer_still_holds_text(monkeypatch):
    calls = []
    monkeypatch.setattr(tmux.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(tmux, "_composer_holds_text", lambda pane: True)
    clock = _FakeClock()
    monkeypatch.setattr(tmux.time, "sleep", clock.sleep)
    monkeypatch.setattr(tmux.time, "monotonic", clock.monotonic)

    assert tmux.deliver(
        "session-a:9.0", "[agent-msg from manatee] hello", submit_key="Enter"
    ) == (True, None)
    assert calls.count(["tmux", "send-keys", "-t", "session-a:9.0", "Enter"]) == 2


def test_deliver_does_not_retry_after_composer_clears(monkeypatch):
    calls = []
    monkeypatch.setattr(tmux.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(tmux, "_composer_holds_text", lambda pane: False)
    monkeypatch.setattr(tmux.time, "sleep", lambda seconds: None)

    assert tmux.deliver(
        "session-a:9.0", "[agent-msg from manatee] hello", submit_key="Enter"
    ) == (True, None)
    assert calls.count(["tmux", "send-keys", "-t", "session-a:9.0", "Enter"]) == 1


def test_deliver_reports_tmux_failure(monkeypatch):
    def failing_run(cmd, capture_output, text, check, timeout, input=None):
        raise tmux.subprocess.CalledProcessError(1, cmd, stderr="can't find pane")

    monkeypatch.setattr(tmux.subprocess, "run", failing_run)
    assert tmux.deliver("session-a:9.0", "hello") == (False, "can't find pane")


def test_cmd_register_uses_detected_current_pane(monkeypatch, capsys):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return SimpleNamespace(text='{"ok": true}', is_success=True)

    monkeypatch.setattr(client, "current_pane", lambda: "session-a:9.0")
    monkeypatch.setenv("AGENT_SWARM_NODE", "testbox")
    monkeypatch.setattr(client.httpx, "post", fake_post)

    args = Namespace(
        pane=None,
        name=None,
        agent_id=None,
        model=None,
        flavor=None,
        instructions=None,
        message_prefix=None,
        submit_key=None,
    )

    assert client.cmd_register(args) == 0
    # The host travels with every registration; it names the assigned handle.
    assert captured["json"] == {"tmux_pane": "session-a:9.0", "host": "testbox"}
    assert capsys.readouterr().out == '{"ok": true}\n'


def test_cmd_task_update_records_worktree(monkeypatch, capsys):
    captured = {}

    def fake_patch(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return SimpleNamespace(text='{"ok": true}', is_success=True)

    monkeypatch.setattr(client.httpx, "patch", fake_patch)
    args = Namespace(
        id=7,
        status="picked_up",
        assignee=None,
        worktree="/tmp/repo-task-7",
        depends_on=None,
        note=None,
    )

    assert client.cmd_task_update(args) == 0
    assert captured["url"].endswith("/tasks/7")
    assert captured["json"] == {
        "status": "picked_up",
        "worktree": "/tmp/repo-task-7",
    }
    assert capsys.readouterr().out == '{"ok": true}\n'


def test_cmd_task_create_files_task(monkeypatch, capsys):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return SimpleNamespace(text='{"ok": true, "task": {"id": 8}}', is_success=True)

    monkeypatch.setattr(client.httpx, "post", fake_post)
    args = Namespace(
        title="Investigate flaky build",
        description="CI failed twice",
        assignee="stoat",
        depends_on="3,5",
    )

    assert client.cmd_task_create(args) == 0
    assert captured["url"].endswith("/tasks")
    assert captured["json"] == {
        "title": "Investigate flaky build",
        "description": "CI failed twice",
        "assignee": "stoat",
        "depends_on": [3, 5],
    }
    assert capsys.readouterr().out == '{"ok": true, "task": {"id": 8}}\n'


def test_cmd_register_sends_requested_name(monkeypatch, capsys):
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return SimpleNamespace(text='{"ok": true}', is_success=True)

    monkeypatch.setattr(client, "current_pane", lambda: "session-a:9.0")
    monkeypatch.setenv("AGENT_SWARM_NODE", "testbox")
    monkeypatch.setattr(client.httpx, "post", fake_post)

    args = Namespace(
        pane=None,
        name="jax",
        agent_id=None,
        model=None,
        flavor=None,
        instructions=None,
        message_prefix=None,
        submit_key=None,
    )

    assert client.cmd_register(args) == 0
    assert captured["json"] == {
        "tmux_pane": "session-a:9.0",
        "host": "testbox",
        "requested_user": "jax",
    }
    capsys.readouterr()


def test_live_agent_panes_excludes_bare_shells(monkeypatch):
    def fake_run(cmd, capture_output, text, check, timeout):
        return SimpleNamespace(stdout=(
            "%1\ta:0.0\tclaude\tt\n%2\ta:0.1\tbash\tt\n%3\tb:2.0\tnode\tt\n%4\tc:0.0\tzsh\tt\n"
        ))

    monkeypatch.setattr(tmux.subprocess, "run", fake_run)
    assert tmux.live_agent_panes() == {"%1", "%3"}
    assert tmux.pane_table()["%3"] == {"label": "b:2.0", "command": "node", "title": "t"}


def test_offline_reason_distinguishes_gone_from_shell():
    existing, live = {"a:0.0", "a:0.1"}, {"a:0.0"}
    assert tmux.offline_reason("a:0.0", existing, live) is None
    assert "bare shell" in tmux.offline_reason("a:0.1", existing, live)
    assert "no longer exists" in tmux.offline_reason("z:9.9", existing, live)


def test_base_url_accepts_legacy_environment_name(monkeypatch):
    monkeypatch.delenv("AGENT_SWARM_URL", raising=False)
    monkeypatch.setenv("AGENT_MSG_URL", "http://legacy.example:9999")
    assert client.base_url() == "http://legacy.example:9999"


def test_base_url_prefers_new_environment_name(monkeypatch):
    monkeypatch.setenv("AGENT_MSG_URL", "http://legacy.example:9999")
    monkeypatch.setenv("AGENT_SWARM_URL", "http://new.example:8765")
    assert client.base_url() == "http://new.example:8765"


def test_cmd_task_update_forwards_the_closing_note(monkeypatch, capsys):
    captured = {}

    def fake_patch(url, json, timeout):
        captured["json"] = json
        return SimpleNamespace(text='{"ok": true}', is_success=True)

    monkeypatch.setattr(client.httpx, "patch", fake_patch)
    args = Namespace(
        id=42,
        status="done",
        assignee=None,
        worktree=None,
        depends_on=None,
        note="Run the suite; see tests/test_server.py.",
    )

    assert client.cmd_task_update(args) == 0
    assert captured["json"] == {
        "status": "done",
        "note": "Run the suite; see tests/test_server.py.",
    }
    capsys.readouterr()


class _FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self):
        return self.now


def test_deliver_returns_as_soon_as_the_submit_lands(monkeypatch):
    calls = []
    clock = _FakeClock()
    checks = iter([True, True, False])  # the composer clears on the third poll
    monkeypatch.setattr(tmux.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(tmux, "_composer_holds_text", lambda pane: next(checks))
    monkeypatch.setattr(tmux.time, "sleep", clock.sleep)
    monkeypatch.setattr(tmux.time, "monotonic", clock.monotonic)

    assert tmux.deliver("s:0.0", "hello", submit_key="Enter") == (True, None)
    assert calls.count(["tmux", "send-keys", "-t", "s:0.0", "Enter"]) == 1
    # Three polls, not the whole verify window.
    assert clock.now < 0.5 < tmux.SUBMIT_VERIFY_DELAY


def test_deliver_retries_only_after_the_whole_verify_window(monkeypatch):
    calls = []
    clock = _FakeClock()
    monkeypatch.setattr(tmux.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(tmux, "_composer_holds_text", lambda pane: True)
    monkeypatch.setattr(tmux.time, "sleep", clock.sleep)
    monkeypatch.setattr(tmux.time, "monotonic", clock.monotonic)

    tmux.deliver("s:0.0", "hello", submit_key="Enter")
    assert calls.count(["tmux", "send-keys", "-t", "s:0.0", "Enter"]) == 2
    assert clock.now >= tmux.SUBMIT_VERIFY_DELAY


@pytest.mark.parametrize(
    "title, summary",
    [
        ("✳ PR 9130 review", "PR 9130 review"),
        ("⠐ Naming variety", "Naming variety"),
        ("Summarize open pull requests | marin", "Summarize open pull requests"),
        ("✳ Claude Code", None),
        ("agent-swarm: jax (claude)", None),
        ("", None),
    ],
)
def test_title_summary_reads_harness_titles(title, summary):
    assert tmux.title_summary(title) == summary


def test_title_summary_ignores_the_default_host_title():
    assert tmux.title_summary(tmux.socket.gethostname()) is None
