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
    "meerkat",
    "armadillo",
    "chinchilla",
    "jerboa",
    "vole",
    "weasel",
    "polecat",
    "genet",
    "coati",
    "tarsier",
    "loris",
    "bushbaby",
    "wallaby",
    "bandicoot",
    "echidna",
    "platypus",
    "aardvark",
    "hyrax",
    "dugong",
    "serval",
    "caracal",
    "margay",
    "jackal",
    "coyote",
    "vicuna",
    "alpaca",
    "okapi",
    "gerenuk",
    "dik-dik",
    "duiker",
    "peccary",
    "tenrec",
    "solenodon",
    "colugo",
    "pika",
    "degu",
    "agouti",
    "paca",
    "vizcacha",
    "kinkajou",
    "olingo",
    "cacomistle",
    "ringtail",
    "grison",
    "tayra",
    "linsang",
    "binturong",
    "fossa",
    "quoll",
    "numbat",
    "bilby",
    "potoroo",
    "sifaka",
    "indri",
    "galago",
    "toucan",
    "hornbill",
    "kookaburra",
    "shoveler",
    "avocet",
    "curlew",
    "sandpiper",
    "plover",
    "grebe",
    "cormorant",
    "gannet",
    "skua",
    "tern",
    "shrike",
    "chukar",
    "ptarmigan",
    "quetzal",
    "trogon",
    "hoopoe",
    "bittern",
    "gadwall",
    "smew",
    "goldeneye",
    "merganser",
    "chameleon",
    "iguana",
    "skink",
    "anole",
    "tuatara",
    "caecilian",
]


def pick_unused(
    conn: sqlite3.Connection,
    tag: str | None = None,
    rng: random.Random | None = None,
) -> str:
    """Return a cute name not yet taken in `recipients`. Falls back to suffixing.

    `tag` (typically a short model label like "opus" or "sol") is appended to
    the animal name so agents sharing the animal pool stay distinguishable,
    e.g. "ferret-opus". Without a tag, behaves like a plain animal name.
    """
    r = rng or random.Random()
    taken = {row[0] for row in conn.execute("SELECT user_id FROM recipients")}

    def with_tag(name: str) -> str:
        return f"{name}-{tag}" if tag else name

    candidates = [n for n in POOL if with_tag(n) not in taken]
    if candidates:
        return with_tag(r.choice(candidates))
    # Pool exhausted (even combined with the tag) — append a numeric suffix.
    base = with_tag(r.choice(POOL))
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


# Handles the server refuses to hand out: 'owner' is the human operator.
RESERVED = frozenset({"owner"})

# 48 rather than 32 so that every handle this module can generate is also one
# an agent may ask for: "salamander-claude-fable-karanslinux" is 35 characters,
# and an agent that loses its pane must be able to re-request the handle it had.
_VALID_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


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
            "name must be 1-48 characters of lowercase letters, digits or "
            "hyphens, and start with a letter or digit"
        )
    if candidate in RESERVED:
        raise InvalidName(f"'{candidate}' is a reserved handle")
    return candidate
