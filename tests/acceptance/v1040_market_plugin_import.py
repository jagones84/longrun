#!/usr/bin/env python3
"""v1040 — commercial plugin packages are read by an adapter and installed as a bundle.

The three standards are read from the package's own manifest, never guessed:

  A  trae   `.trae-plugin/plugin.json`  -> skills + `mcp` document (a ${VAR} = connector)
  B  claude `.claude-plugin/plugin.json` -> skills + `.mcp.json`
  C  a bare directory with SKILL.md
  D  openclaw `openclaw.plugin.json` = CODE -> its skills are imported, the code is named
  E  a path outside the configured roots is refused
  F  the install goes through the SAME bundle path: one record, owner-side state, rm
  G  what cannot travel is named (binaries), never silently dropped
  H  the directory digest is deterministic
  I  the surface is wired (route, page button, CLI verbs)
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1040-")
FIX = os.path.join(_TMP, "fixtures")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_SKILLS_LOCAL_DIR"] = os.path.join(_TMP, "skills", "local")
os.environ["LONGRUN_PLUGIN_ROOTS"] = FIX + os.pathsep + os.path.join(_TMP, "elsewhere")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import market, market_plugins as mp  # noqa: E402
from longrun.interop import mcp_client  # noqa: E402
from longrun.memory import skills  # noqa: E402

mcp_client.CONFIG_LOCAL_JSON_PATH = os.path.join(os.environ["LONGRUN_CONFIG_DIR"],
                                                 "mcp_clients.local.json")
mcp_client.CONFIG_LOCAL_PATH = os.path.join(os.environ["LONGRUN_CONFIG_DIR"],
                                            "mcp_clients.local.yaml")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def pkg(name, files):
    root = os.path.join(FIX, name)
    for rel, text in files.items():
        write(os.path.join(root, rel), text)
    return root


SKILL = "# %s\n\nUse it.\n"

trae = pkg("trae-demo", {
    ".trae-plugin/plugin.json": json.dumps({
        "name": "trae-demo", "version": "2.1.0", "description": "A demo Trae plugin.",
        "author": {"name": "Demo Author"}, "keywords": ["pdf", "documents"],
        "skills": "./skills/", "mcp": ".mcp.json"}),
    "skills/alpha/SKILL.md": SKILL % "Alpha",
    ".mcp.json": json.dumps({"mcpServers": {
        "alpha-server": {"command": "npx", "args": ["-y", "alpha-mcp"],
                         "env": {"ALPHA_TOKEN": "${ALPHA_TOKEN}"}},
    }}),
})

claude = pkg("claude-demo", {
    ".claude-plugin/plugin.json": json.dumps({
        "name": "claude-demo", "version": "1.0.0", "description": "A demo Claude plugin.",
        "author": "Someone"}),
    "skills/beta/SKILL.md": SKILL % "Beta",
    ".mcp.json": json.dumps({"mcpServers": {"beta-server": {"url": "https://beta.test/mcp"}}}),
    "commands/ship.md": "# /ship\n",
})

bare = pkg("bare-skill", {"SKILL.md": SKILL % "Bare"})

openclaw = pkg("code-demo", {
    "openclaw.plugin.json": json.dumps({"id": "code-demo", "contracts": {"tools": ["x"]}}),
    "dist/index.js": "module.exports = {};\n",
})

# A code plugin is still a container: `diffs` (real) ships `skills: ["./skills"]`, `lobster`
# ships a SKILL.md at the root. The portable part is imported; the code is named as ignored.
openclaw_mixed = pkg("code-with-skills", {
    "openclaw.plugin.json": json.dumps({
        "id": "code-with-skills", "name": "Code With Skills",
        "description": "A viewer with instructions.", "version": "3.0.0",
        "contracts": {"tools": ["view"]}, "skills": ["./skills"]}),
    "skills/octo/SKILL.md": SKILL % "Octo",
    "dist/index.js": "module.exports = {};\n",
})

blocked = os.path.join(_TMP, "not-a-root", "pkg")
write(os.path.join(blocked, "SKILL.md"), SKILL % "Blocked")

# ── A/B/C: detection and conversion ────────────────────────────────────────
conv = mp.convert(trae)
check("A1 a Trae package is detected and converted", conv.get("ok") is True
      and conv.get("format") == "trae", conv.get("error"))
mem = [(m["kind"], m["name"]) for m in conv["item"]["members"]]
check("A2 its skill and its MCP server are both members",
      mem == [("skill", "alpha"), ("connector", "alpha-server")], mem)
conn = [m for m in conv["item"]["members"] if m["kind"] == "connector"][0]
check("A3 a ${VAR} in the server block makes it a CONNECTOR with that key",
      conn["keys"] == ["ALPHA_TOKEN"], conn.get("keys"))
check("A4 the publisher and the version come from the manifest",
      conv["item"]["publisher"] == "Demo Author" and conv["item"]["version"] == "2.1.0")

conv = mp.convert(claude)
mem = [(m["kind"], m["name"]) for m in conv["item"]["members"]]
check("B1 a Claude package yields skill + plain mcp",
      conv.get("ok") is True and mem == [("skill", "beta"), ("mcp", "beta-server")], mem)
check("B2 commands cannot travel and are named, never dropped",
      "commands" in conv["ignored"], conv["ignored"])

conv = mp.convert(bare)
check("C1 a bare SKILL.md directory is a one-member plugin",
      conv.get("ok") is True and [m["kind"] for m in conv["item"]["members"]] == ["skill"])

# ── D/E: refusals ──────────────────────────────────────────────────────────
bad = mp.convert(openclaw)
check("D1 an OpenClaw code plugin is refused by name",
      bad.get("ok") is False and "openclaw code plugin" in bad.get("error", ""), bad.get("error"))
check("D2 the refusal names what it carried",
      "tools x" in bad.get("error", ""), bad.get("error"))
mixed = mp.convert(openclaw_mixed)
check("D3 a code plugin that ships skills imports the skills, not nothing",
      mixed.get("ok") is True and [m["name"] for m in mixed["item"]["members"]] == ["octo"],
      mixed.get("error") or mixed.get("ignored"))
check("D4 the code it cannot run is named as ignored, never silent",
      "code" in (mixed.get("ignored") or []) and "view" in " ".join(mixed.get("notes") or []),
      (mixed.get("ignored"), mixed.get("notes")))
# A54 finding F1: the note that names the dropped code must reach the scan row, not only convert().
_rows = mp.scan(max_age=0)["packages"]
_row = [r for r in _rows if str(r.get("path", "")).endswith("code-with-skills")]
check("D5 the scan carries the note that names the code it will not run",
      bool(_row) and any("view" in str(n) for n in _row[0].get("notes") or []),
      _row[0].get("notes") if _row else "row missing")
out = mp.convert(blocked)
check("E1 a path outside the configured roots is refused",
      out.get("ok") is False and "outside the plugin roots" in out.get("error", ""), out.get("error"))

# A54 finding F1: the location gate runs before the format gate, so a plain directory
# outside the roots is refused for the reason that actually applies.
plain = os.path.join(_TMP, "not-a-root", "plain")
os.makedirs(plain, exist_ok=True)
write(os.path.join(plain, "notes.txt"), "nothing to import\n")
out = mp.convert(plain)
check("E2 an outside path without a manifest is still refused for where it lives",
      out.get("ok") is False and "outside the plugin roots" in out.get("error", ""), out.get("error"))
# A54 finding F3: the reported roots are the ENFORCED roots, repository included.
scan = mp.scan(max_age=0)
check("E3 the scan reports every root it actually enforces",
      scan.get("roots") == mp.roots(), (scan.get("roots"), mp.roots()))

# ── G: binaries are named ──────────────────────────────────────────────────
trae_secure = pkg("trae-secure", {
    ".trae-plugin/plugin.json": json.dumps({
        "name": "trae-secure", "description": "Has binaries.", "skills": "./skills/",
        "binaries": {"tool": "bin/tool"}}),
    "skills/gamma/SKILL.md": SKILL % "Gamma",
})
conv = mp.convert(trae_secure)
check("G1 a non-portable member is listed as ignored and the skill still converts",
      "binaries" in conv["ignored"] and [m["name"] for m in conv["item"]["members"]] == ["gamma"],
      conv.get("ignored"))

# ── H: the digest is deterministic ─────────────────────────────────────────
a = mp.dir_zip(os.path.join(trae, "skills", "alpha"))
b = mp.dir_zip(os.path.join(trae, "skills", "alpha"))
write(os.path.join(trae, "skills", "alpha", "extra.md"), "more\n")
c = mp.dir_zip(os.path.join(trae, "skills", "alpha"))
check("H1 the same directory hashes the same, a change moves it",
      a == b and a != c, (len(a), len(b), len(c)))

# ── F: install / audit / rm through the bundle path ───────────────────────
res = mp.install(trae)
check("F1 the package installs as ONE plugin record",
      res.get("ok") is True and res.get("target") == "2 members", res)
check("F2 the skill is on disk", os.path.isdir(
    os.path.join(os.environ["LONGRUN_SKILLS_DIR"], "local", "alpha")))
check("F3 the MCP server landed DISABLED (it is a connector with no key)",
      (mcp_client.load_doc().get("clients") or {}).get("alpha-server", {}).get("enabled") is False)
rec = [r for r in market.installed()["installed"] if r["id"] == "plugin/trae-demo"]
# v1060: an install now ACTIVATES its servers. A connector whose key is unset is the
# one member that stays off — as `needs-key`, naming the key, not as a failure.
_a = [m for m in (rec[0].get("members") if rec else []) or [] if m.get("name") == "alpha-server"]
check("F3b the unkeyed connector is recorded as needs-key, naming the key",
      bool(_a) and _a[0].get("state") == "needs-key"
      and "ALPHA_TOKEN" in str(_a[0].get("error")), _a)
check("F4 the record carries both members and its origin",
      len(rec) == 1 and len(rec[0]["members"]) == 2 and rec[0]["origin_label"] == "Trae", rec)
check("F5 audit agrees with the owners", market.audit()["drift"] == 0)
# Provenance: the Settings panels join the record by NAME, so a member has to resolve
# to the PLUGIN that installed it — otherwise a bundled skill looks operator-made.
mmap = market.installed_map()
check("F5b each member resolves to its plugin, so a panel can say where it came from",
      mmap.get("alpha", {}).get("plugin") == "plugin/trae-demo"
      and mmap.get("alpha-server", {}).get("plugin") == "plugin/trae-demo"
      and mmap.get("alpha", {}).get("origin_label") == "Trae",
      {k: mmap.get(k) for k in ("alpha", "alpha-server")})
check("F6 rm removes what the import created",
      market.forget("plugin/trae-demo", remove_target=True)["ok"] is True
      and not os.path.isdir(os.path.join(os.environ["LONGRUN_SKILLS_DIR"], "local", "alpha"))
      and "alpha-server" not in (mcp_client.load_doc().get("clients") or {}))

check("F7 an empty source is refused, not guessed",
      "no path or url" in mp.install("")["error"])

# ── I: the surface is wired ────────────────────────────────────────────────
API = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
JS = open(os.path.join(REPO, "webui", "assets", "market.js"), encoding="utf-8").read()
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
FORGE = open(os.path.join(REPO, "src", "longrun", "core", "forge.py"), encoding="utf-8").read()
check("I1 the scan and import routes exist",
      '"/api/market/plugin-scan"' in API and '"/api/market/plugin-import"' in API)
check("I2 the page shows what it found, with an Import button",
      "mkt-import-local" in JS and "Found on this machine" in JS)
check("I3 the CLI exposes both verbs",
      '"plugin-scan", "plugin-add"' in FORGE)
check("I4 a card names the package, never a full path that overflows the card",
      "p.title || p.name || base" in JS and "shortHome(" in JS)
# The operator's question: does uninstalling a plugin take its consequences with it?
# The record owns the members, so the UI must ask the RECORD for `?files=1`.
check("I5 Manage uninstalls a plugin with its members, not just the record",
      'data-files="${rec.kind === "plugin" ? "1" : ""}"' in JS and '?files=1' in JS)
check("I6 a bundled skill says which plugin it came from, and that the plugin is the unit",
      'it["market"]["plugin"] = m["plugin"]' in API
      and 'came with plugin' in HTML and 'from ' in HTML)

print("\n---\nv1040: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
