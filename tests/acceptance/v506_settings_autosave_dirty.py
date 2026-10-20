#!/usr/bin/env python3
"""v506 — approval settings auto-save; Config Files save buttons reflect dirtiness."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    UI = f.read()

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """Record one source contract for settings save behavior."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def _function_body(source: str, name: str, next_name: str) -> str:
    """Return a named function and its body from the inline UI script."""
    start = source.find(name)
    end = source.find(next_name, start + len(name))
    return source[start:end] if start >= 0 and end > start else ""


tools = _function_body(UI, "function renderTools(el, d)", "function _toolAdvanced")
approval_save = _function_body(UI, "function scheduleApprovalSave", "function renderTools(el, d)")
section = _function_body(UI, "function _setSectionEl(sec)", "function _setFieldEl")
dirty = _function_body(UI, "function _syncSectionDirty", "function _setFieldEl")
section_save = _function_body(UI, "async function saveSettingsSection", "let _policyLoadedAt")
config_load = _function_body(UI, "async function loadConfigFile", "async function saveConfigFile")
config_save = _function_body(UI, "async function saveConfigFile", "/* JAG-491: structured settings")
config_dirty = _function_body(UI, "function _cfgFileHasDraft()", "async function loadConfigFiles")

check("global approval policy has no manual Save button",
      'id="apSave"' not in tools and "save policy</button>" not in tools)
check("outside-workspace and timeout changes schedule an automatic save",
      "scheduleApprovalSave" in tools
      and 'querySelector("#apOutside")' in tools
      and 'querySelector("#apTimeout")' in tools
      and "scheduleApprovalSave(el, b.dataset.val)" in tools)
check("Matrix promotion remains auto-saved as a separate approval field",
      'querySelector("#apMatrixPromote")' in tools
      and "apMtxCb.onchange = () => scheduleApprovalSave(el)" in tools
      and "allow_matrix_promote" in approval_save)
check("approval autosave posts a complete snapshot from current policy controls",
      "function scheduleApprovalSave" in UI
      and 'api("POST", "/api/tools", {approvals})' in approval_save
      and "outside_workspace" in approval_save
      and "timeout_secs" in approval_save
      and "allow_matrix_promote" in approval_save)
check("every structured Config Files Save starts disabled",
      'data-save disabled' in section
      and "save " in section)
check("structured forms compare typed values and enable Save only when dirty",
      "function _setSectionValues(card, sec)" in UI
      and "JSON.stringify" in dirty
      and "save.disabled = !isDirty" in dirty
      and 'classList.toggle("dirty", isDirty)' in dirty)
check("structured save does not send a clean form and rebases after success",
      "_syncSectionDirty(card, sec)" in section_save
      and "if (!isDirty)" in section_save
      and "card._savedValues =" in section_save)
check("raw YAML Save starts disabled and tracks edits against the loaded text",
      'id="cfgFileSave"' in UI
      and 'id="cfgFileSave" disabled' in UI
      and "_cfgFileBaseline" in config_dirty
      and "ta.value !== _cfgFileBaseline" in config_dirty)
check("raw YAML save refuses unchanged content and resets baseline on success",
      "_cfgFileDirty()" in config_save
      and "if (!sel || !ta || !_cfgFileDirty())" in config_save
      and "_cfgFileBaseline = savedText" in config_save)
check("dirty Save controls use the existing accent token",
      ".config-save.dirty" in UI and "var(--acc)" in UI)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
