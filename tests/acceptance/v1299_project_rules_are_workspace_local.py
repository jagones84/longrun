#!/usr/bin/env python3
"""v1299 — project rules come only from workspace/.longrun/rules and root AGENTS.md.

Operator clarification (2026-11-24): project rules are allowed ONLY in the
selected workspace's `.longrun/rules/`; the only additional project instruction
file is `AGENTS.md` directly at that workspace root. Do not load project rules
from `.trae/rules` or Longrun's external data home.

The workspace state resolver must also leave `.longrun/rules/` in place while it
migrates unrelated state such as `prompt.d/` to the data home.

Run: python3 tests/acceptance/v1299_project_rules_are_workspace_local.py
"""
import os
import sys
import tempfile
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, cond, extra=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(extra)[:300]) if extra else ""))


with tempfile.TemporaryDirectory(prefix="lr-v1299-") as tmp:
    home = os.path.join(tmp, "home")
    os.environ["LONGRUN_DATA_HOME"] = home
    os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "config")
    os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(home, "data", "projects")
    os.environ["LONGRUN_DATA_DIR"] = os.path.join(home, "data")
    os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
    os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)

    from longrun.memory import rules  # noqa: E402
    from longrun.util import paths  # noqa: E402

    ws = os.path.join(tmp, "workspace")
    rule_dir = os.path.join(ws, ".longrun", "rules")
    legacy_dir = os.path.join(ws, ".trae", "rules")
    os.makedirs(rule_dir, exist_ok=True)
    os.makedirs(legacy_dir, exist_ok=True)
    os.makedirs(os.path.join(ws, ".longrun", "prompt.d"), exist_ok=True)

    allowed_rule = os.path.join(rule_dir, "Project_rules.md")
    extra_rule = os.path.join(rule_dir, "team.md")
    root_agents = os.path.join(ws, "AGENTS.md")
    legacy_trae = os.path.join(legacy_dir, "forbidden.md")
    legacy_root = os.path.join(ws, ".longrun", "outside-rules.md")
    prompt_addendum = os.path.join(ws, ".longrun", "prompt.d", "legacy.md")
    external_rule = os.path.join(tmp, "external-rule.md")
    for path, text in (
        (allowed_rule, "ALLOWED PROJECT RULE\n"),
        (extra_rule, "ALLOWED EXTRA RULE\n"),
        (root_agents, "ALLOWED ROOT AGENTS\n"),
        (legacy_trae, "FORBIDDEN TRAE RULE\n"),
        (legacy_root, "FORBIDDEN RULE OUTSIDE RULES FOLDER\n"),
        (external_rule, "FORBIDDEN SYMLINK RULE\n"),
        (prompt_addendum, "NOT A PROJECT RULE SOURCE\n"),
    ):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    os.symlink(external_rule, os.path.join(rule_dir, "linked.md"))

    state = paths.workspace_state_dir(ws)
    os.makedirs(os.path.join(state, "rules"), exist_ok=True)
    with open(os.path.join(state, "Project_rules.md"), "w", encoding="utf-8") as f:
        f.write("FORBIDDEN EXTERNAL PROJECT RULE\n")
    with open(os.path.join(state, "rules", "external.md"), "w", encoding="utf-8") as f:
        f.write("FORBIDDEN EXTERNAL FOLDER RULE\n")

    check("A1 the native project rules file resolves inside workspace/.longrun/rules",
          rules.project_rules_path(ws) == allowed_rule, rules.project_rules_path(ws))
    check("A2 project rule discovery names exactly the one allowed folder",
          rules.project_rules_dirs(ws) == [rule_dir], rules.project_rules_dirs(ws))
    check("B1 resolving harness state leaves local rules in place",
          os.path.isdir(rule_dir) and os.path.isfile(allowed_rule))
    check("B2 unrelated prompt addenda remain external harness state",
          not os.path.exists(prompt_addendum)
          and os.path.isfile(os.path.join(state, "prompt.d", "legacy.md")))

    collected = rules.collect(ws=ws)["project"]
    text = collected["text"]
    loaded = set(collected["files"])
    check("C1 the prompt includes all local .longrun/rules markdown and root AGENTS",
          {allowed_rule, extra_rule, root_agents} <= loaded
          and "ALLOWED PROJECT RULE" in text
          and "ALLOWED EXTRA RULE" in text
          and "ALLOWED ROOT AGENTS" in text)
    check("C2 no project rule is read from .trae, outside .longrun/rules, or data home",
          not any(token in text for token in (
              "FORBIDDEN", "FORBIDDEN EXTERNAL", "NOT A PROJECT RULE SOURCE"))
          and legacy_trae not in loaded
          and legacy_root not in loaded
          and os.path.join(state, "Project_rules.md") not in loaded
          and os.path.join(state, "rules", "external.md") not in loaded,
          sorted(loaded))
    check("C3 every loaded project instruction file is one of the two allowed sources",
          all(os.path.commonpath((p, rule_dir)) == rule_dir or p == root_agents
              for p in loaded), sorted(loaded))

    saved = rules.save("project", "SAVED LOCAL RULE\n", ws=ws)
    check("D1 saving project rules writes only the allowed local Project_rules.md",
          saved.get("ok") and saved.get("path") == allowed_rule
          and open(allowed_rule, encoding="utf-8").read() == "SAVED LOCAL RULE\n",
          saved)

    rejected = rules.set_always_apply(legacy_trae, False, ws=ws)
    accepted = rules.set_always_apply(extra_rule, False, ws=ws)
    check("D2 always-apply accepts only loaded local rules and root AGENTS",
          not rejected.get("ok") and accepted.get("ok") is True,
          (rejected, accepted))

    external_rules = os.path.join(tmp, "external-rules")
    os.makedirs(external_rules, exist_ok=True)
    for name, text in (
            ("Project_rules.md", "FORBIDDEN SYMLINK DIRECTORY RULE\n"),
            ("linked.md", "FORBIDDEN SYMLINK DIRECTORY RULE\n"),
            ("AGENTS.md", "FORBIDDEN SYMLINK AGENTS\n")):
        with open(os.path.join(external_rules, name), "w", encoding="utf-8") as f:
            f.write(text)
    linked_ws = os.path.join(tmp, "linked-workspace")
    os.makedirs(os.path.join(linked_ws, ".longrun"), exist_ok=True)
    os.symlink(external_rules, os.path.join(linked_ws, ".longrun", "rules"))
    os.symlink(os.path.join(external_rules, "AGENTS.md"),
               os.path.join(linked_ws, "AGENTS.md"))
    linked = rules.collect(ws=linked_ws)["project"]
    check("E1 symlinked rule folders, files, and AGENTS cannot import outside text",
          linked["files"] == [] and "FORBIDDEN" not in linked["text"], linked)
    linked_status = rules.status(ws=linked_ws)["project"]
    check("E2 Settings status does not read through a symlinked rules folder",
          not linked_status["exists"] and linked_status["file_text"] == "",
          linked_status)
    from longrun.gen import generate  # noqa: E402
    with mock.patch.object(rules, "get_workspace", lambda: linked_ws):
        generated = generate._rules({})
    check("E3 prompt generation does not read through a symlinked rules folder",
          generated.get("project_rules") == "", generated)
    before = open(os.path.join(external_rules, "Project_rules.md"),
                  encoding="utf-8").read()
    from longrun.util import improve  # noqa: E402
    unsafe_proposal = improve.propose(
        "project", "MUST NOT BE APPROVED\n", ws=linked_ws)
    with mock.patch.object(improve, "_reproduction_gate", return_value=None):
        unsafe_decision = improve.decide(unsafe_proposal["id"], "approve")
    unsafe_record = improve.get_proposal(unsafe_proposal["id"])
    check("E4 a refused project proposal stays pending, not falsely approved",
          not unsafe_decision.get("ok")
          and unsafe_record.get("status") == "pending"
          and open(os.path.join(external_rules, "Project_rules.md"),
                   encoding="utf-8").read() == before,
          (unsafe_decision, unsafe_record))
    linked_save = rules.save("project", "MUST NOT ESCAPE\n", ws=linked_ws)
    linked_append = rules.append("project", "MUST NOT APPEND\n", ws=linked_ws)
    check("E5 saving and appending refuse a symlinked rules directory",
          not linked_save.get("ok")
          and not linked_append.get("ok")
          and open(os.path.join(external_rules, "Project_rules.md"),
                   encoding="utf-8").read() == before,
          (linked_save, linked_append))

    linked_file_ws = os.path.join(tmp, "linked-file-workspace")
    linked_file_rules = os.path.join(linked_file_ws, ".longrun", "rules")
    os.makedirs(linked_file_rules, exist_ok=True)
    os.symlink(os.path.join(external_rules, "Project_rules.md"),
               os.path.join(linked_file_rules, "Project_rules.md"))
    linked_file_status = rules.status(ws=linked_file_ws)["project"]
    linked_file_save = rules.save("project", "MUST NOT OVERWRITE\n", ws=linked_file_ws)
    check("E6 a symlinked native rule file cannot be exposed or overwritten",
          not linked_file_status["exists"] and linked_file_status["file_text"] == ""
          and not linked_file_save.get("ok")
          and open(os.path.join(external_rules, "Project_rules.md"),
                   encoding="utf-8").read() == before,
          (linked_file_status, linked_file_save))

    # The text injected into the model must describe the SAME boundary as the
    # resolver: the workspace rules folder + root AGENTS.md, and nothing else.
    block = rules.rules_prompt_block(ws=ws)
    allowed_folder_text = os.path.join(os.path.realpath(ws), ".longrun", "rules")
    check("F1 the injected rules block names the workspace rules folder and root AGENTS",
          allowed_folder_text in block
          and os.path.join(os.path.realpath(ws), "AGENTS.md") in block,
          block[:400])
    check("F2 the injected rules block offers no other project rule source",
          ".trae" not in block
          and os.path.join(state, "Project_rules.md") not in block
          and os.path.join(state, "rules") not in block,
          block[:400])

    def _src(*parts):
        with open(os.path.join(REPO, "src", "longrun", *parts), encoding="utf-8") as f:
            return f.read()

    policy_src = _src("agent", "agent.py")
    policy = policy_src[policy_src.find("RULES_POLICY = ("):
                        policy_src.find("\n)\n", policy_src.find("RULES_POLICY = ("))]
    check("F3 the rules-policy prompt names the workspace rules folder, not .trae",
          ".longrun/rules" in policy and ".trae" not in policy, policy[:400])

    registry_src = _src("tools", "registry.py")
    guidance = registry_src[registry_src.find('"improve.propose": ('):
                            registry_src.find('"improve.mine": (')]
    check("F4 the improve.propose tool guidance names where project rules live",
          ".longrun/rules" in guidance and ".trae" not in guidance, guidance[:400])

    surfaces_src = _src("gen", "surfaces.py")
    rules_surface = surfaces_src[surfaces_src.find('"rules": ('):
                                 surfaces_src.find('"settings": (')]
    check("F5 the rules automation prompt names the workspace rules folder",
          ".longrun/rules" in rules_surface and ".trae" not in rules_surface,
          rules_surface[:400])

print("---")
ok = sum(results)
print("v1299: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
