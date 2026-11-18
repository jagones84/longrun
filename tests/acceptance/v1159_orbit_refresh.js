#!/usr/bin/env node
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(path.join(__dirname, "../../src/longrun/orbit/web/orbit.html"), "utf8");
const begin = html.indexOf("  refresh(){", html.indexOf("class OrbitApp"));
const end = html.indexOf("  async _refreshOnce(){", begin);
assert.ok(begin >= 0 && end > begin, "Orbit refresh single-flight wrapper is missing");
const OrbitRefresh = new Function("return class { " + html.slice(begin, end) + " }")();

async function main() {
  const app = new OrbitRefresh();
  const pending = [];
  let active = 0, maxActive = 0, calls = 0;
  app._refreshOnce = () => {
    calls++;
    maxActive = Math.max(maxActive, ++active);
    return new Promise((resolve, reject) => pending.push({
      resolve: () => { active--; resolve(); },
      reject: () => { active--; reject(new Error("refresh failed")); }
    }));
  };
  const p = app.refresh();
  await Promise.resolve();
  for (let i = 0; i < 20; i++) app.refresh();
  assert.equal(calls, 1);
  pending.shift().resolve();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 2, "burst must trigger exactly one follow-up");
  app.refresh();
  pending.shift().resolve();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 3, "invalidation during follow-up must not be lost");
  pending.shift().resolve();
  await p;
  assert.equal(maxActive, 1);
  const failed = app.refresh();
  await Promise.resolve();
  pending.shift().reject();
  await assert.rejects(failed, /refresh failed/);
  const retry = app.refresh();
  await Promise.resolve();
  pending.shift().resolve();
  await retry;
  console.log("PASS Orbit refresh serializes bursts, preserves invalidations and retries");
}
main().catch(err => { console.error(err); process.exitCode = 1; });
