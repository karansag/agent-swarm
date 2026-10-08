import test from "node:test";
import assert from "node:assert/strict";
import { shellNewlines } from "../src/newlines.js";

test("a one-line message with literal \\n gets its line breaks", () => {
  assert.equal(shellNewlines("checkpoint:\\n\\ns3://bucket/x\\nResults"), "checkpoint:\n\ns3://bucket/x\nResults");
});

test("a message with real line breaks keeps its \\n as written", () => {
  const text = "Prompt:\n'Question: ...\\nAnswer:'";
  assert.equal(shellNewlines(text), text);
});

test("code spans and escaped backslashes are left alone", () => {
  assert.equal(shellNewlines("run `printf 'a\\nb'`\\nthen check"), "run `printf 'a\\nb'`\nthen check");
  assert.equal(shellNewlines("path C:\\\\new"), "path C:\\\\new");
  assert.equal(shellNewlines("plain text"), "plain text");
});
