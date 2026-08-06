import assert from "node:assert/strict";
import test from "node:test";

globalThis.localStorage = { getItem: () => "en", setItem: () => {} };
Object.defineProperty(globalThis, "navigator", { value: { language: "en" }, configurable: true });
globalThis.document = { documentElement: { lang: "" }, createElement: () => ({}) };

const screenloopStore = await import("../src/store/screenloop.js");

const tv = {
  id: 1,
  name: "Lobby",
  ip: "192.0.2.10",
  profile: "generic_dlna",
  active_playlist_id: null,
  autoplay: true,
  control_url: "",
  node_id: null,
  group_id: 17,
};

test("TV payload preserves its group during an unrelated update", () => {
  const payload = screenloopStore.tvPayload?.(tv, { autoplay: false });

  assert.equal(payload?.group_id, 17);
});

test("TV payload applies an explicit group change", () => {
  const payload = screenloopStore.tvPayload?.(tv, { group_id: 23 });

  assert.equal(payload?.group_id, 23);
});
