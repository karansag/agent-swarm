"""The Node interface: LocalNode delegates to tmux; the registry finds nodes."""

from agent_swarm import nodes, tmux


def test_local_node_snapshot_reads_tmux_at_call_time(monkeypatch):
    node = nodes.LocalNode("here")
    monkeypatch.setattr(tmux, "server_id", lambda: "srv-9")
    monkeypatch.setattr(tmux, "server_start_time", lambda: 42.0)
    monkeypatch.setattr(tmux, "list_panes", lambda: {"%1", "%2"})
    monkeypatch.setattr(tmux, "live_agent_panes", lambda: {"%1"})
    monkeypatch.setattr(
        tmux, "pane_table",
        lambda: {"%1": {"label": "a:0.0", "command": "claude", "title": "✳ topic"}},
    )
    snap = node.snapshot()
    assert snap.server == "srv-9"
    assert snap.server_start == 42.0
    assert snap.existing == {"%1", "%2"}
    assert snap.live == {"%1"}
    assert snap.label("%1") == "a:0.0"
    assert snap.title("%1") == "✳ topic"
    assert snap.label("%2") is None
    assert node.server_id() == "srv-9"


def test_local_node_delivers_through_tmux(monkeypatch):
    calls = []
    monkeypatch.setattr(
        tmux, "deliver",
        lambda pane, text, message_prefix=None, submit_key="C-m", flavor=None: (
            calls.append((pane, text, message_prefix, submit_key, flavor)) or (True, None)
        ),
    )
    ok, err = nodes.LocalNode("here").deliver(
        "%3", "hello", message_prefix="/queue ", submit_key="Enter", flavor="codex"
    )
    assert (ok, err) == (True, None)
    assert calls == [("%3", "hello", "/queue ", "Enter", "codex")]


def test_registry_always_keeps_the_local_node():
    local = nodes.LocalNode("hub")
    fleet = nodes.NodeRegistry(local)
    assert fleet.get(None) is local
    assert fleet.get("hub") is local
    assert fleet.get("laptop") is None
    other = nodes.LocalNode("laptop")
    fleet.add(other)
    assert fleet.get("laptop") is other
    assert fleet.names() == ["hub", "laptop"]
    fleet.remove("laptop")
    fleet.remove("hub")
    assert fleet.names() == ["hub"]
