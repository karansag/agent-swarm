// No imports, so `node --test web/test` can exercise it without a browser.

// Chips for agents that are alive now; dead agents piled up into a wall of
// chips. The selected agent keeps its chip even when dead, so the filter
// (set from a tile's "only" button or a URL) can still be seen and cleared.
export function agentChips(agentCount, recipients, selected) {
  const live = new Set(recipients.filter(r => r.pane_alive).map(r => r.user_id));
  const counts = new Map([...agentCount].filter(([a]) => live.has(a) || a === selected));
  if (selected && !counts.has(selected)) counts.set(selected, 0);
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}
