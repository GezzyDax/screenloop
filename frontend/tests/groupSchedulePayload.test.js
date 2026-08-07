import assert from "node:assert/strict";
import test from "node:test";

globalThis.localStorage = { getItem: () => "en", setItem: () => {} };
Object.defineProperty(globalThis, "navigator", { value: { language: "en" }, configurable: true });
globalThis.document = { documentElement: { lang: "" }, createElement: () => ({}) };

const { groupSchedulePayload } = await import("../src/store/screenloop.js");

test("custom group schedule keeps its weekly window", () => {
  assert.deepEqual(
    groupSchedulePayload({
      schedule_mode: "custom",
      schedule_days: "0,1,2,3,4",
      schedule_start: "08:00",
      schedule_end: "18:00",
    }),
    {
      schedule_mode: "custom",
      schedule_days: "0,1,2,3,4",
      schedule_start: "08:00",
      schedule_end: "18:00",
    },
  );
});

test("inherited group schedule clears stale custom values", () => {
  assert.deepEqual(
    groupSchedulePayload({
      schedule_mode: "inherit",
      schedule_days: "0",
      schedule_start: "08:00",
      schedule_end: "18:00",
    }),
    {
      schedule_mode: "inherit",
      schedule_days: null,
      schedule_start: null,
      schedule_end: null,
    },
  );
});
