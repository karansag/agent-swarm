import test from "node:test";
import assert from "node:assert/strict";
import { createBottomFollower } from "../src/scroll-follow.js";

function scroller() {
  let top = 0;
  return { scrollHeight: 1000, clientHeight: 300,
    get scrollTop() { return top; },
    set scrollTop(value) { top = Math.max(0, Math.min(value, this.scrollHeight - this.clientHeight)); },
  };
}

test("a queued scroll event after content grows does not detach a bottom reader", () => {
  const el = scroller(), follower = createBottomFollower();
  follower.follow(el);
  assert.equal(el.scrollTop, 700);
  el.scrollHeight += 240; // message arrives before an already queued event
  follower.onScroll(el);
  follower.follow(el);
  assert.equal(el.scrollTop, 940);
  el.scrollHeight += 200; // late image loading follows as well
  follower.onScroll(el);
  follower.follow(el);
  assert.equal(el.scrollTop, 1140);
});

test("scrolling up preserves the reading position until returning to the bottom", () => {
  const el = scroller(), follower = createBottomFollower();
  follower.follow(el);
  el.scrollTop = 250; follower.onScroll(el);
  el.scrollHeight += 500; follower.follow(el);
  assert.equal(el.scrollTop, 250);
  el.scrollTop = 450; follower.onScroll(el); // reading down, but not at bottom
  el.scrollHeight += 100; follower.follow(el);
  assert.equal(el.scrollTop, 450);
  el.scrollTop = el.scrollHeight; follower.onScroll(el);
  el.scrollHeight += 200; follower.follow(el);
  assert.equal(el.scrollTop, 1500);
});

test("viewport changes keep a bottom reader pinned, but leave a scrolled-up reader alone", () => {
  const el = scroller(), follower = createBottomFollower();
  follower.follow(el);
  el.clientHeight = 180; follower.onScroll(el); follower.follow(el);
  assert.equal(el.scrollTop, 820);
  el.scrollTop = 200; follower.onScroll(el);
  el.clientHeight = 400; follower.follow(el);
  assert.equal(el.scrollTop, 200);
});
