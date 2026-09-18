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
    "Codex agent; send normal agent-swarm messages. No /queue prefix is needed."
)


MODEL_ENV = ("CLAUDE_MODEL", "ANTHROPIC_MODEL", "CODEX_MODEL")


def helper_env(tmp_path: Path, fake_bin: Path, **extra: str) -> dict[str, str]:
    # Hermetic: no model from the caller's env or real ~/.codex/config.toml.
    env = {k: v for k, v in os.environ.items() if k not in MODEL_ENV}
    return env | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CODEX_HOME": str(tmp_path / "codex-home"),
    } | extra


def run_helper(tmp_path: Path, *args: str, **env: str) -> list[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    agent_swarm = fake_bin / "agent-swarm"
    agent_swarm.write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' "$@"\n')
    agent_swarm.chmod(0o755)
    env = helper_env(tmp_path, fake_bin, **env)
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
        "--flavor",
        "codex",
        "--instructions",
        DEFAULT_INSTRUCTIONS,
    ]


def test_codex_helper_preserves_explicit_instructions(tmp_path):
    assert run_helper(tmp_path, "--instructions", "Keep messages short.") == [
        "register",
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


def run_claude_helper(tmp_path: Path, *args: str, **env: str) -> list[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    agent_swarm = fake_bin / "agent-swarm"
    agent_swarm.write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' "$@"\n')
    agent_swarm.chmod(0o755)
    env = helper_env(tmp_path, fake_bin, **env)
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
        "--flavor",
        "claude",
    ]


def test_claude_helper_forwards_requested_name(tmp_path):
    assert run_claude_helper(tmp_path, "--name", "jax") == [
        "register",
        "--flavor",
        "claude",
        "--name",
        "jax",
    ]


def test_helpers_send_no_placeholder_model(tmp_path):
    # With no model known, omit --model so the server keeps any label on record.
    assert "--model" not in run_helper(tmp_path / "codex")
    assert "--model" not in run_claude_helper(tmp_path / "claude")


def test_helpers_forward_explicit_model(tmp_path):
    out = run_claude_helper(tmp_path, "--model", "claude-opus-4-7")
    assert out[:3] == ["register", "--model", "claude-opus-4-7"]


def test_claude_helper_reads_model_from_env(tmp_path):
    out = run_claude_helper(tmp_path, ANTHROPIC_MODEL="claude-sonnet-4-6")
    assert out[:3] == ["register", "--model", "claude-sonnet-4-6"]


def test_codex_helper_reads_model_from_config(tmp_path):
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "config.toml").write_text(
        'model = "gpt-6-astra"\nmodel_reasoning_effort = "medium"\n\n'
        '[profiles.fast]\nmodel = "gpt-5-mini"\n'
    )
    assert run_helper(tmp_path)[:3] == ["register", "--model", "gpt-6-astra"]
    # The env still wins over the config.
    out = run_helper(tmp_path / "env", CODEX_MODEL="gpt-5-codex")
    assert out[:3] == ["register", "--model", "gpt-5-codex"]


def test_codex_helper_forwards_requested_name(tmp_path):
    assert "--name" in run_helper(tmp_path, "--name", "jax")


def test_helpers_reject_legacy_name_flags(tmp_path):
    for helper in (CLAUDE_HELPER, HELPER):
        result = subprocess.run(
            [str(helper), "--user", "jax"], capture_output=True, text=True
        )
        assert result.returncode == 2
        assert "--name" in result.stderr
