#!/usr/bin/env node
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const html = fs.readFileSync(path.join(__dirname, "../../webui/index.html"), "utf8");
const begin = html.indexOf("function _startBuildWatch()");
const end = html.indexOf("\nfunction connectFeed()", begin);
assert.ok(begin >= 0 && end > begin, "idempotent build watcher is missing");

let polls = 0, timers = 0;
const chip = { hidden: true };
const make = new Function("$", "api", "setInterval", "location",
  "let _buildWatchStarted = false;\n" + html.slice(begin, end) +
  "\nreturn _startBuildWatch;");
const start = make(() => chip, async () => { polls++; return {build: "one"}; },
  () => { timers++; }, {reload() {}});
start(); start(); start();
assert.equal(polls, 1, "reconnecting must not repeat the initial poll");
assert.equal(timers, 1, "reconnecting must not install multiple timers");
console.log("PASS build watcher starts only once");
