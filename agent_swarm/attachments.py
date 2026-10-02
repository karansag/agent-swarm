"""Files attached to messages and tasks, stored by content hash.

Delivery into a tmux pane is text-only, so an agent receives an attachment as
an absolute file path it can open with its own file-reading tool. The file
type is decided by sniffing the bytes, never by the client's claimed type, and
raster images are shown inline; all other files are forced downloads.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024
MAX_PER_MESSAGE = 10

DAY = 24 * 60 * 60
# An upload no message refers to yet is a draft; give it this long to be sent.
ORPHAN_GRACE = DAY
DEFAULT_RETENTION_DAYS = 30.0

MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}

_NAME = re.compile(r"^[0-9a-f]{64}\.(?:png|jpg|gif|webp|file\.[A-Za-z0-9][A-Za-z0-9._-]{0,119})$")


def sniff(data: bytes) -> str | None:
    """File extension for a supported image, from its leading bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save(root: Path, data: bytes, filename: str | None = None) -> str:
    """Store bytes. Non-image uploads require a filename and are downloads."""
    if not data:
        raise ValueError("empty upload")
    if len(data) > MAX_BYTES:
        raise ValueError(f"file larger than {MAX_BYTES // (1024 * 1024)} MB")
    ext = sniff(data)
    if ext is None:
        if not filename:
            raise ValueError("not a PNG, JPEG, GIF, or WebP image; provide a filename for other files")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename.replace("\\", "/").rsplit("/", 1)[-1])
        safe = safe.lstrip("._-")[:120] or "attachment"
        ext = f"file.{safe}"
    name = f"{hashlib.sha256(data).hexdigest()}.{ext}"
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if path.exists():
        # Re-pasting an old image restarts its orphan grace period.
        os.utime(path)
    else:
        tmp = root / f".{name}.{os.getpid()}.{time.monotonic_ns()}.part"
        tmp.write_bytes(data)
        tmp.replace(path)
    return name


def resolve(root: Path, name: str) -> Path | None:
    """Path of a stored attachment, or None if the name is malformed or unknown."""
    if not _NAME.match(name):
        return None
    path = root / name
    return path if path.is_file() else None


def is_image(name: str) -> bool:
    return bool(_NAME.fullmatch(name)) and ".file." not in name


def download_name(name: str) -> str:
    return name.split(".file.", 1)[-1] if ".file." in name else name


def media_type(name: str) -> str:
    return MEDIA_TYPES[name.rsplit(".", 1)[1]] if is_image(name) else "application/octet-stream"


def sweep(
    root: Path,
    last_used: dict[str, float],
    now: float,
    retention: float | None,
    orphan_grace: float = ORPHAN_GRACE,
) -> list[str]:
    """Delete attachments nobody needs any more; return the names removed.

    `last_used` maps each name to the time of the newest message carrying it.
    A file no message refers to is an abandoned draft upload and goes once it
    is older than `orphan_grace`. A referenced file goes once its newest
    message is older than `retention` seconds; None keeps those forever.
    Interrupted uploads (`.part` files) are cleared after the grace period.
    """
    if not root.is_dir():
        return []
    removed = []
    for path in root.iterdir():
        name = path.name
        try:
            if name.startswith(".") and name.endswith(".part"):
                if now - path.stat().st_mtime > orphan_grace:
                    path.unlink()
                continue
            if not _NAME.match(name):
                continue  # not ours; leave it alone
            used = last_used.get(name)
            if used is None:
                expired = now - path.stat().st_mtime > orphan_grace
            else:
                expired = retention is not None and now - used > retention
            if expired:
                path.unlink()
                removed.append(name)
        except FileNotFoundError:
            continue  # removed concurrently
    return removed
