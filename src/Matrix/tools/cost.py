"""Matrix tool namespace: cost — query token and embedding cost log aggregates."""
import os
import time
from longrun.model import costs
from longrun.memory import costlog
from longrun.util.fswrite import read_json

TOOL_SCHEMAS = {
    "cost.status": {
        "description": (
            "Query LLM token and embedding cost aggregates across sessions or for a single session. "
            "Returns total USD, token counts, call counts, per-model breakdown, and recent calls."
        ),
        "type": "object",
        "properties": {
            "session": {
                "type": "string",
                "description": "Optional session ID. Omit to aggregate across all sessions.",
            },
            "tail": {
                "type": "integer",
                "description": "Max recent calls to include (default 20).",
                "default": 20,
            },
        },
        "required": [],
        "approval": "auto",
    },
}


def execute(args, run_id=None, subtool=None):
    args = args or {}
    sid = str(args.get("session") or "").strip()
    tail = max(1, min(int(args.get("tail") or 20), 200))

    if sid:
        s = costs.summary(sid, tail=tail)
        s["ok"] = True
        s["stdout"] = (
            "session %s: %d calls | in=%d out=%d cached=%d | $%.6f"
            % (sid, s.get("calls", 0), s.get("tokens_in", 0),
               s.get("tokens_out", 0), s.get("cached", 0), s.get("total_usd", 0.0))
        )
        return s

    # Aggregate across all session cost ledgers in COSTS_DIR
    all_entries = []
    sessions_count = 0
    if os.path.isdir(costs.COSTS_DIR):
        cutoff = time.time() - costs.RETENTION_DAYS * 86400
        for fn in sorted(os.listdir(costs.COSTS_DIR)):
            if not fn.endswith(".json"):
                continue
            d = read_json(os.path.join(costs.COSTS_DIR, fn), None)
            if not isinstance(d, list):
                continue
            sessions_count += 1
            sess_name = fn[:-5]
            for c in d:
                if not isinstance(c, dict):
                    continue
                try:
                    ts = float(c.get("ts") or 0)
                except (TypeError, ValueError):
                    ts = 0.0
                if ts >= cutoff:
                    row = dict(c)
                    row.setdefault("session", sess_name)
                    all_entries.append(row)

    all_entries.sort(key=lambda r: float(r.get("ts") or 0))
    agg = costs._summarise(all_entries)
    try:
        emb = costlog.summary()
    except Exception:  # noqa: BLE001
        emb = {}
    agg.update({
        "ok": True,
        "sessions_counted": sessions_count,
        "recent": list(reversed(all_entries[-tail:])),
        "embedding": emb,
        "stdout": (
            "all sessions (%d): %d calls | in=%d out=%d cached=%d | $%.6f"
            % (sessions_count, agg.get("calls", 0), agg.get("tokens_in", 0),
               agg.get("tokens_out", 0), agg.get("cached", 0), agg.get("total_usd", 0.0))
        ),
    })
    return agg
