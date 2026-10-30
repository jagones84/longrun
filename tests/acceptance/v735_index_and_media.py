#!/usr/bin/env python3
"""v735 — the code index maps the CODE, a video source is TRANSCRIBED, `A1` is pinned.

EV-40. Three operator findings, one mechanism each:

  A  the codebase index included the whole TEST tree, so in a repo with hundreds
     of test files every real symbol lost the top-k to a fixture — the index now
     drops `tests/`, `spec/`, `test_*.py`, `*.test.ts`… (opt-out: `exclude_tests`)
  B  a YouTube URL added to a notebook was fetched as HTML: the source held the
     page furniture and none of the words. A video URL is now transcribed by an
     out-of-process transcriber; when none is installed the add FAILS with the
     reason (the Knowledge panel shows it) instead of storing silence
  C  `longrunAgent` is the harness's own supervisor and owns the FIRST agent
     number (`A1`), pinned so a reset/retrofit never renames it

Deterministic and OFFLINE: temp dirs, a fake transcriber, no model, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v735-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CODEBASE_DIR"] = os.path.join(TMP, "codebase")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(TMP, "knowledge")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "workspaces")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


from longrun.memory import chunk as C  # noqa: E402
from longrun.memory import indexcfg  # noqa: E402

# ---- A: what counts as a TEST path ------------------------------------------
CASES = (
    ("src/longrun/memory/knowledge.py", False),
    ("src/longrun/memory/chunk.py", False),
    ("webui/index.html", False),
    ("docs/specification.md", False),
    ("tests/acceptance/v735_index_and_media.py", True),
    ("src/longrun/tests/helper.py", True),
    ("src/pkg/test_loader.py", True),
    ("src/pkg/loader_test.py", True),
    ("src/pkg/conftest.py", True),
    ("webui/src/panel.spec.ts", True),
    ("app/src/main.test.tsx", True),
    ("android/app/src/FooTest.java", True),
    ("service/handler_test.go", True),
    ("e2e/login.ts", True),
)
bad = [(p, want) for p, want in CASES if C.is_test_path(p) is not want]
check("A1 `is_test_path` splits tests from the codebase", not bad, bad)

PROJ = os.path.join(TMP, "proj")
for rel in ("src/app.py", "src/util.py", "tests/test_app.py", "tests/helpers.py",
            "src/app.test.ts", "README.md"):
    p = os.path.join(PROJ, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# %s\nvalue = 1\n" % rel)

CFG = {"ignore": [], "max_file_kb": 512}


def _roster(exclude_tests):
    """Relative paths `walk` yields for the fixture tree."""
    return sorted(r for r, _a, _l, _k in C.walk(PROJ, CFG, exclude_tests=exclude_tests))


with_tests = _roster(False)
without = _roster(True)
check("A2 with the flag off the whole tree is walked (opt-out still works)",
      "tests/test_app.py" in with_tests and "src/app.test.ts" in with_tests, with_tests)
check("A3 the test tree is dropped: only the product remains",
      without == ["README.md", "src/app.py", "src/util.py"], without)

check("A4 the CODE index is the caller that sets the flag (KB is untouched)",
      indexcfg.DEFAULT_CONFIG.get("exclude_tests") is True
      and "exclude_tests=bool(cfg.get(\"exclude_tests\", True))"
      in open(os.path.join(REPO, "src", "longrun", "memory", "codeindex.py"),
              encoding="utf-8").read())

# ---- B: a video URL is transcribed, never fetched as a page -----------------
check("B1 the video URL forms are recognised",
      all(C.is_media_url(u) for u in (
          "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
          "https://youtu.be/dQw4w9WgXcQ",
          "https://youtube.com/shorts/abc",
          "https://m.youtube.com/watch?v=abc",
          "https://music.youtube.com/watch?v=abc",
          "http://www.youtube.com/live/abc")))
check("B2 a normal page URL is not a video",
      not any(C.is_media_url(u) for u in (
          "https://www.youtube.com/about", "https://example.org/report.pdf",
          "https://arxiv.org/abs/2401.00001", "")))

_orig_disc = C.DEFAULT_TRANSCRIBERS
C.DEFAULT_TRANSCRIBERS = ()
_txt, _err = C.transcribe_media_url("https://youtu.be/abc", {})
check("B3 no transcriber -> an explicit error, no exception",
      _txt == "" and "no transcriber" in _err, _err)

GOOD = os.path.join(TMP, "good_transcriber.py")
with open(GOOD, "w", encoding="utf-8") as f:
    f.write("import sys\n"
            "a = sys.argv[1:]\n"
            "out = a[a.index('--output_text') + 1] if '--output_text' in a else ''\n"
            "open(out, 'w', encoding='utf-8').write("
            "'The video explains the widget funnel step by step.\\n')\n")
BAD = os.path.join(TMP, "bad_transcriber.py")
with open(BAD, "w", encoding="utf-8") as f:
    f.write("import sys\n"
            "sys.stderr.write('boom: no audio stream found\\n')\n"
            "sys.exit(3)\n")

GOOD_CFG = {"media_transcriber_python": sys.executable,
            "media_transcriber_script": GOOD,
            "media_transcriber_model": "tiny"}
_txt, _err = C.transcribe_media_url("https://youtu.be/abc", GOOD_CFG)
check("B4 a transcriber's words come back as the source text",
      _err == "" and "widget funnel" in _txt, (_txt, _err))

BAD_CFG = dict(GOOD_CFG, media_transcriber_script=BAD)
_txt2, _err2 = C.transcribe_media_url("https://youtu.be/abc", BAD_CFG)
check("B5 a failing transcriber reports its own stderr and exit code",
      _txt2 == "" and "exit 3" in _err2 and "boom" in _err2, _err2)
C.DEFAULT_TRANSCRIBERS = _orig_disc

# ---- B (cont.): the knowledge base uses it ----------------------------------
from longrun.memory import knowledge as kb  # noqa: E402

kb.clear()
indexcfg.save_config({"embed_model": "", "media_transcriber_python": "",
                      "media_transcriber_script": ""})
C.DEFAULT_TRANSCRIBERS = ()
_nb = kb.create_notebook("Videos")

_fail = kb.add_source(_nb["id"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
check("B6 adding a video URL with no transcriber FAILS loudly",
      _fail.get("ok") is False and "no transcriber" in (_fail.get("error") or ""), _fail)
check("B7 the failed add stores no source (no page furniture)",
      [s for s in kb.list_sources(_nb["id"]) if s["ref"].startswith("https://")] == [],
      kb.list_sources(_nb["id"]))

_multi = kb.add_sources(_nb["id"], "https://youtu.be/abc")
check("B8 a batch surfaces the failure as ONE top-level error (the panel reads it)",
      _multi.get("ok") is False and "no transcriber" in (_multi.get("error") or ""), _multi)

indexcfg.save_config({"media_transcriber_python": sys.executable,
                      "media_transcriber_script": GOOD,
                      "media_transcriber_model": "tiny"})
_ok = kb.add_source(_nb["id"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
check("B9 with a transcriber the same URL becomes a searchable source",
      _ok.get("ok") is True and (_ok.get("chunks") or 0) >= 1
      and _ok.get("kind") == "media-url", _ok)
_hits = kb.search("widget funnel", notebook=_nb["id"], k=3, include_text=True)["results"]
check("B10 the transcript — not the page — is what the notebook answers with",
      any("widget funnel" in (h.get("text") or "") for h in _hits), _hits)
indexcfg.save_config({"media_transcriber_python": "", "media_transcriber_script": "",
                      "media_transcriber_model": "small"})
C.DEFAULT_TRANSCRIBERS = _orig_disc

# ---- C: `longrunAgent` owns A1 ----------------------------------------------
from longrun.agent import agents as agents_mod  # noqa: E402

reg = agents_mod.REGISTRY
_first = reg.designate("s-first", name="First worker")
check("C1 a normal session takes the first free number",
      _first.get("agent", {}).get("id") == "A1", _first)

_pin = reg.designate("longrunAgent", kind="session")
check("C2 the pinned supervisor takes A1 even when it is already issued",
      _pin.get("agent", {}).get("id") == "A1", _pin)
_moved = reg.get("s-first")
check("C3 the displaced record is renumbered, never duplicated as A1",
      _moved.get("id") == "A2", _moved)
check("C4 exactly one live record holds A1",
      [a["id"] for a in reg.list()["agents"]].count("A1") == 1,
      [a["id"] for a in reg.list()["agents"]])

reg.designate("s-second", name="Second worker")
check("C5 the sequence continues past the pin",
      (reg.get("s-second") or {}).get("id") == "A3", reg.get("s-second"))
reg.release("s-second")
check("C6 a delete retracts the counter but never touches the pin",
      reg.list()["seq"] == 2
      and (reg.get("longrunAgent") or {}).get("id") == "A1",
      reg.list()["seq"])

from longrun.memory import stores  # noqa: E402

os.remove(os.environ["LONGRUN_AGENTS_FILE"])
stores.ensure_agent({"id": "longrunAgent", "title": "longrunAgent · VEO"})
check("C7 a session born as the supervisor is pinned at birth",
      (reg.get("longrunAgent") or {}).get("id") == "A1", reg.get("longrunAgent"))

from longrun.agent import longrun_agent as LA  # noqa: E402

reg.release("longrunAgent")
check("C8 a registry that lost the supervisor has no A1",
      reg.get("longrunAgent") is None
      and [a["id"] for a in reg.list()["agents"]].count("A1") == 0,
      reg.list()["agents"])
LA.ensure_system_session()
check("C9 ensure_system_session restores the pinned A1",
      (reg.get("longrunAgent") or {}).get("id") == "A1", reg.get("longrunAgent"))

print("\n---")
print("v735: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
