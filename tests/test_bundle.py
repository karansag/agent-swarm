"""Carrying another hub's agents, teams, and tasks over: what the plan
decides, what the export reads, and what the import writes."""

import json
import random
import time

import pytest
from fastapi.testclient import TestClient

from agent_swarm import bundle, db, nodes, server, tmux


def make(**over) -> dict:
    """A small, valid bundle. Override any part of it."""
    data = {
        "agent_swarm_bundle": bundle.FORMAT,
        "exported_at": time.time(),
        "source": {"id": "source-hub-1"},
        "agents": [
            {"user_id": "otter", "agent_id": "conv-otter", "flavor": "claude",
             "model": "claude-code", "instructions": "keep it short", "team": "shipping"},
            {"user_id": "tapir", "agent_id": None, "flavor": "codex", "team": None},
        ],
        "teams": [{"name": "shipping", "queen": "otter", "members": ["otter"]}],
        "tasks": [
            {"id": 1, "title": "first", "status": "done", "assignee": "otter",
             "note": "run the suite", "depends_on": []},
            {"id": 2, "title": "second", "status": "open", "assignee": "tapir",
             "worktree": "/Users/k/repo-2", "depends_on": [1]},
        ],
        "messages": [],
    }
    data.update(over)
    return data


HUB = {"handles": set(), "agents_by_id": {}, "team_names": {}, "nodes": {"hub", "laptop"}}


def hub(**over) -> dict:
    out = {k: (set(v) if isinstance(v, set) else dict(v)) for k, v in HUB.items()}
    out.update(over)
    return out


def test_free_handles_are_kept_and_clashes_renamed():
    plan = bundle.plan(make(), "laptop", hub(handles={"otter"}), rng=random.Random(0))
    assert plan["renamed"].keys() == {"otter"}
    new = plan["renamed"]["otter"]
    assert new != "otter"
    assert {a["user_id"] for a in plan["agents"]} == {new, "tapir"}
    # Every reference follows the rename.
    assert plan["teams"][0]["queen"] == new
    assert plan["teams"][0]["members"] == [new]
    assert [t["assignee"] for t in plan["tasks"]] == [new, "tapir"]
    assert all(a["node"] == "laptop" for a in plan["agents"])


def test_an_agent_already_here_keeps_its_row_and_its_machine():
    state = hub(handles={"ferret"}, agents_by_id={"conv-otter": {"user_id": "ferret", "node": "hub"}})
    plan = bundle.plan(make(), "laptop", state)
    # Nothing is created for it, and references point at the row it has.
    assert [a["user_id"] for a in plan["agents"]] == ["tapir"]
    assert plan["merged"] == [{"from": "otter", "to": "ferret", "node": "hub"}]
    assert plan["tasks"][0]["assignee"] == "ferret"
    assert any("keeps that handle and machine" in w for w in plan["warnings"])
    # It is not moved onto the imported team either.
    assert plan["teams"][0]["members"] == []
    assert plan["teams"][0]["queen"] is None
    assert any("left on whatever team" in w for w in plan["warnings"])


def test_agents_that_never_reported_an_id_are_not_the_same_agent():
    data = make(agents=[
        {"user_id": "otter", "agent_id": None, "flavor": "claude", "team": None},
        {"user_id": "tapir", "agent_id": "", "flavor": "codex", "team": None},
    ], teams=[], tasks=[])
    state = hub(agents_by_id={"": {"user_id": "gecko", "node": "hub"}})
    plan = bundle.plan(data, "laptop", state)
    assert {a["user_id"] for a in plan["agents"]} == {"otter", "tapir"}
    assert plan["merged"] == []


def test_a_name_that_merely_matches_an_agent_here_is_not_borrowed():
    # "puffin" is a stranger on this hub; the bundle's task must not land on it.
    data = make(tasks=[{"id": 1, "title": "stray", "status": "open", "assignee": "puffin", "depends_on": []}])
    plan = bundle.plan(data, "laptop", hub(handles={"puffin"}))
    assert plan["tasks"][0]["assignee"] is None
    assert any("unrelated 'puffin'" in w for w in plan["warnings"])


def test_a_clashing_team_is_imported_under_its_own_name():
    plan = bundle.plan(make(), "laptop", hub(team_names={"shipping": 3}))
    team = plan["teams"][0]
    assert team["name"] == "shipping (laptop)" and team["existing_id"] is None
    assert plan["agents"][0]["team"] == "shipping (laptop)"
    assert any("already here" in w for w in plan["warnings"])


def test_teams_are_merged_only_when_asked():
    plan = bundle.plan(make(), "laptop", hub(team_names={"shipping": 3}, merge_teams=True))
    assert plan["teams"][0]["name"] == "shipping" and plan["teams"][0]["existing_id"] == 3


def test_a_queen_who_is_not_a_member_is_dropped():
    data = make(teams=[{"name": "shipping", "queen": "tapir", "members": ["otter"]}])
    plan = bundle.plan(data, "laptop", hub())
    assert plan["teams"][0]["queen"] is None
    assert any("not one of its members" in w for w in plan["warnings"])


def test_dependencies_that_did_not_come_across_are_reported_not_dropped_quietly():
    data = make(tasks=[{"id": 2, "title": "second", "status": "open", "depends_on": [1, 9]}])
    plan = bundle.plan(data, "laptop", hub())
    assert plan["tasks"][0]["depends_on"] == []
    assert any("#1, #9" in w for w in plan["warnings"])


def test_a_bundle_that_is_malformed_or_circular_is_refused():
    with pytest.raises(bundle.Invalid, match="format"):
        bundle.plan({"agent_swarm_bundle": 99}, "laptop", hub())
    with pytest.raises(bundle.Invalid, match="where it came from"):
        bundle.plan(make(source={}), "laptop", hub())
    with pytest.raises(bundle.Invalid, match="twice"):
        bundle.plan(make(agents=[{"user_id": "otter"}, {"user_id": "otter"}]), "laptop", hub())
    with pytest.raises(bundle.Invalid, match="twice"):
        bundle.plan(make(tasks=[{"id": 1, "title": "a"}, {"id": 1, "title": "b"}]), "laptop", hub())
    cyclic = make(tasks=[{"id": 1, "title": "a", "depends_on": [2]},
                         {"id": 2, "title": "b", "depends_on": [1]}])
    with pytest.raises(bundle.Invalid, match="cycle"):
        bundle.plan(cyclic, "laptop", hub())


def test_a_worktree_keeps_the_machine_it_is_on():
    data = make(tasks=[
        {"id": 1, "title": "here", "worktree": "/Users/k/a", "depends_on": []},
        {"id": 2, "title": "elsewhere", "worktree": "/home/k/b", "worktree_node": "hub", "depends_on": []},
        {"id": 3, "title": "gone", "worktree": "/x", "worktree_node": "retired-box", "depends_on": []},
        {"id": 4, "title": "none", "depends_on": []},
    ])
    plan = bundle.plan(data, "laptop", hub())
    assert [t["worktree_node"] for t in plan["tasks"]] == ["laptop", "hub", "retired-box", None]
    assert any("retired-box" in w for w in plan["warnings"])


def test_messages_arrive_as_marked_history():
    data = make(messages=[
        {"sender": "owner", "recipient": "otter", "context": "task #7", "content": "do it",
         "ts": 1.0, "status": "delivered", "attachments": 2},
        {"sender": "otter", "recipient": "owner", "content": "done", "ts": 2.0, "status": "pending"},
        {"sender": "stranger", "recipient": "otter", "content": "?", "ts": 3.0, "status": "delivered"},
    ])
    plan = bundle.plan(data, "laptop", hub())
    assert len(plan["messages"]) == 2  # the one from a stranger did not come across
    first, second = plan["messages"]
    assert first["context"] == "task #7 · imported"
    assert "2 attachment(s) not migrated" in first["content"]
    assert second["context"].startswith("imported from")
    # Nothing imported is in flight, so nothing reads as waiting to be sent.
    assert second["status"] == "unknown"
    assert {m["status"] for m in plan["messages"]} <= {"delivered", "failed", "unknown"}


def test_export_reads_an_older_database_without_writing_to_it(tmp_path):
    path = tmp_path / "old.sqlite"
    conn = db.connect(path)
    team = db.create_team(conn, "shipping")
    db.register(conn, "otter", "%1", agent_id="conv-otter", model="claude-code",
                flavor="claude", node="mac")
    db.set_agent_team(conn, "otter", team["id"])
    db.update_team(conn, team["id"], queen="otter")
    first = db.create_task(conn, "first", "details", "otter")
    second = db.create_task(conn, "second")
    db.set_task_deps(conn, second["id"], [first["id"]])
    db.update_task(conn, second["id"], worktree="/Users/k/repo", worktree_node="mac")
    db.record_message(conn, "owner", "otter", None, "hello", "delivered")
    # An agent-swarm from before nodes, reservations, and message statuses.
    for drop in ("node", "reserved"):
        conn.execute(f"ALTER TABLE recipients DROP COLUMN {drop}")
    conn.execute("ALTER TABLE tasks DROP COLUMN worktree_node")
    conn.execute("ALTER TABLE messages DROP COLUMN status")
    conn.execute("DROP TABLE meta")
    conn.commit()
    conn.close()

    before = path.stat().st_mtime_ns
    data = bundle.read(bundle.open_readonly(path), with_messages=True)
    assert path.stat().st_mtime_ns == before  # the source is left as it was
    assert [a["user_id"] for a in data["agents"]] == ["otter"]
    assert data["agents"][0]["team"] == "shipping" and "node" not in data["agents"][0]
    assert data["teams"] == [{"name": "shipping", "queen": "otter", "members": ["otter"]}]
    assert [t["title"] for t in data["tasks"]] == ["first", "second"]
    assert data["tasks"][1]["depends_on"] == [first["id"]]
    assert "worktree_node" not in data["tasks"][1]
    assert [m["content"] for m in data["messages"]] == ["hello"]
    # No hub id to borrow, so the export identifies itself.
    assert data["source"]["id"]
    assert bundle.plan(data, "mac", hub())["agents"][0]["user_id"] == "otter"


@pytest.fixture()
def live(tmp_path, monkeypatch):
    monkeypatch.setattr(tmux, "server_id", lambda: "srv-1")
    monkeypatch.setattr(tmux, "resolve_pane", lambda t: (t, t))
    monkeypatch.setattr(
        tmux, "pane_table",
        lambda: {"%1": {"label": "a:0.0", "command": "claude", "title": ""},
                 "%2": {"label": "a:0.1", "command": "codex", "title": ""}},
    )
    monkeypatch.setattr(tmux, "deliver", lambda *a, **k: (True, None))
    monkeypatch.setattr(tmux, "tag_pane", lambda *a: (True, None))
    app = server.create_app(tmp_path / "db.sqlite", monitor=False)
    owner = TestClient(app, client=("127.0.0.1", 40000))
    token = owner.post("/nodes/macbook/token").json()["token"]
    return app, owner, token


def test_a_bundle_becomes_reservations_teams_and_tasks(live):
    app, owner, _ = live
    r = owner.post("/import", json={"node": "macbook", "bundle": make()})
    assert r.status_code == 200
    report = r.json()["report"]
    assert (report["agents"], report["teams"], report["tasks"]) == (2, 1, 2)
    assert r.json()["register"] == [
        "agent-swarm register --name otter --flavor claude",
        "agent-swarm register --name tapir --flavor codex",
    ]
    rows = {x["user_id"]: x for x in owner.get("/recipients").json()["recipients"]}
    assert set(rows) == {"otter", "tapir"}
    assert rows["otter"]["node"] == "macbook"
    assert rows["otter"]["alive"] is False
    assert "has not registered here yet" in rows["otter"]["offline_reason"]
    assert rows["otter"]["instructions"] == "keep it short"
    tasks = {t["title"]: t for t in owner.get("/tasks").json()["tasks"]}
    assert tasks["first"]["status"] == "done" and tasks["first"]["assignee"] == "otter"
    assert tasks["second"]["worktree_node"] == "macbook"
    assert tasks["second"]["depends_on"] == [tasks["first"]["id"]]
    teams = owner.get("/teams").json()["teams"]
    assert teams[0]["name"] == "shipping" and teams[0]["queen"] == "otter"
    # A reservation is not swept away by prune.
    assert owner.post("/recipients/prune", json={"include_shells": True}).json()["removed"] == []


def test_a_dry_run_decides_but_writes_nothing(live):
    app, owner, _ = live
    r = owner.post("/import", json={"node": "macbook", "bundle": make(), "dry_run": True})
    assert r.status_code == 200 and r.json()["dry_run"] is True
    assert r.json()["report"]["agents"] == 2
    assert owner.get("/recipients").json()["recipients"] == []
    assert owner.get("/tasks").json()["tasks"] == []
    # And it can then be imported for real.
    assert owner.post("/import", json={"node": "macbook", "bundle": make()}).status_code == 200


def test_the_same_export_is_not_taken_in_twice(live):
    app, owner, _ = live
    assert owner.post("/import", json={"node": "macbook", "bundle": make()}).status_code == 200
    again = owner.post("/import", json={"node": "macbook", "bundle": make()})
    assert again.status_code == 409
    assert again.json()["detail"]["report"]["tasks"] == 2
    assert len(owner.get("/tasks").json()["tasks"]) == 2
    # Only on purpose does it happen twice.
    assert owner.post("/import", json={"node": "macbook", "bundle": make(), "again": True}).status_code == 200
    assert len(owner.get("/tasks").json()["tasks"]) == 4


def connect(app, name="macbook"):
    """That machine's daemon, connected: a pane there can be resolved."""
    app.state.nodes.add(nodes.LocalNode(name))


def test_a_reserved_handle_is_claimed_by_registering(live):
    app, owner, token = live
    owner.post("/import", json={"node": "macbook", "bundle": make()})
    connect(app)
    node = TestClient(app, client=("100.64.0.9", 1), headers={"Authorization": f"Bearer {token}"})
    r = node.post("/register", json={"tmux_pane": "%1", "node": "macbook",
                                     "agent_id": "conv-otter", "model": "claude-opus-5"})
    assert r.status_code == 200 and r.json()["user_id"] == "otter"
    row = next(x for x in owner.get("/recipients").json()["recipients"] if x["user_id"] == "otter")
    assert row["alive"] is True and row["tmux_pane"] == "%1"
    assert row["instructions"] == "keep it short"  # what it came with is still there
    tasks = {t["title"]: t for t in owner.get("/tasks").json()["tasks"]}
    assert tasks["first"]["assignee"] == "otter"  # and its history followed it
    # An agent that cannot report an id asks for the handle by name, from
    # its own pane.
    r = node.post("/register", json={"tmux_pane": "%2", "node": "macbook", "requested_user": "tapir"})
    assert r.status_code == 200 and r.json()["user_id"] == "tapir"


def test_a_different_agent_cannot_take_a_reserved_handle(live):
    app, owner, token = live
    owner.post("/import", json={"node": "macbook", "bundle": make()})
    connect(app)
    node = TestClient(app, client=("100.64.0.9", 1), headers={"Authorization": f"Bearer {token}"})
    r = node.post("/register", json={"tmux_pane": "%1", "node": "macbook",
                                     "agent_id": "someone-else", "requested_user": "otter"})
    assert r.status_code == 409 and "reserved for another agent" in r.json()["detail"]["error"]


def test_importing_is_the_owners_and_needs_a_machine_this_hub_knows(live):
    app, owner, token = live
    r = owner.post("/import", json={"node": "nowhere", "bundle": make()})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "unknown node"
    assert owner.post("/import", json={"node": tmux.local_node(), "bundle": make()}).status_code == 200
    node = TestClient(app, client=("100.64.0.9", 1), headers={"Authorization": f"Bearer {token}"})
    assert node.post("/import", json={"node": "macbook", "bundle": make()}).status_code == 403
    bad = owner.post("/import", json={"node": "macbook", "bundle": {"agent_swarm_bundle": 99}})
    assert bad.status_code == 400


def test_a_failed_import_writes_nothing(live, monkeypatch):
    app, owner, _ = live
    # A bundle whose last task is unusable: the agents and teams before it
    # must not be left behind.
    broken = make()
    broken["tasks"] = broken["tasks"] + [{"id": 3, "title": "   "}]
    r = owner.post("/import", json={"node": "macbook", "bundle": broken})
    assert r.status_code == 400
    assert owner.get("/recipients").json()["recipients"] == []
    assert owner.get("/teams").json()["teams"] == []
    assert owner.get("/tasks").json()["tasks"] == []
    assert json.loads(json.dumps(owner.get("/api/state").json()))["recipients"] == []
