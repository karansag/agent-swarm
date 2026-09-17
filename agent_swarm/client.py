"""Tiny CLI client. Usage:

    agent-swarm register [--pane Y] [--name HANDLE] [--flavor NAME] [--instructions TXT]
                         [--message-prefix TXT]
    agent-swarm send --to Y [--context CTX] --message MSG
    agent-swarm messages [--user X] [--limit N]
    agent-swarm recipients
    agent-swarm whoami       # prints detected tmux pane + registered handle
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
import sys
from urllib.parse import quote

import httpx

from .tmux import current_pane, local_host


def base_url() -> str:
    return os.environ.get(
        "AGENT_SWARM_URL",
        os.environ.get("AGENT_MSG_URL", "http://127.0.0.1:8765"),
    )


def registered_user(pane: str) -> str | None:
    r = httpx.get(f"{base_url()}/recipients", timeout=5)
    if not r.is_success:
        return None
    for recipient in r.json().get("recipients", []):
        if recipient.get("tmux_pane") == pane:
            return recipient.get("user_id")
    return None


def cmd_register(args: argparse.Namespace) -> int:
    pane = args.pane or current_pane()
    if not pane:
        print(
            "error: could not detect tmux pane; pass --pane explicitly", file=sys.stderr
        )
        return 2
    payload: dict = {"tmux_pane": pane, "host": local_host()}
    if args.name:
        payload["requested_user"] = args.name
    if args.agent_id:
        payload["agent_id"] = args.agent_id
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
    r = httpx.post(f"{base_url()}/register", json=payload, timeout=5)
    print(r.text)
    return 0 if r.is_success else 1


def cmd_send(args: argparse.Namespace) -> int:
    pane = current_pane()
    if not pane:
        print(
            "error: could not detect tmux pane; run inside tmux or register with --pane",
            file=sys.stderr,
        )
        return 2
    sender = registered_user(pane)
    if not sender:
        print(
            "error: current tmux pane is not registered; run `agent-swarm register` first",
            file=sys.stderr,
        )
        return 2
    payload = {
        "tmux_pane": pane,
        "recipient": args.to,
        "content": args.message,
    }
    if args.context:
        payload["context"] = args.context
    r = httpx.post(f"{base_url()}/send", json=payload, timeout=10)
    print(r.text)
    return 0 if r.is_success else 1


def cmd_messages(args: argparse.Namespace) -> int:
    params = {"limit": args.limit}
    if args.user:
        params["user"] = args.user
    r = httpx.get(f"{base_url()}/messages", params=params, timeout=5)
    print(json.dumps(r.json(), indent=2))
    return 0 if r.is_success else 1


def cmd_recipients(_: argparse.Namespace) -> int:
    r = httpx.get(f"{base_url()}/recipients", timeout=5)
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
        pane = current_pane()
        user = registered_user(pane) if pane else None
    if user is None:
        print("error: current pane is not registered; pass --user HANDLE", file=sys.stderr)
        return 2
    response = httpx.delete(f"{base_url()}/recipients/{quote(user, safe='')}", timeout=5)
    print(response.text)
    return 0 if response.is_success else 1


def cmd_tasks(args: argparse.Namespace) -> int:
    r = httpx.get(f"{base_url()}/tasks", timeout=5)
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


def cmd_task_create(args: argparse.Namespace) -> int:
    payload: dict = {"title": args.title}
    if args.description:
        payload["description"] = args.description
    if args.assignee:
        payload["assignee"] = args.assignee
    if args.depends_on is not None:
        payload["depends_on"] = _parse_deps(args.depends_on)
    r = httpx.post(f"{base_url()}/tasks", json=payload, timeout=5)
    print(r.text)
    return 0 if r.is_success else 1


def cmd_task_update(args: argparse.Namespace) -> int:
    payload: dict = {}
    if args.status:
        payload["status"] = args.status
    if args.assignee is not None:
        payload["assignee"] = args.assignee
    if args.worktree is not None:
        payload["worktree"] = args.worktree
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
    r = httpx.patch(f"{base_url()}/tasks/{args.id}", json=payload, timeout=5)
    print(r.text)
    return 0 if r.is_success else 1


def cmd_whoami(_: argparse.Namespace) -> int:
    pane = current_pane()
    user = registered_user(pane) if pane else None
    print(
        json.dumps(
            {"user": user, "pane": pane, "server": base_url()}, indent=2
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

    who = sub.add_parser("whoami")
    who.set_defaults(func=cmd_whoami)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
