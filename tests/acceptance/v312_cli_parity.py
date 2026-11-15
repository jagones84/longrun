#!/usr/bin/env python3
"""v312 — CLI ⇄ WebUI parity (JAG-312).

The CLI must be able to do everything a user can do from the WebUI/Orbit. This
locks the command surface added to close the known gaps:

  * `sessions clear|model` (reset a session, set its model)
  * `context items` (list the context items the Context panel shows)
  * `routines ls|new|rm|enable|disable` (the whole scheduled-heartbeats domain)
  * `jobs get`, plus `--blocked-by/--agents/--coordinator/--mode` on `jobs new`
  * `mcp ls|add|remove|reload|local-file` (client management, not only tools/list)
  * `providers ls|add|rm|default|rm-model` (CRUD, not only a read)
  * `tools runtime|verifier|bestofn|difficulty|selfevolve|reasoning|approvals`
    (the global policy presets the Settings panel writes)
  * `market ls|sources|status|sync|remote|import|install|installed|rm` (the
    Marketplace page: catalogue filters, the background import job, one-row import)

Static: parses the argparse surface + asserts the handler functions exist.
Deterministic, no server. Run: python3 tests/acceptance/v312_cli_parity.py
"""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = open(os.path.join(REPO, "src", "longrun", "core/forge.py"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" :: " + str(detail)) if detail else ""))


# --- functions exist ---------------------------------------------------------
tree = ast.parse(SRC)
funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
for fn in ("cmd_sessions", "cmd_context", "cmd_routines", "cmd_jobs", "cmd_mcp",
           "cmd_providers", "cmd_tools", "cmd_market"):
    check("handler %s exists" % fn, fn in funcs)

# --- action choices actually wired (read the real literals) ------------------
import re


def choices_for(parser_name):
    # find add_parser("<name>") ... choices=[...] within the same statement block
    m = re.search(r'add_parser\("%s"\)(.*?)(?=add_parser\(|args = ap\.parse_args)' % parser_name, SRC, re.S)
    return m.group(1) if m else ""


sess = choices_for("sessions")
check("sessions accepts clear", '"clear"' in sess)
check("sessions accepts model", '"model"' in sess)

ctx = choices_for("context")
check("context accepts items", '"items"' in ctx)

rout = choices_for("routines")
check("routines accepts ls/new/rm/enable/disable",
      all(a in rout for a in ('"ls"', '"new"', '"rm"', '"enable"', '"disable"')))

jobs = choices_for("jobs")
check("jobs accepts get", '"get"' in jobs)
check("jobs new accepts --blocked-by", "--blocked-by" in jobs)
check("jobs new accepts --agents", '"--agents"' in jobs)
check("jobs new accepts --coordinator", '"--coordinator"' in jobs)

mcp = choices_for("mcp")
check("mcp accepts ls/add/remove/reload/local-file",
      all(a in mcp for a in ('"ls"', '"add"', '"remove"', '"reload"', '"local-file"')))

prov = choices_for("providers")
check("providers accepts ls/add/rm/default/rm-model",
      all(a in prov for a in ('"ls"', '"add"', '"rm"', '"default"', '"rm-model"')))

tools = choices_for("tools")
check("tools accepts the preset actions",
      all(a in tools for a in ('"runtime"', '"verifier"', '"bestofn"', '"difficulty"',
                               '"selfevolve"', '"reasoning"', '"approvals"')))

mark = choices_for("market")
check("market accepts ls/sources/status/sync/remote/import/install/installed/rm",
      all(a in mark for a in ('"ls"', '"sources"', '"status"', '"sync"', '"remote"',
                              '"import"', '"install"', '"installed"', '"rm"')))
check("market ls filters by catalogue origin and by area",
      '"--source"' in mark and '"--category"' in mark and '"--offset"' in mark)
check("market sync can follow the job to the end", '"--wait"' in mark)

# --- HTTP routes the CLI calls must exist server-side ------------------------
srv = open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8").read()
srv += open(os.path.join(REPO, "src", "longrun", "core/httpapi.py"), encoding="utf-8").read()
orch = open(os.path.join(REPO, "src", "longrun", "orchestrate/orchestration.py"), encoding="utf-8").read()
api = open(os.path.join(REPO, "src", "longrun", "core/api_v02.py"), encoding="utf-8").read()
check("server serves /api/sessions/<sid>/clear", 'path.endswith("/clear")' in srv)
check("server serves /api/sessions/<sid>/model", 'path.endswith("/model")' in srv)
check("orchestration serves /api/routines", '_is(path, "/api/routines")' in orch)
check("orchestration serves DELETE /api/jobs/<id>", 'method == "DELETE" and path.startswith("/api/jobs/")' in orch)
check("the marketplace routes the CLI calls exist",
      all(('"%s"' % p) in api for p in ("/api/market/catalog", "/api/market/sources",
                                       "/api/market/sync/status", "/api/market/sync",
                                       "/api/market/remote", "/api/market/import-remote",
                                       "/api/market/install", "/api/market/installed")))
check("the installed record is removable with its files",
      'path.startswith("/api/market/installed/")' in api and 'qs.get("files")' in api)

# --- test infra: pytest must be able to import the package -------------------
conf = os.path.join(REPO, "tests", "conftest.py")
check("tests/conftest.py exists (JAG-313)", os.path.isfile(conf))
if os.path.isfile(conf):
    ctext = open(conf, encoding="utf-8").read()
    check("conftest puts src/ on sys.path", '"src"' in ctext and "sys.path.insert" in ctext)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

