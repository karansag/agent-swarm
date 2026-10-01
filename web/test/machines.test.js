import test from "node:test";
import assert from "node:assert/strict";
import { machineColor, machineList } from "../src/machines.js";

test("machine identity survives disconnection and roster reorder", () => {
  const nodes = [{ name: "laptop", connected: true }, { name: "hub", local: true, connected: true }];
  const agents = [{ node: "laptop", pane_alive: true }, { node: "laptop", pane_alive: false }, { node: "retired", pane_alive: false }];
  const before = machineList(nodes, agents);
  const after = machineList(nodes.toReversed().map(n => ({ ...n, connected: false })), agents.toReversed());
  assert.deepEqual(before.map(n => [n.name, machineColor(n.name)]), after.map(n => [n.name, machineColor(n.name)]));
  assert.equal(before[0].name, "hub");
  assert.equal(before.find(n => n.name === "laptop").live, 1);
  assert.equal(before.find(n => n.name === "laptop").total, 2);
  assert.equal(before.find(n => n.name === "retired").missing, true);
  assert.equal(before.find(n => n.name === "retired").connected, false);
});

test("missing provenance remains visible without inventing a hub assignment", () => {
  assert.deepEqual(machineList([], [{ pane_alive: false }]).map(n => n.name), ["Unknown machine"]);
  assert.equal(machineColor(null), machineColor(undefined));
  assert.deepEqual(machineList(), []);
});
