import test from "node:test";
import assert from "node:assert/strict";
import { agentChips } from "../src/history.js";

const recipients = [
  { user_id: "otter", pane_alive: true },
  { user_id: "tapir", pane_alive: true },
  { user_id: "puffin", pane_alive: false },
];

test("agent chips list only live agents, busiest first", () => {
  const counts = new Map([["puffin", 9], ["otter", 2], ["tapir", 5], ["ghost", 4]]);
  assert.deepEqual(agentChips(counts, recipients, ""), [["tapir", 5], ["otter", 2]]);
});

test("the selected agent keeps its chip even when dead", () => {
  const counts = new Map([["puffin", 3], ["otter", 1]]);
  assert.deepEqual(agentChips(counts, recipients, "puffin"), [["puffin", 3], ["otter", 1]]);
  assert.deepEqual(agentChips(new Map(), recipients, "ghost"), [["ghost", 0]]);
});
