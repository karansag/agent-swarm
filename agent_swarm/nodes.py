"""What the server asks of a machine's tmux, behind one interface.

The server never touches tmux directly. It asks the Node that owns the
recipient's pane, found by the recipient's `node` column. LocalNode is the
tmux the server runs beside; a node for another machine arrives with the
node daemon. Every method maps onto one tmux operation, so a remote
implementation is a transport, not a reinterpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from . import tmux


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
    name: str

    def snapshot(self) -> PaneSnapshot: ...
    def server_id(self) -> str | None: ...
    def resolve(self, target: str) -> tuple[str, str] | None: ...
    def capture(self, pane: str) -> tuple[str | None, str | None]: ...
    def deliver(
        self,
        pane: str,
        text: str,
        *,
        message_prefix: str | None = None,
        submit_key: str = tmux.DEFAULT_SUBMIT_KEY,
        flavor: str | None = None,
    ) -> tuple[bool, str | None]: ...
    def spawn(self, command: str | None) -> tuple[str | None, str | None]: ...
    def kill(self, pane: str) -> tuple[bool, str | None]: ...
    def tag_pane(self, pane: str, handle: str) -> tuple[bool, str | None]: ...
    def rename_window(self, pane: str, name: str) -> tuple[bool, str | None]: ...


class LocalNode:
    """The tmux on this machine.

    Looks tmux functions up at call time rather than binding them, so tests
    that monkeypatch the tmux module keep working through the node.
    """

    def __init__(self, name: str):
        self.name = name

    def snapshot(self) -> PaneSnapshot:
        return PaneSnapshot(
            server=tmux.server_id(),
            server_start=tmux.server_start_time(),
            existing=frozenset(tmux.list_panes()),
            live=frozenset(tmux.live_agent_panes()),
            table=tmux.pane_table(),
        )

    def server_id(self) -> str | None:
        return tmux.server_id()

    def resolve(self, target: str) -> tuple[str, str] | None:
        return tmux.resolve_pane(target)

    def capture(self, pane: str) -> tuple[str | None, str | None]:
        return tmux.capture_pane(pane)

    def deliver(
        self,
        pane: str,
        text: str,
        *,
        message_prefix: str | None = None,
        submit_key: str = tmux.DEFAULT_SUBMIT_KEY,
        flavor: str | None = None,
    ) -> tuple[bool, str | None]:
        return tmux.deliver(
            pane, text, message_prefix=message_prefix, submit_key=submit_key, flavor=flavor
        )

    def spawn(self, command: str | None) -> tuple[str | None, str | None]:
        return tmux.spawn_window(command=command)

    def kill(self, pane: str) -> tuple[bool, str | None]:
        return tmux.kill_pane(pane)

    def tag_pane(self, pane: str, handle: str) -> tuple[bool, str | None]:
        return tmux.tag_pane(pane, handle)

    def rename_window(self, pane: str, name: str) -> tuple[bool, str | None]:
        return tmux.rename_window(pane, name)


class NodeRegistry:
    """The nodes this server can reach right now, by name.

    Always holds the local node. A node that is absent is one the server
    cannot reach: its agents read offline and nothing is sent to it.
    """

    def __init__(self, local: Node):
        self.local = local
        self._nodes: dict[str, Node] = {local.name: local}

    def add(self, node: Node) -> None:
        self._nodes[node.name] = node

    def remove(self, name: str) -> None:
        if name != self.local.name:
            self._nodes.pop(name, None)

    def get(self, name: str | None) -> Node | None:
        return self._nodes.get(name or self.local.name)

    def names(self) -> list[str]:
        return list(self._nodes)
