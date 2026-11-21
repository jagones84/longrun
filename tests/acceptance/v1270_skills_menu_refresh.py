#!/usr/bin/env python3
"""v1270 (RED) — `/skills` refreshes a stale catalogue instead of answering "none".

Operator, 2026-11-22: the composer's `/skills` picker said "no skill present"
while the agent — whose prompt is built server-side from
`memory.skills.skills_context` — listed every skill. Measured on the live app:
`GET /api/skills` returned 280 skills and every active symlink resolved, so the
engine was fine; the PICKER rendered `_skillsCache`, filled only by `loadSkills()`
at boot. A tab opened before the skills tree was populated (the checkout moved to
MyRepos and the tree was re-linked under it) kept the empty snapshot forever.

Contract pinned here (source contracts only: no browser, no server, no model):
  A  the cache records WHEN it was filled and exposes ONE staleness predicate;
  B  `openSkillMenu()` refreshes a stale/empty cache BEFORE it renders;
  C  a refresh in flight says "loading skills…" and KEEPS the skills mode, so
     the arriving catalogue is rendered instead of a lie that resets it;
  D  the definitive empty state and the backend engine are untouched.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def _between(start, end):
    i = UI.find(start)
    if i < 0:
        return ""
    j = UI.find(end, i)
    return UI[i:j if j > 0 else i + 4000]


OPEN = _between("function openSkillMenu() {", "function openPluginMenu() {")
EMPTY = _between("if (!plugs.length && !cmds.length && !hits.length && !_plugin) {", "box.innerHTML = \"\";")
LOAD = _between("async function loadSkills() {", "/* JAG-403e")

# ------------------------------------------------------- A: cache freshness
check("A1 the cache records WHEN it was filled",
      "let _skillsLoadedAt = 0;" in UI and "const SKILLS_CACHE_TTL_MS = 30000;" in UI)
check("A2 ONE staleness predicate covers empty AND old",
      "function _skillsStale() {" in UI
      and "!(_skillsCache || []).length" in UI
      and "(Date.now() - _skillsLoadedAt) > SKILLS_CACHE_TTL_MS" in UI)
check("A3 loadSkills stamps the timestamp on success",
      "_skillsCache = d.skills || [];" in LOAD and "_skillsLoadedAt = Date.now();" in LOAD)
check("A4 the in-flight flag is cleared in every outcome",
      "_skillsSyncing = true;" in LOAD and "finally { _skillsSyncing = false; }" in LOAD)

# ------------------------------------------------- B: the picker refetches
check("B1 openSkillMenu refreshes a stale/empty cache before rendering",
      "if (_skillsStale()) {" in OPEN and "loadSkills().then(done, done);" in OPEN)
check("B2 it never claims a result while the catalogue is loading",
      "loading skills…" in OPEN)
check("B3 the re-render is guarded by the skills mode",
      "const done = () => { if (_slashSkillsOnly) skillsAutocomplete(); };" in OPEN)
check("B4 a fresh cache still renders synchronously (no extra round-trip)",
      "} else {\n    skillsAutocomplete();\n  }" in OPEN)

# ------------------------------------------------- C: no lie while syncing
check("C1 the empty state is skipped while a refresh is in flight",
      "_slashSkillsOnly && _skillsSyncing && !(_skillsCache || []).length" in EMPTY)
check("C2 that branch RETURNS, keeping the skills mode for the arriving list",
      "box.hidden = false;\n      return;\n    }" in EMPTY)
check("C3 an explicit empty state still exists once the fetch has landed",
      'if (q) {' in EMPTY and 'no skills installed' in EMPTY)

# ----------------------------------------------------- D: engine untouched
check("D1 the picker still reads the SAME backend route",
      'const d = await api("GET", "/api/skills");' in LOAD)
check("D2 the summary still counts the whole catalogue",
      "_skillsCache.length + \" skills · <b>\" + auto.length" in UI)

ok = all(results)
print(("OK %d/%d" if ok else "RED %d/%d") % (sum(results), len(results)))
sys.exit(0 if ok else 1)
