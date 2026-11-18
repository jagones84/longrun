#!/usr/bin/env node
"use strict";
/* v1165: the WebUI must follow every turn on the page's ONE feed. These are the
   channel primitives extracted from index.html: a turn is addressed by session,
   frames of another turn are never painted, and the terminal is emitted once. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../../webui/index.html"), "utf8");
const begin = html.indexOf("const _turnChannels = new Map();");
const end = html.indexOf('"verify.run", "run.metrics", "bestofn.chosen", "graph.node.added", "graph.node.updated"];', begin);
assert.ok(begin >= 0 && end > begin, "turn channel primitives are missing from index.html");
const src = html.slice(begin, end) +
  '"verify.run", "run.metrics", "bestofn.chosen", "graph.node.added", "graph.node.updated"];\n' +
  "this.api = {_turnChannel, _adoptTurnChannel, _dispatchTurnEvent, _turnChannels, _pendingTurnChannels};";

const timers = [];
const context = { Map, Set, Object, JSON, Number, Date, String,
  setTimeout: (fn) => { timers.push(fn); return timers.length; },
  clearTimeout: (id) => { if (id) timers[id - 1] = null; } };
vm.runInNewContext(src, context);
const { _turnChannel, _adoptTurnChannel, _dispatchTurnEvent, _turnChannels, _pendingTurnChannels } = context.api;
const seen = chan => {
  const out = [];
  ["chat.delta", "tool.call", "done", "chat.final"].forEach(k =>
    chan.addEventListener(k, e => out.push([k, JSON.parse(e.data), e.lastEventId])));
  return out;
};

// 1) a turn started in this tab renders only its own session, in order.
const a = _turnChannel("A", "t1");
const got = seen(a);
_dispatchTurnEvent("chat.delta", { session: "B", text: "wrong" }, 1);
_dispatchTurnEvent("chat.delta", { session: "A", turn_id: "t1", text: "hello" }, 2);
assert.deepEqual(got.map(x => x[1].text), ["hello"]);
assert.equal(got[0][2], "2", "the durable id rides on the frame (resume cursor)");

// 2) a queued SECOND turn on the same session must not paint into the first.
_dispatchTurnEvent("chat.delta", { session: "A", turn_id: "t2", text: "other" }, 3);
assert.equal(got.length, 1, "another turn's frame was painted");

// 3) the terminal is emitted exactly once, whichever event lands first.
_dispatchTurnEvent("chat.done", { session: "A", turn_id: "t1" }, 4);
_dispatchTurnEvent("chat.stream.end", { session: "A", turn_id: "t1" }, 5);
assert.equal(got.filter(x => x[0] === "done").length, 1);
assert.equal(a._lrDone, true);

// 4) a brand-new chat has no session id yet: its frames are HELD, not guessed.
const pending = _turnChannel("", "");
const pendingSeen = seen(pending);
_dispatchTurnEvent("chat.run", { session: "fresh", turn_id: "t9" }, 10);
_dispatchTurnEvent("chat.delta", { session: "fresh", turn_id: "t9", text: "mine" }, 11);
_dispatchTurnEvent("chat.delta", { session: "other", turn_id: "x", text: "not mine" }, 12);
assert.equal(pendingSeen.length, 0, "an unnamed turn must render nothing before the start answers");
_adoptTurnChannel(pending, "fresh");
assert.equal(_turnChannels.get("fresh"), pending);
assert.equal(_pendingTurnChannels.size, 0);
assert.deepEqual(pendingSeen.map(x => x[1].text), ["mine"]);

// 5) a resume buffers live frames and replays them in id order, then live again.
const r = _turnChannel("R", "t3");
const rSeen = seen(r);
r._lrReplaying = true;
r._emit("chat.delta", { session: "R", text: "late" }, 30);
r._emit("chat.delta", { session: "R", text: "early" }, 20);
r._flushReplay();
r._emit("chat.delta", { session: "R", text: "live" }, 40);
assert.deepEqual(rSeen.map(x => x[1].text), ["early", "late", "live"]);
assert.equal(rSeen[0][2], "20");

// 6) the page still holds ONE socket: no turn opens its own EventSource.
const send = html.slice(html.indexOf("function send(text, display, atts)"), html.indexOf("function _bindRenderStream(es, live, adopt)"));
assert.ok(send.includes('"/api/chat/start"'), "send() must start the turn over the short request");
assert.ok(send.includes("_turnChannel("), "send() must follow the turn on the shared feed");
assert.equal((send.match(/new EventSource\(/g) || []).length, 1,
  "the legacy stream may appear ONLY as the fallback");
const attach = html.slice(html.indexOf("function attachTurn(sid, since)"), html.indexOf("async function _resumeTurnFromFeed"));
assert.ok(attach.includes("_turnChannel(") && attach.includes("_resumeTurnFromFeed("),
  "attachTurn() must resume from the shared feed");
console.log("PASS turns ride the shared feed: session-scoped, ordered, one terminal");
