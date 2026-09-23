import MarkdownIt from "markdown-it";

// Message bodies are Markdown. Raw HTML is off, so anything an agent writes
// as HTML shows as text, and markdown-it refuses javascript:/vbscript:/data:
// link targets, so the output is safe to insert. breaks keeps single
// newlines as line breaks, the way these messages are written.
const md = new MarkdownIt({ html: false, linkify: true, breaks: true });

// Link only URLs that carry a scheme (http://, https://, ...). Fuzzy matching
// would turn file names like "main.py" into http://main.py (.py is a TLD) and
// "git@github.com" into a mail link.
md.linkify.set({ fuzzyLink: false, fuzzyEmail: false });

// ![](url) would make the dashboard fetch whatever an agent points it at;
// pasted images arrive as attachments instead.
md.disable("image");

const renderLinkOpen = md.renderer.rules.link_open
  || ((tokens, i, options, env, self) => self.renderToken(tokens, i, options));
md.renderer.rules.link_open = (tokens, i, options, env, self) => {
  tokens[i].attrSet("target", "_blank");
  tokens[i].attrSet("rel", "noopener noreferrer");
  return renderLinkOpen(tokens, i, options, env, self);
};

// The dashboard re-renders every poll; each message body only needs rendering once.
const cache = new Map();
const CACHE_LIMIT = 1000;

export function renderMarkdown(text) {
  const source = text || "";
  let out = cache.get(source);
  if (out === undefined) {
    out = md.render(source);
    if (cache.size >= CACHE_LIMIT) cache.delete(cache.keys().next().value);
    cache.set(source, out);
  }
  return out;
}
