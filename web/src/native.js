// The Mac app in mac/ shows this page in its own window. It badges the
// Dock icon and sends notifications for agents that need the owner, so
// the page tells it who they are. In a plain browser there is no
// window.__TAURI__ and the reporter does nothing.

export function attentionAgents(recipients) {
  return recipients
    .filter(r => r.pane_alive && r.activity?.status === "needs_attention")
    .map(r => r.user_id)
    .sort();
}

// Returns a function to call with every polled state. It sends the full
// list on the first call and again only when the list changes.
export function attentionReporter(invoke) {
  if (!invoke) return () => {};
  let sent = null;
  return recipients => {
    const agents = attentionAgents(recipients);
    const key = agents.join("\n");
    if (key === sent) return;
    sent = key;
    // Resend on the next poll if the app did not take it.
    Promise.resolve(invoke("attention", { agents })).catch(() => { sent = null; });
  };
}
