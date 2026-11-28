#!/usr/bin/env python3
"""v1321 — the tracked docs' links and anchors resolve (the docs guard).

The docs are read by agents and by humans, and a link that points nowhere fails
silently: the README carries its own table of contents as 30 same-file anchors, `docs/`
cross-link each other and `ARCHITECTURE.md` cites three `file:///…` paths into `src/`.
`v1271` pins the doc SET (README links every tracked doc) and `v1278` the countable
claims INSIDE `ARCHITECTURE.md`; before this pin nothing resolved a link.

`harness/checks/docs_guard.py` walks the declared scope (six root docs, `docs/**`,
`.github/**`), skips fenced blocks and inline code, and reports three kinds:
`broken-link`, `missing-anchor`, `stale-absolute`.

Deterministic: no server, no model, no network (paths in, a verdict out).
Run: python3 tests/acceptance/v1321_docs_guard.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import docs_guard  # noqa: E402

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

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
