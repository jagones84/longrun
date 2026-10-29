#!/usr/bin/env python3
"""Matched whole-run execution: frozen inputs, confined container, bounded model.

This is the production counterpart of `probe`'s injected offline seam. One call
freezes a snapshot, executes a reference run, then executes each candidate as a
hardlinked variant differenced only by the declared component. Every run gets its
own gateway with its own request budget, so spend is attributable per run and a
candidate cannot borrow the reference's allowance.

What this proves: both runs consumed the SAME package digest and completed in the
same confined profile. What it does not prove: that one rollout is causal, or
that a behaviour change transfers. `compose.reflect` keeps that distinction.
"""
import json
import os
import shutil
import uuid
from urllib.parse import urlsplit

from longrun.harness import compose as compose_mod
from longrun.harness import contrast as contrast_mod
from longrun.harness import gateway as gateway_mod
from longrun.harness import snapshot as snapshot_mod
from longrun.tools import sandbox

DEFAULTS = {
    "model": "",
    "image": "",
    "gateway_upstream": "",
    "gateway_max_requests": 12,
    "gateway_max_tokens": 4096,
    "gateway_max_seconds": 900,
    "run_timeout": 600,
    "port": 18080,
    "context_length": 32768,
    "snapshot_max_mb": 256,
    "repeats": 1,
}


def _reason(why):
    return {"available": False, "backend": None, "reason": why}


def _router():
    from longrun.model import rllm
    return rllm


def upstream_of(c):
    """The fixed upstream completion URL; the router owner supplies the default."""
    return (str((c or {}).get("gateway_upstream") or "").strip()
            or (_router().ROUTER_BASE.rstrip("/") + "/v1/chat/completions"))


def readiness(c=None):
    """Can a whole run start? Every check names its own missing piece."""
    c = dict(DEFAULTS, **(c or {}))
    if os.name != "posix":
        return _reason("whole-run confinement requires a POSIX host")
    if os.getuid() == 0 or os.getgid() == 0:
        return _reason("whole-run confinement must not run as root")
    image = str(c.get("image") or "")
    if len(image) != 71 or not image.startswith("sha256:"):
        return _reason("no pinned runtime image (LONGRUN_HARNESS_IMAGE=sha256:...)")
    model = str(c.get("model") or "").strip()
    if not model:
        return _reason("no fixed probe model (LONGRUN_HARNESS_MODEL)")
    upstream = urlsplit(upstream_of(c))
    if upstream.scheme != "http" or upstream.hostname not in ("127.0.0.1", "localhost", "::1"):
        return _reason("gateway upstream must be a loopback HTTP endpoint")
    if not shutil.which("docker"):
        return _reason("docker binary is unavailable")
    info = sandbox._run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=8)
    if info["exit_code"] != 0:
        return _reason("docker daemon is unreachable")
    inspect = sandbox._run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                           timeout=8)
    if inspect["exit_code"] != 0:
        return _reason("pinned runtime image is not present locally")
    if inspect["stdout"].strip() != image:
        return _reason("pinned runtime image identity does not match")
    return {"available": True, "backend": "docker-whole", "reason": "",
            "image": image, "model": model, "port": int(c["port"])}


def _run_id(tag):
    safe = "".join(ch for ch in str(tag or "") if ch.isalnum() or ch in "._-")[:24]
    return "%s-%s" % (safe or "run", uuid.uuid4().hex[:12])


def _delta_for(candidate):
    """Container-relative delta path for a supported candidate kind."""
    from longrun.harness import probe as probe_mod
    target, why = probe_mod._target(str(candidate.get("kind") or ""),
                                    candidate.get("name"))
    if not target:
        return None, why
    path = target.replace(os.sep, "/")
    if path.startswith("skills/") or path.startswith("src/Matrix/") \
            or path.startswith("matrix/"):
        return path, ""
    if path == "rules/Project_rules.md":
        return "rules/guardrail.txt", ""
    return None, "candidate target has no snapshot delta"


def _container_args(goal, model, port, guardrail=False):
    args = ["-m", "longrun.harness.runner", "--goal", goal,
            "--model", "h2:" + model,
            "--rules", "/input/rules/snapshot.json",
            "--workspace-from", "/input/workspace",
            "--gateway-socket", "/state/gateway.sock",
            "--gateway-port", str(int(port)),
            "--out", "/state/result.json"]
    if guardrail:
        args += ["--guardrail", "/input/rules/guardrail.txt"]
    return args


def _parse(result, digest, run_id):
    """Extract the runner's evidence line, refusing anything unbound or partial."""
    for line in (result.get("stdout") or "").splitlines():
        if not line.startswith("H2_RESULT "):
            continue
        try:
            payload = json.loads(line[len("H2_RESULT "):])
        except ValueError:
            return None, "runner evidence is not JSON"
        if not isinstance(payload, dict):
            return None, "runner evidence is not an object"
        if payload.get("record_truncated"):
            return None, "runner evidence exceeded the transport bound"
        if payload.get("snapshot") != digest:
            return None, "runner consumed a different snapshot"
        if payload.get("probe_id") != run_id:
            return None, "runner evidence is not bound to this run"
        record = payload.get("record")
        if not isinstance(record, dict):
            return None, str(payload.get("error") or "runner returned no record")[:400]
        return payload, ""
    return None, "runner produced no evidence line"


def _execute(snapshot_path, digest, c, tag, candidates, guardrail=False):
    """One confined run + its own gateway. Returns {ok, record, contrast?...}."""
    run_id = _run_id(tag)
    socket_path = os.path.join(os.path.dirname(os.path.dirname(snapshot_path)),
                               run_id + ".sock")
    gateway = gateway_mod.Gateway(
        model=c["model"], upstream=upstream_of(c),
        max_requests=int(c["gateway_max_requests"]),
        max_tokens=int(c["gateway_max_tokens"]),
        max_seconds=float(c["gateway_max_seconds"]))
    started = gateway.start(socket_path)
    if not started.get("ok"):
        return {"ok": False, "reason": started.get("error") or "gateway unavailable",
                "run_id": run_id}
    try:
        args = _container_args(c["goal"], c["model"], c["port"], guardrail=guardrail)
        env = {"LONGRUN_PROVIDERS": "/input/config/providers.yaml",
               _router().ROUTER_ENV: "http://127.0.0.1:%d" % int(c["port"]),
               "LONGRUN_H2_SNAPSHOT": digest,
               # The frozen package carries BOTH Matrix trees, so the reference
               # and every variant load the same zone (the candidate differs only
               # by its declared delta).
               "LONGRUN_MATRIX_SRC": "/input/src/Matrix",
               "LONGRUN_MATRIX_DOT": "/input/matrix",
               "LONGRUN_HARNESS_PROBE": run_id}
        result = sandbox.run_whole(snapshot_path, c["image"], args,
                                   timeout=float(c["run_timeout"]),
                                   job_id=run_id, gateway_socket=socket_path,
                                   extra_env=env)
        payload, why = _parse(result, digest, run_id)
        if payload is None:
            why = "%s (exit %s%s)" % (
                why, result.get("exit_code"),
                ", timeout" if result.get("timeout") else "")
        record = (payload or {}).get("record")
        if record:
            record.setdefault("evidence", {})
            record["evidence"].update({"scope": "matched_container_run",
                                       "run_binding": run_id,
                                       "snapshot_digest": digest})
        stats = gateway.stats()
        return {"ok": bool(payload), "record": record,
                "reply": (payload or {}).get("reply") or "",
                "model": (payload or {}).get("model") or "",
                "run_id": run_id, "digest": digest,
                "container": result.get("container"),
                "cleanup_verified": bool(result.get("cleanup_verified")),
                "gateway": stats, "reason": why,
                "exit_code": result.get("exit_code")}
    finally:
        gateway.stop()


def run_group(base, candidates, c=None, combine=False):
    """Freeze once, execute the reference, then each candidate (or one composed)."""
    c = dict(DEFAULTS, **(c or {}))
    c["goal"] = str((base or {}).get("goal") or "")
    c["model"] = str(c.get("model") or "").strip()
    ready = readiness(c)
    if not ready["available"]:
        return {"status": "refused", "reason": ready["reason"], "isolation": ready}
    if not c["goal"].strip():
        return {"status": "refused", "reason": "the reference run has no goal"}
    built = snapshot_mod.build(base, {"max_mb": c["snapshot_max_mb"]},
                               model=c["model"], port=int(c["port"]),
                               context_length=int(c["context_length"]))
    if not built.get("ok"):
        return {"status": "refused", "reason": built.get("reason") or "snapshot failed"}
    created = [built["path"]]
    try:
        if not snapshot_mod.verify(built["path"])["ok"]:
            return {"status": "refused", "reason": "snapshot failed verification"}
        references = []
        repeats = max(1, min(3, int(c.get("repeats") or 1)))
        for number in range(1, repeats + 1):
            got = _execute(built["path"], built["digest"], c,
                           "reference-%d" % number, [])
            if not got.get("ok"):
                return {"status": "failed",
                        "reason": got.get("reason") or "reference run failed",
                        "reference": got, "references": references,
                        "digest": built["digest"]}
            references.append(got)
        reference = references[0]
        trials = []
        groups = [list(candidates or [])] if combine else [[x] for x in (candidates or [])]
        for group in groups:
            delta, names, refusals = {}, {}, []
            for candidate in group:
                rel, why = _delta_for(candidate)
                if not rel:
                    refusals.append({"name": candidate.get("name"), "reason": why})
                    continue
                if rel in delta:
                    refusals.append({"name": candidate.get("name"),
                                     "reason": "same delta path as another candidate"})
                    continue
                delta[rel] = candidate.get("content")
                names[str(candidate.get("name") or "")] = rel
            if refusals and not delta:
                trials.append({"candidate": group[0] if len(group) == 1 else {"group": group},
                               "status": "refused", "refusals": refusals,
                               "reason": refusals[0]["reason"]})
                continue
            variant = snapshot_mod.variant(built["path"], delta)
            if not variant.get("ok"):
                trials.append({"candidate": group[0] if len(group) == 1 else {"group": group},
                               "status": "failed", "reason": variant.get("reason"),
                               "refusals": refusals})
                continue
            created.append(variant["path"])
            label = "successor" if combine else str(group[0].get("name") or "candidate")
            runs = []
            try:
                for number in range(1, repeats + 1):
                    got = _execute(variant["path"], variant["digest"], c,
                                   "%s-%d" % (label, number), group,
                                   guardrail=any(r.startswith("rules/") for r in delta))
                    runs.append(got)
                    if not got.get("ok"):
                        break
            finally:
                snapshot_mod.remove(variant["path"])
                created.remove(variant["path"])
            contrasts = [contrast_mod.diff(references[index]["record"], got["record"])
                         for index, got in enumerate(runs) if got.get("ok")]
            row = {"candidate": group[0] if len(group) == 1 else {"group": group},
                   "candidates": group, "status": "failed", "staged": names,
                   "refusals": refusals, "repeats": repeats, "runs": runs,
                   "digest": variant["digest"], "contrasts": contrasts}
            failed = next((got for got in runs if not got.get("ok")), None)
            if failed is not None or not contrasts:
                row.update(reason=(failed or {}).get("reason") or "candidate run failed",
                           run=failed or {})
                trials.append(row)
                continue
            combined = dict(contrasts[0])
            combined["verdict"] = compose_mod.aggregate(contrasts)
            combined["repeat_verdicts"] = [c.get("verdict") for c in contrasts]
            row.update(status="ran", record=runs[0]["record"], run=runs[0],
                       contrast=combined)
            trials.append(row)
        return {"status": "ran", "reference": reference["record"],
                "references": [got["record"] for got in references],
                "reference_run": reference, "reference_runs": references,
                "trials": trials, "digest": built["digest"], "isolation": ready}
    finally:
        for path in list(created):
            snapshot_mod.remove(path)
