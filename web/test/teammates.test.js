import test from "node:test";
import assert from "node:assert/strict";
import { stepTeammate, teammates } from "../src/teammates.js";

const teams = [{ id: 1, name: "swarm", queen: "stoat" }];
const recipients = [
  { user_id: "otter", team_id: 1, pane_alive: true },
  { user_id: "stoat", team_id: 1, pane_alive: true },
  { user_id: "badger", team_id: 1, pane_alive: true },
  { user_id: "puffin", team_id: 1, pane_alive: false },
  { user_id: "loner", team_id: null, pane_alive: true },
];

test("teammates are live members, queen first, then by name", () => {
  assert.deepEqual(teammates(recipients, teams, "otter").members.map(m => m.user_id), ["stoat", "badger", "otter"]);
  assert.equal(teammates(recipients, teams, "loner"), null);
  // A stopped agent's own page still lists it, so the strip shows where you are.
  assert.ok(teammates(recipients, teams, "puffin").members.some(m => m.user_id === "puffin"));
});

test("stepping wraps around and needs someone else", () => {
  const { members } = teammates(recipients, teams, "otter");
  assert.equal(stepTeammate(members, "otter", 1), "stoat");
  assert.equal(stepTeammate(members, "stoat", -1), "otter");
  assert.equal(stepTeammate(members.slice(0, 1), "stoat", 1), null);
});
