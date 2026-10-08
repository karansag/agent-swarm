import test from "node:test";
import assert from "node:assert/strict";
import { ownerChats } from "../src/chats.js";

const m = (id, sender, recipient, content, ts) => ({ id, sender, recipient, content, ts });
const messages = [
  m(1, "owner", "otter", "can you check the zephyr reducers?", 10),
  m(2, "otter", "owner", "yes, skew is small", 20),
  m(3, "owner", "tapir", "deploy the dashboard", 30),
  m(4, "tapir", "stoat", "peer chatter", 40),
  m(2, "otter", "owner", "yes, skew is small", 20),
];

test("one row per agent the owner talked with, newest first", () => {
  const chats = ownerChats(messages);
  assert.deepEqual(chats.map(c => [c.agent, c.count, c.last.id]), [["tapir", 1, 3], ["otter", 2, 2]]);
});

test("a search keeps conversations with a message containing every word", () => {
  const chats = ownerChats(messages, "Zephyr REDUCERS");
  assert.deepEqual(chats.map(c => [c.agent, c.match.id, c.matches]), [["otter", 1, 1]]);
  assert.deepEqual(ownerChats(messages, "zephyr deploy"), []);
});
