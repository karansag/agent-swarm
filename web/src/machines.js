// Machine identity is independent of harness and activity. Hashing the full
// name keeps the color stable across polling, reconnects and roster changes.
const COLORS = ["#80bfff", "#c4a0f5", "#91a4ee", "#ed9bc4", "#adc87f", "#edba83", "#65d5c0", "#d2bd79"];
export const machineName = name => name || "Unknown machine";
export function machineColor(name) {
  let hash = 2166136261;
  for (const c of machineName(name)) hash = Math.imul(hash ^ c.codePointAt(0), 16777619);
  return COLORS[(hash >>> 0) % COLORS.length];
}
export function machineList(nodes = [], recipients = []) {
  const all = new Map(nodes.map(n => [machineName(n.name), { ...n, name: machineName(n.name) }]));
  for (const r of recipients) {
    const name = machineName(r.node);
    if (!all.has(name)) all.set(name, { name, connected: false, missing: true });
  }
  return [...all.values()].map(n => {
    const agents = recipients.filter(r => machineName(r.node) === n.name);
    return { ...n, total: agents.length, live: agents.filter(r => r.pane_alive).length };
  }).sort((a, b) => Number(!!b.local) - Number(!!a.local) || a.name.localeCompare(b.name));
}
