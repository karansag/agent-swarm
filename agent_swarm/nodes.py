"""What the server asks of a machine's tmux, behind one interface.

The server never touches tmux directly. It asks the Node that owns the
recipient's pane, found by the recipient's `node` column. LocalNode is the
tmux the server runs beside; a node for another machine arrives with the
node daemon. Every method maps onto one tmux operation, so a remote
implementation is a transport, not a reinterpretation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from . import tmux


@dataclass(frozen=True)
class Result:
    """Outcome of an operation with a side effect.

    `unknown` means the node cannot say whether the side effect happened: a
    message may have been pasted and its result lost. The caller must not
    retry an unknown operation on its own, or the agent gets it twice.
    """

    status: Literal["ok", "failed", "unknown"]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class Spawned:
    """Outcome of a spawn: a Result plus the pane it made, when it did."""

    status: Literal["ok", "failed", "unknown"]
    pane: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class Unavailable(Exception):
    """The node could not observe its tmux coherently right now.

    Distinct from an empty snapshot: nothing is known, so nothing may be
    treated as confirmed absent.
    """


def new_op_id() -> str:
    """An id for a side-effecting operation that has no message row of its own."""
    return uuid.uuid4().hex


@dataclass(frozen=True)
class PaneSnapshot:
    """One look at a node's tmux: which panes exist and which hold an agent."""

    server: str | None  # tmux server id; None when tmux is not running
    server_start: float | None
    existing: frozenset[str]
    live: frozenset[str]  # existing panes running something other than a shell
    table: dict[str, dict[str, str]]  # pane id -> {label, command, title}

    def label(self, pane: str) -> str | None:
        row = self.table.get(pane)
        return row["label"] if row else None

    def title(self, pane: str) -> str | None:
        row = self.table.get(pane)
        return row["title"] if row else None


class Node(Protocol):
    """One machine's tmux.

    Every operation on a pane also names the tmux server that issued the
    pane id, and the node checks it before acting: pane ids start over when
    tmux restarts, so an id checked only at the hub could reach a different
    pane by the time the command runs. The check narrows that window; it is
    not atomic with the tmux calls that follow it.

    Every operation with a side effect (deliver, spawn, kill, tag_pane,
    rename_window) carries an op id, the message id for a delivery and a
    fresh id otherwise, and returns a Result that can be unknown. A node
    that may execute a command more than once (a remote one, after a
    reconnect) uses the id to return the earlier result instead of acting
    twice.

    snapshot() raises Unavailable when the node cannot observe its tmux
    coherently; callers treat that as nothing known, never as empty.
    """

    name: str

    def snapshot(self) -> PaneSnapshot: ...
    def server_id(self) -> str | None: ...
    def resolve(self, target: str) -> tuple[str, str] | None: ...
    def capture(self, pane: str, tmux_server: str | None) -> tuple[str | None, str | None]: ...
    def deliver(
        self,
        op_id: str,
        pane: str,
        tmux_server: str | None,
        text: str,
        *,
        attachments: list[str] = (),
        message_prefix: str | None = None,
        submit_key: str = tmux.DEFAULT_SUBMIT_KEY,
        flavor: str | None = None,
    ) -> Result: ...
    def spawn(self, op_id: str, command: str | None) -> Spawned: ...
    def kill(self, op_id: str, pane: str, tmux_server: str | None) -> Result: ...
    def tag_pane(self, op_id: str, pane: str, tmux_server: str | None, handle: str) -> Result: ...
    def rename_window(self, op_id: str, pane: str, tmux_server: str | None, name: str) -> Result: ...


def _stale_server(expected: str | None) -> str | None:
    """Why a pane id from `expected` cannot be used now, or None if it can."""
    if expected is None:
        return None
    current = tmux.server_id()
    if current == expected:
        return None
    return f"tmux server changed ({expected} is gone); the pane id is from an earlier session"


class LocalNode:
    """The tmux on this machine.

    Looks tmux functions up at call time rather than binding them, so tests
    that monkeypatch the tmux module keep working through the node.
    """

    def __init__(self, name: str, attachments_root: Path | None = None):
        self.name = name
        # Where attachments live on this machine. Delivery is text-only, so
        # an attachment reaches an agent as a path it can open; the path has
        # to be one on the machine the pane is on.
        self.attachments_root = attachments_root

    def render_attachments(self, text: str, paths: list[str]) -> str:
        """The message text plus one line per attached image, as a local path."""
        lines = [f"[attached image: {p}]" for p in paths]
        return "\n\n".join(part for part in (text, "\n".join(lines)) if part)

    def snapshot(self) -> PaneSnapshot:
        # One read of the pane table, bracketed by the server id, so a tmux
        # restart in between cannot mix one server's panes with another's
        # identity. Existing and live panes derive from that same read. Two
        # restarts in a row is not something to guess about.
        for _ in range(2):
            before = tmux.server_id()
            table = tmux.pane_table()
            server = tmux.server_id()
            if server == before:
                break
        else:
            raise Unavailable("tmux restarted during every attempt to read its panes")
        try:
            start = float(server.split(":")[1]) if server else None
        except (IndexError, ValueError):
            start = None
        return PaneSnapshot(
            server=server,
            server_start=start,
            existing=frozenset(table),
            live=frozenset(
                p for p, row in table.items() if row["command"] not in tmux.SHELL_COMMANDS
            ),
            table=table,
        )

    def server_id(self) -> str | None:
        return tmux.server_id()

    def resolve(self, target: str) -> tuple[str, str] | None:
        return tmux.resolve_pane(target)

    def capture(self, pane: str, tmux_server: str | None) -> tuple[str | None, str | None]:
        if stale := _stale_server(tmux_server):
            return None, stale
        return tmux.capture_pane(pane)

    def deliver(
        self,
        op_id: str,
        pane: str,
        tmux_server: str | None,
        text: str,
        *,
        attachments: list[str] = (),
        message_prefix: str | None = None,
        submit_key: str = tmux.DEFAULT_SUBMIT_KEY,
        flavor: str | None = None,
    ) -> Result:
        if stale := _stale_server(tmux_server):
            return Result("failed", stale)
        if attachments:
            root = self.attachments_root
            text = self.render_attachments(
                text, [str(root / name) if root else name for name in attachments]
            )
        # tmux.deliver is several subprocesses. It reports failure only while
        # nothing has reached the pane; once the paste may have landed it
        # raises Uncertain, which is exactly the unknown outcome.
        try:
            ok, err = tmux.deliver(
                pane, text, message_prefix=message_prefix, submit_key=submit_key, flavor=flavor
            )
        except tmux.Uncertain as e:
            return Result("unknown", str(e))
        return Result("ok" if ok else "failed", err)

    def spawn(self, op_id: str, command: str | None) -> Spawned:
        try:
            pane, err = tmux.spawn_window(command=command)
        except tmux.Uncertain as e:
            return Spawned("unknown", e.pane, str(e))
        return Spawned("ok", pane) if pane else Spawned("failed", None, err)

    def kill(self, op_id: str, pane: str, tmux_server: str | None) -> Result:
        if stale := _stale_server(tmux_server):
            return Result("failed", stale)
        try:
            ok, err = tmux.kill_pane(pane)
        except tmux.Uncertain as e:
            return Result("unknown", str(e))
        return Result("ok" if ok else "failed", err)

    def tag_pane(self, op_id: str, pane: str, tmux_server: str | None, handle: str) -> Result:
        if stale := _stale_server(tmux_server):
            return Result("failed", stale)
        ok, err = tmux.tag_pane(pane, handle)
        return Result("ok" if ok else "failed", err)

    def rename_window(self, op_id: str, pane: str, tmux_server: str | None, name: str) -> Result:
        if stale := _stale_server(tmux_server):
            return Result("failed", stale)
        ok, err = tmux.rename_window(pane, name)
        return Result("ok" if ok else "failed", err)


class NodeRegistry:
    """The nodes this server can reach right now, by name.

    Always holds the local node. A node that is absent is one the server
    cannot reach: its agents read offline and nothing is sent to it.
    """

    def __init__(self, local: Node):
        self.local = local
        self._nodes: dict[str, Node] = {local.name: local}

    def add(self, node: Node) -> None:
        # The local node is fixed for the server's life; a connection
        # claiming its name is misconfigured, never a replacement.
        if node.name == self.local.name:
            raise ValueError(f"{node.name} is this server's own node")
        self._nodes[node.name] = node

    def remove(self, name: str) -> None:
        if name != self.local.name:
            self._nodes.pop(name, None)

    def get(self, name: str | None) -> Node | None:
        return self._nodes.get(name or self.local.name)

    def names(self) -> list[str]:
        return list(self._nodes)
