"""Tests for the cute-name pool and its model-tag suffixing."""

import random
import sqlite3

from agent_swarm import names


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


def test_pick_unused_falls_back_to_numeric_suffix_when_pool_exhausted():
    conn = _conn()
    for animal in names.POOL:
        _take(conn, f"{animal}-opus")
    name = names.pick_unused(conn, "opus", rng=random.Random(1))
    base, _, suffix = name.rpartition("-")
    assert suffix == "2"
    assert base.endswith("-opus")
