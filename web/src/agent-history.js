import { useEffect, useRef, useState } from "preact/hooks";
import { POLL_MS } from "./shared.js";

// The global activity feed is deliberately small; detail history is independent.
export function useAgentHistory(user) {
  const [history, setHistory] = useState({ messages: [], loaded: false, more: false, busy: false, error: "" });
  const older = useRef(() => {});
  useEffect(() => {
    let active = true, polling = false, loadingOlder = false;
    let newest = null, oldest = null;
    const abort = new AbortController();
    const read = async query => {
      const response = await fetch(`/api/agents/${encodeURIComponent(user)}/messages?${query}`, { signal: abort.signal });
      if (!response.ok) throw Error("History unavailable");
      const page = await response.json();
      if (!Array.isArray(page.messages) || typeof page.has_more !== "boolean") throw Error("Invalid history");
      return page;
    };
    const merge = (page, initial = false, isOlder = false) => {
      if (!active) return;
      const ids = page.messages.map(m => m.id);
      if (ids.length) {
        newest = Math.max(newest ?? 0, ...ids);
        oldest = Math.min(oldest ?? Infinity, ...ids);
      } else if (initial) newest = 0;
      setHistory(prev => ({ ...prev, loaded: true, error: "",
        more: initial || isOlder ? page.has_more : prev.more,
        messages: [...new Map([...prev.messages, ...page.messages].map(m => [m.id, m])).values()],
      }));
    };
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const initial = newest === null;
        let page = await read(initial ? "limit=300" : `after=${newest}&limit=300`);
        merge(page, initial);
        // Catch up completely even when more than one page arrived between polls.
        while (active && !initial && page.has_more) {
          page = await read(`after=${newest}&limit=300`);
          merge(page);
        }
      } catch {
        if (active) setHistory(prev => ({ ...prev, error: "Could not load conversation history. Retrying…" }));
      } finally { polling = false; }
    };
    older.current = async () => {
      if (loadingOlder || oldest === null) return;
      loadingOlder = true;
      setHistory(prev => ({ ...prev, busy: true }));
      try { merge(await read(`before=${oldest}&limit=300`), false, true); }
      catch { if (active) setHistory(prev => ({ ...prev, error: "Could not load older messages. Please try again." })); }
      finally {
        loadingOlder = false;
        if (active) setHistory(prev => ({ ...prev, busy: false }));
      }
    };
    poll();
    const timer = setInterval(poll, POLL_MS);
    return () => { active = false; abort.abort(); clearInterval(timer); };
  }, [user]);
  return { ...history, loadOlder: () => older.current() };
}
