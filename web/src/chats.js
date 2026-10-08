// No imports, so `node --test web/test` can exercise it without a browser.

// The owner's conversations, one per agent, newest first. `messages` may hold
// the same message twice (full history plus the live poll); ids decide. With
// a query, only conversations with a message containing every word are kept,
// and each carries its newest matching message.
export function ownerChats(messages, query = "") {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const seen = new Set();
  const byAgent = new Map();
  for (const m of messages) {
    if (seen.has(m.id) || (m.sender !== "owner" && m.recipient !== "owner")) continue;
    if (m.sender === "owner" && m.recipient === "owner") continue;
    seen.add(m.id);
    const agent = m.sender === "owner" ? m.recipient : m.sender;
    const chat = byAgent.get(agent) || { agent, last: null, count: 0, match: null, matches: 0 };
    chat.count += 1;
    if (!chat.last || m.ts > chat.last.ts) chat.last = m;
    if (words.length) {
      const text = `${m.context || ""} ${m.content || ""}`.toLowerCase();
      if (words.every(w => text.includes(w))) {
        chat.matches += 1;
        if (!chat.match || m.ts > chat.match.ts) chat.match = m;
      }
    }
    byAgent.set(agent, chat);
  }
  return [...byAgent.values()]
    .filter(c => !words.length || c.matches > 0)
    .sort((a, b) => (words.length ? b.match.ts - a.match.ts : b.last.ts - a.last.ts));
}
