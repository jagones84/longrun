#!/usr/bin/env python3
"""v491 — every config knob is a WebUI object, not hand-typed YAML (JAG-491).

JAG-488 made ``config/*.yaml`` editable as raw text. The operator asked for
*controls*: a checkbox per boolean, a bounded number field, a select per enum, a
repeatable row per hook. This test pins:

  A. schema coverage — every leaf of every config file is either declared in
     ``core.settings`` (a real form) or owned by a documented dedicated panel;
  B. the coercion rules (types, bounds, selects, string lists, repeatable rows);
  C. ``update()`` rejects unknown paths/types and accepts a valid section;
  D. the API + WebUI wiring (endpoint, renderer, advanced per-tool editor);
  E. the Config panel is a backup — every structured form declares its home
     Settings panel and the WebUI routes it there (settings.py `panel`).

Deterministic: no network, no model, no live config write.

Run: python3 tests/acceptance/v491_settings_forms.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v491-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("data", "sessions"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import settings  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(name):
    with open(os.path.join(REPO, name), encoding="utf-8") as f:
        return f.read()


# ---- A) every leaf of every config file is covered --------------------------
def _leaves(doc, prefix=""):
    out = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            path = (prefix + "." + str(k)) if prefix else str(k)
            if isinstance(v, dict):
                out.extend(_leaves(v, path))
            else:
                out.append(path)
    return out


def _prefix_hit(path, prefixes):
    # "*" means "the whole file is owned by that panel".
    return "*" in prefixes or any(path == p or path.startswith(p + ".")
                                  for p in prefixes)


def _schema_paths(file):
    return {f["path"] for s in settings._sections() if s["file"] == file
            for f in s["fields"]}


missing = []
checked = 0
for name in sorted(os.listdir(os.path.join(REPO, "config"))):
    if not name.endswith((".yaml", ".yml")):
        continue
    text = _read(os.path.join("config", name))
    try:
        import yaml
        doc = yaml.safe_load(text) or {}
    except Exception:  # noqa: BLE001
        doc = {}
    leaves = _leaves(doc)
    # A file whose policy sits under ONE wrapper key (`compaction:`, `jobs:`) is
    # edited by its form UNWRAPPED, so normalise the leaf paths.
    _wrap = {"compaction.yaml": "compaction.", "jobs.yaml": "jobs."}.get(name)
    if _wrap:
        leaves = [ln[len(_wrap):] if ln.startswith(_wrap) else ln
                  for ln in leaves]
    known = _schema_paths(name)
    prefixes = list((settings.DEDICATED.get(name) or {}).keys())
    for leaf in leaves:
        checked += 1
        if leaf in known or _prefix_hit(leaf, prefixes):
            continue
        missing.append(name + ":" + leaf)
check("A1 every config leaf is a form field or a documented dedicated panel",
      not missing, missing)
check("A2 the audit actually walked the config store", checked >= 25, checked)
_ids = {s["id"] for s in settings._sections()}
check("A3 the six structured sections exist",
      {"index", "compaction", "routing", "decisions",
       "hooks", "mcp_env"} <= _ids, sorted(_ids))
_compact_form = next((s for s in settings._sections() if s["id"] == "compaction"), {})
_compact_paths = {f["path"] for f in _compact_form.get("fields", [])}
check("A5 one Compaction form owns auto policy and summarizer settings",
      _compact_form.get("panel") == "compaction"
      and {"trigger_pct", "target_pct", "keep_recent",
           "summarizer.input_max_chars", "summarizer.output_max_chars",
           "summarizer.max_parts", "summarizer.instruction"} <= _compact_paths
      and "compaction.yaml" not in settings.DEDICATED,
      (_compact_form.get("panel"), sorted(_compact_paths),
       settings.DEDICATED.get("compaction.yaml")))
_compact_view = next((s for s in settings.view()["sections"]
                      if s.get("id") == "compaction"), {})
check("A6 the Compaction module exposes clickable editor paths for its files",
      "config/compaction.yaml" in (_compact_view.get("files") or [])
      and (("config/compaction.local.yaml" in (_compact_view.get("files") or []))
           == os.path.isfile(os.path.join(settings.CONFIG_DIR, "compaction.local.yaml")))
      and "config/compaction.yaml" in _read("webui/index.html")
      and 'data-config-file="' in _read("webui/index.html")
      and "openInEditor(link.dataset.configFile" in _read("webui/index.html"),
      _compact_view.get("files"))
_routing_form = next((s for s in settings._sections() if s["id"] == "routing"), {})
check("A4 Models routing leaves subagent model and fallbacks to the Subagents panel",
      any(f["path"].startswith("roles.") for f in _routing_form.get("fields", []))
      and not any(f["path"] in ("roles.subagent.model", "roles.subagent.fallbacks")
                  for f in _routing_form.get("fields", []))
      and settings.DEDICATED.get("routing.yaml", {}).get("roles.subagent.model")
      == "Settings ▸ Subagents"
      and settings.DEDICATED.get("routing.yaml", {}).get("roles.subagent.fallbacks")
      == "Settings ▸ Subagents")

# ---- B) coercion rules ------------------------------------------------------
def _field(**kw):
    base = {"path": "x", "label": "x"}
    base.update(kw)
    return base


check("B1 an int respects its bounds",
      settings._coerce(_field(type="int", min=1, max=10), "7") == 7)
try:
    settings._coerce(_field(type="int", min=1, max=10), "99")
    bad = False
except ValueError:
    bad = True
check("B2 an out-of-range int is rejected", bad)
check("B3 a bool is a bool", settings._coerce(_field(type="bool"), True) is True)
check("B4 an enum accepts only its options",
      settings._coerce(_field(type="select", options=["a", "b"]), "b") == "b")
try:
    settings._coerce(_field(type="select", options=["a", "b"]), "c")
    bad = False
except ValueError:
    bad = True
check("B5 an unknown enum value is rejected", bad)
check("B6 a string list is trimmed, deduped and split on newlines/commas",
      settings._coerce(_field(type="strlist"), "*.log\n *.tmp,*.log\n") == ["*.log", "*.tmp"])
rows = settings._coerce(
    _field(type="rows", item=[_field(path="event", label="e", type="select",
                                     options=["Stop"]),
                              _field(path="timeout_secs", label="t", type="int",
                                     min=1, max=60)]),
    [{"event": "Stop", "timeout_secs": "5"}])
check("B7 rows coerce every sub-field",
      rows == [{"event": "Stop", "timeout_secs": 5}], rows)

# ---- C) update() validates and applies --------------------------------------
_orig_save = settings._save
captured = {}


def _fake_save(name, clean):
    captured["name"] = name
    captured["clean"] = clean
    return {}


try:
    settings._save = _fake_save
    bad = settings.update({"file": "index.yaml", "values": {"nope": 1}})
    check("C1 an unknown setting is refused", not bad.get("ok")
          and "unknown setting" in str(bad.get("error")), bad)
    bad = settings.update({"file": "index.yaml", "values": {"chunk_lines": 0}})
    check("C2 an out-of-range value is refused before writing", not bad.get("ok"))
    ok = settings.update({"file": "index.yaml",
                          "values": {"chunk_lines": 90, "ignore": ["*.log"]}})
    check("C3 a valid section is applied with typed values",
          ok.get("ok") and captured.get("name") == "index.yaml"
          and captured["clean"] == {"chunk_lines": 90, "ignore": ["*.log"]}, ok)
    bad = settings.update({"file": "providers.yaml", "values": {"x": 1}})
    check("C4 a file owned by a dedicated panel has no generic form",
          not bad.get("ok"), bad)
    bad = settings.update({"file": "index.yaml", "values": {}})
    check("C5 an empty payload is refused", not bad.get("ok"))
finally:
    settings._save = _orig_save
check("C6 dotted get/set create and read nested mappings",
      settings._get({"a": {"b": {"c": 3}}}, "a.b.c") == 3
      and (lambda d: (settings._set(d, "a.b.d", 4), settings._get(d, "a.b.d"))[1])({}) == 4)

# ---- D) API + WebUI wiring --------------------------------------------------
API = _read("src/longrun/core/api_v02.py")
UI = _read("webui/index.html")
check("D1 GET and POST /api/settings exist",
      'path == "/api/settings"' in API and API.count('"/api/settings"') >= 2)
check("D2 the panel renders schema-driven controls",
      "loadSettingsForms" in UI and "_setSectionEl" in UI and "_setReadField" in UI)
check("D3 every control type has a renderer",
      all(t in UI for t in ('"bool"', '"int"', '"select"', '"strlist"', '"rows"')))
check("D4 the per-tool advanced policy has object fields",
      "apOutside" in UI and "sbxPids" in UI and "data-adv" in UI
      and "_toolAdvanced" in UI)
check("D5 the approval policy POST accepts outside_workspace/timeout",
      "outside_workspace" in API and "timeout_secs" in API)
check("D6 the dedicated panels are listed, not duplicated",
      "setDedicated" in UI and bool(settings.DEDICATED))

# ---- E) the Config panel is a backup; every form lives in its own panel -----
_panels = {"harness", "hooks", "tools", "models", "subagents", "mcp", "knowledge"}
_panels.add("compaction")
check("E1 every structured section declares a real home panel",
      all(s.get("panel") in _panels for s in settings._sections()),
      sorted({s.get("panel") for s in settings._sections()}))
check("E1a lifecycle hooks belong to the dedicated Hooks panel",
      any(s.get("file") == "hooks.yaml" and s.get("panel") == "hooks"
          for s in settings._sections()))
check("E2 view() exposes the panel for every section",
      all(sec.get("panel") for sec in settings.view()["sections"]))
check("E3 the WebUI routes each form to its declared panel",
      "_settingsSectionHost" in UI and "sec.panel" in UI)
check("E4 Settings ▸ Config keeps the raw-YAML fallback, stated plainly",
      "— the complete fallback: every key is editable here" in UI
      and "DO NOT REMOVE! ITS BACKUP (the complete fallback)" not in UI)
check("E5 the Context rail has no duplicate auto-compact controls",
      "cmpTrigger" not in UI and "cmpPolicyCard" not in UI
      and "loadCompactionPolicy" not in UI and "saveCompactionPolicy" not in UI
      and 'data-call="openSettings" data-args=\'["compaction"]\'' in UI)
check("E6 Info credits the maintainer's GitHub identity",
      "Giovanni J. Agones (@jagones84)" in UI
      and "https://github.com/jagones84" in UI)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
