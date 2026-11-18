#!/usr/bin/env node
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../../src/longrun/orbit/web/orbit.html"), "utf8");
const begin = html.indexOf("class FeedView {");
const end = html.indexOf("/* ---------------------------------------------------------------- App --- */", begin);
assert.ok(begin >= 0 && end > begin);

function setup(embedded) {
  const listeners = {}, timers = [], posts = [], lines = [], led = [];
  const parent = {postMessage: (data, origin) => posts.push({data, origin})};
  const win = {
    addEventListener: (name, fn) => { listeners[name] = fn; },
    removeEventListener: (name, fn) => { if (listeners[name] === fn) delete listeners[name]; },
    parent: embedded ? parent : null
  };
  if (!embedded) win.parent = win;
  let direct = 0;
  const api = {
    es: () => { direct++; return new EventTarget(); },
    get: async () => ({events: []})
  };
  const context = {
    window: win, location: {origin: "http://fixture", search: embedded ? "?embed=1" : ""},
    URLSearchParams, EventTarget, MessageEvent, Event,
    setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout: () => {},
    $: id => id === "led" ? {classList: {add() { led.push("on"); }, remove() { led.push("off"); }}} : null,
    esc: x => x, console
  };
  vm.runInNewContext(html.slice(begin, end) + "\nthis.FeedView = FeedView;", context);
  const feed = new context.FeedView(api, () => lines.push("sync"));
  feed.line = (kind, data) => lines.push([kind, data.session]);
  feed.paintBacklog = () => {};
  feed.connect();
  return {feed, listeners, timers, posts, parent, lines, led, direct: () => direct};
}

const embedded = setup(true);
assert.equal(embedded.direct(), 0, "embedded Orbit must wait for the parent feed");
assert.equal(embedded.posts[0].data.type, "longrun-feed-subscribe");
assert.equal(embedded.posts[0].origin, "http://fixture");
embedded.listeners.message({origin: "http://evil", source: embedded.parent,
  data: {type: "longrun-feed-event", kind: "chat.run", data: '{"session":"bad"}'}});
assert.equal(embedded.lines.length, 0, "foreign origin must be ignored");
embedded.listeners.message({origin: "http://fixture", source: {}, data: {type: "longrun-feed-ack"}});
embedded.timers[0]();
assert.equal(embedded.direct(), 1, "unacknowledged parent must fall back to direct feed");

const shared = setup(true);
shared.listeners.message({origin: "http://fixture", source: shared.parent,
  data: {type: "longrun-feed-ack"}});
shared.timers[0]();
shared.listeners.message({origin: "http://fixture", source: shared.parent,
  data: {type: "longrun-feed-event", kind: "chat.run", data: '{"session":"good"}'}});
assert.equal(shared.direct(), 0);
assert.deepEqual(shared.lines[0], ["chat.run", "good"]);
const disconnected = setup(true);
disconnected.listeners.message({origin: "http://fixture", source: disconnected.parent,
  data: {type: "longrun-feed-ack", connected: false}});
assert.deepEqual(disconnected.led, ["off"], "acknowledging subscription must not claim an offline feed is live");
disconnected.listeners.message({origin: "http://fixture", source: disconnected.parent,
  data: {type: "longrun-feed-ack", connected: true}});
assert.deepEqual(disconnected.led, ["off", "on"]);
assert.equal(setup(false).direct(), 1, "standalone Orbit keeps its direct feed");

const page = fs.readFileSync(path.join(__dirname, "../../webui/index.html"), "utf8");
const bridgeStart = page.indexOf("const _orbitFeedSubscribers = new Set();");
const bridgeEnd = page.indexOf("function _startBuildWatch()", bridgeStart);
assert.ok(bridgeStart >= 0 && bridgeEnd > bridgeStart);
const parentListeners = {}, deliveries = [];
const child = {postMessage: (data, origin) => deliveries.push({data, origin})};
const stranger = {postMessage: () => { throw Error("unexpected subscriber"); }};
const parentContext = {
  window: {addEventListener: (name, fn) => { parentListeners[name] = fn; }},
  document: {getElementById: id => id === "panelFrame" ? {contentWindow: child} : null},
  location: {origin: "http://fixture"}, Set
};
vm.runInNewContext(page.slice(bridgeStart, bridgeEnd) + "\nthis.bridge = _bridgeOrbitFeed;", parentContext);
parentListeners.message({origin: "http://evil", source: child, data: {type: "longrun-feed-subscribe"}});
parentListeners.message({origin: "http://fixture", source: stranger, data: {type: "longrun-feed-subscribe"}});
assert.equal(deliveries.length, 0, "parent rejects untrusted origin and window");
parentListeners.message({origin: "http://fixture", source: child, data: {type: "longrun-feed-subscribe"}});
assert.equal(deliveries[0].data.type, "longrun-feed-ack");
assert.equal(deliveries[0].data.connected, false);
const source = new EventTarget();
parentContext.bridge(source);
source.dispatchEvent(new Event("open"));
assert.equal(deliveries[1].data.connected, true);
source.dispatchEvent(new MessageEvent("chat.run", {data: '{"session":"good"}'}));
assert.equal(deliveries[2].data.kind, "chat.run");
assert.equal(deliveries[2].origin, "http://fixture");
console.log("PASS embedded Orbit uses authenticated parent feed with standalone fallback");
