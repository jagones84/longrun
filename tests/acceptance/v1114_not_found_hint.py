#!/usr/bin/env python3
"""v1114 — a not-found refusal names what DOES exist near the path.

Round 46. The failure register states the remedy for this family — "confirm the
path first (workspace list / sessions tree)" — and the harness never paid for it:
measured 2026-11-18 over the live store, 6 `fs.read` cards carried only
`no such file: <abs path>`, and the model's next call was a guess
(`jevarium/config.py` → `server/engine.py`) or a fallback to glob/grep.

The listing is the result's `hint` and NOT part of `error`, on purpose:
`error_class` reads `error`, and a listing there would fork the class per folder.

  A  a missing file names its folder and the names in it (folders marked `/`)
  B  the closest name comes first, so the typo case is answered, not dumped
  C  a missing PARENT names the nearest folder that does exist
  D  the OBSERVATION carries the hint — what the model reads, not only the dict
  E  fs.edit carries the same hint (one helper, two call sites)
  F  a real file still reads normally and gains no hint key
  G  the class stays `no such file: <path>`, so the register still groups it
  H  a folder read lists what is inside instead of claiming it does not exist

Deterministic: temp dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1114_not_found_hint.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402
from longrun.util import selfevolve as SE  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


_tmp = tempfile.mkdtemp(prefix="v1114-")
os.makedirs(os.path.join(_tmp, "server"))
for _n in ("config.py", "engine.py", "notes.txt"):
    with open(os.path.join(_tmp, _n), "w", encoding="utf-8") as _f:
        _f.write("x = 1\n")
_empty = os.path.join(_tmp, "empty")
os.makedirs(_empty)

_orig = T.registry.tool_spec
T.registry.tool_spec = lambda name: ({"roots": [_tmp]} if name in ("fs.read", "fs.edit")
                                     else _orig(name))
try:
    # ------------------------------------------------- A: the folder listing ---
    a = T._fs_read({"path": os.path.join(_tmp, "nope.py")}, "v1114")
    hint_a = str(a.get("hint") or "")
    check("A1 the refusal is still a not-found", a.get("ok") is False
          and str(a.get("error") or "").endswith("nope.py"), a)
    check("A2 the hint names the folder and what the folder has",
          "has:" in hint_a and "config.py" in hint_a and "engine.py" in hint_a,
          hint_a)
    check("A3 a subfolder is marked as one", "server/" in hint_a, hint_a)

    # ------------------------------------------------- B: the closest first ---
    b = T._fs_read({"path": os.path.join(_tmp, "engin.py")}, "v1114")
    tail = str(b.get("hint") or "").split("has:", 1)[-1].strip()
    check("B1 the near miss is the first name offered",
          tail.startswith("engine.py"), b.get("hint"))

    # ------------------------------------------------- C: the missing parent --
    c = T._fs_read({"path": os.path.join(_tmp, "nope", "deep", "x.py")}, "v1114")
    check("C1 a missing parent names the nearest folder that exists",
          "nearest existing folder is `%s`" % _tmp in str(c.get("hint") or ""),
          c.get("hint"))

    # ------------------------------------------------- D: the observation -----
    obs = T.observation(dict(a, tool="fs.read", exit_code=1, backend="host",
                             sandboxed=False))
    check("D1 the model's observation carries the hint",
          "hint:" in obs and "config.py" in obs, obs)

    # ------------------------------------------------- E: fs.edit too ---------
    e = T._fs_edit({"path": os.path.join(_tmp, "ghost.py"), "search": "a",
                    "replace": "b"}, "v1114")
    check("E1 fs.edit carries the same hint", e.get("ok") is False
          and "no such file" in str(e.get("error") or "")
          and "has:" in str(e.get("hint") or ""), e)

    # ------------------------------------------------- F: no regression -------
    f = T._fs_read({"path": os.path.join(_tmp, "config.py")}, "v1114")
    check("F1 a real file still reads", f.get("ok") is True
          and (f.get("content") or "").strip() == "x = 1", f.get("error"))
    check("F2 a successful read gains no hint key", "hint" not in f, f)

    # ------------------------------------------------- G: the class -----------
    check("G1 the class is still `no such file: <path>`",
          SE.error_class(a.get("error")) == "no such file: <path>",
          SE.error_class(a.get("error")))
    h = T._fs_read({"path": os.path.join(_empty, "x.py")}, "v1114")
    check("G2 an empty folder says why nothing can be offered",
          "no folder near it can be listed" in str(h.get("hint") or ""), h.get("hint"))

    # ------------------------------------------------- H: it IS a folder ------
    d = T._fs_read({"path": _tmp}, "v1114")
    check("H1 reading a folder says so instead of claiming it does not exist",
          d.get("ok") is False and "that is a folder, not a file" in str(d.get("hint") or "")
          and "config.py" in str(d.get("hint") or ""), d.get("hint"))
finally:
    T.registry.tool_spec = _orig

print("\n---\nv1114: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
