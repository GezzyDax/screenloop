import assert from "node:assert/strict";
import test from "node:test";

import { copyText } from "../src/utils/clipboard.js";

function fakeDocument(copyResult = true) {
  const children = [];
  const execCommands = [];
  const textareas = [];
  const document = {
    body: {
      children,
      appendChild(node) {
        children.push(node);
      },
    },
    createElement(tagName) {
      assert.equal(tagName, "textarea");
      const node = {
        value: "",
        style: {},
        selected: false,
        selectionRange: null,
        setAttribute() {},
        select() {
          this.selected = true;
        },
        setSelectionRange(start, end) {
          this.selectionRange = [start, end];
        },
        remove() {
          const index = children.indexOf(this);
          if (index >= 0) children.splice(index, 1);
        },
      };
      textareas.push(node);
      return node;
    },
    execCommand(command) {
      execCommands.push(command);
      return copyResult;
    },
    execCommands,
    textareas,
  };
  return document;
}

test("copyText uses the modern clipboard API when available", async () => {
  const writes = [];
  const navigator = { clipboard: { writeText: async (text) => writes.push(text) } };

  await copyText("one-time-token", { navigator });

  assert.deepEqual(writes, ["one-time-token"]);
});

test("copyText falls back to a temporary textarea on an HTTP origin", async () => {
  const document = fakeDocument();

  await copyText("one-time-token", { navigator: {}, document });

  assert.deepEqual(document.execCommands, ["copy"]);
  assert.equal(document.textareas[0].value, "one-time-token");
  assert.equal(document.textareas[0].selected, true);
  assert.deepEqual(document.textareas[0].selectionRange, [0, 14]);
  assert.equal(document.body.children.length, 0);
});

test("copyText falls back when browser policy rejects the modern API", async () => {
  const document = fakeDocument();
  const navigator = {
    clipboard: {
      writeText: async () => {
        throw new Error("NotAllowedError");
      },
    },
  };

  await copyText("one-time-token", { navigator, document });

  assert.deepEqual(document.execCommands, ["copy"]);
  assert.equal(document.body.children.length, 0);
});

test("copyText reports total failure and still removes the textarea", async () => {
  const document = fakeDocument(false);

  await assert.rejects(
    copyText("one-time-token", { navigator: {}, document }),
    /Unable to copy text/,
  );

  assert.equal(document.body.children.length, 0);
});
