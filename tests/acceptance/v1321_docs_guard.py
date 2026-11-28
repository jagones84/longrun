#!/usr/bin/env python3
"""v1321 — the tracked docs' links and anchors resolve (the docs guard).

The docs are read by agents and by humans, and a link that points nowhere fails
silently: the README carries its own table of contents as 30 same-file anchors, `docs/`
cross-link each other and `ARCHITECTURE.md` cites three `file:///…` paths into `src/`.
`v1271` pins the doc SET (README links every tracked doc) and `v1278` the countable
claims INSIDE `ARCHITECTURE.md`; before this pin nothing resolved a link.

`harness/docs_guard.py` walks the declared scope (six root docs, `docs/**`,
`.github/**`), skips fenced blocks and inline code, and reports three kinds:
`broken-link`, `missing-anchor`, `stale-absolute`. It is reachable from BOTH doors —
the CLI (`forge.py docsguard`) and the model-facing `harness` tool's `docsguard`
action — so this pin proves them identical (D).

Deterministic: temp stores, no model, no network, no server.
Run: python3 tests/acceptance/v1321_docs_guard.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import docs_guard  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail else ""))


def written(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ---- A: the real tree -------------------------------------------------------
out = docs_guard.check(REPO)
stats = out["stats"]
check("A1 the guard read the tracked docs", stats["docs"] >= 20, stats)
check("A2 it counted the relative links", stats["links"] >= 30, stats)
check("A3 it counted the markdown anchors", stats["anchors"] >= 30, stats)
check("A4 every link and anchor resolves", out["verdict"] == "clean",
      out["findings"][:3] or stats)
check("A5 every result carries the module's own format",
      out["format"] == "longrun-docs-guard/1", out["format"])

# ---- B: a synthetic tree — each detector must bite, and fences must not ----
tmp = tempfile.mkdtemp(prefix="sf-v1321-")
written(tmp, "docs/good.md", "# Good\n\n## Present\n")
written(tmp, "README.md", "\n".join([
    "# Doc",
    "",
    "## Here",
    "",
    "- [ok](docs/good.md)",
    "- [ok-anchor](docs/good.md#present)",
    "- [same](#here)",
    "- [bad](docs/missing.md)",
    "- [bad-anchor](docs/good.md#absent)",
    "- [bad-same](#absent)",
    "- [bad-abs](file:///nonexistent/guard_probe.py#L1)",
    "",
    "```",
    "[fenced](docs/missing-fenced.md)",
    "```",
    "",
    "An inline `[inline](docs/missing-inline.md)` example is not a claim.",
    "",
]))
probe = docs_guard.check(tmp)
found = sorted((f["kind"], f["target"]) for f in probe["findings"])
expected = sorted([
    ("broken-link", "docs/missing.md"),
    ("missing-anchor", "docs/good.md#absent"),
    ("missing-anchor", "#absent"),
    ("stale-absolute", "file:///nonexistent/guard_probe.py#L1"),
])
check("B1 the four real breakages are reported, exactly", found == expected, found)
check("B2 a valid link, a valid anchor and a same-file anchor are accepted",
      not any(f["target"] in ("docs/good.md", "docs/good.md#present", "#here")
              for f in probe["findings"]),
      [f for f in probe["findings"] if f["target"].startswith("docs/good.md")])
check("B3 a link inside a fence or inline code is not a claim", not any(
    "missing-fenced" in f["target"] or "missing-inline" in f["target"]
    for f in probe["findings"]), probe["findings"])
check("B4 the synthetic verdict is `problems` and each finding names file+line",
      probe["verdict"] == "problems"
      and all({"file", "line", "kind", "target"} <= set(f) for f in probe["findings"]),
      probe["findings"][:2])

# ---- C: the verdict is the exit contract -----------------------------------
check("C1 `clean` means zero findings and `problems` means at least one",
      (out["verdict"] == "clean") == (not out["findings"])
      and (probe["verdict"] == "problems") == bool(probe["findings"]))

# ---- D: the model-facing door (the `harness` tool) -------------------------
# The agent reaches the SAME check through `harness.docsguard`; the stores are
# throwaway so importing the tool package never touches the operator's data.
TMP_STORES = tempfile.mkdtemp(prefix="sf-v1321-stores-")
for _key, _name in (("LONGRUN_CONFIG_DIR", "cfg"), ("LONGRUN_SESSIONS_DIR", "sessions"),
                    ("LONGRUN_DATA_DIR", "data"), ("LONGRUN_DB", "events.db"),
                    ("LONGRUN_GRAPH_DIR", "graphs"), ("LONGRUN_JOBS", "jobs.json")):
    os.environ[_key] = os.path.join(TMP_STORES, _name)
    if not _name.endswith(".json"):
        os.makedirs(os.environ[_key], exist_ok=True)

from longrun.tools import registry          # noqa: E402
from longrun.tools import tools as T        # noqa: E402

schema = registry._LEGACY_SCHEMAS["harness"]
actions = schema["properties"]["action"].get("enum") or []
check("D1 docsguard is a declared `harness` action", "docsguard" in actions, actions)
check("D2 restart/status/graph survive (no regression)",
      {"restart", "status", "graph"} <= set(actions), actions)
check("D3 docsguard reads no field",
      registry._SUBTOOL_FIELDS["harness"].get("docsguard") == [],
      registry._SUBTOOL_FIELDS["harness"])
guide = registry._SUBTOOL_GUIDANCE.get("harness.docsguard") or ""
check("D4 it has its own one actionable guidance line",
      80 < len(guide) < 400 and "link" in guide.lower(), len(guide))
check("D5 reading the docs opens no approval gate",
      registry.subtool_gate("harness.docsguard", {}) is None)
tool_out = T._harness({"action": "docsguard"}, None)
check("D6 the tool answers the SAME verdict and stats as check(REPO)",
      tool_out.get("ok") is True and tool_out.get("verdict") == out["verdict"]
      and tool_out.get("stats") == out["stats"], str(tool_out)[:200])
check("D7 the finding list is capped so a broken tree never floods the context",
      len(tool_out.get("findings") or []) <= 50
      and tool_out.get("findings_total") == len(out["findings"]), str(tool_out)[:140])
check("D8 tools.py reaches the harness ROOT, never checks/",
      "from longrun.harness import docs_guard" in open(
          os.path.join(REPO, "src", "longrun", "tools", "tools.py"), encoding="utf-8").read())

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
