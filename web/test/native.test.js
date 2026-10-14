import test from "node:test";
import assert from "node:assert/strict";
import { attentionAgents, attentionReporter } from "../src/native.js";

const agent = (user_id, status, pane_alive = true) => ({ user_id, pane_alive, activity: { status } });

test("only live agents that need attention count, sorted", () => {
  const rs = [agent("stoat", "needs_attention"), agent("otter", "working"),
    agent("badger", "needs_attention"), agent("puffin", "needs_attention", false), { user_id: "newt", pane_alive: true }];
  assert.deepEqual(attentionAgents(rs), ["badger", "stoat"]);
});

test("the app hears the list once, then only when it changes", async () => {
  const calls = [];
  const report = attentionReporter(async (cmd, args) => { calls.push([cmd, args.agents]); });
  report([agent("otter", "working")]);
  report([agent("otter", "working")]);
  report([agent("otter", "needs_attention")]);
  report([agent("otter", "needs_attention")]);
  report([]);
  assert.deepEqual(calls, [["attention", []], ["attention", ["otter"]], ["attention", []]]);
});

test("a failed call is retried on the next poll", async () => {
  let fail = true;
  const calls = [];
  const report = attentionReporter(async (cmd, args) => { calls.push(args.agents); if (fail) throw new Error("no"); });
  report([agent("otter", "needs_attention")]);
  await new Promise(r => setTimeout(r, 0));
  fail = false;
  report([agent("otter", "needs_attention")]);
  assert.deepEqual(calls, [["otter"], ["otter"]]);
});

test("in a browser without the app it does nothing", () => {
  assert.doesNotThrow(() => attentionReporter(undefined)([agent("otter", "needs_attention")]));
});
