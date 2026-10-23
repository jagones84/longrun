#!/usr/bin/env python3
"""v493 — first-run WebUI token setup.

The first browser visit must be usable without hand-editing `.env`. A local
first-run action persists LONGRUN_TOKEN, activates it in the current process,
and rejects remote setup or a second setup attempt.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v493-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.path.join(TMP, "data"), exist_ok=True)
os.makedirs(os.path.join(TMP, "sessions"), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401
from longrun.core import httpapi  # noqa: E402
from longrun.model import keys  # noqa: E402

results = []
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


old_env = keys.ENV_FILE
old_auth = httpapi.AUTH_TOKEN
try:
    keys.ENV_FILE = os.path.join(TMP, ".env")
    httpapi.AUTH_TOKEN = None

    check("A1 unconfigured server reports first-run setup",
          httpapi.first_run_setup_available() is True)
    check("A2 remote client cannot claim first-run setup",
          httpapi.configure_first_run_token("abc", "192.168.1.20").get("error")
          == "first-run setup is local-only")
    saved = httpapi.configure_first_run_token("chosen-token", "127.0.0.1")
    check("A3 local setup persists and activates the token",
          saved.get("ok") is True and httpapi.AUTH_TOKEN == "chosen-token"
          and "LONGRUN_TOKEN=chosen-token" in open(keys.ENV_FILE).read())
    check("A4 second setup is rejected",
          httpapi.configure_first_run_token("other-token", "127.0.0.1").get("error")
          == "token is already configured")
    check("A5 configured server is no longer first-run",
          httpapi.first_run_setup_available() is False)
    httpapi.sync_runtime_token("rotated-token")
    check("A6 persisted token changes can rotate the live gate",
          httpapi.AUTH_TOKEN == "rotated-token")
finally:
    keys.ENV_FILE = old_env
    httpapi.AUTH_TOKEN = old_auth

check("B1 WebUI contains a blocking first-run setup panel",
      "firstRunSetup" in UI and "First-run security setup" in UI
      and "firstRunSave" in UI)
check("B2 WebUI saves through the one-time setup endpoint",
      "/api/setup/token" in UI and "LONGRUN_TOKEN" in UI
      and "sf_setup_skipped" in UI)
check("B3 WebUI checks setup before loading the application",
      "await firstRunSetup()" in UI and "loadSessions()" in UI)
check("B4 WebUI distinguishes server token from browser credential",
      "Longrun token" in UI and "live server updates" in UI)
check("B5 static WebUI shell is reachable before browser authentication",
      'if path in ("/", "/index.html")' in
      open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
           encoding="utf-8").read())
check("B6 rotating LONGRUN_TOKEN refreshes the browser credential",
      'if (name === "LONGRUN_TOKEN")' in UI and 'localStorage.setItem("sf_token", TOKEN)' in UI)

key_rows = {row["env"]: row for row in keys.keys_status()["keys"]}
check("C1 empty provider discovery still offers the default chat key",
      "OPENROUTER_API_KEY" in key_rows
      and key_rows["OPENROUTER_API_KEY"].get("description"))
check("C2 every key row has a description without exposing its value",
      all(row.get("description") and "value" not in row for row in key_rows.values()))
check("C3 the Keys panel always exposes a custom-key form",
      "addCustomKey" in UI and "New key" in UI and "customKeyName" in UI)
check("C4 unauthorized key responses are not rendered as an empty key list",
      "unauthorized" in UI.lower() and "no keys known" not in UI)
check("C5 Info panel recognizes API errors returned as JSON",
      'if (d.error)' in UI and "Longrun rejected this browser token" in UI)

custom_name = "LONGRUN_V493_CUSTOM_KEY"
old_env_file = keys.ENV_FILE
old_custom_value = os.environ.pop(custom_name, None)
try:
    keys.ENV_FILE = os.path.join(TMP, "custom-keys.env")
    saved_custom = keys.set_key(custom_name, "fixture-secret")
    custom_text = open(keys.ENV_FILE, encoding="utf-8").read()
    custom_row = next(row for row in saved_custom["keys"] if row["env"] == custom_name)
    check("C6 custom keys persist through the existing key API",
          saved_custom.get("ok") is True and custom_name + "=fixture-secret" in custom_text
          and custom_row.get("description") == "Custom environment variable"
          and "value" not in custom_row)
finally:
    keys.ENV_FILE = old_env_file
    os.environ.pop(custom_name, None)
    if old_custom_value is not None:
        os.environ[custom_name] = old_custom_value

# JAG-2.9 keys: ONE place. The repo `.env` is what Settings > Keys writes, so it
# must also be the only file the harness READS — no ~/.hermes fallback that makes
# a key appear "set" while the UI cannot find (or clear) it.
check("C7 the Keys panel advertises ONLY the repo .env",
      keys.keys_status().get("env_files") == [".env"],
      keys.keys_status().get("env_files"))
_keys_src = open(os.path.join(REPO, "src", "longrun", "model", "keys.py"),
                 encoding="utf-8").read()
check("C8 read_secret has no ~/.hermes fallback", "~/.hermes" not in _keys_src)
_pv = open(os.path.join(REPO, "config", "providers.yaml"), encoding="utf-8").read()
_mcp = open(os.path.join(REPO, "config", "mcp_clients.yaml"), encoding="utf-8").read()
check("C9 the shipped env_files are local only",
      "~/.hermes" not in _pv and "~/.hermes" not in _mcp)

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
