"""Run tracing + token/cost accounting (RunTrace, the runs table, the token proxy).

`RunTrace` records spans and token/cost accounting for one run (chat, plan, agent).
Spans go through OpenTelemetry when the SDK is installed (see ``otel_tracing``);
otherwise a lightweight local span list is kept in the `runs` SQLite table.

Extracted from ``server.py`` (JAG-374). Stdlib + the local `otel_tracing` module.
"""
import hashlib
import json
import os
import subprocess
import time
import uuid

from longrun.model import otel_tracing
from longrun.core.events import _db_lock, db
from longrun.util import paths as _paths

# Token pricing per 1M tokens (input, output) for known local model families.
# Local models are free in $, but we still account tokens; cost is 0 unless a
# price is configured via LONGRUN_PRICES (json: {"alias": [in, out]}).
try:
    MODEL_PRICES = json.loads(os.environ.get("LONGRUN_PRICES", "{}"))
except Exception:
    MODEL_PRICES = {}


def count_tokens(text):
    """Cheap proxy: ~4 chars/token (good enough for local accounting)."""
    return max(1, len(text) // 4) if text else 0


# JAG-86: the model's REAL prompt tokens per session (from the router's `usage`).
# The chars/4 proxy under-reports (Italian ≈ 3.5 chars/token) and ignores the
# chat template, so when the server reports the true count we prefer it.
_REAL_PROMPT_TOKENS = {}

# JAG-273: how many of those prompt tokens came from the provider's PREFIX (KV)
# cache — `usage.prompt_tokens_details.cached_tokens` (OpenAI-compatible) or
# `timings.cache_n` (llama.cpp native). This is the number that proves the prompt
# ordering (static-first / dynamic-last) actually pays off: cached/prompt = hit %.
_REAL_CACHED_TOKENS = {}


# ------------------------------------------------------------- manifest (R1) --
# A run is only diagnosable if a third party can rebuild the conditions it ran
# under: the code revision, every config file in force, the live policy overlay
# the Settings panel writes, and the exact system prompt that was sent. All of
# them are digests, not copies — the manifest stays small and never leaks content.
# Every helper swallows its errors: a broken manifest must never break a run.

_GIT_CACHE = {}


def file_digest(path):
    """sha256 of a file, or None when it cannot be read (never raises)."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:  # noqa: BLE001 — a missing file is data, not an error
        return None


def git_revision(repo_root=None):
    """Short git sha of the checkout, or None. Cached per root for the process."""
    root = os.path.abspath(repo_root or _paths.REPO_ROOT)
    if root in _GIT_CACHE:
        return _GIT_CACHE[root]
    rev = None
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                             capture_output=True, text=True, timeout=3)
        if out.returncode == 0:
            rev = (out.stdout or "").strip() or None
    except Exception:  # noqa: BLE001 — no git, no repo, no permission: unknown
        rev = None
    _GIT_CACHE[root] = rev
    return rev


def _config_digests(config_dir=None):
    """{filename: sha256} for every YAML in the checkout's config dir."""
    root = config_dir or os.path.join(_paths.REPO_ROOT, "config")
    out = {}
    try:
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isfile(path) and name.endswith((".yaml", ".yml")):
                digest = file_digest(path)
                if digest:
                    out[name] = digest
    except Exception:  # noqa: BLE001
        pass
    return out


def build_manifest(kind, model=None, run_id=None, config_dir=None, overlay_path=None,
                   repo_root=None):
    """The conditions of one run, as digests. See `RunTrace.__init__`."""
    overlay = (overlay_path if overlay_path is not None
               else os.path.join(_paths.DATA_DIR, "tools.overlay.yaml"))
    return {
        "run_id": run_id,
        "kind": kind,
        "model": model,
        "created": round(time.time(), 3),
        "revision": git_revision(repo_root),
        "config": _config_digests(config_dir),
        "overlay": file_digest(overlay),
        "prompt": None,
    }


def _runs_dir(runs_dir=None):
    return (runs_dir or os.environ.get("LONGRUN_RUNS_DIR")
            or os.path.join(_paths.DATA_DIR, "runs"))


def _safe_name(value):
    return "".join(c for c in str(value or "") if c.isalnum() or c in "-_.") or "run"


def manifest_path(run_id, runs_dir=None):
    return os.path.join(_runs_dir(runs_dir), _safe_name(run_id), "manifest.json")


def write_manifest(run_id, data, runs_dir=None):
    """Write one manifest atomically; returns its path, or None on failure."""
    path = manifest_path(run_id, runs_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path
    except Exception:  # noqa: BLE001
        return None


def read_manifest(run_id, runs_dir=None):
    """The stored manifest, or None when absent/corrupt."""
    try:
        with open(manifest_path(run_id, runs_dir), "r", encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _prompt_digest(messages):
    """sha256 + size of the system message actually sent (None if none)."""
    for msg in messages or []:
        if isinstance(msg, dict) and msg.get("role") == "system":
            text = msg.get("content")
            if isinstance(text, str) and text:
                return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "chars": len(text)}
    return None


class RunTrace:
    """Records spans + token/cost accounting for one run (chat, plan, agent).

    Spans go through OpenTelemetry when the SDK is installed (see
    otel_tracing.py); otherwise a lightweight local span list is kept.
    """

    def __init__(self, kind, goal=None, model=None):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.goal = (goal or "")[:300]
        self.model = model
        self.ts = round(time.time(), 3)
        self.tokens_in = 0
        self.tokens_out = 0
        self.spans = []
        self.status = "running"
        # R1: the conditions of this run, written before the first call.
        self.manifest = build_manifest(kind, model=model, run_id=self.id)
        write_manifest(self.id, self.manifest)
        with _db_lock:
            db().execute(
                "INSERT INTO runs(id, kind, goal, model, ts) VALUES(?,?,?,?,?)",
                (self.id, kind, self.goal, model, self.ts))
            db().commit()
        self.otel = otel_tracing.init_provider()
        self._otel_root = None
        self._otel_ctx = None
        if self.otel:
            from opentelemetry.trace import set_span_in_context
            attrs = {"longrun.run_id": self.id, "longrun.kind": kind}
            if self.goal:
                attrs["longrun.goal"] = self.goal
            if self.model:
                attrs["longrun.model"] = self.model
            self._otel_root = otel_tracing.get_tracer().start_span("longrun.run", attributes=attrs)
            self._otel_ctx = set_span_in_context(self._otel_root)

    def span(self, name, **attrs):
        s = {"name": name, "ts": round(time.time(), 3), **attrs}
        self.spans.append(s)
        if self.otel and self._otel_root is not None:
            otel_attrs = {"longrun.run_id": self.id}
            otel_attrs.update({k: v for k, v in attrs.items() if v is not None})
            try:
                child = otel_tracing.get_tracer().start_span(
                    name, context=self._otel_ctx, attributes=otel_attrs)
                child.end()
            except Exception:
                pass
        return s

    def llm_call(self, messages, answer):
        # R1: the first call binds the EXACT system prompt that was sent, so the
        # run cannot be "explained" by a prompt that no longer exists on disk.
        if isinstance(self.manifest, dict) and not self.manifest.get("prompt"):
            self.manifest["prompt"] = _prompt_digest(messages)
            if self.manifest["prompt"]:
                write_manifest(self.id, self.manifest)
        tin = sum(count_tokens(m.get("content", "")) for m in messages)
        tout = count_tokens(answer)
        self.tokens_in += tin
        self.tokens_out += tout
        return tin, tout

    def finish(self, status="done"):
        self.status = status
        price = MODEL_PRICES.get(self.model or "", [0.0, 0.0])
        cost = (self.tokens_in / 1e6) * price[0] + (self.tokens_out / 1e6) * price[1]
        spans = self.spans
        if self.otel and self._otel_root is not None:
            try:
                self._otel_root.set_attribute("longrun.status", status)
                self._otel_root.end()
            except Exception:
                pass
            otel_spans = otel_tracing.take_spans(self.id)
            if otel_spans:
                spans = otel_spans
        with _db_lock:
            db().execute(
                "UPDATE runs SET tokens_in=?, tokens_out=?, cost_usd=?, status=?, model=?, spans=? WHERE id=?",
                (self.tokens_in, self.tokens_out, round(cost, 6), status,
                 self.model, json.dumps(spans, ensure_ascii=False), self.id))
            db().commit()

    def summary(self):
        return {"run_id": self.id, "kind": self.kind, "goal": self.goal,
                "model": self.model, "ts": self.ts, "status": self.status,
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "spans": self.spans}


def get_run_trace(run_id):
    with _db_lock:
        row = db().execute(
            "SELECT id, kind, goal, model, ts, tokens_in, tokens_out, cost_usd, status, spans"
            " FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return None
    spans = json.loads(row[9])
    trace_id = next((s.get("trace_id") for s in spans if s.get("trace_id")), None)
    return {"run_id": row[0], "kind": row[1], "goal": row[2], "model": row[3],
            "ts": row[4], "tokens_in": row[5], "tokens_out": row[6],
            "cost_usd": row[7], "status": row[8], "spans": spans,
            "otel": bool(trace_id), "trace_id": trace_id,
            "manifest": read_manifest(run_id)}


def runs_summary(limit=50):
    with _db_lock:
        rows = db().execute(
            "SELECT id, kind, goal, model, ts, tokens_in, tokens_out, cost_usd, status"
            " FROM runs ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [{"run_id": r[0], "kind": r[1], "goal": r[2], "model": r[3], "ts": r[4],
             "tokens_in": r[5], "tokens_out": r[6], "cost_usd": r[7], "status": r[8]}
            for r in rows]

