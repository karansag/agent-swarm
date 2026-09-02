from __future__ import annotations

import os
import subprocess
from pathlib import Path


HELPER = (
    Path(__file__).parents[1]
    / "skills/codex/agent-swarm-register/scripts/register-codex-agent"
)
CODEX_SKILL = Path(__file__).parents[1] / "skills/codex/agent-swarm-register/SKILL.md"
CLAUDE_SKILL = Path(__file__).parents[1] / "skills/claude/agent-swarm-register/SKILL.md"
DEFAULT_INSTRUCTIONS = (
    "Codex agent; send normal agent-msg messages. No /queue prefix is needed."
)


def run_helper(tmp_path: Path, *args: str) -> list[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    agent_msg = fake_bin / "agent-msg"
    agent_msg.write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' "$@"\n')
    agent_msg.chmod(0o755)
    env = os.environ | {"PATH": f"{fake_bin}:{os.environ['PATH']}"}
    result = subprocess.run(
        [str(HELPER), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.splitlines()


def test_codex_helper_supplies_codex_accurate_default_instructions(tmp_path):
    assert run_helper(tmp_path) == [
        "register",
        "--model",
        "gpt-5-codex",
        "--flavor",
        "codex",
        "--instructions",
        DEFAULT_INSTRUCTIONS,
    ]


def test_codex_helper_preserves_explicit_instructions(tmp_path):
    assert run_helper(tmp_path, "--instructions", "Keep messages short.") == [
        "register",
        "--model",
        "gpt-5-codex",
        "--flavor",
        "codex",
        "--instructions",
        "Keep messages short.",
    ]


def test_codex_skill_does_not_tell_callers_to_pass_flavor():
    skill = CODEX_SKILL.read_text()
    assert "Always register Codex agents with `--flavor codex`" not in skill
    assert "Do not pass `--flavor`" in skill


def test_claude_skill_does_not_tell_callers_to_pass_flavor():
    skill = CLAUDE_SKILL.read_text()
    assert "Always register Claude agents with `--flavor claude`" not in skill
    assert "Do not pass `--flavor`" in skill


CLAUDE_HELPER = (
    Path(__file__).parents[1]
    / "skills/claude/agent-swarm-register/scripts/register-claude-agent"
)


def run_claude_helper(tmp_path: Path, *args: str) -> list[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    agent_msg = fake_bin / "agent-msg"
    agent_msg.write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' "$@"\n')
    agent_msg.chmod(0o755)
    env = os.environ | {"PATH": f"{fake_bin}:{os.environ['PATH']}"}
    result = subprocess.run(
        [str(CLAUDE_HELPER), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.splitlines()


def test_claude_helper_runs_with_no_optional_flags(tmp_path):
    # Regression: bash 3.2 treats an unguarded empty "${extra_args[@]}" under
    # `set -u` as an unbound variable, which broke every bare invocation.
    assert run_claude_helper(tmp_path) == [
        "register",
        "--model",
        "claude-code",
        "--flavor",
        "claude",
    ]


def test_claude_helper_forwards_requested_name(tmp_path):
    assert run_claude_helper(tmp_path, "--name", "jax") == [
        "register",
        "--model",
        "claude-code",
        "--flavor",
        "claude",
        "--name",
        "jax",
    ]


def test_codex_helper_forwards_requested_name(tmp_path):
    assert "--name" in run_helper(tmp_path, "--name", "jax")


def test_helpers_reject_legacy_name_flags(tmp_path):
    for helper in (CLAUDE_HELPER, HELPER):
        result = subprocess.run(
            [str(helper), "--user", "jax"], capture_output=True, text=True
        )
        assert result.returncode == 2
        assert "--name" in result.stderr
