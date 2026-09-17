"""Tests for the cute-name pool and its model-tag suffixing."""

import random
import sqlite3

from agent_swarm import names, tmux


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE recipients (user_id TEXT PRIMARY KEY)")
    return conn


def _take(conn, user_id):
    conn.execute("INSERT INTO recipients (user_id) VALUES (?)", (user_id,))


def test_pick_unused_without_tag_returns_bare_animal_name():
    conn = _conn()
    name = names.pick_unused(conn)
    assert name in names.POOL


def test_pick_unused_with_tag_combines_animal_and_tag():
    conn = _conn()
    name = names.pick_unused(conn, "opus")
    animal, _, tag = name.partition("-")
    assert animal in names.POOL
    assert tag == "opus"


def test_pick_unused_avoids_names_already_taken():
    conn = _conn()
    _take(conn, "otter-opus")
    name = names.pick_unused(conn, "opus", rng=random.Random(0))
    assert name != "otter-opus"


def test_same_animal_can_be_reused_under_a_different_tag():
    conn = _conn()
    _take(conn, "otter-opus")
    # "otter" itself, and "otter" under a different tag, are still free.
    assert names.pick_unused(conn) is not None
    name = names.pick_unused(conn, "sonnet", rng=random.Random(0))
    assert not name.endswith("-opus")


def test_every_generated_handle_can_be_requested_back():
    # An agent that loses its pane reclaims its handle with `register --name`,
    # which runs it through normalize_requested. The longest handle the
    # generator can produce must therefore still be a legal request.
    conn = _conn()
    longest_animal = max(names.POOL, key=len)
    tag = tmux.handle_tag("claude", "claude-fable-5-1", "karans-linux")
    generated = names.pick_unused(conn, tag)
    assert names.normalize_requested(generated) == generated
    assert names.normalize_requested(f"{longest_animal}-{tag}")


def test_pick_unused_falls_back_to_numeric_suffix_when_pool_exhausted():
    conn = _conn()
    for animal in names.POOL:
        _take(conn, f"{animal}-opus")
    name = names.pick_unused(conn, "opus", rng=random.Random(1))
    base, _, suffix = name.rpartition("-")
    assert suffix == "2"
    assert base.endswith("-opus")
