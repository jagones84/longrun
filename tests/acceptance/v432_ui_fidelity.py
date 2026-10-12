"""v432 — WebUI fidelity: the UI must mirror REAL backend state (JAG-431b/c).

The user's rule: "the graphics must be a mirror of the real existing things — not
stubbed things, not disconnected from the real things they represent."

Pins two fixes:
  * index.html — ONE source of the todo graph (the per-session graph via
    `loadPlan()`); `loadGraph()` no longer reads `/api/runs/<curRunId>/graph` from
    the stale `localStorage("sf_run")` mirror, and the live-event handler no longer
    gates on `curRunId`.
  * console.html — never FABRICATE on a backend hiccup: the demo deck is opt-in
    (`?demo=1`), failures show an explicit empty offline state, its graph reads the
    real per-session graph (not the legacy `/api/plan`), and the TASKS chip no
    longer falls back to the phantom `tasks.json` board.

Deterministic, offline.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


IDX = _read("webui", "index.html")
CON = _read("webui", "console.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _fn(src, header):
    """Slice a JS function body (C-style braces): single-line or up to the first `}` line."""
    lines = src[src.index(header):].splitlines()
    out = []
    for i, ln in enumerate(lines):
        out.append(ln)
        if i == 0 and ln.rstrip().endswith("}"):
            break
        if i > 0 and ln.strip() == "}":
            break
    return "\n".join(out)


# --- index.html: one source for the todo graph ------------------------------
lg = _fn(IDX, "async function loadGraph()")
check("1a loadGraph() reads the SESSION graph (delegates to loadPlan)",
      "await loadPlan()" in lg, "")
check("1b loadGraph() no longer calls /api/runs/<runId>/graph",
      'api("GET", "/api/runs/' not in lg, "")
ag = _fn(IDX, "function applyGraphEvent(")
check("1c applyGraphEvent no longer gates on the localStorage curRunId",
      "curRunId !== d.run" not in ag and "setRun(d.run)" not in ag, "")

# --- console.html: never fabricate on error ---------------------------------
check("2a the demo deck is opt-in (wantDemo)", "function wantDemo(" in CON, "")
check("2b an explicit empty offline state exists", "function enterOffline(" in CON, "")

ls = _fn(CON, "async function loadStatus(")
check("2c loadStatus failure shows OFFLINE (not fabricated demo)",
      "enterOffline()" in ls and "wantDemo()" in ls, "")
lss = _fn(CON, "async function loadSessions(")
check("2d loadSessions failure shows OFFLINE (not fabricated demo)",
      "enterOffline()" in lss and "wantDemo()" in lss, "")

# --- console.html: real graph + no phantom tasks fallback -------------------
cg = _fn(CON, "async function loadGraph(")
check("2e console loadGraph calls the real per-session graph endpoint",
      'api("/api/sessions/' in cg and 'api("/api/plan' not in cg, "")
check("2f the TASKS chip no longer falls back to the legacy tasks board",
      "st.tasks ?" not in CON, "")

# --- console.html: demo only behind ?demo=1 ---------------------------------
boot = _fn(CON, "async function boot(")
check("2g boot only enters demo behind wantDemo()",
      "if (wantDemo()){ enterDemo(); return; }" in boot, "")
check("2h file:// shows the offline state, not a fabricated deck",
      "enterOffline()" in boot, "")

# --- console.html: models read the real catalogue ---------------------------
lm = _fn(CON, "async function loadModels(")
check("2i console models read the real /api/models catalogue",
      'api("/api/models")' in lm and "state.status.models" not in lm, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
