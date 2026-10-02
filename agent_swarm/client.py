"""Tiny CLI client. Usage:

    agent-swarm register [--pane Y] [--name HANDLE] [--flavor NAME] [--instructions TXT]
                         [--message-prefix TXT]
    agent-swarm send --to Y [--context CTX] --message MSG
    agent-swarm messages [--user X] [--limit N]
    agent-swarm recipients
    agent-swarm whoami       # prints detected tmux pane + registered handle
    agent-swarm status "working on X"   # what you are doing, shown on the dashboard
    agent-swarm tasks [--status open|picked_up|done]
    agent-swarm task-create TITLE [--description TEXT] [--assignee HANDLE] [--depends-on 3,5]
    agent-swarm task-update ID --status open|picked_up|done [--assignee X] [--worktree PATH]
                            [--depends-on 3,5] [--note TEXT]   # --note required to close

Defaults:
    --pane            current shell's tmux pane (via `TMUX_PANE`-targeted `tmux display-message`)
    server URL        $AGENT_SWARM_URL (else http://127.0.0.1:8765)
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from urllib.parse import quote, urlparse

import httpx

from pathlib import Path

from . import bundle, config, tmux
from .tmux import current_pane, local_node


def base_url() -> str:
    return config.load().hub


def _headers() -> dict[str, str]:
    """The bearer token for this machine, when it has one.

    A hub on the tailnet requires one from every non-loopback caller; a
    single-machine install has none and needs none.
    """
    token = config.load().token
    return {"Authorization": f"Bearer {token}"} if token else {}


# Each harness tells its commands which session they belong to. That is the
# caller's identity wherever the command runs: Claude Code and Codex can run a
# session's tools in a background host whose TMUX_PANE is missing or names
# another agent's pane, so the pane alone can't say who is calling.
SESSION_ENV = (
    ("claude", "CLAUDE_CODE_SESSION_ID"),
    ("codex", "CODEX_THREAD_ID"),
    ("codex", "CODEX_SESSION_ID"),
)


def harness_session_id() -> str | None:
    """The calling harness's session id, or None outside a harness.

    When ids from both harnesses are set (one launched the other), the nearer
    harness in this process's ancestry is the caller.
    """
    found: dict[str, str] = {}
    for harness, var in SESSION_ENV:
        value = os.environ.get(var, "").strip()
        if value and harness not in found:
            found[harness] = value
    if len(found) < 2:
        return next(iter(found.values()), None)
    for _, command in tmux.ancestors():
        program = command.split(" ", 1)[0].rsplit("/", 1)[-1]
        if program == "codex" or "/codex/" in command.split(" ", 1)[0]:
            return found["codex"]
        if program == "claude" or "/claude/versions/" in command.split(" ", 1)[0]:
            return found["claude"]
    return found["claude"]


def caller(pane_arg: str | None = None, agent_id_arg: str | None = None) -> dict:
    """Who this process is, as far as it can tell, for the server to resolve.

    `pane_verified` is True when the pane was given explicitly or this process
    really runs inside it, False when it doesn't (a background host, or tmux's
    active-pane guess with no TMUX_PANE), None when that can't be checked.
    """
    pane = pane_arg or current_pane()
    if pane_arg:
        verified: bool | None = True
    else:
        verified = tmux.process_in_pane(pane) if pane else None
    return {
        "pane": pane,
        "pane_verified": verified,
        "agent_id": agent_id_arg or harness_session_id(),
        "explicit_pane": bool(pane_arg),
    }


def whoami_lookup(who: dict) -> dict:
    """The server's view of `who`: user_id, identified_by, detail, pane label."""
    params = {"node": local_node()}
    if who["pane"]:
        params["tmux_pane"] = who["pane"]
    if who["agent_id"]:
        params["agent_id"] = who["agent_id"]
    if who["pane_verified"] is not None:
        params["pane_verified"] = "true" if who["pane_verified"] else "false"
    r = httpx.get(f"{base_url()}/whoami", params=params, headers=_headers(), timeout=5)
    if not r.is_success:
        code, text = getattr(r, "status_code", "?"), getattr(r, "text", "")
        return {"user_id": None, "detail": f"server said {code}: {text[:200]}"}
    return r.json()


def registered_user(pane: str) -> str | None:
    """The handle registered for this caller (by session id, else this pane)."""
    who = caller(pane)
    who["explicit_pane"] = False
    who["pane_verified"] = tmux.process_in_pane(pane)
    return whoami_lookup(who).get("user_id")


def _not_in_pane_message(who: dict) -> str:
    source = (
        "TMUX_PANE names it" if os.environ.get("TMUX_PANE")
        else "TMUX_PANE is unset, so this is tmux's active pane"
    )
    return (
        f"this process is not running inside tmux pane {who['pane']} ({source}). Acting\n"
        "  from here would act as whatever agent is in that pane. This happens when a harness\n"
        "  runs commands in a background host: Codex's app-server (start it with --no-daemon)\n"
        "  or a Claude Code background session. Run this from the agent's own pane, or pass\n"
        "  --pane <its pane> if you are certain which pane the agent is in."
    )


def _identify_or_explain(who: dict) -> str | None:
    """The calling agent's handle, or None after printing why it isn't known."""
    if not who["pane"] and not who["agent_id"]:
        print("error: not in a tmux pane and no harness session id; run inside the agent's pane", file=sys.stderr)
        return None
    answer = whoami_lookup(who)
    if answer.get("user_id"):
        return answer["user_id"]
    if who["pane_verified"] is False and not who["agent_id"]:
        print(f"error: {_not_in_pane_message(who)}", file=sys.stderr)
    else:
        print(f"error: {answer.get('detail') or 'this caller is not registered'}; run `agent-swarm register`", file=sys.stderr)
    return None


def cmd_register(args: argparse.Namespace) -> int:
    who = caller(args.pane, args.agent_id)
    if not who["pane"]:
        print(
            "error: could not detect tmux pane; pass --pane explicitly", file=sys.stderr
        )
        return 2
    if who["pane_verified"] is False:
        # Registering binds a handle to this pane for delivery; from a process
        # outside it, that would be someone else's pane.
        print(f"error: {_not_in_pane_message(who)}", file=sys.stderr)
        return 2
    payload: dict = {"tmux_pane": who["pane"], "node": local_node()}
    if args.name:
        payload["requested_user"] = args.name
    if who["agent_id"]:
        payload["agent_id"] = who["agent_id"]
    if args.model:
        payload["model"] = args.model
    if args.flavor:
        payload["flavor"] = args.flavor
    if args.instructions:
        payload["instructions"] = args.instructions
    if args.message_prefix:
        payload["message_prefix"] = args.message_prefix
    if args.submit_key:
        payload["submit_key"] = args.submit_key
    r = httpx.post(f"{base_url()}/register", json=payload, headers=_headers(), timeout=5)
    print(r.text)
    return 0 if r.is_success else 1


def _identity_payload(who: dict) -> dict:
    payload: dict = {"node": local_node()}
    if who["pane"]:
        payload["tmux_pane"] = who["pane"]
    if who["agent_id"]:
        payload["agent_id"] = who["agent_id"]
    if who["pane_verified"] is not None:
        payload["pane_verified"] = who["pane_verified"]
    return payload


def cmd_send(args: argparse.Namespace) -> int:
    who = caller(getattr(args, "pane", None))
    if not _identify_or_explain(who):
        return 2
    payload = {**_identity_payload(who), "recipient": args.to, "content": args.message}
    if args.context:
        payload["context"] = args.context
    r = httpx.post(f"{base_url()}/send", json=payload, headers=_headers(), timeout=10)
    print(r.text)
    return 0 if r.is_success else 1


def cmd_status(args: argparse.Namespace) -> int:
    who = caller(getattr(args, "pane", None))
    if not _identify_or_explain(who):
        return 2
    r = httpx.post(
        f"{base_url()}/status", json={**_identity_payload(who), "text": args.text}, headers=_headers(), timeout=5
    )
    print(r.text)
    return 0 if r.is_success else 1


def cmd_messages(args: argparse.Namespace) -> int:
    params = {"limit": args.limit}
    if args.user:
        params["user"] = args.user
    r = httpx.get(f"{base_url()}/messages", params=params, headers=_headers(), timeout=5)
    print(json.dumps(r.json(), indent=2))
    return 0 if r.is_success else 1


def cmd_recipients(_: argparse.Namespace) -> int:
    r = httpx.get(f"{base_url()}/recipients", headers=_headers(), timeout=5)
    print(json.dumps(r.json(), indent=2))
    return 0 if r.is_success else 1


def cmd_prune(args: argparse.Namespace) -> int:
    r = httpx.post(
        f"{base_url()}/recipients/prune",
        json={"include_shells": args.include_shells},
        timeout=10,
    )
    print(json.dumps(r.json(), indent=2))
    return 0 if r.is_success else 1


def cmd_unregister(args: argparse.Namespace) -> int:
    user = args.user
    if user is None:
        who = caller()
        if who["pane"] or who["agent_id"]:
            user = whoami_lookup(who).get("user_id")
    if user is None:
        print("error: current pane is not registered; pass --user HANDLE", file=sys.stderr)
        return 2
    response = httpx.delete(f"{base_url()}/recipients/{quote(user, safe='')}", headers=_headers(), timeout=5)
    print(response.text)
    return 0 if response.is_success else 1


def cmd_tasks(args: argparse.Namespace) -> int:
    r = httpx.get(f"{base_url()}/tasks", headers=_headers(), timeout=5)
    if not r.is_success:
        print(r.text, file=sys.stderr)
        return 1
    tasks = r.json()["tasks"]
    if args.status:
        tasks = [t for t in tasks if t["status"] == args.status]
    print(json.dumps({"tasks": tasks}, indent=2))
    return 0


def _parse_deps(raw: str) -> list[int]:
    """'3,5' -> [3, 5]; '' -> [] (clears dependencies on update)."""
    return [int(part) for part in raw.split(",") if part.strip()]


def _acting_fields() -> dict:
    """This pane and node, so a task notification goes out in this agent's name."""
    pane = current_pane()
    return {"tmux_pane": pane, "node": local_node()} if pane else {}


def cmd_task_create(args: argparse.Namespace) -> int:
    payload: dict = {"title": args.title, **_acting_fields()}
    if args.description:
        payload["description"] = args.description
    if args.assignee:
        payload["assignee"] = args.assignee
    if args.depends_on is not None:
        payload["depends_on"] = _parse_deps(args.depends_on)
    r = httpx.post(f"{base_url()}/tasks", json=payload, headers=_headers(), timeout=5)
    print(r.text)
    return 0 if r.is_success else 1


def cmd_task_update(args: argparse.Namespace) -> int:
    payload: dict = {}
    fields = _acting_fields()
    if args.status:
        payload["status"] = args.status
    if args.assignee is not None:
        payload["assignee"] = args.assignee
    if args.worktree is not None:
        payload["worktree"] = args.worktree
        # A path is only meaningful on the machine it is on.
        payload["worktree_node"] = local_node()
    if args.depends_on is not None:
        payload["depends_on"] = _parse_deps(args.depends_on)
    if args.note is not None:
        payload["note"] = args.note
    if not payload:
        print(
            "error: pass --status, --assignee, --worktree, --note, "
            "and/or --depends-on",
            file=sys.stderr,
        )
        return 2
    payload.update(fields)
    r = httpx.patch(f"{base_url()}/tasks/{args.id}", json=payload, headers=_headers(), timeout=5)
    print(r.text)
    return 0 if r.is_success else 1


def cmd_join(args: argparse.Namespace) -> int:
    """Point this machine at a hub: write the settings file, then check the
    hub answers and takes this token for this node."""
    node = args.node or config.hostname()
    path = config.write(args.hub, args.token, node)
    hub = config.load().hub
    reachable, enrolled, problem = False, False, None
    try:
        reachable = httpx.get(f"{hub}/health", timeout=5).is_success
        r = httpx.get(f"{hub}/nodes/me", headers=_headers(), timeout=5)
        if r.status_code == 401:
            problem = "the hub rejected the token"
        elif r.is_success:
            me = r.json()
            if me.get("kind") == "node" and me.get("node") != node:
                problem = f"the token belongs to node {me.get('node')!r}, not {node!r}; pass --node {me.get('node')}"
            elif me.get("kind") == "node":
                enrolled = True
            else:
                problem = "no token given: the hub sees this as the owner, which only works on the hub itself"
        else:
            problem = f"unexpected answer from the hub: {r.status_code}"
    except httpx.HTTPError as e:
        problem = f"the hub did not answer: {e}"
    print(json.dumps({"config": str(path), "hub": hub, "node": node,
                      "hub_reachable": reachable, "enrolled": enrolled}, indent=2))
    if problem:
        print(f"warning: {problem}; settings were written anyway", file=sys.stderr)
        return 1
    return 0


def cmd_node_token(args: argparse.Namespace) -> int:
    """Enrol a node with the hub (or rotate its token). Prints the token once."""
    r = httpx.post(
        f"{base_url()}/nodes/{quote(args.name, safe='')}/token", headers=_headers(), timeout=5
    )
    if not r.is_success:
        print(r.text, file=sys.stderr)
        return 1
    body = r.json()
    print(json.dumps(body, indent=2))
    # The join command runs on the other machine, so a loopback hub address
    # would point at that machine itself; guess this host's name instead.
    hub = base_url()
    host = urlparse(hub).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1"):
        port = urlparse(hub).port or 8765
        hub = f"http://{config.hostname()}:{port}"
        print(f"(hub address guessed as {hub}; use this machine's tailnet name if that is wrong)", file=sys.stderr)
    print(
        f"On {body['name']}, run:\n  agent-swarm join {shlex.quote(hub)} "
        f"--token {shlex.quote(body['token'])} --node {shlex.quote(body['name'])}",
        file=sys.stderr,
    )
    return 0


def cmd_nodes(_: argparse.Namespace) -> int:
    r = httpx.get(f"{base_url()}/nodes", headers=_headers(), timeout=5)
    print(json.dumps(r.json(), indent=2))
    return 0 if r.is_success else 1


def cmd_export(args: argparse.Namespace) -> int:
    """Write this machine's agents, teams, and tasks out as a bundle.

    Reads the database without writing to it, so it is safe against a live
    server's file or an archived copy.
    """
    path = args.db or os.environ.get("AGENT_SWARM_DB", "~/.agent-swarm/db.sqlite")
    try:
        conn = bundle.open_readonly(path)
        data = bundle.read(conn, with_messages=args.with_messages)
    except bundle.Invalid as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    text = json.dumps(data, indent=1)
    counts = {k: len(data[k]) for k in ("agents", "teams", "tasks", "messages")}
    if args.out and args.out != "-":
        out = Path(args.out).expanduser()
        out.write_text(text)
        print(json.dumps({"out": str(out), "source": data["source"]["id"], **counts}, indent=2))
    else:
        print(text)
        print(json.dumps({"source": data["source"]["id"], **counts}), file=sys.stderr)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """Hand a bundle to the hub, for agents that run on `--node`."""
    try:
        data = json.loads(Path(args.bundle).expanduser().read_text())
    except (OSError, ValueError) as e:
        print(f"error: could not read {args.bundle}: {e}", file=sys.stderr)
        return 2
    payload = {
        "node": args.node, "bundle": data, "dry_run": args.dry_run,
        "again": args.again, "merge_teams": args.merge_teams,
    }
    r = httpx.post(f"{base_url()}/import", json=payload, headers=_headers(), timeout=120)
    if not r.is_success:
        print(r.text, file=sys.stderr)
        return 1
    body = r.json()
    print(json.dumps(body["report"], indent=2))
    if body["dry_run"]:
        print("\nnothing was written; run again without --dry-run", file=sys.stderr)
    if body.get("register"):
        print(
            "\nOn " + args.node + ", only agents still running and not automatically "
            "reconnected need to run their line inside their own pane. "
            "Offline agents can wait until resumed:", file=sys.stderr,
        )
        for line in body["register"]:
            print("  " + line, file=sys.stderr)
    return 0


def cmd_whoami(_: argparse.Namespace) -> int:
    who = caller()
    answer = whoami_lookup(who) if (who["pane"] or who["agent_id"]) else {}
    if who["pane_verified"] is False and not answer.get("identified_by") == "session":
        print(f"warning: {_not_in_pane_message(who)}", file=sys.stderr)
    session = who["agent_id"]
    print(
        json.dumps(
            {
                "user": answer.get("user_id"),
                "identified_by": answer.get("identified_by"),
                "session": f"{session[:8]}…" if session else None,
                "pane": who["pane"],
                "in_pane": who["pane_verified"],
                "node": local_node(),
                "server": base_url(),
                **({"detail": answer["detail"]} if answer.get("detail") else {}),
            },
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent-swarm")
    sub = p.add_subparsers(dest="cmd", required=True)

    reg = sub.add_parser("register")
    reg.add_argument("--pane")
    reg.add_argument(
        "--name",
        help="preferred handle; granted when free, 409 when another agent holds it "
        "(default: server picks from the name pool)",
    )
    reg.add_argument(
        "--agent-id",
        help="stable session identifier (e.g. conversation UUID); used as real identity",
    )
    reg.add_argument(
        "--model", help="model label for telemetry only (e.g. claude-opus-4-7)"
    )
    reg.add_argument(
        "--flavor",
        help="delivery flavor used to pick default submit behavior (e.g. codex)",
    )
    reg.add_argument(
        "--instructions",
        help="human guidance for peers talking to this agent",
    )
    reg.add_argument(
        "--message-prefix",
        help="literal text prefixed to each delivered message (e.g. '/queue ')",
    )
    reg.add_argument(
        "--submit-key",
        help="tmux key name used to submit each delivered message (default: C-m)",
    )
    reg.set_defaults(func=cmd_register)

    unregister = sub.add_parser("unregister", help="remove one registration without deleting messages or tasks")
    unregister.add_argument("--user", help="handle to remove (default: current pane's handle)")
    unregister.set_defaults(func=cmd_unregister)

    snd = sub.add_parser("send")
    snd.add_argument("--to", required=True)
    snd.add_argument("--message", required=True)
    snd.add_argument("--context")
    snd.add_argument("--pane", help="the agent's tmux pane, when this process isn't in it")
    snd.set_defaults(func=cmd_send)

    msg = sub.add_parser("messages")
    msg.add_argument("--user")
    msg.add_argument("--limit", type=int, default=20)
    msg.set_defaults(func=cmd_messages)

    rcp = sub.add_parser("recipients")
    rcp.set_defaults(func=cmd_recipients)

    prune = sub.add_parser(
        "prune",
        help="forget registered agents whose tmux pane no longer exists "
        "(add --include-shells to also forget panes that only run a bare shell)",
    )
    prune.add_argument("--include-shells", action="store_true")
    prune.set_defaults(func=cmd_prune)

    tsk = sub.add_parser("tasks")
    tsk.add_argument("--status", choices=["open", "picked_up", "done"])
    tsk.set_defaults(func=cmd_tasks)

    tcreate = sub.add_parser(
        "task-create", help="file a task so it appears on the shared task board"
    )
    tcreate.add_argument("title")
    tcreate.add_argument("--description")
    tcreate.add_argument("--assignee")
    tcreate.add_argument(
        "--depends-on", help="comma-separated task ids this task waits on (e.g. 3,5)"
    )
    tcreate.set_defaults(func=cmd_task_create)

    tup = sub.add_parser("task-update")
    tup.add_argument("id", type=int)
    tup.add_argument("--status", choices=["open", "picked_up", "done"])
    tup.add_argument("--assignee")
    tup.add_argument("--worktree")
    tup.add_argument(
        "--depends-on",
        help="comma-separated task ids this task waits on; empty string clears",
    )
    tup.add_argument(
        "--note",
        help="how to verify the work: how to use it, how to reproduce the "
        "problem it fixes, and where to look. Required to close a task.",
    )
    tup.set_defaults(func=cmd_task_update)

    st = sub.add_parser(
        "status", help="say in a line what you are working on; shown on the dashboard"
    )
    st.add_argument("text", help='e.g. "working on #12: pane-id migration"')
    st.add_argument("--pane", help="the agent's tmux pane, when this process isn't in it")
    st.set_defaults(func=cmd_status)

    who = sub.add_parser("whoami")
    who.set_defaults(func=cmd_whoami)

    join = sub.add_parser(
        "join", help="point this machine at a hub (writes ~/.agent-swarm/node.toml)"
    )
    join.add_argument("hub", help="hub URL, e.g. http://karans-linux:8765")
    join.add_argument("--token", help="this machine's token, from `agent-swarm node-token` on the hub")
    join.add_argument("--node", help="this machine's node name (default: short hostname)")
    join.set_defaults(func=cmd_join)

    ntok = sub.add_parser(
        "node-token", help="enrol a machine with this hub, or rotate its token; prints it once"
    )
    ntok.add_argument("name", help="the node name that machine will register as")
    ntok.set_defaults(func=cmd_node_token)

    nds = sub.add_parser("nodes", help="list enrolled machines")
    nds.set_defaults(func=cmd_nodes)

    exp = sub.add_parser(
        "export", help="write this machine's agents, teams, and tasks out as a bundle"
    )
    exp.add_argument("--db", help="database to read (default: $AGENT_SWARM_DB)")
    exp.add_argument("--out", help="file to write (default: standard output)")
    exp.add_argument(
        "--with-messages", action="store_true",
        help="carry message history too, as history: it is never delivered again",
    )
    exp.set_defaults(func=cmd_export)

    imp = sub.add_parser("import", help="take a bundle into this hub")
    imp.add_argument("bundle", help="the file `agent-swarm export` wrote")
    imp.add_argument("--node", required=True, help="the machine those agents run on")
    imp.add_argument("--dry-run", action="store_true", help="report what would happen, write nothing")
    imp.add_argument("--again", action="store_true", help="import a bundle that was imported before")
    imp.add_argument(
        "--merge-teams", action="store_true",
        help="add to a team of the same name here instead of importing it under a new one",
    )
    imp.set_defaults(func=cmd_import)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
