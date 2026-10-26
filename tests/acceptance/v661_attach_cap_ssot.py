"""v661 — ONE ceiling for an attachment: upload and preview cannot disagree.

Operator's SSOT audit of the whole codebase: "general single source of truth AUDIT
for the whole codebase". The remaining finding this cuts is the attachment cap:

  * `LONGRUN_ATTACH_MAX` was read in THREE places with the same default written
    three times (`core/api_v02.py` twice, `core/httpapi.py` once);
  * the inline preview guard (`GET /api/fs/raw`) did not read the variable AT ALL
    and compared against a bare `32 * 1024 * 1024`.

So raising `LONGRUN_ATTACH_MAX` admitted a bigger attachment and then refused to
PREVIEW the very file it had accepted — one question ("how big may an attachment
be?") with two answers. After v661 there is one reader, `paths.attach_max_bytes()`,
read at CALL time, and no literal cap survives anywhere in the backend.

Deterministic, no model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v661-")
for _var, _tail in (
    ("LONGRUN_DATA_DIR", "data"),
    ("LONGRUN_CONFIG_DIR", "cfg"),
    ("LONGRUN_DB", "events.db"),
    ("LONGRUN_SESSIONS_DIR", "sessions"),
    ("LONGRUN_GRAPH_DIR", "graphs"),
):
    os.environ[_var] = os.path.join(TMP, _tail)
os.environ.pop("LONGRUN_ATTACH_MAX", None)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import paths  # noqa: E402
from longrun.core import api_v02  # noqa: E402

API_SRC = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
               encoding="utf-8").read()
HTTP_SRC = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
                encoding="utf-8").read()
DEFAULT = 32 * 1024 * 1024

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def ceiling_with(raw):
    """The ceiling the process reports while LONGRUN_ATTACH_MAX holds `raw`."""
    if raw is None:
        os.environ.pop("LONGRUN_ATTACH_MAX", None)
    else:
        os.environ["LONGRUN_ATTACH_MAX"] = raw
    return paths.attach_max_bytes()


# ---- A. one reader, one default ---------------------------------------------
check("A1 the default ceiling is 32 MiB",
      ceiling_with(None) == DEFAULT, ceiling_with(None))
check("A2 the operator's override is honoured",
      ceiling_with("1048576") == 1048576)
check("A3 a blank value falls back to the default",
      ceiling_with("   ") == DEFAULT)
check("A4 a non-numeric value falls back to the default (no crash)",
      ceiling_with("lots") == DEFAULT)
check("A5 a non-positive value falls back to the default",
      ceiling_with("0") == DEFAULT and ceiling_with("-5") == DEFAULT)
check("A6 the value is read at CALL time, never cached at import",
      ceiling_with("2048") == 2048 and ceiling_with("4096") == 4096)
check("A7 the default is a named constant, not a literal per call site",
      paths.ATTACH_MAX_DEFAULT == DEFAULT)

# ---- B. the variable is read in exactly one module ---------------------------
# The QUOTED literal, so a comment that merely NAMES the variable (e.g. the note
# left at the preview guard) is not counted as a reader.
_QUOTED = '"LONGRUN_ATTACH_MAX"'
READS = []
for _root, _dirs, _files in os.walk(os.path.join(REPO, "src", "longrun")):
    _dirs[:] = [d for d in _dirs if d != "__pycache__"]
    for _f in _files:
        if not _f.endswith(".py"):
            continue
        _p = os.path.join(_root, _f)
        if _QUOTED in open(_p, encoding="utf-8").read():
            READS.append(os.path.relpath(_p, REPO).replace("\\", "/"))
check("B1 LONGRUN_ATTACH_MAX is read in ONE module only",
      READS == ["src/longrun/util/paths.py"], READS)
check("B2 no backend file still carries the bare 32 MiB literal",
      "32 * 1024 * 1024" not in API_SRC and "32 * 1024 * 1024" not in HTTP_SRC)
_N_API = API_SRC.count("_paths.attach_max_bytes()")
_N_HTTP = HTTP_SRC.count("_paths.attach_max_bytes()")
check("B3 all three former call sites ask the one reader",
      _N_API == 2 and _N_HTTP == 1, (_N_API, _N_HTTP))
check("B4 the preview guard asks the same reader (was the bare literal)",
      "if _os.path.getsize(p) > _paths.attach_max_bytes():" in API_SRC)

# ---- C. behaviour: the cap the OPERATOR sets is the cap that applies ---------
os.environ["LONGRUN_ATTACH_MAX"] = "1024"
_big = api_v02.attach_save(b"x" * 2048, name="probe.txt", session="v661")
_small = api_v02.attach_save(b"x" * 512, name="probe-ok.txt", session="v661")
check("C1 a payload over the operator's cap is refused with THAT number",
      _big.get("ok") is False and "2048 > 1024 bytes" in str(_big.get("error")),
      _big.get("error"))
check("C2 a payload under it is accepted",
      _small.get("ok") is True and _small.get("size") == 512, _small.get("error"))
os.environ["LONGRUN_ATTACH_MAX"] = "4096"
_retry = api_v02.attach_save(b"x" * 2048, name="probe-again.txt", session="v661")
check("C3 raising the cap admits the SAME payload — one reader drives the upload",
      _retry.get("ok") is True, _retry.get("error"))
os.environ.pop("LONGRUN_ATTACH_MAX", None)

print("\n---\nv661: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
