#!/usr/bin/env python3
"""Bare-model adapter — the NO-HARNESS baseline (JAG-454).

The fair control for "how much is the harness worth?": it sends the SAME task
prompt to the SAME model over a plain OpenAI-compatible chat/completions call,
with NO tools, NO system prompt, NO todo list, NO memory, NO compaction — i.e.
exactly what you get by curling the model API. Any delta against
`LongrunAdapter` on the same task set + model is attributable to the harness.

Nothing here imports `longrun.*` (same rule as the Longrun adapter): it is a
client of the model endpoint, not of the harness.

Env: OPENAI_BASE_URL (default https://api.deepseek.com/v1), OPENAI_API_KEY, or a
per-provider base/key passed to the constructor.
"""
import json
import os
import time
import urllib.error
import urllib.request

from .protocol import AgentRef, HarnessResult

_DEFAULT_BASE = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1")


def _key(env_names):
    for n in env_names:
        v = os.environ.get(n)
        if v:
            return v
    return ""


def _env_file_key(env_names, path="~/.hermes/.env"):
    """Read a key from a dotenv-style file (the DGX keeps API keys there)."""
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                for n in env_names:
                    if line.startswith(n + "="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


class BareAdapter:
    """Direct model call — the baseline a harness must beat to be worth using."""

    name = "bare"

    def __init__(self, base=None, api_key=None, model=None, timeout=600.0,
                 temperature=0.0, max_tokens=8192):
        self.base = (base or _DEFAULT_BASE).rstrip("/")
        self.api_key = (api_key or os.environ.get("DEEPSEEK_API_KEY")
                        or os.environ.get("OPENAI_API_KEY")
                        or _key(["DEEPSEEK_API_KEY", "OPENAI_API_KEY"])
                        or _env_file_key(["DEEPSEEK_API_KEY", "OPENAI_API_KEY"]))
        self.model = model or "deepseek-reasoner"
        self.timeout = float(timeout)
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _req(self, body, timeout=None):
        req = urllib.request.Request(
            self.base + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"error": raw[:400]}
        except OSError as e:
            return 0, {"error": repr(e)[:200]}

    def provenance(self):
        return {"harness": "bare", "base_url": self.base, "model": self.model,
                "temperature": self.temperature, "max_tokens": self.max_tokens,
                "tools": 0, "system_prompt": False}

    # ---- adapter contract (stateless: no session to create/back up) ---------
    def create_agent(self, task):
        return AgentRef(id=str(task.get("id") or "bare"), session="bare")

    def send_task(self, ref, prompt, timeout=None):
        t0 = time.time()
        st, obj = self._req({"model": self.model, "temperature": self.temperature,
                             "max_tokens": self.max_tokens,
                             "messages": [{"role": "user", "content": prompt}]},
                            timeout=timeout)
        dur = round(time.time() - t0, 3)
        if st != 200:
            return HarnessResult(ok=False, error=str(obj.get("error"))[:400],
                                 duration_s=dur, provenance=self.provenance())
        try:
            out = obj["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as e:
            return HarnessResult(ok=False, error="bad response shape: %s" % e,
                                 duration_s=dur, provenance=self.provenance())
        usage = obj.get("usage") or {}
        return HarnessResult(ok=True, output=out, duration_s=dur,
                             tokens=int(usage.get("total_tokens") or 0),
                             provenance=self.provenance())

    def backup_session(self, ref):
        return ""

    def restore(self, ref, checkpoint):
        return False

    def delete_agent(self, ref):
        return True

    def docker_args(self):
        return []