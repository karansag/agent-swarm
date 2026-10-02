"""Callers are identified by their harness session id when they send one.

Claude Code and Codex can run a session's tools in a background host whose
TMUX_PANE is missing or names another agent's pane, so the pane alone can't
say who is calling. These tests pin how /send, /status and /whoami resolve a
caller, and that an unknown or foreign session id never falls back to the
agent that happens to hold the named pane."""

from tests.test_auth import enrol, hub, owner, remote  # noqa: F401  (fixtures/helpers)
from tests.test_server import client  # noqa: F401  (reuse the app fixture)


def register(client, pane, name, agent_id=None):
    body = {"tmux_pane": pane, "requested_user": name}
    if agent_id:
        body["agent_id"] = agent_id
    r = client.post("/register", json=body)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


def whoami(client, **params):
    return client.get("/whoami", params=params).json()


def send(client, **body):
    return client.post("/send", json={"recipient": "owner", "content": "hi", **body})


def test_a_known_session_is_the_caller_whatever_pane_it_names(client):
    # explainer's case: its commands ran in a background host and guessed
    # tmux's active pane, which was numbat's.
    register(client, "0:0.0", "numbat", agent_id="sess-numbat")
    register(client, "0:1.0", "explainer", agent_id="sess-explainer")
    answer = whoami(client, tmux_pane="0:0.0", agent_id="sess-explainer", pane_verified="false")
    assert answer["user_id"] == "explainer" and answer["identified_by"] == "session"
    r = send(client, tmux_pane="0:0.0", agent_id="sess-explainer", pane_verified=False)
    assert r.status_code == 200
    last = client.get("/api/state").json()["messages"][-1]
    assert last["sender"] == "explainer"


def test_a_session_can_send_with_no_pane_at_all(client):
    register(client, "0:1.0", "explainer", agent_id="sess-explainer")
    assert send(client, agent_id="sess-explainer").status_code == 200
    r = client.post("/status", json={"agent_id": "sess-explainer", "text": "working on it"})
    assert r.status_code == 200 and r.json()["user_id"] == "explainer"


def test_an_unknown_session_never_borrows_an_unverified_pane(client):
    # A daemon-hosted Codex session naming mongoose's pane must not become mongoose.
    register(client, "0:0.0", "mongoose")  # registered before session ids existed
    r = send(client, tmux_pane="0:0.0", agent_id="sess-stranger", pane_verified=False)
    assert r.status_code == 404
    assert "not verified" in r.json()["detail"]["detail"]
    assert whoami(client, tmux_pane="0:0.0", agent_id="sess-stranger")["user_id"] is None


def test_a_verified_pane_adopts_the_session_onto_a_registration_without_one(client):
    # Agents registered before the CLI sent session ids get theirs on first contact.
    register(client, "0:0.0", "mongoose")
    r = send(client, tmux_pane="0:0.0", agent_id="sess-mongoose", pane_verified=True)
    assert r.status_code == 200
    # From now on the session alone identifies it, even from a background host.
    assert whoami(client, agent_id="sess-mongoose")["user_id"] == "mongoose"


def test_a_pane_held_by_a_different_session_is_refused(client):
    register(client, "0:0.0", "mongoose", agent_id="sess-mongoose")
    r = send(client, tmux_pane="0:0.0", agent_id="sess-other", pane_verified=True)
    assert r.status_code == 404
    assert "different session" in r.json()["detail"]["detail"]


def test_without_a_session_id_the_pane_is_the_identity_as_before(client):
    # Older CLIs send no agent_id.
    register(client, "0:0.0", "otter")
    assert whoami(client, tmux_pane="0:0.0")["user_id"] == "otter"
    assert send(client, tmux_pane="0:0.0").status_code == 200


def test_a_node_cannot_speak_as_another_nodes_session(hub):
    # Session ids are public; knowing one must not let a node act as that agent.
    register(owner(hub), "%1", "otter", agent_id="hub-session")
    token = enrol(hub, "macbook")
    node = remote(hub, token)
    r = node.post("/send", json={"node": "macbook", "agent_id": "hub-session",
                                 "recipient": "owner", "content": "x"})
    assert r.status_code == 404
    assert "another node" in r.json()["detail"]["detail"]
    answer = node.get("/whoami", params={"node": "macbook", "agent_id": "hub-session"}).json()
    assert answer["user_id"] is None


def test_a_node_resolves_its_own_sessions(hub):
    token = enrol(hub, "macbook")
    node = remote(hub, token)
    r = node.post("/register", json={"tmux_pane": "%1", "node": "macbook",
                                      "agent_id": "mac-session", "requested_user": "puffin"})
    assert r.status_code == 200, r.text
    answer = node.get("/whoami", params={"node": "macbook", "agent_id": "mac-session"}).json()
    assert answer["user_id"] == "puffin" and answer["identified_by"] == "session"
