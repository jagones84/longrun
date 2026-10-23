#!/usr/bin/env python3
"""v539 — diagnosable failures, generic local models, no stray Automate.

Covers the operator-facing gaps found live:
  * the Codebase inspector must not carry a generic longrunAgent Automate bar;
  * the chat model picker rejects retired/unknown refs and persists a fallback;
  * a local provider's catalogue is completed from its LIVE server roster;
  * `self action=diagnostics` exposes the SAME Settings report (no duplicate
    checks) and can isolate one code/source.
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v539-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(ROOT, "src"))

from longrun.core import diagnostics as D          # noqa: E402
from longrun.model import providers as P          # noqa: E402
from longrun.tools import diag                     # noqa: E402
from longrun.tools import registry                 # noqa: E402
from longrun.tools import tools as T               # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


with open(os.path.join(ROOT, "webui", "index.html"), encoding="utf-8") as f:
    ui = f.read()

check("A1 Codebase inspector no longer renders the generic Automate bar",
      'mountSectionAutomate(\'section[data-insp="codebase"]\'' not in ui
      and "function mountSectionAutomate" in ui
      and "mountCategoryAutomate(name)" in ui)
check("A2 the model picker rejects unknown refs and persists an available fallback",
      "function _modelKnown(ref)" in ui
      and "function _ensureAvailableModel()" in ui
      and '"/api/sessions/" + encodeURIComponent(sessionId) + "/model"' in ui
      and "no longer available; switched to" in ui
      and "_ensureAvailableModel();" in ui)

_orig = (P.load, P.local_contexts, P.available)
try:
    P.load = lambda reload=False: {
        "providers": [{
            "id": "dgx", "name": "DGX", "kind": "openai", "local": True,
            "base_url": "http://127.0.0.1:8080/v1",
            "models": [{"id": "declared", "context_length": 4096}],
        }],
        "default": None,
    }
    P.available = lambda provider: True
    P.local_contexts = lambda pid, block=False: {"declared": 4096,
                                                 "installed-new": 8192}
    cat = P.catalog()
    rows = {m["id"]: m for p in cat["providers"] for m in p.get("models", [])}
    check("B1 a local provider lists the live roster, not just providers.yaml",
          rows.get("installed-new", {}).get("ref") == "dgx:installed-new"
          and rows["installed-new"]["context_length"] == 8192
          and rows.get("declared", {}).get("context_length") == 4096,
          sorted(rows))
finally:
    P.load, P.local_contexts, P.available = _orig

_orig_lc = P.local_contexts
try:
    P.local_contexts = lambda pid, block=False: {"installed-new": 8192}
    cfg = {"providers": [{
        "id": "dgx", "local": True, "kind": "openai",
        "base_url": "http://127.0.0.1:8080/v1",
        "models": [{"id": "declared"}],
    }]}
    live_issues = D.validate_provider_config(cfg, {}, {}, "dgx:installed-new")
    check("B6 diagnostics accept an installed live model without a false positive",
          not [i for i in live_issues
               if i.get("code") == "model.id_not_configured"], live_issues)
finally:
    P.local_contexts = _orig_lc

check("B2 registry exposes self.diagnostics with isolation fields",
      "self.diagnostics" in {t["name"] for t in registry.catalog() if t.get("name")}
      and "diagnostics" in (registry.TOOL_SCHEMAS["self"]["properties"]["action"]
                            .get("enum") or [])
      and all(k in registry.TOOL_SCHEMAS["self"]["properties"]
              for k in ("code", "source", "model")))

_CANNED = {
    "ok": True,
    "summary": {"errors": 1, "warnings": 1, "info": 0, "actionable": 2},
    "issues": [
        {"code": "provider.auth_rejected", "severity": "error",
         "source": "openrouter", "session": "s1", "model": "openrouter:x"},
        {"code": "config.value_invalid", "severity": "warning",
         "source": "tools.yaml", "file": "tools.yaml", "field": "runtime.x"},
    ],
}
_orig_collect = D.collect
try:
    D.collect = lambda session_id=None, model=None, host="127.0.0.1": dict(_CANNED)
    full = diag.settings_report()
    check("B3 settings_report reuses the Settings collector verbatim",
          full.get("total") == 2 and full.get("summary") == _CANNED["summary"]
          and [i["code"] for i in full["issues"]]
          == ["provider.auth_rejected", "config.value_invalid"], full)
    one = diag.settings_report(code="provider.auth_rejected")
    check("B4 code/source filters isolate one issue and recount the summary",
          one.get("total") == 1
          and one["issues"][0]["source"] == "openrouter"
          and one.get("summary", {}).get("errors") == 1
          and one.get("summary", {}).get("warnings") == 0
          and diag.settings_report(source="TOOLS")["total"] == 1, one)
finally:
    D.collect = _orig_collect

_orig_report = diag.settings_report
try:
    diag.settings_report = lambda **kwargs: {"ok": True, "total": 1,
                                             "summary": {"errors": 0, "warnings": 1,
                                                         "info": 0, "actionable": 1},
                                             "issues": [{"code": "x"}]}
    res = T.execute("self", {"action": "diagnostics", "code": "x"})
    check("B5 self action=diagnostics attaches the Settings report",
          res.get("ok") is True
          and res.get("diagnostics", {}).get("total") == 1
          and res.get("repo_path") == ROOT, res.get("action"))
finally:
    diag.settings_report = _orig_report

shutil.rmtree(TMP, ignore_errors=True)
print("v539: %d/%d PASS" % (sum(results), len(results)))
raise SystemExit(0 if all(results) else 1)
