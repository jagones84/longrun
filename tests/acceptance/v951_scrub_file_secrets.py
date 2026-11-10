#!/usr/bin/env python3
"""v951 — the scrubber knows the webhook secrets and URL credentials.

`_secret_values` collected secret-looking env vars and `.env` entries. Anything
else was invisible to it: the webhook store (`webhooks.json`) keeps one secret per
inlet and sits in the repo data home where `fs.read` is auto-approved, so a plain
read handed every hook secret to the model; and a git remote written as
`https://user:token@host` travelled through `git` / `fs.read .git/config` intact.

The scrubber now asks `webhooks.secret_values()` (the module that OWNS the store
format, no second parser) and redacts a URL's userinfo credential by pattern.

Deterministic: temp stores, no server, no model, no network.
Run: python3 tests/acceptance/v951_scrub_file_secrets.py
"""

import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v951-")
os.environ["LONGRUN_DATA_DIR"] = TMP
for _k in ("SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR", "CONFIG_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
HOOKS = os.path.join(TMP, "webhooks.json")
os.environ["LONGRUN_WEBHOOKS"] = HOOKS
SECRET = "wh-5eed-9876543210"
with open(HOOKS, "w", encoding="utf-8") as f:
    json.dump({"hooks": {"h1": {"id": "h1", "name": "ci", "mode": "observe",
                               "secret": SECRET}}}, f)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import webhooks as WH   # noqa: E402
from longrun.tools import tools as T      # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A. the store's own secrets reach the scrubber -------------------------
check("A1 webhooks.secret_values() returns the stored secret",
      SECRET in WH.secret_values(), WH.secret_values())
check("A2 _secret_values() includes it", SECRET in T._secret_values())
out = T._scrub_result_secrets({"ok": True, "stdout": "file: " + SECRET + " end"})
check("A3 a read of the store cannot hand the secret to the model",
      "[redacted-secret]" in out["stdout"] and SECRET not in out["stdout"], out["stdout"])
check("A4 the name/shape of the payload is still readable",
      out["stdout"].startswith("file: ") and out["stdout"].endswith(" end"), out["stdout"])

# ---- B. list_hooks still hides it ------------------------------------------
row = (WH.list_hooks().get("hooks") or [{}])[0]
check("B1 the panel payload still carries only a tail",
      "secret" not in row and row.get("secret_set") is True
      and row.get("secret_tail") == SECRET[-4:], row)

# ---- C. a URL credential is redacted by pattern ----------------------------
url = "remote origin = https://giova:tok999secret@github.com/org/repo.git"
out = T._scrub_result_secrets({"stdout": url})["stdout"]
check("C1 the credential is gone", "tok999secret" not in out and "giova:" not in out, out)
check("C2 the redaction keeps the URL readable",
      "https://[redacted]@" in out and out.endswith("github.com/org/repo.git"), out)
out = T._scrub_result_secrets({"stdout": "ssh://git@github.com/org/repo.git"})["stdout"]
check("C3 a plain ssh username is NOT redacted (not a secret)",
      out == "ssh://git@github.com/org/repo.git", out)
out = T._scrub_result_secrets({"stdout": "see https://github.com/org/repo"})["stdout"]
check("C4 a plain URL is untouched", out == "see https://github.com/org/repo", out)
out = T._scrub_result_secrets({"stdout": "key: value\nC:\\Users\\x: y"})["stdout"]
check("C5 ordinary colons are untouched", "key: value" in out and "C:\\Users\\x: y" in out, out)

# ---- D. nested payloads and no false positive on ordinary words ------------
out = T._scrub_result_secrets({"result": {"rows": [{"cmd": "git remote -v " + url}]}})
nested = out["result"]["rows"][0]["cmd"]
check("D1 a nested result is scrubbed too", "tok999secret" not in nested, nested)
out = T._scrub_result_secrets({"stdout": "the word secret and token appear here"})
check("D2 ordinary words are not redacted",
      out["stdout"] == "the word secret and token appear here", out["stdout"])

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
