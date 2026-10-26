#!/usr/bin/env python3
"""v664 — R1: a run records the configuration it ran under.

`RunTrace` stored id/kind/goal/model/ts + tokens/cost/spans, so a finished run
could not be recomputed: the config in force, the policy overlay and the exact
system prompt were lost. This test pins the manifest:

* `<runs>/<run_id>/manifest.json` is written at run start;
* every `config/*.yaml` is digested, plus the live policy overlay;
* the git revision is recorded (None when it cannot be read, never a raise);
* the first `llm_call` adds the system-prompt digest;
* `get_run_trace` exposes it read-only.

Deterministic, no live model, no network, no server.
"""
import hashlib
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v664-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import tracing           # noqa: E402

RUNS = os.path.join(TMP, "runs")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A. primitives ---------------------------------------------------------
check("A1 the manifest API exists",
      all(callable(getattr(tracing, n, None)) for n in
          ("file_digest", "git_revision", "build_manifest", "manifest_path",
           "write_manifest", "read_manifest")))

cfgdir = os.path.join(TMP, "cfg-src")
os.makedirs(cfgdir, exist_ok=True)
tools_yaml = os.path.join(cfgdir, "tools.yaml")
routing_yaml = os.path.join(cfgdir, "routing.yaml")
with open(tools_yaml, "w", encoding="utf-8") as f:
    f.write("approvals:\n  mode: normal\n")
with open(routing_yaml, "w", encoding="utf-8") as f:
    f.write("providers: []\n")

d1 = tracing.file_digest(tools_yaml)
check("A2 a digest is a stable short sha",
      isinstance(d1, str) and 8 <= len(d1) <= 64
      and d1 == tracing.file_digest(tools_yaml), d1)
check("A3 a missing file digests to None (never raises)",
      tracing.file_digest(os.path.join(TMP, "nope.yaml")) is None)

# ---- B. the manifest content ------------------------------------------------
m1 = tracing.build_manifest("chat", model="m1", config_dir=cfgdir,
                            overlay_path=os.path.join(TMP, "no-overlay.yaml"),
                            repo_root=REPO)
check("B1 the manifest names the run and its config",
      m1.get("kind") == "chat" and m1.get("model") == "m1"
      and sorted(m1.get("config") or {}) == ["routing.yaml", "tools.yaml"],
      sorted(m1.get("config") or {}))
check("B2 the git revision is recorded",
      isinstance(m1.get("revision"), str) and len(m1["revision"]) >= 7, m1.get("revision"))
check("B3 a missing overlay is null",
      m1.get("overlay") is None, m1.get("overlay"))

with open(tools_yaml, "w", encoding="utf-8") as f:
    f.write("approvals:\n  mode: full\n")
m2 = tracing.build_manifest("chat", model="m1", config_dir=cfgdir,
                            overlay_path=os.path.join(TMP, "no-overlay.yaml"),
                            repo_root=REPO)
check("B4 editing one config file moves exactly its digest",
      m2["config"]["tools.yaml"] != m1["config"]["tools.yaml"]
      and m2["config"]["routing.yaml"] == m1["config"]["routing.yaml"])

m3 = tracing.build_manifest("chat", model="m1", config_dir=cfgdir,
                            overlay_path=os.path.join(TMP, "no-overlay.yaml"),
                            repo_root=REPO)
check("B5 the same config is stable across runs",
      m3["config"] == m2["config"], m3["config"])

overlay = os.path.join(TMP, "tools.overlay.yaml")
with open(overlay, "w", encoding="utf-8") as f:
    f.write("tools:\n  shell:\n    enabled: false\n")
m4 = tracing.build_manifest("chat", config_dir=cfgdir, overlay_path=overlay,
                            repo_root=REPO)
check("B6 the live policy overlay is digested",
      isinstance(m4.get("overlay"), str) and m4["overlay"] == tracing.file_digest(overlay),
      m4.get("overlay"))
check("B7 an unreadable repo yields revision null, never a raise",
      tracing.build_manifest("chat", config_dir=cfgdir,
                             repo_root=os.path.join(TMP, "no-repo"))["revision"] is None)

# ---- C. RunTrace writes it --------------------------------------------------
tr = tracing.RunTrace("chat", goal="v664 probe", model="m1")
path = tracing.manifest_path(tr.id)
check("C1 the run writes <runs>/<id>/manifest.json", os.path.isfile(path), path)
stored = tracing.read_manifest(tr.id) or {}
check("C2 the stored manifest carries the run id and the config",
      stored.get("run_id") == tr.id and bool(stored.get("config")),
      stored.get("run_id"))
check("C3 no prompt digest before the first call",
      stored.get("prompt") is None, stored.get("prompt"))

system = "You are Longrun. Rules: be useful."
tr.llm_call([{"role": "system", "content": system},
             {"role": "user", "content": "hi"}], "hello")
stored = tracing.read_manifest(tr.id) or {}
prompt = stored.get("prompt") or {}
check("C4 the first call binds the system prompt",
      prompt.get("sha256") == hashlib.sha256(system.encode("utf-8")).hexdigest(),
      prompt.get("sha256"))
check("C5 the prompt digest carries its size",
      prompt.get("chars") == len(system), prompt.get("chars"))
_first = prompt.get("sha256")
tr.llm_call([{"role": "system", "content": "a DIFFERENT prompt"},
             {"role": "user", "content": "again"}], "ok")
check("C6 a later call does not rewrite the first prompt digest",
      (tracing.read_manifest(tr.id) or {}).get("prompt", {}).get("sha256") == _first)

tr.finish()
tr2 = tracing.get_run_trace(tr.id) or {}
check("C7 get_run_trace exposes the manifest",
      (tr2.get("manifest") or {}).get("run_id") == tr.id,
      type(tr2.get("manifest")).__name__)

# ---- D. failures never break a run -----------------------------------------
blocker = os.path.join(TMP, "blocked")
with open(blocker, "w", encoding="utf-8") as f:
    f.write("not a directory")
check("D1 an unwritable runs dir returns None instead of raising",
      tracing.write_manifest("deadbeef", {"run_id": "deadbeef"},
                             runs_dir=os.path.join(blocker, "runs")) is None)
tr3 = tracing.RunTrace("agent", model=None)
check("D2 a run without a model still writes a manifest",
      os.path.isfile(tracing.manifest_path(tr3.id)))
check("D3 a missing manifest reads as None",
      tracing.read_manifest("does-not-exist") is None)

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
