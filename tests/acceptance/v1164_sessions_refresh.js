#!/usr/bin/env node
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../../webui/index.html"), "utf8");
const start = html.indexOf("let _sessionsRefreshInFlight");
const end = html.indexOf("async function _loadSessionsOnce()", start);
assert.ok(start >= 0 && end > start, "sessions refresh coordinator is missing");

async function main() {
  const pending = [];
  let calls = 0, active = 0, maxActive = 0;
  const context = {
    _loadSessionsOnce: () => {
      calls++;
      maxActive = Math.max(maxActive, ++active);
      return new Promise((resolve, reject) => pending.push({
        resolve: () => { active--; resolve(); },
        reject: () => { active--; reject(Error("failed")); }
      }));
    }
  };
  vm.runInNewContext(html.slice(start, end) + "\nthis.refresh = loadSessions;", context);
  const first = context.refresh();
  for (let i = 0; i < 20; i++) context.refresh();
  await Promise.resolve();
  pending.shift().resolve();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 1, "synchronous invalidations before a request starts need only one refresh");
  await first;
  const burst = context.refresh();
  await Promise.resolve();
  for (let i = 0; i < 20; i++) context.refresh();
  assert.equal(calls, 2);
  pending.shift().resolve();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 3, "burst must schedule one final refresh");
  context.refresh();
  pending.shift().resolve();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 4, "invalidations during the follow-up must not be lost");
  pending.shift().resolve();
  await burst;
  assert.equal(maxActive, 1);
  const failure = context.refresh();
  await Promise.resolve();
  pending.shift().reject();
  await assert.rejects(failure, /failed/);
  const retry = context.refresh();
  await Promise.resolve();
  pending.shift().resolve();
  await retry;
  console.log("PASS sessions refresh serializes bursts and preserves invalidations");
}
main().catch(err => { console.error(err); process.exitCode = 1; });
