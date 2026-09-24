"""FastAPI server. Endpoints: /register, /send, /messages, /recipients, /health,
plus the live web portal at / (backed by /api/state and /api/peek)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import activity, attachments, db, names, panes, tmux

log = logging.getLogger("agent_swarm.monitor")

# Default activity shown when the monitor is off or hasn't observed an agent
# yet. The dashboard must tolerate this shape.
UNKNOWN_ACTIVITY = {"status": "unknown", "detail": None, "since": None}

DB_PATH = Path(
    os.environ.get(
        "AGENT_SWARM_DB",
        os.environ.get("AGENT_MSG_DB", "~/.agent-swarm/db.sqlite"),
    )
).expanduser()
PORTAL_PATH = Path(__file__).parent / "portal.html"
PORTAL_STATIC_PATH = Path(__file__).parent / "static"

# Reserved handle for the human operator. Never assigned to an agent
# (the name pool contains only animals). Messages sent to it are recorded
# for the dashboard instead of being injected into a tmux pane.
OWNER = "owner"

# Said the same way wherever a worker meets it: in the assignment message, in
# the protocol brief, and in the error it gets if it tries to close without one.
NOTE_GUIDANCE = (
    "Say how to verify the work: for a feature, how to use it; for a fix, how "
    "to reproduce the problem it solves; and where to look - the command to "
    "run, the endpoint or screen to open, or the files that changed. Write it "
    "for someone coming back to this later with no memory of the work."
)

# The dashboard shows each agent's latest status line, so the owner can see
# what everyone is doing (and did last) without a task to go by.
STATUS_GUIDANCE = (
    "Whenever you start on something new, run `agent-swarm status \"working on "
    "<what, in a few words>\"` so the owner's dashboard shows what you are "
    "doing; say when you finish, e.g. `agent-swarm status \"done: <what>\"`."
)


class RegisterReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tmux_pane: str = Field(min_length=1)
    agent_id: str | None = Field(
        default=None,
        description="Stable session identifier (e.g. Claude conversation UUID). "
        "This is the agent's 'real' identity across model changes.",
    )
    requested_user: str | None = Field(
        default=None,
        description="Preferred handle. Granted when it is free and well-formed; "
        "a handle held by another agent is a 409 rather than a silent "
        "reassignment. Omit to let the server pick from the name pool.",
    )
    model: str | None = Field(
        default=None,
        description="Model label for telemetry only (e.g. 'claude-opus-4-7'). "
        "Not used for identity.",
    )
    flavor: str | None = Field(
        default=None,
        description="Optional delivery flavor; controls default submit key behavior.",
    )
    host: str | None = Field(
        default=None,
        description="Machine the agent runs on, used in the assigned handle. "
        "The client sends $AGENT_SWARM_NODE or the short hostname.",
    )
    instructions: str | None = Field(
        default=None,
        description="Optional human guidance for peers talking to this agent.",
    )
    message_prefix: str | None = Field(
        default=None,
        description="Optional literal prefix inserted before each delivered message.",
    )
    submit_key: str | None = Field(
        default=None,
        description="Optional tmux submit key override (defaults to C-m).",
    )


class PruneReq(BaseModel):
    include_shells: bool = Field(
        default=False,
        description="Also drop registrations whose pane exists but only runs a bare shell.",
    )


class StatusReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tmux_pane: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=200)


class SendReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tmux_pane: str = Field(min_length=1)
    recipient: str = Field(min_length=1)
    content: str = Field(min_length=1)
    context: str | None = None


class OwnerSendReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient: str = Field(min_length=1)
    content: str = ""
    context: str | None = None
    attachments: list[str] = Field(
        default_factory=list,
        max_length=attachments.MAX_PER_MESSAGE,
        description="Names returned by POST /attachments. The recipient agent "
        "gets each as an absolute file path appended to the message.",
    )


class TaskCreateReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    description: str | None = None
    assignee: str | None = None
    team_id: int | None = None
    depends_on: list[int] | None = None


class TaskUpdateReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["open", "picked_up", "done"] | None = None
    assignee: str | None = None
    worktree: str | None = Field(default=None, min_length=1)
    team_id: int | None = None
    depends_on: list[int] | None = None
    note: str | None = Field(
        default=None,
        description="How to verify the finished work: how to use it if it is a "
        "feature, how to reproduce if it is a fix, and where to look. Required "
        "to close a task, and kept on the task so it can be read later.",
    )


class SpawnReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flavor: Literal["claude", "codex", "pi", "hermes"] = "claude"
    model: str | None = Field(
        default=None,
        description="Optional harness model. Only honored when it is one of "
        "the harness's known models; otherwise the harness default is used.",
    )
    autonomy: Literal["auto", "supervised"] = Field(
        default="auto",
        description="'auto' launches the harness with its non-blocking "
        "permission flags so the agent never stops for approval; "
        "'supervised' keeps the harness's normal ask-first behavior.",
    )


class TeamCreateReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)


class TeamUpdateReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    queen: str | None = None
    objective: str | None = Field(
        default=None,
        description="Coordination objective delivered with a queen promotion.",
    )


class AgentTeamReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: int | None = None


class AgentModelReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(
        default=None,
        max_length=120,
        description="Model label shown on the dashboard, e.g. claude-opus-4-7. "
        "Display only: the running agent is not switched. Blank clears it.",
    )


def _queen_prompt(team: dict, objective: str) -> str:
    teammates = [m for m in team["members"] if m != team["queen"]]
    roster = ", ".join(teammates) if teammates else "(no teammates yet)"
    return (
        f"The owner has made you Queen of team '{team['name']}'. "
        f"Your teammates: {roster}.\n\n"
        f"Objective: {objective}\n\n"
        "Act as the owner's coordination point for this team until the owner ends "
        "or changes this role. Immediately notify each teammate, using context "
        "queen-status, that you coordinate this team for this objective and that "
        "their task coordination should route through you.\n\n"
        "Decompose the objective into concrete tasks; create and assign them to "
        "teammates with agent-swarm task-create and agent-swarm task-update, and "
        "record ordering with --depends-on <ids> so the board shows the "
        "dependency graph. Tasks "
        "the owner assigns to the team are delivered to you: parcel them out by "
        "reassigning or splitting them among teammates as appropriate, and "
        "monitor your workers' progress. Normally coordinate rather than "
        "implement. Require repository workers to use "
        "branch task/<id> in a dedicated worktree and record it on the task. "
        "Track progress, dependencies, stopped agents, commits, tests, and "
        "integration; integrate one branch at a time. Keep the owner informed of "
        "material progress and decisions, and ask before changing scope or the "
        "definition of done. Coordinate only your own team.\n\n"
        "This is a prompt-driven role, not special server authority. The owner "
        "retains every right and can replace or demote you at any time."
    )


def _protocol_brief(user_id: str, peers: list[dict]) -> str:
    """A one-shot primer the agent sees in its register response.

    Tells the agent what inbound messages look like so a line appearing in
    its prompt doesn't get mistaken for user input.
    """

    def _peer_line(p: dict) -> str:
        tags = []
        if p.get("flavor"):
            tags.append(f"flavor={p['flavor']}")
        if p.get("model"):
            tags.append(p["model"])
        if p.get("agent_id"):
            tags.append(f"agent={p['agent_id']}")
        if p.get("submit_key"):
            tags.append(f"submit={p['submit_key']}")
        if p.get("alive") is False:
            tags.append("OFFLINE")
        suffix = f" ({', '.join(tags)})" if tags else ""
        instructions = f" -- {p['instructions']}" if p.get("instructions") else ""
        return f"  - {p['user_id']}{suffix}{instructions}"

    peer_lines = "\n".join(_peer_line(p) for p in peers) or "  (none yet)"
    offline = [p["user_id"] for p in peers if p.get("alive") is False]
    offline_note = (
        "Peers tagged OFFLINE are registered but not running (pane gone or a bare "
        "shell); sending to them is refused until they restart.\n\n"
        if offline else ""
    )
    return (
        f"You are registered as '{user_id}'.\n"
        f"\n"
        f"Incoming messages from the owner and other agents are delivered by injecting a "
        f"line into your tmux pane (as if typed) followed by the configured "
        f"submit key (default `C-m`). The "
        f"format is:\n"
        f"\n"
        f"    [agent-msg from <sender> · <context>] <content>\n"
        f"\n"
        f"The `· <context>` segment is omitted when the sender didn't "
        f"supply a context tag. Reply to the sender through the agent-swarm API "
        f"so the response reaches their inbox.\n"
        f"\n"
        f"To reply or initiate, POST to /send (or use the `agent-swarm send` "
        f"CLI). Currently registered peers:\n"
        f"{peer_lines}\n"
        f"\n"
        f"{offline_note}"
        f"List peers anytime: GET /recipients.\n"
        f"\n"
        f"The reserved handle 'owner' is the human operator in charge of "
        f"all agents. Messages from 'owner' are instructions from the "
        f"human, not from a peer agent. To message the human, send to "
        f"recipient 'owner'; replies land on the owner's dashboard. "
        f"Terminal-only output does not reach the owner.\n"
        f"\n"
        f"The owner can assign you tasks. They arrive as messages tagged "
        f"'task #N'. When you start one, run "
        f"`agent-swarm task-update N --status picked_up`; when you finish, "
        f"run `agent-swarm task-update N --status done --note \"...\"`. "
        f"The note is required: closing without one is refused. {NOTE_GUIDANCE} "
        f"It stays on the task, so the owner can open it later and see how to "
        f"check the work. "
        f"List tasks anytime: `agent-swarm tasks`. You can file work for the "
        f"shared board with `agent-swarm task-create \"title\"` (optionally "
        f"add `--description`, `--assignee`, or `--depends-on 3,5` to record "
        f"ordering; dependencies show as a graph on the dashboard).\n"
        f"\n"
        f"{STATUS_GUIDANCE}\n"
        f"\n"
        f"The owner may group agents into teams, each with a queen who "
        f"coordinates that team's work. Tasks can be assigned to a team; "
        f"they reach the queen, who parcels them out."
    )


def create_app(db_path: Path = DB_PATH, monitor: bool = True) -> FastAPI:
    conn = db.connect(db_path)
    attachments_root = Path(db_path).expanduser().resolve().parent / "attachments"

    # Per-agent activity state, mutated by the monitor loop and read by
    # /api/state. Keyed by user_id; see agent_swarm.activity.step for the shape.
    registry: dict[str, dict] = {}
    interval = float(
        os.environ.get(
            "AGENT_SWARM_MONITOR_INTERVAL",
            os.environ.get("AGENT_MSG_MONITOR_INTERVAL", "5.0"),
        )
    )
    grace = float(
        os.environ.get(
            "AGENT_SWARM_ATTENTION_GRACE",
            os.environ.get("AGENT_MSG_ATTENTION_GRACE", "60.0"),
        )
    )

    async def _monitor_tick():
        _migrate_legacy_panes()
        recipients = db.list_recipients(conn)
        live_panes = tmux.live_agent_panes()
        titles = {p: row["title"] for p, row in tmux.pane_table().items()}
        server = tmux.server_id()
        observations = []
        for r in recipients:
            pane = r["tmux_pane"]
            # An id from an earlier tmux server now names some other pane.
            alive = pane in live_panes and _stale(r, server) is None
            capture = None
            if alive:
                # Claude Code and Codex title their pane with the current topic.
                topic = tmux.title_summary(titles.get(pane, ""))
                if topic:
                    db.record_summary(conn, r["user_id"], topic, "title")
                # Subprocess capture must not block the event loop.
                text, err = await asyncio.to_thread(tmux.capture_pane, pane)
                capture = text if err is None else None
            observations.append(
                activity.Observation(r["user_id"], r.get("flavor"), alive, capture)
            )
        notes = activity.step(registry, observations, time.time(), interval, grace)
        for note in notes:
            db.record_message(
                conn,
                sender=note.user_id,
                recipient=OWNER,
                context="attention",
                content=f"needs attention: {note.detail}",
                delivered=True,
                delivery_error=None,
            )

    retention_days = float(
        os.environ.get(
            "AGENT_SWARM_ATTACHMENT_RETENTION_DAYS", attachments.DEFAULT_RETENTION_DAYS
        )
    )
    # 0 (or less) keeps sent images forever; unsent drafts are still swept.
    retention = retention_days * attachments.DAY if retention_days > 0 else None
    message_days = float(os.environ.get("AGENT_SWARM_MESSAGE_RETENTION_DAYS", "60"))

    def _cleanup() -> dict:
        """Daily cleanup: old messages first, then images nothing needs."""
        now = time.time()
        messages = 0
        if message_days > 0:
            messages = db.delete_messages_before(conn, now - message_days * attachments.DAY)
        # Images carried only by the messages just deleted are now unreferenced
        # and, being older than the orphan grace, go in the same pass.
        images = attachments.sweep(
            attachments_root, db.attachment_last_used(conn), now, retention
        )
        if messages or images:
            log.info("cleanup removed %d message(s), %d image(s)", messages, len(images))
        return {"messages": messages, "images": images}

    async def _cleanup_loop():
        while True:
            try:
                await asyncio.to_thread(_cleanup)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("cleanup failed")
            await asyncio.sleep(attachments.DAY)

    async def _monitor_loop():
        while True:
            try:
                await _monitor_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A failed tick is logged and skipped, never fatal to the loop.
                log.exception("monitor tick failed")
            await asyncio.sleep(interval)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Background work (monitor, daily cleanup) is off in tests.
        tasks = (
            [asyncio.create_task(_monitor_loop()), asyncio.create_task(_cleanup_loop())]
            if monitor else []
        )
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="agent-swarm", version="0.1.0", lifespan=lifespan)
    app.state.cleanup = _cleanup
    app.state.monitor_tick = _monitor_tick
    app.mount(
        "/static",
        StaticFiles(directory=PORTAL_STATIC_PATH),
        name="portal-static",
    )
    # Same dict the monitor loop mutates; exposed so tests can seed it.
    app.state.activity_registry = registry

    @app.get("/health")
    def health():
        return {"ok": True, "db": str(db_path)}

    @app.post("/register")
    def register(req: RegisterReq):
        _migrate_legacy_panes()
        pane, label, server = _pane_ref(req.tmux_pane)
        flavor_hint = req.flavor or (tmux.infer_flavor(req.model) if req.model else None)
        existing_id = None
        if req.agent_id:
            existing_id = db.lookup_user_by_agent_id(conn, req.agent_id)
        if existing_id is None:
            existing_id = db.lookup_user_by_pane(conn, pane, server)
        if existing_id is None and server is not None and label and flavor_hint:
            existing_id = db.lookup_user_by_restored_label(conn, label, flavor_hint, server)

        requested = None
        if req.requested_user is not None:
            try:
                requested = names.normalize_requested(req.requested_user)
            except names.InvalidName as e:
                raise HTTPException(
                    status_code=400,
                    detail={"error": str(e), "requested_user": req.requested_user},
                ) from e
            # A handle whose agent is offline can be reclaimed, so a restarted
            # agent gets its name and history back from a new pane.
            if (
                db.name_taken_by_other(conn, requested, req.agent_id, pane)
                and _is_alive(requested)
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "name already taken by another agent",
                        "requested_user": requested,
                    },
                )

        renamed_from = None
        if requested is not None:
            # Honor the request, moving an already-registered agent's history
            # over when it is asking for a different handle than it holds.
            if existing_id is not None and existing_id != requested:
                if db.get_recipient(conn, requested) is not None:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": f"this pane is registered as {existing_id}; "
                            f"unregister it before claiming {requested}",
                            "requested_user": requested,
                        },
                    )
                db.rename_recipient(conn, existing_id, requested)
                renamed_from = existing_id
            user_id = requested
        elif existing_id is not None:
            user_id = existing_id
        else:
            # A brand new registration has no stored flavor to fall back on,
            # so what the agent just told us is the whole picture.
            user_id = names.pick_unused(
                conn,
                tmux.handle_tag(
                    req.flavor or tmux.infer_flavor(req.model), req.model, req.host
                ),
            )
        # A re-register that omits both model and flavor must not downgrade a
        # known harness to 'generic': the write COALESCEs, but only over NULL,
        # so fall back to what is already stored before defaulting.
        current = db.get_recipient(conn, user_id)
        flavor = req.flavor or (tmux.infer_flavor(req.model) if req.model else None)
        if flavor is None:
            flavor = (current["flavor"] if current else None) or tmux.infer_flavor(None)
        submit_key = req.submit_key or tmux.submit_key_for_flavor(flavor)
        db.register(
            conn,
            user_id,
            pane,
            req.agent_id,
            req.model,
            flavor,
            req.instructions,
            req.message_prefix,
            submit_key,
            tmux_server=server,
            pane_label=label,
        )
        tmux.tag_pane(pane, user_id)
        registered = db.get_recipient(conn, user_id)
        peers = [r for r in _annotated_recipients() if r["user_id"] != user_id]
        return {
            "ok": True,
            "user_id": user_id,
            "tmux_pane": pane,
            "pane_label": label,
            "agent_id": registered["agent_id"] if registered else req.agent_id,
            "model": registered["model"] if registered else req.model,
            "flavor": registered["flavor"] if registered else flavor,
            "instructions": registered["instructions"] if registered else req.instructions,
            "message_prefix": registered["message_prefix"] if registered else req.message_prefix,
            "submit_key": (
                registered["submit_key"] if registered and registered["submit_key"] else tmux.DEFAULT_SUBMIT_KEY
            ),
            "assigned": requested is None,
            "requested_user": requested,
            "renamed_from": renamed_from,
            "protocol_brief": _protocol_brief(user_id, peers),
        }

    def _pane_ref(target: str) -> tuple[str, str, str | None]:
        """(pane id, session:window.pane label, tmux server) for a pane target.

        Clients send either form; both are resolved to the pane's id now, while
        the positional one still means what the client meant. Without tmux the
        target is kept as given, tied to no server.
        """
        resolved = tmux.resolve_pane(target)
        if resolved is None:
            return target, target, None
        return resolved[0], resolved[1], tmux.server_id()

    def _offline(r: dict, existing: set[str], live: set[str], server: str | None) -> str | None:
        return tmux.offline_reason(r["tmux_pane"], existing, live, stale=_stale(r, server))

    def _stale(r: dict, server: str | None) -> str | None:
        """Why a row's pane id no longer identifies its pane, or None."""
        if server is None:
            return None  # no tmux to compare against
        bound = r.get("tmux_server")
        if bound == db.UNBOUND:
            return "its pane could not be verified when pane ids were introduced"
        if bound is not None and bound != server:
            return "its pane is from an earlier tmux session"
        if bound is None and r["tmux_pane"].startswith("%"):
            return "its pane id was never tied to a tmux session"
        return None

    def _annotated_recipients() -> list[dict]:
        _migrate_legacy_panes()
        existing, live = tmux.list_panes(), tmux.live_agent_panes()
        server, table = tmux.server_id(), tmux.pane_table()
        rows = db.list_recipients(conn)
        for r in rows:
            r["offline_reason"] = _offline(r, existing, live, server)
            r["alive"] = r["offline_reason"] is None
            # Show where the pane is right now; fall back to where it last was.
            if r["alive"] and r["tmux_pane"] in table:
                r["pane_label"] = table[r["tmux_pane"]]["label"]
            r["pane_label"] = r.get("pane_label") or r["tmux_pane"]
        return rows

    def _is_alive(user_id: str) -> bool:
        return any(r["user_id"] == user_id and r["alive"] for r in _annotated_recipients())

    def _migrate_legacy_panes() -> None:
        """Rebind rows stored before pane ids; see agent_swarm/panes.py."""
        rows = db.legacy_pane_rows(conn)
        if not rows:
            return
        server = tmux.server_id()
        if server is None:
            return  # no tmux right now; try again on a later call
        for d in panes.plan(rows, tmux.pane_table(), tmux.server_start_time()):
            row = next(r for r in rows if r["user_id"] == d.user_id)
            if d.pane_id is not None:
                db.bind_pane(conn, d.user_id, d.pane_id, server, d.label)
            elif d.gone:
                # Keeping the old address under this server reads as "pane no
                # longer exists" (addresses never match ids), so prune clears it.
                db.bind_pane(conn, d.user_id, row["tmux_pane"], server, row["tmux_pane"])
            else:
                db.bind_pane(conn, d.user_id, row["tmux_pane"], db.UNBOUND, row["tmux_pane"])
            log.info("pane migration: %s -> %s (%s)", d.user_id, d.pane_id or "offline", d.reason)

    def _refuse_if_offline(
        sender: str, recipient: dict, context, content, files: list[str] | None = None
    ) -> None:
        reason = _offline(
            recipient, tmux.list_panes(), tmux.live_agent_panes(), tmux.server_id()
        )
        if reason is None:
            return
        mid = db.record_message(
            conn, sender, recipient["user_id"], context, content,
            delivered=False, delivery_error=reason, attachments=files,
        )
        raise HTTPException(
            status_code=409,
            detail={"error": reason, "recipient": recipient["user_id"], "message_id": mid},
        )

    @app.get("/recipients")
    def recipients():
        return {"recipients": _annotated_recipients()}

    @app.post("/recipients/prune")
    def prune_recipients(req: PruneReq):
        """Drop registrations that can't come back on their own.

        By default only panes that no longer exist are removed: a pane that
        still exists but runs a bare shell keeps its registration, so an agent
        restarted in that pane gets the same identity back.
        """
        removed, kept_offline = [], []
        for r in _annotated_recipients():
            if r["alive"]:
                continue
            gone = "no longer exists" in r["offline_reason"]
            if gone or req.include_shells:
                db.delete_recipient(conn, r["user_id"])
                removed.append(r["user_id"])
            else:
                kept_offline.append(r["user_id"])
        return {"ok": True, "removed": removed, "kept_offline": kept_offline}

    @app.delete("/recipients/{user_id}")
    def unregister(user_id: str):
        if not db.delete_recipient(conn, user_id):
            raise HTTPException(status_code=404, detail="recipient not registered")
        return {"ok": True, "user_id": user_id}

    def _with_attachments(content: str, files: list[str]) -> str:
        """Message text plus one line per attached image, as a path the agent can open."""
        lines = [
            f"[attached image: {attachments_root / name}]" for name in files
        ]
        return "\n\n".join(part for part in (content, "\n".join(lines)) if part)

    def _deliver_from_owner(
        recipient_id: str,
        content: str,
        context: str | None,
        files: list[str] | None = None,
    ):
        """Deliver a message from the human operator to an agent's pane."""
        files = files or []
        recipient = db.get_recipient(conn, recipient_id)
        if recipient is None:
            mid = db.record_message(
                conn,
                OWNER,
                recipient_id,
                context,
                content,
                delivered=False,
                delivery_error="recipient not registered",
                attachments=files,
            )
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "recipient not registered",
                    "recipient": recipient_id,
                    "message_id": mid,
                },
            )
        _refuse_if_offline(OWNER, recipient, context, content, files)
        body = tmux.format_message(OWNER, context, _with_attachments(content, files))
        ok, err = tmux.deliver(
            recipient["tmux_pane"],
            body,
            message_prefix=recipient.get("message_prefix"),
            submit_key=recipient.get("submit_key") or tmux.DEFAULT_SUBMIT_KEY,
            flavor=recipient.get("flavor"),
        )
        mid = db.record_message(
            conn, OWNER, recipient_id, context, content, delivered=ok,
            delivery_error=err, attachments=files,
        )
        return {"ok": ok, "message_id": mid, "delivery_error": err}

    @app.post("/send")
    def send(req: SendReq):
        pane, _, server = _pane_ref(req.tmux_pane)
        sender = db.lookup_user_by_pane(conn, pane, server)
        if sender is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "sender not registered",
                    "tmux_pane": req.tmux_pane,
                },
            )
        if req.recipient == OWNER:
            # Messages to the human are recorded for the dashboard, not
            # injected into a pane.
            mid = db.record_message(
                conn,
                sender,
                OWNER,
                req.context,
                req.content,
                delivered=True,
                delivery_error=None,
            )
            return {"ok": True, "message_id": mid, "delivered_to_pane": None,
                    "delivery_error": None}
        recipient = db.get_recipient(conn, req.recipient)
        if recipient is None:
            mid = db.record_message(
                conn,
                sender,
                req.recipient,
                req.context,
                req.content,
                delivered=False,
                delivery_error="recipient not registered",
            )
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "recipient not registered",
                    "recipient": req.recipient,
                    "message_id": mid,
                },
            )
        _refuse_if_offline(sender, recipient, req.context, req.content)
        body = tmux.format_message(sender, req.context, req.content)
        ok, err = tmux.deliver(
            recipient["tmux_pane"],
            body,
            message_prefix=recipient.get("message_prefix"),
            submit_key=recipient.get("submit_key") or tmux.DEFAULT_SUBMIT_KEY,
            flavor=recipient.get("flavor"),
        )
        mid = db.record_message(
            conn,
            sender,
            req.recipient,
            req.context,
            req.content,
            delivered=ok,
            delivery_error=err,
        )
        return {
            "ok": ok,
            "message_id": mid,
            "delivered_to_pane": recipient["tmux_pane"],
            "delivery_error": err,
        }

    @app.post("/status")
    def set_status(req: StatusReq):
        """An agent says, in a line, what it is working on."""
        pane, _, server = _pane_ref(req.tmux_pane)
        user_id = db.lookup_user_by_pane(conn, pane, server)
        if user_id is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "sender not registered", "tmux_pane": req.tmux_pane},
            )
        text = " ".join(req.text.split())
        if not text:
            raise HTTPException(status_code=422, detail={"error": "status is empty"})
        db.record_summary(conn, user_id, text, "agent")
        return {"ok": True, "user_id": user_id, "status": text}

    @app.get("/messages")
    def messages(user: str | None = None, limit: int = 50):
        return {"messages": db.fetch_messages(conn, user, limit)}

    @app.post("/owner/send")
    def owner_send(req: OwnerSendReq):
        content = req.content.strip()
        if not content and not req.attachments:
            raise HTTPException(
                status_code=422, detail={"error": "message needs text or an image"}
            )
        unknown = [
            name for name in req.attachments
            if attachments.resolve(attachments_root, name) is None
        ]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail={"error": "unknown attachment", "attachments": unknown},
            )
        return _deliver_from_owner(req.recipient, content, req.context, req.attachments)

    @app.post("/attachments")
    async def attachments_upload(request: Request):
        """Store a pasted or dropped image; the raw bytes are the request body."""
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > attachments.MAX_BYTES:
            raise HTTPException(status_code=413, detail={"error": "image too large"})
        data = await request.body()
        try:
            name = await asyncio.to_thread(attachments.save, attachments_root, data)
        except ValueError as exc:
            status = 413 if len(data) > attachments.MAX_BYTES else 415
            raise HTTPException(status_code=status, detail={"error": str(exc)})
        return {
            "ok": True,
            "name": name,
            "url": f"/attachments/{name}",
            "path": str(attachments_root / name),
        }

    @app.get("/attachments/{name}")
    def attachments_get(name: str):
        path = attachments.resolve(attachments_root, name)
        if path is None:
            raise HTTPException(status_code=404, detail={"error": "unknown attachment"})
        return FileResponse(
            path,
            media_type=attachments.media_type(name),
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )

    def _team_line(user_id: str) -> str:
        """One sentence telling an agent who its teammates are right now."""
        recipient = db.get_recipient(conn, user_id)
        if recipient is None or not recipient.get("team_id"):
            return ""
        team = db.get_team(conn, recipient["team_id"])
        if team is None:
            return ""
        others = [m for m in team["members"] if m != user_id]
        mates = ", ".join(others) if others else "no one else yet"
        line = f" You are on team '{team['name']}' with {mates}"
        if team["queen"]:
            line += f" (queen: {team['queen']})"
        return line + "."

    def _notify_assignment(task: dict):
        hint = (
            f"Before editing, use branch task/{task['id']} in a dedicated git worktree. "
            f"Record it when you start: agent-swarm task-update {task['id']} "
            f"--worktree /absolute/path --status picked_up. "
            f"When finished: agent-swarm task-update {task['id']} --status done "
            f"--note \"...\". The note is required and the close is refused "
            f"without one. {NOTE_GUIDANCE} "
            f"When you start, also run agent-swarm status \"working on "
            f"#{task['id']}: <a few words>\" so the dashboard shows it."
        )
        content = f"You are assigned task #{task['id']}: {task['title']}."
        if task.get("description"):
            content += f" Details: {task['description']}."
        content += f" {hint}{_team_line(task['assignee'])}"
        try:
            _deliver_from_owner(task["assignee"], content, f"task #{task['id']}")
        except HTTPException:
            pass  # assignee validated by callers; pane may still be gone

    def _notify_team_assignment(task: dict):
        team = db.get_team(conn, task["team_id"])
        if team is None:
            return
        context = f"task #{task['id']}"
        detail = f" Details: {task['description']}." if task.get("description") else ""
        if team["queen"]:
            content = (
                f"Task #{task['id']} is assigned to your team '{team['name']}': "
                f"{task['title']}.{detail} As queen, parcel it out: split it into "
                f"subtasks or hand it to a teammate with agent-swarm task-update "
                f"{task['id']} --assignee <member>, then monitor progress."
            )
            targets = [team["queen"]]
        else:
            content = (
                f"Task #{task['id']} is assigned to your team '{team['name']}' "
                f"(no queen yet): {task['title']}.{detail} Coordinate with your "
                f"teammates; whoever takes it should run agent-swarm task-update "
                f"{task['id']} --assignee <yourself>."
            )
            targets = team["members"]
        for target in targets:
            try:
                _deliver_from_owner(target, content + _team_line(target), context)
            except HTTPException:
                pass  # membership validated; a pane may still be gone

    def _require_registered_assignee(assignee: str | None):
        if assignee and db.get_recipient(conn, assignee) is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "assignee not registered", "assignee": assignee},
            )

    def _require_known_team(team_id: int | None):
        if team_id is not None and db.get_team(conn, team_id) is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "unknown team", "team_id": team_id},
            )

    @app.get("/tasks")
    def tasks_list():
        return {"tasks": db.list_tasks(conn)}

    def _set_deps(task_id: int, depends_on: list[int]):
        try:
            db.set_task_deps(conn, task_id, depends_on)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)})

    @app.post("/tasks")
    def tasks_create(req: TaskCreateReq):
        _require_registered_assignee(req.assignee)
        _require_known_team(req.team_id)
        task = db.create_task(
            conn, req.title, req.description, req.assignee, req.team_id
        )
        if req.depends_on:
            _set_deps(task["id"], req.depends_on)
            task = db.get_task(conn, task["id"])
        if task["assignee"]:
            _notify_assignment(task)
        elif task["team_id"]:
            _notify_team_assignment(task)
        return {"ok": True, "task": task}

    @app.patch("/tasks/{task_id}")
    def tasks_update(task_id: int, req: TaskUpdateReq):
        before = db.get_task(conn, task_id)
        if before is None:
            raise HTTPException(status_code=404, detail={"error": "unknown task"})
        kwargs = {}
        if req.status is not None:
            kwargs["status"] = req.status
        if "assignee" in req.model_fields_set:
            _require_registered_assignee(req.assignee)
            kwargs["assignee"] = req.assignee or None
        if "team_id" in req.model_fields_set:
            _require_known_team(req.team_id)
            kwargs["team_id"] = req.team_id
        if "worktree" in req.model_fields_set:
            kwargs["worktree"] = req.worktree
        if "note" in req.model_fields_set:
            kwargs["note"] = (req.note or "").strip() or None
        if "depends_on" in req.model_fields_set:
            _set_deps(task_id, req.depends_on or [])
        # Closing is the one moment the worker still has the context needed to
        # say how the work is checked, so it is the moment we insist on it.
        if req.status == "done" and not (kwargs.get("note") or before["note"]):
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "a task needs a note before it can be closed",
                    "note": NOTE_GUIDANCE,
                },
            )
        task = db.update_task(conn, task_id, **kwargs)
        if task["assignee"] and task["assignee"] != before["assignee"]:
            _notify_assignment(task)
        elif task["team_id"] and task["team_id"] != before["team_id"]:
            _notify_team_assignment(task)
        return {"ok": True, "task": task}

    @app.get("/api/spawn-options")
    def spawn_options():
        return {"harnesses": tmux.spawn_options()}

    @app.post("/agents/spawn")
    def agents_spawn(req: SpawnReq):
        command = tmux.spawn_launch_command(req.flavor, req.model, req.autonomy)
        # Only record the model when it is one that actually launched.
        spec = tmux.HARNESS_SPAWN.get(req.flavor)
        model = req.model if (spec and req.model in spec.models) else None
        pane, err = tmux.spawn_window(command=command)
        if pane is None:
            raise HTTPException(
                status_code=500,
                detail={"error": "could not create tmux window", "detail": err},
            )
        # A spawned agent always lands in a pane on the server's own machine.
        user_id = names.pick_unused(
            conn, tmux.handle_tag(req.flavor, model, tmux.local_host())
        )
        _, label, server = _pane_ref(pane)
        db.register(
            conn,
            user_id,
            pane,
            None,
            model,
            req.flavor,
            None,
            None,
            tmux.submit_key_for_flavor(req.flavor),
            tmux_server=server,
            pane_label=label,
        )
        tmux.tag_pane(pane, user_id)
        tmux.rename_window(pane, user_id)
        return {
            "ok": True, "user_id": user_id, "tmux_pane": pane, "pane_label": label,
            "flavor": req.flavor, "model": model, "autonomy": req.autonomy,
        }

    @app.post("/agents/{user_id}/stop")
    def agents_stop(user_id: str):
        recipient = db.get_recipient(conn, user_id)
        if recipient is None:
            raise HTTPException(status_code=404, detail={"error": "unknown agent"})
        pane = recipient["tmux_pane"]
        # A pane that is gone, or that only holds a bare shell, has no agent
        # to stop; leave the shell (and the registration) alone.
        if _stale(recipient, tmux.server_id()) or pane not in tmux.live_agent_panes():
            return {
                "ok": True, "user_id": user_id, "tmux_pane": pane,
                "already_stopped": True,
            }
        ok, err = tmux.kill_pane(pane)
        if not ok:
            raise HTTPException(
                status_code=500,
                detail={"error": "could not stop tmux pane", "detail": err},
            )
        return {
            "ok": True, "user_id": user_id, "tmux_pane": pane,
            "already_stopped": False,
        }

    @app.get("/teams")
    def teams_list():
        return {"teams": db.list_teams(conn)}

    @app.post("/teams")
    def teams_create(req: TeamCreateReq):
        return {"ok": True, "team": db.create_team(conn, req.name.strip())}

    @app.patch("/teams/{team_id}")
    def teams_update(team_id: int, req: TeamUpdateReq):
        kwargs = {}
        if req.name is not None:
            kwargs["name"] = req.name.strip()
        if "queen" in req.model_fields_set:
            kwargs["queen"] = req.queen or None
        try:
            team = db.update_team(conn, team_id, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)})
        if team is None:
            raise HTTPException(status_code=404, detail={"error": "unknown team"})
        promotion = None
        if kwargs.get("queen"):
            objective = (req.objective or "").strip() or (
                "Coordinate your team to execute the shared task board."
            )
            promotion = _deliver_from_owner(
                team["queen"], _queen_prompt(team, objective), "queen-promotion"
            )
        return {"ok": True, "team": team, "promotion": promotion}

    @app.delete("/teams/{team_id}")
    def teams_delete(team_id: int):
        if not db.delete_team(conn, team_id):
            raise HTTPException(status_code=404, detail={"error": "unknown team"})
        return {"ok": True}

    @app.post("/agents/{user_id}/team")
    def agents_set_team(user_id: str, req: AgentTeamReq):
        try:
            recipient = db.set_agent_team(conn, user_id, req.team_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"error": str(exc)})
        if recipient is None:
            raise HTTPException(status_code=404, detail={"error": "unknown agent"})
        return {"ok": True, "recipient": recipient}

    @app.post("/agents/{user_id}/model")
    def agents_set_model(user_id: str, req: AgentModelReq):
        model = (req.model or "").strip() or None
        recipient = db.set_recipient_model(conn, user_id, model)
        if recipient is None:
            raise HTTPException(status_code=404, detail={"error": "unknown agent"})
        return {"ok": True, "recipient": recipient}

    @app.get("/", response_class=HTMLResponse)
    def portal():
        return PORTAL_PATH.read_text()

    @app.get("/api/state")
    def state(limit: int = 300):
        recipients = _annotated_recipients()
        summaries = db.summaries_by_user(conn)
        for r in recipients:
            r["pane_alive"] = r["alive"]
            r["summaries"] = summaries.get(r["user_id"], [])
            row = registry.get(r["user_id"])
            r["activity"] = (
                {"status": row["status"], "detail": row["detail"], "since": row["since"]}
                if row
                else dict(UNKNOWN_ACTIVITY)
            )
        msgs = db.fetch_messages(conn, None, limit)
        msgs.reverse()  # oldest first for thread rendering
        return {
            "now": time.time(),
            "recipients": recipients,
            "messages": msgs,
            "tasks": db.list_tasks(conn),
            "teams": db.list_teams(conn),
        }

    @app.get("/api/peek/{user_id}")
    def peek(user_id: str):
        recipient = db.get_recipient(conn, user_id)
        if recipient is None:
            raise HTTPException(status_code=404, detail={"error": "unknown agent"})
        text, err = tmux.capture_pane(recipient["tmux_pane"])
        live = tmux.pane_table().get(recipient["tmux_pane"])
        return {
            "user_id": user_id,
            "tmux_pane": recipient["tmux_pane"],
            "pane_label": live["label"] if live else recipient.get("pane_label") or recipient["tmux_pane"],
            "text": text,
            "error": err,
        }

    return app


app = create_app()


def _run() -> None:
    """Console-script entry: `agent-swarm-server` starts uvicorn on 127.0.0.1:8765."""
    import uvicorn

    port = int(
        os.environ.get("AGENT_SWARM_PORT", os.environ.get("AGENT_MSG_PORT", "8765"))
    )
    host = os.environ.get(
        "AGENT_SWARM_HOST", os.environ.get("AGENT_MSG_HOST", "127.0.0.1")
    )
    uvicorn.run("agent_swarm.server:app", host=host, port=port, reload=False)
