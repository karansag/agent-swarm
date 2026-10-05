import { TaskTrash } from "./task-trash.js";
import { html, render } from "htm/preact";
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";

import {
  POLL_MS,
  PEEK_MS,
  JSONH,
  FLAVOR_ICON,
  STATE,
  agentStatus,
  Avatar,
  Bee,
  MachineBadge,
  rel,
  currentTask,
  SUMMARY_SOURCE,
  pairKey,
  disp,
  focusHash,
  patchTask,
} from "./shared.js";
import { deliveryOutcome, spawnOutcome, spawnTarget, unansweredOutcome } from "./outcome.js";
import { machineColor, machineList, machineName } from "./machines.js";
import { COMPACT_LAYOUT, useMedia } from "./use-media.js";
import { HiveView } from "./hive.js";
import { HistoryView, HISTORY_ROUTE, historyHash } from "./history.js";
import { AttachmentLink, AttachmentList, AttachmentPicker, useAttachments } from "./attachments.js";
import { createBottomFollower } from "./scroll-follow.js";
import { renderMarkdown } from "./markdown.js";
import "../styles.css";

/* ---------- roster (right sidebar) ---------- */

function RosterChip({ r, state, team, selected, unread, ping, refresh }) {
  const [stopping, setStopping] = useState(false);
  const [crowning, setCrowning] = useState(false);
  const isQueen = !!team && team.queen === r.user_id;
  const task = currentTask(state.tasks, r.user_id);
  const flavor = (r.flavor || "generic").toLowerCase();
  const status = agentStatus(r);
  const st = STATE[status] || STATE.unknown;
  const detail = r.activity && r.activity.detail;
  const attention = status === "needs_attention";
  const doing = r.summaries && r.summaries[0];
  const sub = attention
    ? html`<span class="attn" title=${detail || "needs attention"}>${detail || "needs attention"}</span>`
    : doing
      ? html`<span class="doing" title=${[
          `${doing.text} (${SUMMARY_SOURCE[doing.source] || doing.source}, ${rel(doing.ts, state.now)})`,
          task && `task #${task.id}: ${task.title}`,
        ].filter(Boolean).join("\n")}>${doing.text}</span> <span class="age">· ${rel(doing.ts, state.now)}</span>`
      : task
        ? html`<span class="on">#${task.id}</span> ${task.title}`
        : html`<span class="stateword" style=${`color:${st.color}`}>${st.word}</span>`;
  const stop = async (e) => {
    e.stopPropagation();
    if (!confirm(`Stop ${r.user_id}? This will kill tmux pane ${r.pane_label}.`)) return;
    setStopping(true);
    const res = await fetch(`/agents/${encodeURIComponent(r.user_id)}/stop`, { method: "POST" });
    setStopping(false);
    if (res.ok) {
      // If we're viewing the agent we just stopped, leave its detail page
      // (its terminal can no longer be captured) for another running agent,
      // or the overview if none are left.
      if (selected) {
        const next = state.recipients.find(x => x.pane_alive && x.user_id !== r.user_id);
        location.hash = next ? focusHash(next.user_id) : "#/";
      }
      refresh();
    } else alert(`Could not stop ${r.user_id}.`);
  };
  const crown = async (e) => {
    e.stopPropagation();
    if (isQueen) {
      if (!confirm(`Remove ${r.user_id} as queen of ${team.name}?`)) return;
      setCrowning(true);
      await fetch(`/teams/${team.id}`, {
        method: "PATCH", headers: JSONH, body: JSON.stringify({ queen: null }),
      });
      setCrowning(false);
      refresh();
      return;
    }
    const raw = prompt(
      `Objective for ${r.user_id} as queen of ${team.name}?`,
      "Coordinate your team to execute the shared task board.",
    );
    if (raw === null) return;
    setCrowning(true);
    const res = await fetch(`/teams/${team.id}`, {
      method: "PATCH", headers: JSONH,
      body: JSON.stringify({ queen: r.user_id, objective: raw.trim() }),
    });
    setCrowning(false);
    if (!res.ok) alert(`Could not make ${r.user_id} queen.`);
    refresh();
  };
  const dragStart = (e) => {
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("application/x-agent-swarm-agent", r.user_id);
    e.dataTransfer.setData("text/plain", r.user_id);
  };
  return html`<div class=${`chip-card state-${st.cls} ${selected ? "sel" : ""} ${ping ? "ping" : ""}`}
      style=${`--machine:${machineColor(r.node)}`}
      draggable="true" onDragStart=${dragStart}
      onClick=${() => { location.hash = focusHash(r.user_id); }}>
    <${Bee} node=${r.node} flavor=${r.flavor} size="small" working=${st.cls === "working"} />
    <div class="who">
      <${MachineBadge} node=${r.node} />
      ${team && html`<span class="agent-team" title=${`Team: ${team.name}`}>${team.name}</span>`}
      <div class="nm">${r.user_id}${isQueen && html`<span class="crown" title="team queen">♛</span>`}<span class=${`status ${st.cls}`} title=${st.word}></span></div>
      <div class="sub">${sub}</div>
      <div class="tech" title=${[flavor, r.model, r.node, r.pane_label, r.tmux_pane].filter(Boolean).join(" · ")}><span class="flavor">${flavor}</span>${r.model && html` · <span class="model">${shortModel(r.model, flavor)}</span>`} · ${r.pane_label}</div>
    </div>
    <div class="controls">
      <span class="flav" title=${flavor}>${FLAVOR_ICON[flavor] || FLAVOR_ICON.generic}</span>
      <${JumpToPane} r=${r} compact=${true} />
      ${team && r.pane_alive && html`<button type="button" class="queen-agent" disabled=${crowning}
        title=${isQueen ? `remove ${r.user_id} as queen` : `make ${r.user_id} queen of ${team.name}`}
        aria-label=${isQueen ? `Remove ${r.user_id} as queen` : `Make ${r.user_id} queen of ${team.name}`}
        onClick=${crown}>${crowning ? "…" : isQueen ? "♛ queen" : "♛"}</button>`}
      ${r.pane_alive && html`<button type="button" class="stop-agent" disabled=${stopping}
        title=${`stop ${r.user_id}`} onClick=${stop}>${stopping ? "stopping…" : "stop"}</button>`}
    </div>
    ${(unread || attention) && html`<span class="badge" title=${attention ? "needs attention" : "new messages"}></span>`}
  </div>`;
}

// The tmux command that takes you to an agent's pane, typed at tmux's command
// prompt (prefix, then ":"). It uses the pane id, which stays valid however
// windows and panes are renumbered.
function JumpToPane({ r, compact = false }) {
  const [copied, setCopied] = useState(false);
  const paneExists = r.pane_alive || (r.offline_reason || "").includes("bare shell");
  if (!paneExists || !String(r.tmux_pane).startsWith("%")) return null;
  const command = `switch-client -t ${r.tmux_pane}`;
  const copy = async (e) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      prompt("Copy this, then paste it at tmux's command prompt (prefix, then :)", command);
    }
  };
  const title = `Copy "${command}" — paste it at tmux's command prompt (prefix, then :) to jump to ${r.pane_label}`;
  if (compact) {
    return html`<button type="button" class="jump-agent" title=${title}
      aria-label=${`Copy tmux command to jump to ${r.user_id}`} onClick=${copy}>${copied ? "copied" : "⇥"}</button>`;
  }
  return html`<span class="jump-cmd" title=${title}>
    · <code>${command}</code>
    <button type="button" class="mini" onClick=${copy}>${copied ? "copied" : "copy"}</button>
  </span>`;
}

// Types the harness's own compact command (e.g. /compact) into the agent's
// pane. The server picks the command by flavor; null means none is known.
function CompactButton({ r }) {
  const [busy, setBusy] = useState(false);
  if (!r.pane_alive || !r.compact_command) return null;
  const compact = async () => {
    if (!confirm(`Compact ${r.user_id}'s context? This types ${r.compact_command} into its pane.`)) return;
    setBusy(true);
    const res = await fetch(`/agents/${encodeURIComponent(r.user_id)}/compact`, { method: "POST" });
    setBusy(false);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      alert(`Could not compact ${r.user_id}: ${body.detail?.error || res.status}`);
    }
  };
  return html`<button type="button" class="mini" disabled=${busy}
    title=${`Type ${r.compact_command} into ${r.user_id}'s pane to compact its context`}
    onClick=${compact}>${busy ? "compacting…" : "compact"}</button>`;
}

// "claude-opus-4-7" reads as "opus-4-7" next to the claude flavor tag.
function shortModel(model, flavor) {
  const prefix = `${flavor}-`;
  return model.toLowerCase().startsWith(prefix) ? model.slice(prefix.length) : model;
}

// The model label is display-only: it records what the agent is running so
// the roster can show it. Switching models still happens in the agent's own
// pane (e.g. /model); this just keeps the dashboard in step.
function ModelLabel({ r, refresh }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [known, setKnown] = useState([]);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);
  useEffect(() => { if (editing) inputRef.current?.focus(); }, [editing]);
  const flavor = (r.flavor || "generic").toLowerCase();
  const listId = `models-${r.user_id}`;
  const start = () => {
    setValue(r.model || "");
    setEditing(true);
    fetch("/api/spawn-options")
      .then(res => res.json())
      .then(d => setKnown(((d.harnesses || []).find(h => h.flavor === flavor) || {}).models || []))
      .catch(() => {});
  };
  const save = async () => {
    if (busy) return;
    if (value.trim() === (r.model || "")) { setEditing(false); return; }
    setBusy(true);
    const res = await fetch(`/agents/${encodeURIComponent(r.user_id)}/model`, {
      method: "POST", headers: JSONH, body: JSON.stringify({ model: value }),
    });
    setBusy(false);
    if (!res.ok) { alert(`Could not update the model label for ${r.user_id}.`); return; }
    setEditing(false);
    refresh();
  };
  if (!editing) {
    return html`<button type="button" class="model-label" onClick=${start}
      title="Edit the model label. Display only: switch the real model in the agent's pane, then update it here.">
      ${r.model ? html`<b>${r.model}</b>` : html`<span class="unset">set model</span>`} <span class="pen">✎</span>
    </button>`;
  }
  return html`<span class="model-edit">
    <input type="text" value=${value} list=${listId} placeholder="e.g. claude-opus-4-7"
      aria-label=${`Model label for ${r.user_id}`} disabled=${busy} ref=${inputRef}
      onInput=${e => setValue(e.target.value)}
      onKeyDown=${e => {
        if (e.key === "Enter") { e.preventDefault(); save(); }
        if (e.key === "Escape") setEditing(false);
      }} />
    <datalist id=${listId}>${known.map(m => html`<option key=${m} value=${m} />`)}</datalist>
    <button type="button" class="mini" disabled=${busy} onClick=${save}>${busy ? "saving…" : "save"}</button>
    <button type="button" class="mini" disabled=${busy} onClick=${() => setEditing(false)}>cancel</button>
  </span>`;
}

const DEFAULT_MODEL = "default";

function SpawnControl({ refresh, nodes }) {
  const [harnesses, setHarnesses] = useState([]);
  const [node, setNode] = useState("");
  const [flavor, setFlavor] = useState("claude");
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [autonomy, setAutonomy] = useState("auto");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    let live = true;
    fetch("/api/spawn-options")
      .then(r => r.json())
      .then(d => { if (live && d.harnesses) setHarnesses(d.harnesses); })
      .catch(() => {});
    return () => { live = false; };
  }, []);

  // Where this spawn would go. A picked machine that has gone away or
  // disconnected stays picked and blocks the form; it is never swapped for
  // the hub behind the user's back.
  const target = spawnTarget(nodes, node, harnesses);
  const offered = target.harnesses || [];
  const models = (offered.find(h => h.flavor === flavor) || {}).models || [];
  const pickFlavor = (f) => { setFlavor(f); setModel(DEFAULT_MODEL); };
  const pickNode = (n) => {
    setNode(n);
    const next = spawnTarget(nodes, n, harnesses);
    if (next.ok && next.harnesses.length && !next.harnesses.some(h => h.flavor === flavor)) pickFlavor(next.harnesses[0].flavor);
  };
  const enrolled = nodes || [];
  const choices = enrolled.some(n => n.name === node) || !node
    ? enrolled : enrolled.concat([{ name: node, connected: false, gone: true }]);

  const spawn = async (e) => {
    e.preventDefault();
    if (!target.ok) { setErr(target.reason); return; }
    setBusy(true);
    setErr("");
    const body = { flavor, model: model === DEFAULT_MODEL ? null : model, autonomy };
    if (target.remote) body.node = target.node;
    try {
      const r = await fetch("/agents/spawn", {
        method: "POST", headers: JSONH, body: JSON.stringify(body),
      });
      let payload = null;
      try { payload = await r.json(); } catch { payload = null; }
      const outcome = spawnOutcome(r.ok, payload);
      if (outcome.status === "failed") setErr(`spawn failed: ${outcome.reason}`);
      else if (outcome.status === "unknown") setErr(`spawn outcome unknown: ${outcome.reason}${outcome.user ? ` (registered as ${outcome.user})` : ""}`);
      else if (outcome.status === "uncertain") setErr(`spawn not confirmed: ${outcome.reason}; check the roster`);
    } catch (err) {
      setErr(`not confirmed: ${unansweredOutcome(err).reason}`);
    } finally {
      setBusy(false);
      refresh();
    }
  };

  const flavors = offered.length ? offered.map(h => h.flavor) : [];
  return html`<form class="spawn" onSubmit=${spawn}>
    <div class="spawn-heading">Spawn agent · choose destination</div>
    ${(enrolled.length > 1 || node) && html`<select title="machine" value=${node} onChange=${e => pickNode(e.target.value)}>
      ${choices.map(n => html`<option key=${n.name} value=${n.local ? "" : n.name} disabled=${!n.local && !n.connected}>${n.local ? `${n.name} (hub)` : n.gone ? `${n.name} (no longer enrolled)` : n.connected ? n.name : `${n.name} (not connected)`}</option>`)}
    </select>`}
    ${!target.ok && html`<span class="spawn-note">${target.reason}. Pick a connected machine.</span>`}
    <select title="harness" value=${flavor} onChange=${e => pickFlavor(e.target.value)} disabled=${!target.ok}>
      ${flavors.map(f => html`<option key=${f} value=${f}>${f}</option>`)}
    </select>
    <select title="model" value=${model} onChange=${e => setModel(e.target.value)}
      disabled=${models.length === 0}>
      <option value=${DEFAULT_MODEL}>default model</option>
      ${models.map(m => html`<option key=${m} value=${m}>${m}</option>`)}
    </select>
    <select title="permissions" value=${autonomy} onChange=${e => setAutonomy(e.target.value)}>
      <option value="auto">permissions: auto</option>
      <option value="supervised">permissions: ask first</option>
    </select>
    <button class="act" type="submit" disabled=${busy || !target.ok}>${busy ? "spawning…" : "spawn agent"}</button>
    ${err && html`<span style="color:var(--alert); font-size:11px">${err}</span>`}
  </form>`;
}

const ACTIVITY_RANK = { working: 0, needs_attention: 1, idle: 2, unknown: 3 };
const AGENT_DRAG_TYPE = "application/x-agent-swarm-agent";

function sortByActivity(agents) {
  return agents
    .map((r, i) => [r, i])
    .sort(([a, ai], [b, bi]) =>
      (ACTIVITY_RANK[agentStatus(a)] ?? 3) - (ACTIVITY_RANK[agentStatus(b)] ?? 3) || ai - bi)
    .map(([r]) => r);
}

async function moveAgentToTeam(user, teamId, refresh) {
  await fetch(`/agents/${encodeURIComponent(user)}/team`, {
    method: "POST", headers: JSONH, body: JSON.stringify({ team_id: teamId }),
  });
  refresh();
}

function agentDropProps(setOver, onDropUser) {
  return {
    onDragOver: (e) => {
      if (![...e.dataTransfer.types].includes(AGENT_DRAG_TYPE)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setOver(true);
    },
    onDragLeave: (e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOver(false); },
    onDrop: (e) => {
      e.preventDefault();
      setOver(false);
      const user = e.dataTransfer.getData(AGENT_DRAG_TYPE);
      if (user) onDropUser(user);
    },
  };
}

function TeamBox({ team, members, chip, refresh }) {
  const [over, setOver] = useState(false);
  const disband = async (e) => {
    e.stopPropagation();
    if (!confirm(`Disband team ${team.name}? Its agents keep running.`)) return;
    await fetch(`/teams/${team.id}`, { method: "DELETE" });
    refresh();
  };
  return html`<div class=${`teambox ${over ? "over" : ""}`}
      ...${agentDropProps(setOver, user => moveAgentToTeam(user, team.id, refresh))}>
    <div class="teamhead">
      <span class="teamname">${team.name}</span>
      ${team.queen
        ? html`<span class="queen-tag" title=${`queen: ${team.queen}`}>♛ ${team.queen}</span>`
        : html`<span class="queen-tag" style="opacity:.55">no queen</span>`}
      <button type="button" class="mini" title="disband team" onClick=${disband}>disband</button>
    </div>
    ${members.length === 0
      ? html`<div class="teamempty">drag agents here</div>`
      : members.map(chip)}
  </div>`;
}

function NewTeam({ refresh }) {
  const [name, setName] = useState("");
  const create = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    await fetch("/teams", {
      method: "POST", headers: JSONH, body: JSON.stringify({ name: name.trim() }),
    });
    setName("");
    refresh();
  };
  return html`<form class="newteam" onSubmit=${create}>
    <input type="text" placeholder="team name" value=${name}
      onInput=${e => setName(e.target.value)} />
    <button class="act" type="submit">new team</button>
  </form>`;
}

// A delivery whose outcome was lost is never replayed by the server. The
// owner can send the same text again, as a new message with its own id,
// knowing the agent may already have the first.
function Resend({ m, refresh }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const resend = async () => {
    if (!window.confirm(
      "The outcome of this message is unknown: the agent may already have it. Send it again as a new message?"
    )) return;
    setBusy(true);
    setNote("");
    try {
      const r = await fetch("/owner/send", {
        method: "POST", headers: JSONH,
        body: JSON.stringify({ recipient: m.recipient, content: m.content, context: m.context, attachments: m.attachments || [] }),
      });
      let body = null;
      try { body = await r.json(); } catch { body = null; }
      const outcome = deliveryOutcome(r.ok, body);
      if (outcome.status !== "delivered") setNote(`${outcome.status}: ${outcome.reason}`);
    } catch (err) {
      setNote(`not confirmed: ${unansweredOutcome(err).reason}`);
    } finally {
      setBusy(false);
      refresh();
    }
  };
  return html`<button type="button" class="resend" disabled=${busy} onClick=${resend}
    title="Send this message again as a new message">${busy ? "sending…" : "send again"}</button>${note && html` <span class="ctx">${note}</span>`}`;
}

// The same machine key drives the hive and roster, including disconnected
// or removed machines whose agents still have history here.
function MachineBar({ state, machine, selectMachine }) {
  const machines = machineList(state.nodes, state.recipients);
  return html`<section class="machine-bar" aria-label="Machine selector">
    <div class="machine-heading"><span>Machines</span><small>Color identifies the machine</small></div>
    <div class="machine-choices">
      <button class=${`machine-choice all ${machine === null ? "active" : ""}`} aria-pressed=${machine === null}
        onClick=${() => selectMachine(null)}><strong>All machines</strong><span>${machines.length} machines · ${state.recipients.filter(r => r.pane_alive).length} live agents</span></button>
      ${machines.map(n => html`<button key=${n.name} class=${`machine-choice ${machine === n.name ? "active" : ""} ${n.connected ? "" : "disconnected"}`}
          style=${`--machine:${machineColor(n.name)}`} aria-pressed=${machine === n.name}
          onClick=${() => selectMachine(machine === n.name ? null : n.name)}>
        <strong><span class="machine-mark" aria-hidden="true"></span>${n.name}${n.local && html`<small>hub</small>`}</strong>
        <span>${n.connected ? "Connected" : n.missing ? "Not enrolled" : "Disconnected"} · ${n.live} live${n.total > n.live ? ` / ${n.total} registered` : " agents"}</span>
      </button>`)}
    </div>
    ${machine !== null && html`<div class="machine-filter-note">Highlighting bees and showing agents on <b>${machine}</b>. Task board shows all machines. <button onClick=${() => selectMachine(null)}>Clear filter ×</button></div>`}
  </section>`;
}

function Roster({ state, focusUser, unreadFor, pings, refresh, machine, onClose }) {
  const [groupBy, setGroupBy] = useState("team");
  const [overUnteam, setOverUnteam] = useState(false);
  const teams = state.teams || [];
  const teamById = new Map(teams.map(t => [t.id, t]));
  const visible = state.recipients.filter(r => machine === null || machineName(r.node) === machine);
  const running = sortByActivity(visible.filter(r => r.pane_alive));
  const stopped = visible.filter(r => !r.pane_alive);
  const unteamed = running.filter(r => !teamById.has(r.team_id));
  const chip = (r) => html`<${RosterChip} key=${r.user_id} r=${r} state=${state}
    team=${teamById.get(r.team_id) || null}
    selected=${focusUser === r.user_id} unread=${unreadFor(r.user_id)}
    ping=${!!pings[r.user_id]} refresh=${refresh} />`;
  return html`<aside class="roster">
    <div class="roster-heading"><h2>agents ${running.length > 0 && html`<span class="count">· ${running.length}</span>`}</h2><button type="button" class="mini" aria-label="Hide agents" onClick=${onClose}>Hide →</button></div>
    <div class="roster-grouping" aria-label="Group agents by">
      <span>Group by</span>${["machine", "team"].map(g => html`<button aria-pressed=${groupBy === g} onClick=${() => setGroupBy(g)}>${g}</button>`)}
    </div>
    ${groupBy === "machine" ? machineList(state.nodes, state.recipients).filter(n => machine === null || machine === n.name).map(n => html`<section class="machine-group" key=${n.name} style=${`--machine:${machineColor(n.name)}`}>
      <h3><${MachineBadge} node=${n.name} /><span>${running.filter(r => machineName(r.node) === n.name).length} live</span></h3>
      ${running.filter(r => machineName(r.node) === n.name).map(chip)}
      ${!running.some(r => machineName(r.node) === n.name) && html`<p class="machine-empty">${n.connected ? "No live agents" : n.missing ? "Machine no longer enrolled" : "Machine disconnected"}</p>`}
      ${stopped.some(r => machineName(r.node) === n.name) && html`<details class="stopped"><summary>Offline / stopped · ${stopped.filter(r => machineName(r.node) === n.name).length}</summary>${stopped.filter(r => machineName(r.node) === n.name).map(chip)}</details>`}
    </section>`) : html`<div>
    ${teams.map(t => html`<${TeamBox} key=${t.id} team=${t} chip=${chip} refresh=${refresh}
      members=${running.filter(r => r.team_id === t.id)} />`)}
    <${NewTeam} refresh=${refresh} />
    <div class=${`unteam-drop ${overUnteam ? "over" : ""}`}
        ...${agentDropProps(setOverUnteam, user => moveAgentToTeam(user, null, refresh))}>
      ${teams.length > 0 && html`<div class="hint">no team · drop here to unteam</div>`}
      ${running.length === 0
        ? html`<div class="empty" style="padding:20px">No agents running.<br /><br />
            <code>agent-swarm register</code></div>`
        : unteamed.map(chip)}
    </div>
    ${stopped.length > 0 && html`<details class="stopped">
      <summary>stopped · ${stopped.length}</summary>
      ${stopped.map(chip)}
    </details>`}
    </div>`}
    <${SpawnControl} refresh=${refresh} nodes=${state.nodes || []} />
  </aside>`;
}

/* ---------- overview mode ---------- */

function TaskCard({ t, agentIds, teams, blockers, refresh }) {
  const [dragging, setDragging] = useState(false);
  const [closing, setClosing] = useState(false);
  const [note, setNote] = useState("");
  const [showNote, setShowNote] = useState(false);
  const [err, setErr] = useState("");
  const when = new Date(t.created_at * 1000)
    .toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const ids = t.assignee && !agentIds.includes(t.assignee)
    ? agentIds.concat(t.assignee) : agentIds;
  const act = async (p) => {
    const r = await patchTask(t.id, p);
    if (!r.ok) { setErr(r.error); return false; }
    setErr(""); refresh(); return true;
  };
  const close = async () => {
    if (await act({ status: "done", note: note.trim() })) {
      setClosing(false); setNote("");
    }
  };
  const draggable = t.status !== "done";
  const blocked = blockers.length > 0 && t.status !== "done";
  const deps = t.depends_on || [];
  const dragStart = (e) => {
    if (!draggable) return;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("application/x-agent-swarm-task", String(t.id));
    e.dataTransfer.setData("text/plain", String(t.id));
    setDragging(true);
  };
  const onAssign = (e) => {
    const v = e.target.value;
    if (v.startsWith("t:")) act({ team_id: Number(v.slice(2)) });
    else if (v) act({ assignee: v });
    else act({ assignee: null, team_id: null });
  };
  return html`<div class=${`tcard ${dragging ? "dragging" : ""} ${blocked ? "blocked" : ""}`} draggable=${draggable}
      onDragStart=${dragStart} onDragEnd=${() => setDragging(false)}
      title=${draggable ? "Drag this task onto a bee or team in the activity view to assign it" : "Reopen this task before assigning it by drag"}>
    <div class="t">${t.title}</div>
    <div class="meta">#${t.id} · created ${when}${deps.length > 0 ? ` · after ${deps.map(d => `#${d}`).join(" ")}` : ""}${t.description ? ` · ${t.description}` : ""}${t.worktree ? ` · worktree ${t.worktree}` : ""}</div>
    ${blocked && html`<div class="meta blocked-tag" title="dependencies not yet done">blocked by ${blockers.map(d => `#${d}`).join(" ")}</div>`}
    <${AttachmentList} files=${t.attachments} />
    ${t.assignee && html`<div class="meta">${t.status === "open" ? "assigned to" : t.status === "done" ? "done by" : "picked up by"} <a class="agent-link" href=${focusHash(t.assignee)}
        title=${`Open ${t.assignee} and message it`}>${t.assignee}</a></div>`}
    ${t.note && html`<div class="tnote">
      <button type="button" class="tnote-toggle" onClick=${() => setShowNote(!showNote)}
        title="How to verify this work">${showNote ? "▾" : "▸"} how to verify</button>
      ${showNote && html`<div class="tnote-body">${t.note}</div>`}
    </div>`}
    ${closing && html`<div class="tnote-edit">
      <textarea rows="3" value=${note} autofocus
        placeholder="How is this verified? How to use it, or how to reproduce what it fixed, and where to look."
        onInput=${(e) => setNote(e.target.value)}></textarea>
      <div class="tnote-actions">
        <button class="mini" disabled=${!note.trim()} onClick=${close}>save & close</button>
        <button class="mini" onClick=${() => { setClosing(false); setErr(""); }}>cancel</button>
      </div>
    </div>`}
    ${err && html`<div class="meta tnote-err">${err}</div>`}
    <div class="foot">
      <${TaskTrash} task=${t} refresh=${refresh} />
      <select title="assignee" value=${t.team_id ? `t:${t.team_id}` : (t.assignee || "")}
        onChange=${onAssign}>
        <option value="">unassigned</option>
        ${teams.length > 0 && html`<optgroup label="teams">
          ${teams.map(x => html`<option key=${`t:${x.id}`} value=${`t:${x.id}`}>team ${x.name}</option>`)}
        </optgroup>`}
        ${ids.map(a => html`<option key=${a} value=${a}>${a}${agentIds.includes(a) ? "" : " (stopped)"}</option>`)}
      </select>
      ${t.status === "done"
        ? html`<button class="mini" onClick=${() => act({ status: "open" })}>reopen</button>`
        : html`<button class="mini" onClick=${() => { setNote(t.note || ""); setClosing(!closing); }}>done</button>`}
    </div>
  </div>`;
}

const DONE_ON_BOARD = 10;

function TaskComposer({ state, refresh, user = "" }) {
  const draftKey = `agent-swarm:task-draft:${user || "board"}`;
  const [draft] = useState(() => {
    try { return JSON.parse(localStorage.getItem(draftKey) || "null") || {}; } catch { return {}; }
  });
  const [title, setTitle] = useState(draft.title || "");
  const [description, setDescription] = useState(draft.description || "");
  const [assignee, setAssignee] = useState(draft.assignee ?? user);
  const [files, setFiles] = useState(Array.isArray(draft.files) ? draft.files.filter(f => typeof f === "string") : []);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const attachments = useAttachments(files, setFiles, setStatus, draftKey);
  useEffect(() => {
    try {
      if (title || description || files.length) localStorage.setItem(draftKey, JSON.stringify({ title, description, assignee, files }));
      else localStorage.removeItem(draftKey);
    } catch { /* draft storage is best effort */ }
  }, [draftKey, title, description, assignee, files]);
  const agents = state.recipients.filter(r => r.pane_alive || r.user_id === user || r.user_id === assignee);
  const teams = state.teams || [];
  const targetExists = !assignee || (assignee.startsWith("t:")
    ? teams.some(t => `t:${t.id}` === assignee) : agents.some(r => r.user_id === assignee));
  const create = async e => {
    e.preventDefault();
    if (busy || attachments.uploading || !title.trim() || !targetExists) return;
    setBusy(true); setStatus("Creating task…");
    const body = { title: title.trim(), description: description.trim() || null, attachments: files };
    if (assignee.startsWith("t:")) body.team_id = Number(assignee.slice(2));
    else if (assignee) body.assignee = assignee;
    try {
      const response = await fetch("/tasks", { method: "POST", headers: JSONH, body: JSON.stringify(body) });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.task?.id) {
        setStatus(result?.detail?.error ? `Task not created: ${result.detail.error}. Draft kept.` : "Creation not confirmed. Check the board before retrying; draft kept.");
        return;
      }
      setTitle(""); setDescription(""); setFiles([]);
      setStatus(`Created task #${result.task.id}${result.task.assignee ? ` · assigned to ${result.task.assignee}` : result.task.team_id ? " · assigned to team" : " · unassigned"}.`);
      await refresh();
    } catch {
      setStatus("Creation not confirmed. Check the board before retrying; draft kept.");
    } finally { setBusy(false); }
  };
  return html`<form class=${`task-composer ${attachments.dragging ? "dragging" : ""}`} onSubmit=${create} ...${busy ? {} : attachments.dropProps}>
    <div class="task-compose-heading">${user ? `Create a task for ${user}` : "New task"}</div>
    <input class="task-title" aria-label="Task title" placeholder="What needs doing?" value=${title} disabled=${busy} onInput=${e => setTitle(e.target.value)} onPaste=${attachments.onPaste} required />
    <textarea aria-label="Task details" placeholder="Details, context, or steps to reproduce… (optional)" rows="2" value=${description} disabled=${busy} onInput=${e => setDescription(e.target.value)} onPaste=${attachments.onPaste} />
    <${AttachmentPicker} files=${files} controls=${attachments} disabled=${busy} />
    <div class="task-compose-actions"><label>Assign to <select aria-label="Task assignee" value=${assignee} disabled=${busy} onChange=${e => setAssignee(e.target.value)}>
      <option value="">Unassigned</option>
      ${!targetExists && html`<option value=${assignee} disabled>${assignee} (unavailable)</option>`}
      ${teams.length > 0 && html`<optgroup label="Teams">${teams.map(t => html`<option value=${`t:${t.id}`}>${t.name}</option>`)}</optgroup>`}
      <optgroup label="Agents">${agents.map(r => html`<option value=${r.user_id}>${r.user_id} · ${machineName(r.node)}${r.pane_alive ? "" : " (offline)"}</option>`)}</optgroup>
    </select></label><button class="act" disabled=${busy || attachments.uploading > 0 || !title.trim() || !targetExists}>${busy ? "Creating…" : "create task"}</button></div>
    ${!targetExists && html`<p class="task-compose-status">The selected assignee is unavailable. Choose another destination.</p>`}
    ${status && html`<p class="task-compose-status" role="status">${status}</p>`}
  </form>`;
}

function Kanban({ state, refresh }) {
  const agentIds = state.recipients.filter(r => r.pane_alive).map(r => r.user_id);
  const teams = state.teams || [];
  const byId = new Map(state.tasks.map(t => [t.id, t]));
  const cols = [
    ["open", "open"],
    ["picked_up", "picked up"],
    ["done", "done"],
  ];
  return html`<div>
    <h2>tasks ${state.tasks.length > 0 && html`<span class="count">· ${state.tasks.length}</span>`}</h2>
    <${TaskComposer} key="board" state=${state} refresh=${refresh} />
    <div class="board">
      ${cols.map(([status, label]) => {
        const all = state.tasks.filter(t => t.status === status);
        // Done keeps growing forever; the board shows only the latest few and
        // the history view holds the rest.
        const items = status === "done"
          ? [...all].sort((a, b) => b.updated_at - a.updated_at).slice(0, DONE_ON_BOARD)
          : all;
        return html`<div key=${status} class=${`col ${status}`}>
          <div class="colhead">${label}<span class="n">${all.length}</span></div>
          <div class="cards">
            ${items.length === 0
              ? html`<div class="colempty">none</div>`
              : items.map(t => html`<${TaskCard} key=${t.id} t=${t}
                  agentIds=${agentIds} teams=${teams}
                  blockers=${(t.depends_on || []).filter(d => (byId.get(d) || {}).status !== "done")}
                  refresh=${refresh} />`)}
          </div>
          ${status === "done" && all.length > 0 && html`<a class="col-more" href=${historyHash({ status: "done" })}
            title="Search every task in the history view">${all.length > items.length ? `all ${all.length} done tasks →` : "search done tasks →"}</a>`}
        </div>`;
      })}
    </div>
  </div>`;
}

function Overview({ state, refresh, machine }) {
  return html`<div>
    <h2>activity</h2>
    <${HiveView} state=${state} refresh=${refresh} machine=${machine} />
    <${Kanban} state=${state} refresh=${refresh} />
  </div>`;
}

/* ---------- agent focus mode ---------- */

function Scope({ user, refresh }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const preRef = useRef(null);
  const pinned = useRef(true);
  useEffect(() => {
    let live = true;
    setData(null);
    if (!open) return;
    pinned.current = true;
    const load = async () => {
      try {
        const r = await fetch(`/api/peek/${encodeURIComponent(user)}`);
        const d = await r.json();
        if (live) setData(d);
      } catch { /* next tick */ }
    };
    load();
    const t = setInterval(load, PEEK_MS);
    return () => { live = false; clearInterval(t); };
  }, [user, open]);
  useEffect(() => {
    const pre = preRef.current;
    if (pre && pinned.current) pre.scrollTop = pre.scrollHeight;
  }, [data]);
  const onScroll = (e) => {
    const el = e.target;
    pinned.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
  };
  return html`<details class="scope" onToggle=${e => setOpen(e.currentTarget.open)}>
    <summary class="bar">
      <span class="t">terminal</span>
      <span>${data ? data.pane_label : ""}</span>
      <span style="margin-left:auto">${open ? "live capture · 2s" : "show terminal"}</span>
    </summary>
    ${data && data.error
      ? html`<div class="err">could not capture pane: ${data.error}</div>`
      : html`<pre ref=${preRef} onScroll=${onScroll}>${data
          ? ((data.text || "").replace(/\s+$/, "") || "(pane is blank)")
          : "capturing pane…"}</pre>`}
    <${MessageComposer} recipient=${user} refresh=${refresh} draftId="terminal" />
  </details>`;
}

// Messages the owner has sent that the server has not confirmed yet. Composers
// announce them here so the thread can show them the moment send is pressed.
const pendingSends = new EventTarget();
let pendingSeq = 0;

function MessageComposer({ recipient, refresh, draftId = "thread" }) {
  const [text, setText] = useState("");
  const [context, setContext] = useState("");
  const [images, setImages] = useState([]);
  const [status, setStatus] = useState("");
  const [sending, setSending] = useState(false);
  const composerRef = useRef(null);
  const draftKey = `agent-swarm:draft:${recipient}:${draftId}`;
  const attachments = useAttachments(images, setImages, setStatus, draftKey);
  const { uploading, dragging } = attachments;
  useEffect(() => {
    try {
      const draft = JSON.parse(localStorage.getItem(draftKey) || "null");
      setText(draft?.text || "");
      setContext(draft?.context || "");
      setImages(Array.isArray(draft?.images) ? draft.images : []);
      setStatus("");
    } catch { /* an invalid saved draft should not block messaging */ }
  }, [draftKey]);
  useEffect(() => {
    const el = composerRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);
  useEffect(() => {
    let timer;
    const onOutcome = (e) => {
      if (e.detail.draftKey !== draftKey) return;
      const { status: next, draft } = e.detail;
      if (draft) {
        setText(t => t || draft.text);
        setContext(c => c || draft.context);
        setImages(imgs => (imgs.length ? imgs : draft.images));
      }
      setStatus(next);
      clearTimeout(timer);
      if (next === "delivered") timer = setTimeout(() => setStatus(s => (s === "delivered" ? "" : s)), 2500);
    };
    pendingSends.addEventListener("outcome", onOutcome);
    return () => { clearTimeout(timer); pendingSends.removeEventListener("outcome", onOutcome); };
  }, [draftKey]);
  // Keep the draft (text, tag, and uploaded images) across reloads.
  const loadedKey = useRef(null);
  useEffect(() => {
    if (loadedKey.current !== draftKey) { loadedKey.current = draftKey; return; }
    try {
      if (text || context || images.length) localStorage.setItem(draftKey, JSON.stringify({ text, context, images }));
      else localStorage.removeItem(draftKey);
    } catch { /* storage full or blocked: the draft just isn't kept */ }
  }, [draftKey, text, context, images]);
  const canSend = !sending && uploading === 0 && (text.trim() || images.length > 0);
  const send = async (e) => {
    e.preventDefault();
    const content = text.trim();
    if (!canSend) return;
    // Clear the composer and show the message in the thread right away; the
    // server confirms delivery afterwards, and a failure restores the draft.
    const draft = { text, context, images };
    const pending = {
      id: `pending-${++pendingSeq}`, pending: true, delivered: true, status: "delivered",
      sender: "owner", recipient, content, context: context.trim() || null,
      attachments: images, ts: Date.now() / 1000,
    };
    setSending(true);
    setStatus("sending…");
    setText("");
    setContext("");
    setImages([]);
    pendingSends.dispatchEvent(new CustomEvent("add", { detail: pending }));
    // The outcome is addressed by draft key, not to this component: sending
    // the first message turns the empty panel into a thread with its own
    // composer, and that one has to show the result and get the draft back.
    const report = (detail) => pendingSends.dispatchEvent(
      new CustomEvent("outcome", { detail: { draftKey, ...detail } }));
    const keepDraft = () => {
      try { localStorage.setItem(draftKey, JSON.stringify(draft)); } catch { /* best effort */ }
    };
    let outcome;
    try {
      const r = await fetch("/owner/send", {
        method: "POST", headers: JSONH,
        body: JSON.stringify({ recipient, content, context: pending.context, attachments: images }),
      });
      let body = null;
      try { body = await r.json(); } catch { body = null; }
      outcome = deliveryOutcome(r.ok, body);
    } catch (err) {
      outcome = unansweredOutcome(err);
    }
    if (outcome.status === "delivered") {
      report({ status: "delivered" });
    } else if (outcome.status === "unknown") {
      // The paste may have landed. No draft comes back: resending is a
      // deliberate act on the marked message, not a reflex.
      report({ status: `outcome unknown: ${outcome.reason}. The agent may have it; see the marked message.` });
    } else if (outcome.status === "uncertain") {
      keepDraft();
      report({ status: `not confirmed: ${outcome.reason}. It may have arrived; draft kept`, draft });
    } else {
      keepDraft();
      report({ status: `delivery failed: ${outcome.reason}. Draft kept`, draft });
    }
    // Swap the placeholder for the server's copy in one step, no flicker.
    await refresh();
    pendingSends.dispatchEvent(new CustomEvent("settle", { detail: pending.id }));
    setSending(false);
  };
  const clearDraft = () => {
    setText("");
    setContext("");
    setImages([]);
    setStatus("");
    composerRef.current?.focus();
  };
  return html`<form class=${`composer ${dragging ? "dragging" : ""}`} onSubmit=${send} ...${sending ? {} : attachments.dropProps}>
    <div class="compose-row">
      <span class="mark">❯</span>
      <textarea ref=${composerRef} value=${text} rows="2"
        onInput=${e => setText(e.target.value)}
        onPaste=${sending ? undefined : attachments.onPaste}
        onKeyDown=${e => {
          if (e.key === "Enter" && !e.shiftKey && !(e.metaKey || e.ctrlKey)) send(e);
        }}
        placeholder=${`Message ${recipient}… (paste or drop files)`} aria-label=${`Message ${recipient} as owner`} />
    </div>
    <${AttachmentPicker} files=${images} controls=${attachments} disabled=${sending} />
    <div class="compose-meta">
      <input class="context" type="text" value=${context} onInput=${e => setContext(e.target.value)}
        placeholder="context tag (optional)" aria-label="Optional context tag" />
      <span class="count">${text.length} character${text.length === 1 ? "" : "s"}${images.length > 0 ? ` · ${images.length} file${images.length === 1 ? "" : "s"}` : ""}</span>
      <span class="hint">Enter to send · Shift + Enter for a new line</span>
      <div class="actions">
        ${status && html`<span class=${status.startsWith("delivery failed") || status.startsWith("image not added") ? "error" : "sent"} role="status">${status}</span>`}
        ${(text || context || images.length > 0) && html`<button type="button" class="mini" onClick=${clearDraft}>clear</button>`}
        <button class="act" type="submit" disabled=${!canSend}>
          ${sending ? "sending…" : uploading ? "uploading…" : "send"}
        </button>
      </div>
    </div>
  </form>`;
}

function Thread({ a, b, msgs, freshIds, now, refresh }) {
  const boxRef = useRef(null);
  const follower = useRef(null);
  if (!follower.current) follower.current = createBottomFollower();
  const resizeRef = useRef(null);
  const [historyHeight, setHistoryHeight] = useState(null);
  const recipient = a === "owner" ? b : b === "owner" ? a : null;
  const [expanded, setExpanded] = useState(!!recipient);
  const savedScroll = useRef(0);
  const bodyId = `thread-${encodeURIComponent(pairKey(a, b))}`;
  useLayoutEffect(() => {
    if (expanded && boxRef.current) boxRef.current.scrollTop = savedScroll.current;
  }, [expanded]);
  // Follow synchronously after rendering, before a queued browser scroll
  // event can mistake the new bottom distance for the reader scrolling up.
  // Stay pinned to the newest message whenever the history box or any bubble
  // changes size (drag-resize, window resize, late font/layout), not only
  // when a message arrives.
  const lastId = msgs.length ? msgs[msgs.length - 1].id : null;
  useLayoutEffect(() => {
    const el = boxRef.current;
    if (!el || !expanded) return;
    const stick = () => follower.current.follow(el);
    const ro = new ResizeObserver(stick);
    ro.observe(el);
    for (const child of el.children) ro.observe(child);
    stick();
    return () => ro.disconnect();
  }, [msgs.length, lastId, historyHeight, expanded]);
  const onScroll = (e) => {
    if (!expanded) return;
    savedScroll.current = e.currentTarget.scrollTop;
    follower.current.onScroll(e.currentTarget);
  };
  const resizeBounds = () => ({ min: 120, max: Math.max(120, Math.floor(innerHeight * .85)) });
  const resizeTo = (height) => {
    const { min, max } = resizeBounds();
    setHistoryHeight(Math.max(min, Math.min(max, Math.round(height))));
  };
  const resizeStart = (e) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    resizeRef.current = { y: e.clientY, height: boxRef.current.getBoundingClientRect().height };
  };
  const resizeMove = (e) => {
    if (!resizeRef.current) return;
    resizeTo(resizeRef.current.height + e.clientY - resizeRef.current.y);
  };
  const resizeEnd = (e) => {
    if (!resizeRef.current) return;
    resizeRef.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
  };
  const resizeKey = (e) => {
    const current = historyHeight ?? boxRef.current.getBoundingClientRect().height;
    const { min, max } = resizeBounds();
    const next = e.key === "ArrowUp" ? current - 40
      : e.key === "ArrowDown" ? current + 40
        : e.key === "Home" ? min
          : e.key === "End" ? max : null;
    if (next === null) return;
    e.preventDefault();
    resizeTo(next);
  };
  return html`<div class="thread">
    <button type="button" class="bar thread-toggle" aria-expanded=${expanded} aria-controls=${bodyId}
        onClick=${() => setExpanded(v => !v)}>
      <span class="thread-chevron" aria-hidden="true">${expanded ? "▾" : "▸"}</span>
      ${disp(a)} <span class="swap">⇄</span> ${disp(b)}
      <span class="n">${msgs.length} msg${msgs.length === 1 ? "" : "s"}</span>
    </button>
    <div id=${bodyId} class="thread-body" hidden=${!expanded}>
    <div class="msgs" ref=${boxRef} onScroll=${onScroll}
      style=${historyHeight === null ? null : { height: `${historyHeight}px` }}>
      ${msgs.slice(-40).map(m => html`
        <div key=${m.id} class=${[
            "msg",
            m.sender === a ? "" : "right",
            freshIds.has(m.id) ? "fresh" : "",
            m.status === "failed" ? "failed" : m.status === "unknown" ? "unknown" : "",
            m.sender === "owner" ? "from-owner" : "",
            m.pending ? "pending" : "",
          ].join(" ")}>
          <div class="bubble">${m.content && html`<div class="md"
            dangerouslySetInnerHTML=${{ __html: renderMarkdown(m.content) }} />`}${m.attachments?.length > 0 && html`<div class=${`msg-images ${m.content ? "" : "only"}`}>
            ${m.attachments.map(name => html`<${AttachmentLink} key=${name} name=${name} />`)}
          </div>`}</div>
          <div class="tag">${disp(m.sender)}${m.context && html` · <span class="ctx">${m.context}</span>`} · ${m.pending ? "sending…" : rel(m.ts, now)}${m.status === "failed" && html` · <span class="ctx">undelivered${m.delivery_error ? `: ${m.delivery_error}` : ""}</span>`}${m.status === "unknown" && html` · <span class="ctx">outcome unknown${m.delivery_error ? `: ${m.delivery_error}` : ""}</span>${m.sender === "owner" && html` <${Resend} m=${m} refresh=${refresh} />`}`}</div>
        </div>`)}
    </div>
    <button type="button" class="history-resizer" role="separator" aria-orientation="horizontal"
      aria-label="Resize conversation history"
      aria-valuemin="120" aria-valuemax=${resizeBounds().max}
      aria-valuenow=${historyHeight ?? 340} title="Drag to resize conversation history"
      onPointerDown=${resizeStart} onPointerMove=${resizeMove}
      onPointerUp=${resizeEnd} onPointerCancel=${resizeEnd} onKeyDown=${resizeKey}>
      <span>drag to resize history</span>
    </button>
    ${recipient && html`<${MessageComposer} recipient=${recipient} refresh=${refresh} />`}
    </div>
  </div>`;
}

// What the agent is doing now, then what it did before, newest first.
function Doing({ summaries, now }) {
  const compact = useMedia(COMPACT_LAYOUT);
  if (summaries.length === 0) {
    return html`<div class="doing-box empty-doing">No status yet. Agents post one with
      <code>agent-swarm status "working on …"</code>; Claude Code and Codex pane titles
      show up here too.</div>`;
  }
  const [cur, ...past] = summaries.slice(0, 6);
  const line = (s) => html`<span class="src" title=${SUMMARY_SOURCE[s.source] || s.source}>${s.source === "agent" ? "✎" : "▭"}</span>`;
  return html`<div class="doing-box">
    <div class="now">${line(cur)} ${cur.text} <span class="age">· ${rel(cur.ts, now)}</span></div>
    ${past.length > 0 && html`<details class="status-history" open=${!compact}><summary>Recent status history</summary><ol class="past">
      ${past.map(s => html`<li>${line(s)} ${s.text} <span class="age">· ${rel(s.ts, now)}</span></li>`)}
    </ol></details>`}
  </div>`;
}

function FocusView({ user, state, refresh, freshIds }) {
  // A thread's rank is assigned once, so a new peer message cannot reorder
  // every existing conversation on the next polling render.
  const threadOrder = useRef(new Map());
  const nextThreadOrder = useRef(0);
  const r = state.recipients.find(x => x.user_id === user);
  if (!r) return html`<div class="empty">No agent named "${user}".
    <br /><br /><button class="mini" onClick=${() => { location.hash = "#/"; }}>back to overview</button></div>`;
  const flavor = (r.flavor || "generic").toLowerCase();
  const status = agentStatus(r);
  const st = STATE[status] || STATE.unknown;
  const detail = r.activity && r.activity.detail;
  const myTasks = state.tasks.filter(t => t.assignee === user);
  const agentIds = state.recipients.filter(x => x.pane_alive).map(x => x.user_id);
  const taskIds = agentIds.includes(user) ? agentIds : agentIds.concat(user);
  const groups = new Map();
  for (const m of state.messages) {
    if (m.sender !== user && m.recipient !== user) continue;
    const k = pairKey(m.sender, m.recipient);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(m);
  }
  for (const key of groups.keys()) {
    if (!threadOrder.current.has(key)) {
      threadOrder.current.set(key, nextThreadOrder.current++);
    }
  }
  const ownerThread = pairKey("owner", user);
  const threads = [...groups.entries()]
    .sort(([a], [b]) => {
      if (a === ownerThread) return -1;
      if (b === ownerThread) return 1;
      return threadOrder.current.get(a) - threadOrder.current.get(b);
    })
    .map(([, msgs]) => msgs);
  const hasOwnerThread = groups.has(ownerThread);
  const act = async (id, p) => { await patchTask(id, p); refresh(); };
  return html`<div>
    <button type="button" class="focus-back" onClick=${() => { location.hash = "#/"; }}>← back to overview</button>
    <div class="fhead">
      <${Bee} node=${r.node} flavor=${r.flavor} working=${status === "working"} />
      <div class="who">
        <div class="nm">${user}<span class=${`status ${st.cls}`} title=${st.word}></span></div>
        <div class="meta">
          <span class="chip">${FLAVOR_ICON[flavor] || FLAVOR_ICON.generic} ${flavor}</span>
          <${ModelLabel} r=${r} refresh=${refresh} /> · <${MachineBadge} node=${r.node} /> · pane <b>${r.pane_label}</b>${r.pane_alive ? "" : " (stopped)"}
          <${JumpToPane} r=${r} />
          <${CompactButton} r=${r} />
          · joined ${rel(r.registered_at, state.now)}
          · <span style=${`color:${st.color}`}>${st.word}</span>${status === "needs_attention" && detail ? html` <span class="attn">${detail}</span>` : ""}
        </div>
        ${r.instructions && html`<div class="inst">"${r.instructions}"</div>`}
      </div>
    </div>
    <${Doing} summaries=${r.summaries || []} now=${state.now} />
    <${Scope} key=${user} user=${user} refresh=${refresh} />
    <${TaskComposer} key=${user} user=${user} state=${state} refresh=${refresh} />
    <h2>conversations ${threads.length > 0 && html`<span class="count">· ${threads.length}</span>`}</h2>
    ${threads.length === 0
      ? html`<div class="thread"><div class="empty">Nothing yet. Start a conversation with ${user} below.</div>
          <${MessageComposer} recipient=${user} refresh=${refresh} /></div>`
      : threads.map(msgs => {
          const [a, b] = pairKey(msgs[0].sender, msgs[0].recipient).split(" ");
          return html`<${Thread} key=${pairKey(a, b)} a=${a} b=${b} msgs=${msgs}
            freshIds=${freshIds} now=${state.now} refresh=${refresh} />`;
        })}
    ${threads.length > 0 && !hasOwnerThread && html`<div class="thread" style="margin-top:14px">
      <div class="bar">${disp("owner")} <span class="swap">⇄</span> ${user}</div>
      <${MessageComposer} recipient=${user} refresh=${refresh} />
    </div>`}
    <h2 style="margin-top:26px">tasks ${myTasks.length > 0 && html`<span class="count">· ${myTasks.length}</span>`}
      ${myTasks.length > 0 && html`<a class="h2-link" href=${historyHash({ agent: user })}>search ${user}'s history →</a>`}</h2>
    ${myTasks.length === 0
      ? html`<div class="empty">No tasks assigned to ${user}. Assign one from the overview board.</div>`
      : myTasks.map(t => html`<div key=${t.id} class=${`trow ${t.status}`}>
          <span class="tid">#${t.id}</span>
          <span class="t">${t.title}<${AttachmentList} files=${t.attachments} /></span>
          <span class=${`pill ${t.status}`}>${t.status.replace("_", " ")}</span>
          <select title="assignee" value=${t.assignee || ""}
            onChange=${e => act(t.id, { assignee: e.target.value })}>
            <option value="">unassigned</option>
            ${taskIds.map(a => html`<option key=${a} value=${a}>${a}${agentIds.includes(a) ? "" : " (stopped)"}</option>`)}
          </select>
          ${t.status === "done"
            ? html`<button class="mini" onClick=${() => act(t.id, { status: "open" })}>reopen</button>`
            : html`<button class="mini" onClick=${() => act(t.id, { status: "done" })}>done</button>`}
        </div>`)}
  </div>`;
}

/* ---------- app ---------- */

function App() {
  const compact = useMedia(COMPACT_LAYOUT);
  const [state, setState] = useState(null);
  const [machine, setMachine] = useState(null);
  const [rosterOpen, setRosterOpen] = useState(() => {
    try { const saved = localStorage.getItem("swarm-roster-open"); return saved === null ? true : saved === "true"; }
    catch { return true; }
  });
  const rosterOpenRef = useRef(rosterOpen);
  rosterOpenRef.current = rosterOpen;
  const toggleRef = useRef(null);
  const updateRoster = open => {
    setRosterOpen(open);
    try { localStorage.setItem("swarm-roster-open", String(open)); } catch {}
  };
  const toggleRoster = () => {
    const opening = compact || !rosterOpen;
    updateRoster(opening);
    if (opening && compact) requestAnimationFrame(() => {
      document.getElementById("agent-sidebar")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start" });
    });
  };
  const closeRoster = () => { updateRoster(false); toggleRef.current?.focus(); };
  const [connected, setConnected] = useState(true);
  const [clock, setClock] = useState(new Date().toLocaleTimeString());
  const [route, setRoute] = useState(location.hash);
  const [freshIds, setFreshIds] = useState(new Set());
  const [pings, setPings] = useState({});
  const seen = useRef({ maxId: 0, first: true, byAgent: {} });
  const [pending, setPending] = useState([]);
  useEffect(() => {
    const add = (e) => setPending(p => [...p, e.detail]);
    const settle = (e) => setPending(p => p.filter(m => m.id !== e.detail));
    pendingSends.addEventListener("add", add);
    pendingSends.addEventListener("settle", settle);
    return () => {
      pendingSends.removeEventListener("add", add);
      pendingSends.removeEventListener("settle", settle);
    };
  }, []);

  const focusUser = route.startsWith("#/agent/")
    ? decodeURIComponent(route.slice("#/agent/".length)) : null;
  const onHistory = route.startsWith(HISTORY_ROUTE);
  // A roster link may be several screens down on a phone. Bring the new
  // view into sight; polling and task-history filters must not move it.
  const previousView = useRef({ focusUser, onHistory });
  useEffect(() => {
    const before = previousView.current;
    previousView.current = { focusUser, onHistory };
    if ((before.focusUser !== focusUser || before.onHistory !== onHistory) && compact)
      document.querySelector(".stage")?.scrollIntoView({ block: "start" });
  }, [focusUser, onHistory, compact]);

  const poll = async () => {
    try {
      const r = await fetch("/api/state");
      const s = await r.json();
      const st = seen.current;
      const maxId = Math.max(st.maxId, ...s.messages.map(m => m.id), 0);
      const fresh = s.messages.filter(m => m.id > st.maxId);
      if (!st.first && fresh.length) {
        setFreshIds(new Set(fresh.map(m => m.id)));
        setPings(Object.fromEntries(fresh.flatMap(m => [[m.sender, 1], [m.recipient, 1]])));
        setTimeout(() => setPings({}), 1000);
      }
      for (const rec of s.recipients) {
        if (st.first || !(rec.user_id in st.byAgent)) st.byAgent[rec.user_id] = maxId;
      }
      st.maxId = maxId;
      st.first = false;
      setState(s);
      setConnected(true);
    } catch {
      setConnected(false);
    }
  };
  useEffect(() => {
    poll();
    const t = setInterval(poll, POLL_MS);
    const c = setInterval(() => setClock(new Date().toLocaleTimeString()), 1000);
    const onHash = () => setRoute(location.hash);
    const onKey = (e) => {
      if (e.key === "Escape" && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) {
        if (rosterOpenRef.current) closeRoster();
        else location.hash = "#/";
      }
    };
    addEventListener("hashchange", onHash);
    addEventListener("keydown", onKey);
    return () => {
      clearInterval(t); clearInterval(c);
      removeEventListener("hashchange", onHash);
      removeEventListener("keydown", onKey);
    };
  }, []);

  // messages involving the focused agent count as read
  if (focusUser && seen.current.byAgent[focusUser] !== undefined) {
    seen.current.byAgent[focusUser] = seen.current.maxId;
  }
  const unreadFor = (u) => {
    if (!state || u === focusUser) return false;
    const since = seen.current.byAgent[u] ?? seen.current.maxId;
    return state.messages.some(m =>
      m.id > since && m.sender === u && m.recipient === "owner");
  };

  const header = html`<header class="top">
    <h1 style="cursor:pointer" onClick=${() => { location.hash = "#/"; }}>Agent Swarm Dashboard</h1>
    <nav class="views" aria-label="views">
      <a href="#/" class=${!onHistory && !focusUser ? "on" : ""}>overview</a>
      <a href=${HISTORY_ROUTE} class=${onHistory ? "on" : ""}>task history</a>
    </nav>
    <div class="right">
      <span><span class=${`beacon ${connected ? "" : "down"}`}></span>${connected ? "watching" : "server unreachable"}</span>
      <span>${clock}</span>
    </div>
  </header>`;

  if (!state) return html`${header}<main><div class="stage"><div class="empty">connecting…</div></div></main>`;
  const view = pending.length ? { ...state, messages: [...state.messages, ...pending] } : state;

  return html`${header}
  <${MachineBar} state=${state} machine=${machine} selectMachine=${setMachine} />
  <button type="button" ref=${toggleRef} class=${`roster-toggle ${rosterOpen ? "is-open" : ""}`}
    aria-expanded=${rosterOpen} aria-controls="agent-sidebar" onClick=${toggleRoster}>
    <span class="desktop-roster-label">${rosterOpen ? "Agents ›" : "‹ Agents"}</span><span class="mobile-roster-label">Agent roster ↓</span> · ${state.recipients.filter(r => r.pane_alive).length}
  </button>
  <main class=${`dashboard-layout ${rosterOpen ? "roster-open" : ""}`}>
    <div class="stage">
      ${focusUser
        ? html`<${FocusView} user=${focusUser} state=${view} refresh=${poll} freshIds=${freshIds} />`
        : onHistory
          ? html`<${HistoryView} state=${state} />`
          : html`<${Overview} state=${state} refresh=${poll} machine=${machine} />`}
    </div>
    <div id="agent-sidebar" class=${`roster-drawer ${rosterOpen ? "is-open" : ""}`} inert=${!rosterOpen} aria-hidden=${!rosterOpen}>
      <${Roster} state=${state} focusUser=${focusUser} unreadFor=${unreadFor}
        pings=${pings} refresh=${poll} machine=${machine} onClose=${closeRoster} />
    </div>
  </main>`;
}

render(html`<${App} />`, document.getElementById("app"));
