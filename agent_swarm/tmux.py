"""Tmux delivery. Keeps stdin/text-injection details in one place."""

from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
import time


def current_pane() -> str | None:
    """Return the caller's own pane id (session:window.pane), or None if not in tmux."""
    pane_target = os.environ.get("TMUX_PANE")
    command = ["tmux", "display-message", "-p"]
    if pane_target:
        command.extend(["-t", pane_target])
    command.append("#S:#I.#P")
    try:
        out = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    val = out.stdout.strip()
    return val or None


DEFAULT_FLAVOR = "generic"

DEFAULT_SUBMIT_KEY = "C-m"

FLAVOR_SUBMIT_KEYS = {
    "generic": DEFAULT_SUBMIT_KEY,
    "claude": DEFAULT_SUBMIT_KEY,
    "codex": "Enter",
    "hermes": DEFAULT_SUBMIT_KEY,
    "pi": "Enter",
}

FLAVOR_SUBMIT_DELAYS = {
    "codex": 0.2,
}

SUBMIT_VERIFY_DELAY = float(
    os.environ.get(
        "AGENT_SWARM_SUBMIT_VERIFY_DELAY",
        os.environ.get("AGENT_MSG_SUBMIT_VERIFY_DELAY", "1.5"),
    )
)


def _has_label_token(label: str, token: str) -> bool:
    return (
        re.search(rf"(^|[^a-z0-9]){re.escape(token)}([^a-z0-9]|$)", label)
        is not None
    )


def infer_flavor(model: str | None) -> str:
    """Best-effort default delivery flavor from a telemetry model label."""
    if not model:
        return DEFAULT_FLAVOR
    label = model.lower()
    if "codex" in label:
        return "codex"
    if "claude" in label:
        return "claude"
    if "hermes" in label:
        return "hermes"
    if _has_label_token(label, "pi"):
        return "pi"
    return DEFAULT_FLAVOR


# Named model lines, which identify a model far better than its family does.
# Checked before the generic fallback so "claude-opus-4-7" reads as "opus"
# rather than the redundant "claude".
_MODEL_LINE_KEYWORDS = [
    "opus", "sonnet", "haiku", "fable",  # claude lines
    "sol", "terra", "luna",  # codex model codenames
    "gemini",
]


def model_line(model: str | None) -> str | None:
    """Short name for a model label's specific line, e.g. "claude-opus-4-7" -> "opus"."""
    if not model:
        return None
    label = model.lower()
    for kw in _MODEL_LINE_KEYWORDS:
        if _has_label_token(label, kw):
            return kw
    # Unnamed line: use the leading family token with its major version, so
    # "gpt-5-codex" -> "gpt5" stays distinct from a later "gpt-6-codex".
    match = re.match(r"[^a-z]*([a-z]+)[^0-9a-z]*(\d+)?", label)
    if not match:
        return None
    family, version = match.group(1), match.group(2)
    return f"{family}{version}" if version else family


def local_host() -> str:
    """This machine's short name, as agents should report it.

    AGENT_SWARM_NODE wins so a machine whose hostname is long or ambiguous can
    present a better one; cross-machine setups rely on the same override.
    """
    return os.environ.get("AGENT_SWARM_NODE") or socket.gethostname().split(".")[0]


def host_tag(host: str | None) -> str | None:
    """Short handle-safe token for a machine name, e.g. "karans-linux.local" -> "karanslinux".

    Only the first DNS label is kept, then everything outside [a-z0-9] is
    dropped rather than turned into a hyphen: the handle already uses hyphens
    to separate its parts, so a host must not be able to add more of them.
    """
    if not host:
        return None
    label = host.strip().lower().split(".")[0]
    token = re.sub(r"[^a-z0-9]", "", label)
    return token[:12] or None


def handle_tag(
    flavor: str | None, model: str | None, host: str | None = None
) -> str | None:
    """Suffix identifying an agent, e.g. ("claude", "opus", "karans-linux") -> "claude-opus-karanslinux".

    Auto-assigned handles append this to an animal name so agents drawing from
    the same pool are told apart by what they actually are and where they run.
    The harness leads because it is always known and decides delivery; the
    model line follows only when it adds something the harness does not, so a
    bare "claude-code" stays "claude" rather than "claude-claude"; the host
    trails as the "where", and is omitted when the agent did not report one.
    """
    harness = (flavor or "").lower() or None
    line = model_line(model)
    if harness is None:
        parts = [line]
    elif line is None or line == harness or line.startswith(harness):
        parts = [harness]
    else:
        parts = [harness, line]
    parts.append(host_tag(host))
    kept = [p for p in parts if p]
    return "-".join(kept) if kept else None


def submit_key_for_flavor(flavor: str | None) -> str:
    """Return the default submit key for a delivery flavor."""
    if not flavor:
        return DEFAULT_SUBMIT_KEY
    return FLAVOR_SUBMIT_KEYS.get(flavor.lower(), DEFAULT_SUBMIT_KEY)


def submit_delay_for_flavor(flavor: str | None) -> float:
    """Return the delay to wait after text injection before submit."""
    if not flavor:
        return 0.0
    return FLAVOR_SUBMIT_DELAYS.get(flavor.lower(), 0.0)


def status_title(user_id: str, flavor: str | None = None) -> str:
    """Return the short label shown in tmux pane titles."""
    if flavor:
        return f"agent-swarm: {user_id} ({flavor})"
    return f"agent-swarm: {user_id}"


def set_pane_title(pane: str, title: str) -> tuple[bool, str | None]:
    """Set a tmux pane title without renaming the window or agent session."""
    try:
        subprocess.run(
            ["tmux", "select-pane", "-t", pane, "-T", title],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip() or str(e)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return False, str(e)
    return True, None


def rename_window(pane: str, name: str) -> tuple[bool, str | None]:
    """Rename the tmux window containing `pane` so it shows the agent's id
    in the window list. Also disables automatic renaming so the launched
    command can't clobber it. Returns (ok, error_message_or_None)."""
    try:
        subprocess.run(
            ["tmux", "set-window-option", "-t", pane, "automatic-rename", "off"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        subprocess.run(
            ["tmux", "rename-window", "-t", pane, name],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip() or str(e)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return False, str(e)
    return True, None


def _composer_holds_text(pane: str) -> bool:
    """True when the row under the cursor is more than a bare prompt.

    After a successful submit the composer collapses to an empty prompt line.
    When the submit key was swallowed (e.g. Codex still consuming a paste burst)
    the text — or Codex's "[Pasted Content N chars]" placeholder — is still there.
    """
    try:
        pos = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane, "#{cursor_y}"],
            capture_output=True, text=True, check=True, timeout=2,
        )
        y = int(pos.stdout.strip())
        screen = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", pane],
            capture_output=True, text=True, check=True, timeout=3,
        )
    except (ValueError, subprocess.SubprocessError, FileNotFoundError):
        return False
    rows = screen.stdout.splitlines()
    if y < 0 or y >= len(rows):
        return False
    row = rows[y].strip()
    return len(re.sub(r"^[>›❯$%#]+", "", row).strip()) > 0


def deliver(
    pane: str,
    text: str,
    message_prefix: str | None = None,
    submit_key: str = DEFAULT_SUBMIT_KEY,
    flavor: str | None = None,
) -> tuple[bool, str | None]:
    """Paste text into a tmux pane, then submit it.

    The text goes in as a bracketed paste (tmux only adds the paste markers when
    the pane's application has enabled them), so TUIs that detect typing bursts
    as pastes — Codex in particular — receive one atomic paste event and the
    following submit key is unambiguous. Returns (ok, error_message_or_None).
    """
    injected = f"{message_prefix or ''}{text}"
    buf = f"agent-swarm-{os.getpid()}-{time.monotonic_ns()}"
    try:
        subprocess.run(
            ["tmux", "load-buffer", "-b", buf, "-"],
            input=injected, capture_output=True, text=True, check=True, timeout=5,
        )
        subprocess.run(
            ["tmux", "paste-buffer", "-p", "-d", "-b", buf, "-t", pane],
            capture_output=True, text=True, check=True, timeout=5,
        )
        time.sleep(max(0.05, submit_delay_for_flavor(flavor)))
        subprocess.run(
            ["tmux", "send-keys", "-t", pane, submit_key],
            capture_output=True, text=True, check=True, timeout=5,
        )
        time.sleep(SUBMIT_VERIFY_DELAY)
        if _composer_holds_text(pane):
            # Retry only the submit key once; re-pasting would duplicate text.
            subprocess.run(
                ["tmux", "send-keys", "-t", pane, submit_key],
                capture_output=True, text=True, check=True, timeout=5,
            )
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip() or str(e)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return False, str(e)
    return True, None


AGENTS_SESSION = "agents"

# Harnesses the dashboard can spawn. Each has a launch binary, the CLI flag
# that selects a model, and a curated set of known models offered in the UI.
# "generic" is intentionally not spawnable: launching a bare shell produces a
# registered pane with no agent in it, which is not a working target.
#
# startup_args are always passed: they remove interactive startup blockers
# that would leave a freshly spawned pane stuck before the agent is usable
# (e.g. codex's update prompt). auto_args additionally put the harness in a
# non-blocking permission mode so a spawned worker never stops to ask for
# approval; they are only passed when the spawn requests autonomy "auto".
# Every flag verified against the installed harness in a live pane.
class HarnessSpec:
    def __init__(
        self,
        binary: str,
        model_flag: str,
        models: list[str],
        startup_args: str = "",
        auto_args: str = "",
    ):
        self.binary = binary
        self.model_flag = model_flag
        self.models = models
        self.startup_args = startup_args
        self.auto_args = auto_args


HARNESS_SPAWN: dict[str, HarnessSpec] = {
    "claude": HarnessSpec(
        "claude",
        "--model",
        ["opus", "sonnet", "haiku"],
        auto_args="--permission-mode bypassPermissions",
    ),
    "codex": HarnessSpec(
        "codex",
        "--model",
        ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"],
        startup_args="-c check_for_update_on_startup=false",
        auto_args="--ask-for-approval never --sandbox workspace-write",
    ),
    "pi": HarnessSpec(
        "pi",
        "--model",
        [
            "~anthropic/claude-opus-latest",
            "~anthropic/claude-sonnet-latest",
            "~openai/gpt-latest",
        ],
        # pi does not gate commands behind approval prompts; auto needs
        # no extra flags.
    ),
    "hermes": HarnessSpec(
        "hermes",
        "-m",
        [],
        auto_args="--yolo --accept-hooks",
    ),
}

SPAWNABLE_FLAVORS = tuple(HARNESS_SPAWN)


def spawn_options() -> list[dict]:
    """The harness/model menu the dashboard offers, as plain data."""
    return [
        {"flavor": flavor, "models": spec.models}
        for flavor, spec in HARNESS_SPAWN.items()
    ]


def spawn_launch_command(
    flavor: str, model: str | None = None, autonomy: str = "auto"
) -> str | None:
    """Build the shell command that launches a harness in a fresh pane.

    Returns None for an unspawnable flavor. A model is only honored when it is
    one of the harness's known models; it is shell-quoted so patterns like
    `~anthropic/claude-opus-latest` are passed literally (no tilde expansion).
    autonomy "auto" (the default) adds the harness's non-blocking permission
    flags; "supervised" launches it in its normal ask-first mode.
    """
    spec = HARNESS_SPAWN.get(flavor)
    if spec is None:
        return None
    parts = [spec.binary]
    if spec.startup_args:
        parts.append(spec.startup_args)
    if model and model in spec.models:
        parts.append(f"{spec.model_flag} {shlex.quote(model)}")
    if autonomy == "auto" and spec.auto_args:
        parts.append(spec.auto_args)
    return " ".join(parts)


def spawn_window(
    session: str = AGENTS_SESSION, command: str | None = None
) -> tuple[str | None, str | None]:
    """Create a detached tmux window (and session if needed) and optionally
    launch a command in it. Returns (pane_id, error_or_None)."""
    fmt = "#S:#I.#P"
    try:
        has = subprocess.run(
            ["tmux", "has-session", "-t", session],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if has.returncode != 0:
            out = subprocess.run(
                ["tmux", "new-session", "-d", "-s", session,
                 "-x", "220", "-y", "50", "-P", "-F", fmt],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
        else:
            out = subprocess.run(
                ["tmux", "new-window", "-d", "-t", session, "-P", "-F", fmt],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
        pane = out.stdout.strip()
        if not pane:
            return None, "tmux did not report a pane id"
        if command:
            subprocess.run(
                ["tmux", "send-keys", "-t", pane, command, "C-m"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
        return pane, None
    except subprocess.CalledProcessError as e:
        return None, e.stderr.strip() or str(e)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return None, str(e)


def list_panes() -> set[str]:
    """Return all live pane ids (session:window.pane); empty set if tmux is unavailable."""
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#S:#I.#P"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return set()
    return {line for line in out.stdout.splitlines() if line}


# A pane whose foreground process is one of these has no agent in it: the
# harness exited (typically a reboot) and tmux restored, or fell back to, a
# plain shell. Delivering there would type the message into the shell.
SHELL_COMMANDS = {"bash", "zsh", "sh", "dash", "fish", "ksh", "tcsh", "csh"}


def pane_commands() -> dict[str, str]:
    """Map every live pane id to its foreground command; {} if tmux is unavailable."""
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#S:#I.#P\t#{pane_current_command}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return {}
    result = {}
    for line in out.stdout.splitlines():
        pane, _, command = line.partition("\t")
        if pane:
            result[pane] = command.strip()
    return result


def live_agent_panes() -> set[str]:
    """Panes that exist and are running something other than a bare shell."""
    return {pane for pane, cmd in pane_commands().items() if cmd not in SHELL_COMMANDS}


def offline_reason(pane: str, existing: set[str], live: set[str]) -> str | None:
    """Why a registered pane can't take a message right now, or None if it can."""
    if pane not in existing:
        return f"recipient offline: pane {pane} no longer exists"
    if pane not in live:
        return f"recipient offline: pane {pane} is a bare shell (agent not running)"
    return None


def kill_pane(pane: str) -> tuple[bool, str | None]:
    """Kill a tmux pane. Returns (ok, error_message_or_None)."""
    try:
        subprocess.run(
            ["tmux", "kill-pane", "-t", pane],
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        )
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip() or str(e)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return False, str(e)
    return True, None


def capture_pane(pane: str) -> tuple[str | None, str | None]:
    """Return the pane's visible screen as text. Returns (text, error_or_None)."""
    try:
        out = subprocess.run(
            ["tmux", "capture-pane", "-p", "-J", "-t", pane],
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        )
    except subprocess.CalledProcessError as e:
        return None, e.stderr.strip() or str(e)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return None, str(e)
    return out.stdout, None


def format_message(sender: str, context: str | None, content: str) -> str:
    """Compose the inbound message body that lands in the recipient's pane."""
    head = f"[agent-msg from {sender}"
    if context:
        head += f" · {context}"
    head += "] "
    if sender == "owner":
        head += (
            'Reply to owner via the agent-swarm API (POST /send with recipient "owner", '
            'or `agent-msg send --to owner --message "..."`) so your response appears on the dashboard.\n\n'
        )
    return head + content
