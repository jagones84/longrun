#!/usr/bin/env python3
"""Semantic setup blocks — progress control for environment setup.

Source: arXiv:2611.18443, "HerAgent: A Block-Level Checkpointing Harness for
Coding-Agent Environment Setup" (round 106). Its measured result: controlling
progress at *command* granularity recovers too little (polluted state survives),
whole-script granularity recovers too much (useful progress is lost), and a
**block** — a group of commands plus one validation — is the unit that makes
setup both reliable (Installamatic-Bench 52.0% -> 85.0%) and cheap (up to 94.5%
less setup work).

Longrun already had session checkpoints (`memory/checkpoints.py`: plan, tasks,
transcript). It had nothing for the *workspace an agent sets up before it can
run tests*: `shell.exec` runs on the host, and a failed `npm install` leaves the
tree in a state the next command trusts.

This module adds the missing unit:

    block = {"name": str, "commands": [str], "validate": str|None, "timeout": int}

  * `run_block`   executes the block's commands, then its validation;
  * a failed command OR a failed validation restores the last good block's
    checkpoint — block-level rollback, the paper's `repair`/`rollback`;
  * every successful block writes a replayable checkpoint (tar + manifest with
    the per-file hashes and the block digest);
  * `reuse` skips a block whose digest and pre-block workspace fingerprint match
    a stored checkpoint — the replay artifact, and the measured cost saving.

Stdlib only; no model, no network. The runner is injectable so tests never need
a real toolchain.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
import time

FORMAT = "longrun-setup-blocks/1"
DEFAULT_TIMEOUT = 600


def _safe(name):
    return "".join(c for c in str(name or "") if c.isalnum() or c in "-_.")[:80] or "block"


def _digest(obj):
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def block_digest(block):
    """Name+commands+validation: what makes two blocks the same block."""
    return _digest({"name": block.get("name"),
                    "commands": list(block.get("commands") or []),
                    "validate": block.get("validate")})


def workspace_fingerprint(root, skip=()):
    """sha256 over (relpath, size, sha256) of the tree — the pre-block state.

    Content, not mtime: a rollback or a re-run of an idempotent command must
    produce the SAME fingerprint, otherwise `reuse` never matches (round 106).
    """
    h = hashlib.sha256()
    root = os.path.abspath(root)
    skip = {os.path.abspath(p) for p in skip}
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs
                         if os.path.abspath(os.path.join(base, d)) not in skip
                         and d != ".git")
        for fn in sorted(files):
            p = os.path.join(base, fn)
            if os.path.abspath(p) in skip:
                continue
            try:
                st = os.stat(p)
                with open(p, "rb") as fh:
                    body = fh.read()
            except OSError:
                continue
            h.update(("%s\0%d\0%s\n" % (os.path.relpath(p, root), st.st_size,
                                        hashlib.sha256(body).hexdigest())).encode("utf-8"))
    return h.hexdigest()[:32]


def _default_runner(command, cwd, timeout):
    try:
        p = subprocess.run(command, shell=True, cwd=cwd, timeout=timeout,
                           capture_output=True, text=True)
        return {"command": command, "exit_code": p.returncode,
                "stdout": (p.stdout or "")[-4000:], "stderr": (p.stderr or "")[-4000:]}
    except subprocess.TimeoutExpired:
        return {"command": command, "exit_code": 124,
                "stdout": "", "stderr": "timeout after %ss" % timeout}
    except Exception as e:  # noqa: BLE001 — a setup step failing must be reported
        return {"command": command, "exit_code": 125, "stdout": "", "stderr": str(e)}


class _Store:
    """Checkpoints for one setup run, under `<state_dir>/setup/<name>/`."""

    def __init__(self, state_dir, workdir):
        self.base = os.path.join(state_dir, "setup")
        self.workdir = os.path.abspath(workdir)
        os.makedirs(self.base, exist_ok=True)

    def _dir(self, name):
        return os.path.join(self.base, _safe(name))

    def save(self, block, pre_digest, manifest_extra=None):
        d = self._dir(block.get("name"))
        os.makedirs(d, exist_ok=True)
        tar_path = os.path.join(d, "snapshot.tar.gz")
        tmp = tar_path + ".tmp"
        with tarfile.open(tmp, "w:gz") as tar:
            for base, dirs, files in os.walk(self.workdir):
                dirs[:] = sorted(x for x in dirs
                                 if x != ".git"
                                 and os.path.abspath(os.path.join(base, x)) != self.base)
                for fn in sorted(files):
                    full = os.path.join(base, fn)
                    tar.add(full, arcname=os.path.relpath(full, self.workdir))
        os.replace(tmp, tar_path)
        manifest = {
            "format": FORMAT,
            "block": block.get("name"),
            "digest": block_digest(block),
            "pre_digest": pre_digest,
            "post_digest": workspace_fingerprint(self.workdir),
            "created": round(time.time(), 3),
            "tarball": os.path.basename(tar_path),
            **(manifest_extra or {}),
        }
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
        return manifest

    def load(self, name):
        d = self._dir(name)
        try:
            with open(os.path.join(d, "manifest.json"), encoding="utf-8") as fh:
                man = json.load(fh)
        except (OSError, ValueError):
            return None
        if not os.path.isfile(os.path.join(d, man.get("tarball") or "")):
            return None
        man["_dir"] = d
        return man

    def restore(self, name):
        man = self.load(name)
        if not man:
            return None
        # A rollback must remove the POLLUTION, not only restore old bytes: a
        # file the failed block created would otherwise survive and the next
        # command would trust it (HerAgent §I: command-level recovery is "too
        # local to remove polluted state").
        tar_path = os.path.join(man["_dir"], man["tarball"])
        with tarfile.open(tar_path, "r:gz") as tar:
            keep = {m.name for m in tar.getmembers()}
        for base, dirs, files in os.walk(self.workdir, topdown=False):
            for fn in files:
                p = os.path.join(base, fn)
                if os.path.relpath(p, self.workdir) not in keep:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            for d in dirs:
                p = os.path.join(base, d)
                try:
                    if not os.listdir(p):
                        os.rmdir(p)
                except OSError:
                    pass
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(self.workdir)  # noqa: S202 — the archive is our own
        return man

    def latest(self):
        best = None
        for name in os.listdir(self.base):
            man = self.load(name)
            if man and (best is None or man.get("created", 0) > best[1].get("created", 0)):
                best = (name, man)
        return best


def run(blocks, workdir, state_dir, runner=None, reuse=False, on_event=None):
    """Run blocks in order; rollback to the last good checkpoint on failure.

    Returns `{"ok", "blocks": [...], "cost": {...}, "state_dir"}`. A block is
    `{"name", "commands": [...], "validate": "cmd"|None, "timeout": int}`.
    """
    runner = runner or _default_runner
    store = _Store(state_dir, workdir)
    results = []
    commands_run = 0
    commands_skipped = 0
    last_good = None

    def _steps(block):
        return len(block.get("commands") or []) + (1 if block.get("validate") else 0)

    def emit(kind, **data):
        if on_event:
            try:
                on_event(kind, **data)
            except Exception:  # noqa: BLE001 — reporting never breaks setup
                pass

    # HerAgent's replay artifact: a tree already in the last block's post-state
    # is a finished setup. Skip the whole plan and report the saving.
    if reuse and blocks:
        skip_dirs = [os.path.join(state_dir, "setup")]
        cur = workspace_fingerprint(workdir, skip=skip_dirs)
        last = blocks[-1]
        last_man = store.load(str(last.get("name") or "block"))
        if (last_man and last_man.get("digest") == block_digest(last)
                and last_man.get("post_digest") == cur):
            complete = all(
                (store.load(str(b.get("name") or "block")) or {}).get("digest")
                == block_digest(b) for b in blocks)
            if complete:
                skipped = sum(_steps(b) for b in blocks)
                return {"ok": True, "state_dir": state_dir,
                        "blocks": [{"name": str(b.get("name") or "block"),
                                    "status": "reused", "digest": block_digest(b)}
                                   for b in blocks],
                        "cost": {"commands_run": 0, "commands_skipped": skipped}}

    for block in blocks or []:
        name = str(block.get("name") or "block")
        digest = block_digest(block)
        pre = workspace_fingerprint(workdir, skip=[os.path.join(state_dir, "setup")])
        prev = store.load(name)
        if reuse and prev and prev.get("digest") == digest and prev.get("pre_digest") == pre:
            skipped = _steps(block)
            commands_skipped += skipped
            results.append({"name": name, "status": "reused", "digest": digest,
                            "checkpoint": prev.get("digest"),
                            "commands_skipped": skipped})
            last_good = name
            emit("setup.block", block=name, status="reused", skipped=skipped)
            continue

        timeout = int(block.get("timeout") or DEFAULT_TIMEOUT)
        outputs = []
        failed = None
        for cmd in block.get("commands") or []:
            commands_run += 1
            out = runner(cmd, workdir, timeout)
            outputs.append(out)
            if int(out.get("exit_code") or 0) != 0:
                failed = {"stage": "command", "output": out}
                break
        if failed is None and block.get("validate"):
            commands_run += 1
            out = runner(block["validate"], workdir, timeout)
            outputs.append(out)
            if int(out.get("exit_code") or 0) != 0:
                failed = {"stage": "validate", "output": out}

        if failed is not None:
            restored = store.restore(last_good) if last_good else None
            results.append({"name": name, "status": "failed", "digest": digest,
                            "failed": failed, "rollback": last_good if restored else None,
                            "outputs": outputs})
            emit("setup.block", block=name, status="failed",
                 stage=failed["stage"], rollback=last_good)
            return {"ok": False, "blocks": results, "state_dir": state_dir,
                    "cost": {"commands_run": commands_run,
                             "commands_skipped": commands_skipped},
                    "failed_block": name}

        man = store.save(block, pre)
        last_good = name
        results.append({"name": name, "status": "ran", "digest": digest,
                        "checkpoint": man["digest"],
                        "post_digest": man["post_digest"], "outputs": outputs})
        emit("setup.block", block=name, status="ran", checkpoint=man["digest"])

    return {"ok": True, "blocks": results, "state_dir": state_dir,
            "cost": {"commands_run": commands_run,
                     "commands_skipped": commands_skipped}}


def load_plan(path):
    """Read a JSON plan: `{"blocks": [...]}` or a bare list."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if isinstance(doc, dict):
        doc = doc.get("blocks")
    if not isinstance(doc, list):
        raise ValueError("setup plan must be a list of blocks (or {\"blocks\": [...]})")
    return doc
