"""Per-machine settings: where the hub is, what this machine is called, and
the token that proves it.

Read from the environment first, then from ~/.agent-swarm/node.toml, then
defaults. The file exists so that an agent already running in a tmux pane,
which inherited its environment at launch, can still find the hub: its
harness runs the CLI as a subprocess, and the CLI reads the file. A
single-machine install needs no file at all; the defaults are loopback.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HUB = "http://127.0.0.1:8765"


def config_path() -> Path:
    return Path(os.environ.get("AGENT_SWARM_CONFIG", "~/.agent-swarm/node.toml")).expanduser()


@dataclass(frozen=True)
class Settings:
    hub: str
    token: str | None
    node: str


def _file() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def hostname() -> str:
    return socket.gethostname().split(".")[0]


def load() -> Settings:
    file = _file()
    hub = (
        os.environ.get("AGENT_SWARM_URL")
        or os.environ.get("AGENT_MSG_URL")
        or file.get("hub")
        or DEFAULT_HUB
    )
    token = os.environ.get("AGENT_SWARM_TOKEN") or file.get("token") or None
    node = os.environ.get("AGENT_SWARM_NODE") or file.get("node") or hostname()
    return Settings(hub=hub.rstrip("/"), token=token, node=node)


def _toml_string(value: str) -> str:
    # A JSON string is a valid TOML basic string for anything we write.
    return json.dumps(value)


def write(hub: str, token: str | None, node: str) -> Path:
    """Write the settings file, readable by this user only (it holds the token).

    Written to a temporary file created with mode 0600 and then renamed over
    the target, so the token is never on disk world-readable, even briefly,
    and a crash mid-write leaves the old file intact.
    """
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# agent-swarm per-machine settings, written by `agent-swarm join`.",
        f"hub = {_toml_string(hub.rstrip('/'))}",
        f"node = {_toml_string(node)}",
    ]
    if token:
        lines.append(f"token = {_toml_string(token)}")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".node.toml.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
    return path
