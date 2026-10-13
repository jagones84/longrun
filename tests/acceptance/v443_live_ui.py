"""v443 — WebUI live-UI fixes (JAG-431r8).

Three operator-reported issues, pinned deterministically:

  1) Paste an image from the clipboard into the composer → attachment (no paste
     listener existed).
  2) The chat window did not update live for a turn the browser did not begin
     (a job / routine / another tab): the re-attach stream replayed ONLY
     chat.delta, so tool cards / harness injects / todo nodes appeared only after
     the turn ended. Now the own-turn and re-attach streams share ONE handler set
     and the server replays the render events too.
  3) The RH "Plan" pane showed ONLY the current plan, so a session whose todos
     span several plans looked like it had a couple (Master: 19 todos across 5
     plans, panel showed the 2 of the last plan). Now every other plan is shown
     in a collapsible section.

Deterministic, offline.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")
HTTP = _read("src", "longrun", "core", "httpapi.py")
THREADS = _read("src", "longrun", "memory", "threads.py")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _fn(src, header):
    lines = src[src.index(header):].splitlines()
    out = []
    for i, ln in enumerate(lines):
        out.append(ln)
        if i == 0 and ln.rstrip().endswith("}"):
            break
        if i > 0 and ln.strip() == "}":
            break
    return "\n".join(out)


# --- 1) paste an image/file from the clipboard ------------------------------
check("1a the composer has a paste listener that reads clipboard file items",
      'addEventListener("paste"' in HTML and "clipboardData" in HTML
      and "getAsFile" in HTML, "")
check("1b a pasted clipboard image is uploaded through the SAME attach path",
      "attachFiles(named)" in HTML and "attachFiles(" in HTML, "")

# --- 2) one shared render binder for own-turn + re-attach streams -----------
check("2a a single _bindRenderStream() binder exists",
      "function _bindRenderStream(" in HTML, "")
check("2b the own-turn stream (send) uses the shared binder",
      "_bindRenderStream(es, live, adopt)" in HTML, "")
check("2c the re-attach stream (attachTurn) uses the shared binder",
      "_bindRenderStream(es, live)" in HTML, "")
br = _fn(HTML, "function _bindRenderStream(")
check("2d the binder renders tools + harness injects + graph nodes",
      all(s in br for s in ('es.addEventListener("tool.call"', 'es.addEventListener("tool.result"',
                            'es.addEventListener("harness.inject"',
                            'es.addEventListener("graph.node.added"',
                            'es.addEventListener("graph.node.updated"')), "")
check("2e the server re-attach stream replays the render kinds (not just chat.delta)",
      all(('"%s"' % k) in HTTP for k in ("harness.inject", "tool.call",
                                         "graph.node.added", "graph.node.updated")), "")
# the old attachTurn-only-chat.delta wiring must be gone (extract the whole
# function region — `_fn` stops at the first `}` line, which lands inside its
# `end()` closure).
_at = HTML[HTML.index("function attachTurn("):HTML.index("async function attachIfRunning(")]
check("2f attachTurn no longer hand-codes a partial chat.delta-only stream",
      'es.addEventListener("chat.delta"' not in _at and "_bindRenderStream" in _at, "")

# --- 3) the RH Plan pane shows EVERY plan, not just the current one ---------
check("3a renderGraph computes the non-current plans",
      "const _older = (graph.nodes || []).filter" in HTML, "")
check("3b the other plans render in a collapsible 'older-plans' section",
      'class="older-plans"' in HTML and "older plan " in HTML, "")
check("3c task rows resolve against ALL nodes so older-plan rows are clickable",
      "(graph.nodes || []).find(x => String(x.id) === el.dataset.id)" in HTML, "")

# --- 4) Free.N titles/summaries update LIVE (chapters tool) -----------------
check("4a set_title publishes a threads.updated feed event",
      'set_title' in THREADS and '_publish("threads.updated"' in THREADS
      and 'session=sid' in THREADS, "")
check("4b the WebUI repaints Free.N labels on threads.updated (no reload)",
      'es.addEventListener("threads.updated"' in HTML
      and "loadThreadTitles(d.session || sessionId).then(applyThreadTitles)" in HTML, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)