#!/usr/bin/env python3
"""Longrun benchmark adapter (JAG-426 · Domain 3).

Drives a RUNNING Longrun over its public REST API only:

    POST /api/sessions            create the session (the "agent")
    POST /api/chat                one blocking turn -> reply + run_id
    POST /api/checkpoints         backup_session (a restore point)
    POST /api/checkpoints/restore restore(ref, checkpoint)
    DELETE /api/sessions/<id>     delete_agent
    GET  /api/status, /api/self    provenance (version, model, router)

Nothing here imports `longrun.*`: the point is to measure the deployed harness
the same way any external benchmark would.

Auth: `Authorization: Bearer <LONGRUN_TOKEN>` (falls back to
~/.config/longrun/env, then the query token). Stdlib only.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from .protocol import AgentRef, HarnessResult

_ENV_FILE = os.path.expanduser("~/.config/longrun/env")


def _token_from_env_file():
    try:
        with open(_ENV_FILE, encoding="utf-8") as f:
            for line in f:
                if line.startswith("LONGRUN_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _git_sha(root):
    try:
        return subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=4).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


class LongrunAdapter:
    """Implements benchmarks.protocol.HarnessAdapter against a live server."""

    name = "longrun"

    def __init__(self, base=None, token=None, model=None, timeout=900.0, repo=None,
                 keep_sessions=False, tag=None):
        self.base = (base or os.environ.get("LONGRUN_BASE")
                     or "http://127.0.0.1:8790").rstrip("/")
        self.token = token or os.environ.get("LONGRUN_TOKEN") or _token_from_env_file()
        self.model = model
        self.timeout = float(timeout)
        self.repo = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Captured by `setup()`, restored by `teardown()`, reported in `provenance()`.
        self._policy = {}
        self._verifier = {}
        self._routing = {}
        # `keep_sessions`: do NOT delete the benchmark sessions — the operator wants
        # to open them in the WebUI and read what the harness actually did. `tag`
        # prefixes the session title so the runs are findable in the rail.
        self.keep_sessions = bool(keep_sessions)
        self.tag = tag

    # ---- transport ----------------------------------------------------------
    def _req(self, method, path, body=None, timeout=None):
        url = self.base + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"error": raw[:400]}
        except OSError as e:
            return 0, {"error": repr(e)[:200]}

    # ---- provenance ---------------------------------------------------------
    def provenance(self):
        """Harness identity + settings that make a run reproducible."""
        _, status = self._req("GET", "/api/status", timeout=10)
        _, selfinfo = self._req("GET", "/api/self", timeout=10)
        return {
            "harness": "longrun",
            "version": status.get("version") or selfinfo.get("version"),
            "git_sha": _git_sha(self.repo),
            "base_url": self.base,
            "model": self.model or status.get("model") or status.get("default_model"),
            "router": selfinfo.get("router"),
            "policy": self._policy,
        }

    # ---- run configuration --------------------------------------------------
    # A headless benchmark has NO human to click Approve, so any `required` tool
    # (shell / fs.write / fs.edit / git — see config/tools.yaml) would be raised as
    # an approval request, time out, and the model would move on WITHOUT editing
    # anything. That silently measures "the harness with its hands tied". `setup()`
    # puts the server in the state a real benchmark run needs and returns what it
    # changed, so `teardown()` restores the operator's own settings afterwards.
    def setup(self):
        """Make the live server benchmark-ready. Returns the PREVIOUS policy.

        - approvals.mode = full  (run every enabled tool; hard-deny still blocks)
        - approvals.kinds.* = auto (memory/proposals/skills/subagent emitted freely)
        - verifier.enabled = false (an "apply-only-if-green" gate needs a per-repo
          command and would roll back every edit otherwise)
        - EVERY routing role pinned to THIS arm's model.

        The routing pin is essential for an equal-conditions run: with the shipped
        routing.yaml, `chat`/`planner`/`agent` resolve by `pattern: qwen` to the
        LOCAL DGX model, so a session pinned to a cloud model still burned the local
        GPU for the planner call — the benchmark then measured a mixed model, not
        one. Pinning all roles to the arm's model keeps the comparison honest.
        """
        _, before = self._req("GET", "/api/tools", timeout=10)
        self._policy = dict(before.get("policy") or {})
        self._verifier = dict(before.get("verifier") or {})
        self._req("POST", "/api/tools", {
            "approvals": {"mode": "full",
                          "kinds": {"memory": "auto", "proposals": "auto",
                                    "skills": "auto", "subagent": "auto"}},
            "verifier": {"enabled": False},
        }, timeout=10)
        _, rstatus = self._req("GET", "/api/routing", timeout=10)
        self._routing = dict((rstatus or {}).get("config") or {})
        if self.model:
            roles = ("chat", "planner", "agent", "subagent", "summarizer")
            self._req("POST", "/api/routing",
                      {"roles": {r: {"model": self.model} for r in roles}}, timeout=10)
        return {"policy": self._policy, "verifier": self._verifier,
                "routing": self._routing}

    def teardown(self):
        """Restore the operator's settings captured by `setup()`."""
        body = {"approvals": {"mode": (self._policy or {}).get("mode", "normal")}}
        if self._policy.get("kinds"):
            body["approvals"]["kinds"] = self._policy["kinds"]
        if self._verifier:
            body["verifier"] = self._verifier
        self._req("POST", "/api/tools", body, timeout=10)
        # Put back the original role pins (the shipped config has no explicit
        # `model` for chat/planner/agent, so this clears our pin and restores
        # pattern-based selection).
        if getattr(self, "_routing", None):
            roles = {}
            for role, entry in (self._routing.get("roles") or {}).items():
                roles[role] = {"model": entry.get("model") or ""}
            if roles:
                self._req("POST", "/api/routing", {"roles": roles}, timeout=10)
        return True

    # ---- adapter contract ---------------------------------------------------
    def create_agent(self, task):
        base_title = str(task.get("id") or task.get("instance_id") or "bench")[:60]
        title = ("%s · %s" % (self.tag, base_title)) if self.tag else base_title
        st, obj = self._req("POST", "/api/sessions", {"title": title[:80]})
        sid = obj.get("id") or obj.get("session")
        if not sid:
            return AgentRef(id=title, session="", meta={"error": obj.get("error", "no session")})
        # Pin the model on the session so the harness uses the arm's model for every
        # turn of this task (a cloud model, not whatever the session default is).
        if self.model:
            self._req("POST", "/api/sessions/%s/model" % urllib.parse.quote(sid),
                      {"model": self.model})
        ws = task.get("workspace")
        if ws:
            self._req("POST", "/api/sessions/%s/workspace" % urllib.parse.quote(sid),
                      {"workspace": ws})
        return AgentRef(id=title, session=sid, meta={"task": task.get("id")})

    def send_task(self, ref, prompt, timeout=None):
        t0 = time.time()
        body = {"session": ref.session, "message": prompt}
        if self.model:
            body["model"] = self.model
        st, obj = self._req("POST", "/api/chat", body, timeout=timeout or self.timeout)
        dur = round(time.time() - t0, 3)
        ok = st == 200 and not obj.get("error")
        return HarnessResult(
            ok=ok, output=obj.get("reply") or "", run_id=obj.get("run_id") or "",
            duration_s=dur, error="" if ok else str(obj.get("error"))[:400],
            provenance=self.provenance())

    def backup_session(self, ref):
        st, obj = self._req("POST", "/api/checkpoints", {"session": ref.session,
                                                         "label": "bench"})
        return obj.get("id") or ""

    def restore(self, ref, checkpoint):
        st, obj = self._req("POST", "/api/checkpoints/restore", {"id": checkpoint})
        return bool(obj.get("ok"))

    def delete_agent(self, ref):
        # `keep_sessions`: the operator wants to inspect the run in the WebUI, so the
        # session survives the benchmark (it is NOT equivalent to leaving garbage —
        # the title is tagged, so the whole run is one keystroke to find and clear).
        if self.keep_sessions:
            return True
        st, _ = self._req("DELETE", "/api/sessions/%s" % urllib.parse.quote(ref.session))
        return st in (200, 204)

    def docker_args(self):
        """The harness runs ON the machine under test — no extra container."""
        return []
