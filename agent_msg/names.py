"""Cute name pool for auto-assigned recipient ids."""

from __future__ import annotations

import random
import re
import sqlite3

POOL = [
    "otter",
    "ferret",
    "badger",
    "panda",
    "tapir",
    "axolotl",
    "puffin",
    "quokka",
    "narwhal",
    "capybara",
    "mongoose",
    "lemur",
    "stoat",
    "marten",
    "ocelot",
    "wombat",
    "pangolin",
    "salamander",
    "kestrel",
    "magpie",
    "hedgehog",
    "raccoon",
    "fennec",
    "dormouse",
    "shrew",
    "manatee",
    "ibis",
    "heron",
    "viper",
    "newt",
    "civet",
    "gecko",
]


def pick_unused(conn: sqlite3.Connection, rng: random.Random | None = None) -> str:
    """Return a cute name not yet taken in `recipients`. Falls back to suffixing."""
    r = rng or random.Random()
    taken = {row[0] for row in conn.execute("SELECT user_id FROM recipients")}
    candidates = [n for n in POOL if n not in taken]
    if candidates:
        return r.choice(candidates)
    # Pool exhausted — append a numeric suffix.
    base = r.choice(POOL)
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


# Handles the server refuses to hand out: 'owner' is the human operator.
RESERVED = frozenset({"owner"})

_VALID_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class InvalidName(ValueError):
    """A requested handle that the server will not assign."""


def normalize_requested(name: str) -> str:
    """Validate an agent-requested handle, returning its canonical form.

    Handles are lowercase so routing is case-insensitive; they are used raw in
    tmux pane titles and message headers, so the character set stays tight.
    """
    candidate = name.strip().lower()
    if not _VALID_NAME.match(candidate):
        raise InvalidName(
            "name must be 1-32 characters of lowercase letters, digits or "
            "hyphens, and start with a letter or digit"
        )
    if candidate in RESERVED:
        raise InvalidName(f"'{candidate}' is a reserved handle")
    return candidate
