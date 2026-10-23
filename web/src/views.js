// Pure view routing, kept apart from tabs.js so Node's test runner can load
// it without the UI libraries installed.

// Pages named in the hub's AGENT_SWARM_TABS, such as an AI usage page. The
// hub serves each one at /tabs/<name>/ on its own origin.
export const TAB_ROUTE = "#/tab/";
export const tabHash = name => `${TAB_ROUTE}${encodeURIComponent(name)}`;

// Cmd/Ctrl+Shift+[ and ] step through the header's views in order, wrapping.
// `views` is that order, overview ("#/") first; any page not in it (an
// agent's page) counts as the overview.
export function stepView(hash, views, by) {
  const at = Math.max(0, views.findIndex(v => v !== "#/" && (hash === v || hash.startsWith(`${v}?`))));
  return views[(at + by + views.length) % views.length];
}
