import test from "node:test";
import assert from "node:assert/strict";
import { stepView, tabHash } from "../src/tabs.js";

const views = ["#/", "#/chats", tabHash("usage"), tabHash("usage2"), "#/tasks"];

test("views step in header order and wrap at both ends", () => {
  assert.equal(stepView("#/", views, 1), "#/chats");
  assert.equal(stepView("#/chats?q=deploy", views, 1), "#/tab/usage");
  assert.equal(stepView("#/tab/usage", views, 1), "#/tab/usage2");
  assert.equal(stepView("#/tab/usage2", views, -1), "#/tab/usage");
  assert.equal(stepView("#/tasks", views, 1), "#/");
  assert.equal(stepView("#/", views, -1), "#/tasks");
});

test("an agent page or an empty hash counts as the overview", () => {
  assert.equal(stepView("#/agent/stoat", views, 1), "#/chats");
  assert.equal(stepView("", views, -1), "#/tasks");
});
