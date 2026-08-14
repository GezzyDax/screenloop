import assert from "node:assert/strict";
import test from "node:test";

globalThis.localStorage = { getItem: () => "en", setItem: () => {} };
Object.defineProperty(globalThis, "navigator", { value: { language: "en" }, configurable: true });
globalThis.document = { documentElement: { lang: "" }, createElement: () => ({}) };

const { mediaState } = await import("../src/store/screenloop.js");

const hourAgo = Math.floor(Date.now() / 1000) - 3600;
const hourAhead = Math.floor(Date.now() / 1000) + 3600;

test("a clip from before the lifecycle column reads as published", () => {
  assert.equal(mediaState({ id: 1 }), "published");
});

test("the stored state wins", () => {
  assert.equal(mediaState({ lifecycle: "draft" }), "draft");
  assert.equal(mediaState({ lifecycle: "archived" }), "archived");
});

test("a passed expiry reads as expired", () => {
  assert.equal(mediaState({ lifecycle: "published", expires_at: hourAgo }), "expired");
});

test("an expiry still ahead changes nothing", () => {
  assert.equal(mediaState({ lifecycle: "published", expires_at: hourAhead }), "published");
});

test("an archived clip is not relabelled by its expiry", () => {
  assert.equal(mediaState({ lifecycle: "archived", expires_at: hourAgo }), "archived");
});
