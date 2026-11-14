#!/usr/bin/env python3
"""Harness restart: the restart ticket and the session continuation (2026-11-15).

`restart` used to live in `core/matrix.py` because the Matrix self-evolution loop
was its first caller. It is a HARNESS lifecycle action — it kills the whole
process, every running turn in every session — so the tool moved to
`harness.restart` and this module owns the mechanics.

Two things must survive the exit: WHICH session asked for the restart, and WHY.
The service manager (`Restart=always` in `deploy/longrun.service`) brings the
process back; this module writes and consumes the durable ticket.

Resume has ONE owner. When the asking turn left an inflight record (the normal
case: the tool ran inside a turn), boot lets `inflight.recover` deliver the
standard `[Harness restart]` continuation. The ticket path only spawns its own
turn when there is no inflight record to recover.

Nothing here may break a turn: every write is best-effort.
"""
import json
import os
import threading
import time

from longrun.util import fswrite
from longrun.util.paths import DATA_DIR

TICKET_NAME = "restart_ticket.json"


def _ticket_path(data_dir=None):
    base = str(data_dir) if data_dir else DATA_DIR
    return os.path.join(base, TICKET_NAME)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 — a missing/corrupt ticket is "no ticket"
        return None


def _ledger(kind, **fields):
    try:
        from longrun.util import improve
        improve.ledger_add(kind, origin="harness", **fields)
    except Exception:  # noqa: BLE001
        pass


def schedule_restart(session_id=None, reason="", data_dir=None, dry_run=False):
    """Write a durable session continuation ticket and optionally restart."""
    ticket = {
        "session_id": str(session_id or "").strip(),
        "reason": str(reason or "Harness restart").strip()[:300],
        "ts": round(time.time(), 3),
    }
    if dry_run:
        # A rehearsal must not leave a resume ticket behind: the NEXT boot (for
        # any reason) would consume it and spawn a continuation turn nobody asked
        # for. Mark it so `resume_after_restart` ignores it.
        ticket["dry_run"] = True
    path = _ticket_path(data_dir)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fswrite.write_json(path, ticket)
    _ledger("harness.restart_scheduled", session=ticket["session_id"],
            reason=ticket["reason"])
    if not dry_run:
        def _delayed_restart():
            time.sleep(0.6)
            os._exit(0)
        threading.Thread(target=_delayed_restart, daemon=True).start()
    return {"ok": True, "ticket": ticket, "dry_run": bool(dry_run)}


def consume_resume_ticket(data_dir=None):
    """Read and atomically delete the restart ticket if present."""
    p = _ticket_path(data_dir)
    if not os.path.isfile(p):
        return None
    data = _read(p)
    try:
        os.remove(p)
    except OSError:
        pass
    return data


def resume_after_restart(data_dir=None, spawn_turn=True):
    """Called on server startup after `reconcile_orphan_turns`."""
    ticket = consume_resume_ticket(data_dir)
    if not ticket or not ticket.get("session_id") or ticket.get("dry_run"):
        return {"resumed": False}
    sid = ticket["session_id"]
    reason = ticket.get("reason") or "harness restart"
    try:
        from longrun.memory import stores
        sess = stores.load_session(sid)
        if sess is not None:
            # ONE resume owner: an interrupted turn is already recoverable, so
            # `inflight.recover` (which runs next) delivers the standard
            # continuation. Only a caller with no inflight record needs the
            # fallback turn below.
            try:
                from longrun.core import inflight as _inflight
                _running = sid in (_inflight.snapshot() or {})
            except Exception:  # noqa: BLE001
                _running = False
            if _running and (sess.get("interrupted") or {}):
                return {"resumed": True, "session_id": sid, "deferred": "inflight"}
            msgs = sess.get("messages") or []
            if msgs and (msgs[-1].get("meta") or {}).get("error_detail") == "interrupted-by-restart":
                msgs.pop()
            stores.append_message(
                sess,
                "assistant",
                "[Harness restart] Service restarted cleanly (%s). Continuing session." % reason,
                meta={"restart_resumed": True, "reason": reason},
            )
            cont_msg = (
                "[Harness restart] Warm restart complete (%s). "
                "Verify your changes and continue the active run." % reason
            )
            if spawn_turn:
                stores.append_message(
                    sess,
                    "user",
                    cont_msg,
                    meta={"restart_continuation": True, "reason": reason},
                )
                def _run_cont():
                    try:
                        from longrun.agent import agent as _ag
                        s2 = stores.load_session(sid)
                        if s2 is not None:
                            _ag.chat_once(s2, cont_msg, model=s2.get("model"), autonomous=True)
                    except Exception:  # noqa: BLE001
                        pass
                threading.Thread(target=_run_cont, daemon=True).start()
            return {"resumed": True, "session_id": sid, "reason": reason}
    except Exception:  # noqa: BLE001
        pass
    return {"resumed": False, "session_id": sid}
