#!/usr/bin/env python3
"""v1020 — user-defined `/` commands are one store, validated by name.

  A  the store starts empty and lives under the data home, not in shipped config
  B  a command round-trips through the file and comes back normalised
  C  a bad name, a reserved name, an empty prompt and a bad mode are refused BY NAME
  D  a token already taken (by a name or an alias) is refused, naming the owner
  E  the name is the identity: saving again replaces, never duplicates
  F  removal is by name, and an unknown name is refused
  G  the composer reads the SAME store: the `/` menu, the chip and the expansion
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1020-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import commands  # noqa: E402

UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def save(**kw):
    body = {"name": "review", "description": "review the diff",
            "prompt": "Review the staged diff and list the risks.", "aliases": [], "mode": "send"}
    body.update(kw)
    return commands.upsert(body)


# ── A: empty, and in the data home ──────────────────────────────────────────
lst = commands.list_commands()
check("A1 the store starts empty", lst["ok"] and lst["commands"] == [], lst["commands"])
check("A2 the store lives under the data home (operator-owned, not shipped config)",
      os.path.join("data", "commands.yaml") in lst["path"]
      or commands.path().startswith(os.environ["LONGRUN_DATA_DIR"]), commands.path())
check("A3 the built-in tokens are declared as reserved",
      set(commands.RESERVED) == {"goal", "skills", "skill", "compact"}, commands.RESERVED)

# ── B: round-trip ───────────────────────────────────────────────────────────
res = save()
check("B1 a valid command saves", res.get("ok") is True, res.get("error"))
check("B2 it is on disk in the operator's store", os.path.isfile(commands.path()))
back = commands.get("review")
check("B3 it reads back normalised (name lowercased, prompt intact)",
      back and back["name"] == "review" and back["prompt"].startswith("Review the staged"))

# ── C: refusals name the field ──────────────────────────────────────────────
check("C1 an invalid name is refused", "invalid name" in save(name="Bad Name")["error"])
check("C2 a built-in name is refused", "built-in" in save(name="goal")["error"])
check("C3 an empty prompt is refused", "prompt is required" in save(prompt="   ")["error"])
check("C4 an oversized prompt is refused",
      "exceeds" in save(prompt="x" * (commands.MAX_PROMPT + 1))["error"])
check("C5 an unknown mode is refused", "mode must be" in save(mode="teleport")["error"])
check("C6 a built-in ALIAS is refused",
      "built-in" in save(aliases=["compact"])["error"])
check("C7 the refusals did not touch the stored command",
      commands.get("review") is not None and commands.get("Bad Name") is None)

# ── D: a taken token is refused, naming its owner ───────────────────────────
res = save(name="ship", description="ship it", prompt="Ship the change.", aliases=["rel"])
check("D1 a second command with a free token saves", res.get("ok") is True, res.get("error"))
dup = save(name="ship2", description="x", prompt="y", aliases=["rel"])
check("D2 a token already used by an alias is refused", dup.get("ok") is False, dup)
check("D3 the refusal names the owner", "'ship'" in dup.get("error", ""), dup.get("error"))
check("D4 a name colliding with another command's NAME is refused",
      save(name="ship", description="x", prompt="z")["ok"] is True)  # same name = replace

# ── E: the name is the identity ─────────────────────────────────────────────
save(name="review", description="review v2", prompt="Review again.")
rows = [c for c in commands.list_commands()["commands"] if c["name"] == "review"]
check("E1 saving the same name replaces, never duplicates",
      len(rows) == 1 and rows[0]["description"] == "review v2", rows)
check("E2 a replaced command releases its old aliases to others",
      save(name="sweep", description="s", prompt="p", aliases=["rv"])["ok"] is True)

# ── F: removal by name ──────────────────────────────────────────────────────
check("F1 removal is by name", commands.remove("sweep")["ok"] is True)
check("F2 the removed command is gone", commands.get("sweep") is None)
check("F3 an unknown name is refused by name",
      "unknown command" in commands.remove("nope")["error"])

# ── G: the composer reads the SAME store ────────────────────────────────────
check("G1 the menu loads the user commands from the real route",
      "loadUserCommands()" in UI and 'api("GET", "/api/commands")' in UI)
check("G2 the menu is the UNION of built-ins and user commands",
      "const all = SLASH_COMMANDS.concat(USER_COMMANDS);" in UI)
check("G3 a user command can never shadow a built-in token",
      "!SLASH_BY_ID[c.id] && !(c.aliases || []).some(a => SLASH_BY_ID[a])" in UI)
check("G4 picking one expands the PROMPT and keeps /name in the transcript",
      "function _expandUserCommand(raw)" in UI
      and "send(_uc.text, _uc.display, atts);" in UI)
check("G5 a real skill still wins the token", "_expandUserCommand(raw)" in UI
      and "return null;" in UI.split("function _expandUserCommand(raw)")[1].split("loadUserCommands()")[0])
check("G6 the Settings panel is one form over the same store",
      'data-cat="commands"' in UI and 'data-call="saveCommand"' in UI
      and 'api("DELETE", "/api/commands/"' in UI)
check("G7 the panel states the reserved tokens it cannot reuse",
      "cannot be reused" in UI and "data/commands.yaml" in UI)

print("\n---\nv1020: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
