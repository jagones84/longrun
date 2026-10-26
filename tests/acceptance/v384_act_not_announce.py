#!/usr/bin/env python3
"""v384 — "act, don't announce" must catch a promise that is NOT the first sentence (JAG-384).

Observed live (session 34e0630510f2, goal "L hai provata sulla codebase tua? Pero non
cambiare nulla proponi solo"): the model replied "No: **non l'ho ancora provata sulla
codebase**. …  Da ora procedo **in sola lettura sulla codebase**: analizzo e propongo …".
The JAG-74 promise detector was anchored on the START of the message, so it MISSED the
second-paragraph promise: the nudge never fired, the turn ended `goal_reached` (0 open
steps at that moment) and the announced work was never done. The detector now matches the
verb at ANY sentence/line start too, with a short lead-in ("Da ora procedo", "Adesso
analizzo", "Then I'll …").

Deterministic, no model, no network (the stream is stubbed).
Run: python3 tests/acceptance/v384_act_not_announce.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-384-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- A: the JAG-74 legacy cases must still hold -------------------------------
check("A1 a short first-person promise at the START is detected",
      server._looks_like_promise("Carico un'altra skill per dimostrare che funziona.") is True)
check("A2 an English promise is detected",
      server._looks_like_promise("I'll load another skill now.") is True)
check("A3 a real RESULT is not a promise",
      server._looks_like_promise("Ho caricato la skill: ecco l'elenco completo.") is False)
check("A4 a long answer is never treated as a promise",
      server._looks_like_promise("Carico " + "x" * 500) is False)
check("A5 empty text is not a promise", server._looks_like_promise("") is False)

# --- B: the promise is NOT the first sentence (the live miss) -----------------
_REAL = ("No: **non l'ho ancora provata sulla codebase**. L'avevo solo indicata come "
         "prossima skill da provare.\n\nDa ora procedo **in sola lettura sulla codebase**: "
         "analizzo e propongo, senza modificare file, eseguire comandi di scrittura o "
         "applicare cambiamenti.")
check("B1 a second-paragraph promise IS detected (the exact live reply)",
      server._looks_like_promise(_REAL) is True)
check("B2 a lead-in promise ('Adesso analizzo …') is detected",
      server._looks_like_promise("Ok, capito.\n\nAdesso analizzo il file e ti dico.") is True)
check("B3 a genuine multi-sentence result is still NOT a promise",
      server._looks_like_promise(
          "Ho completato l'analisi. Il file X contiene 3 funzioni. Nessuna modifica necessaria."
      ) is False)

# --- C: integration — the second-paragraph promise nudges the model to act -----
seq = [
    (_REAL, "", "m1"),
    ('{"action":"tool","tool":"skills","args":{"action":"list"}}', "", "m1"),
    ("Fatto: elenco skill mostrato, nessuna modifica applicata.", "", "m1"),
]
calls = {"n": 0}


def fake_stream(msgs, model, kind, on_delta, timeout=300, usage=None, **kwargs):
    calls["n"] += 1
    return seq.pop(0) if seq else ("Fine.", "", model)


server.stream_with_fallback = fake_stream
server.api_v02.gated_call = lambda tool, args, run_id=None, **kw: {
    "status": "executed", "observation": "skills ok"}
sess = server.get_or_create_session("act384")
reply, _ = server.chat_once(
    sess, "L hai provata sulla codebase tua? Pero non cambiare nulla proponi solo", None)
check("C1 the second-paragraph announcement triggered a nudge (>=3 model calls)",
      calls["n"] >= 3, "calls=%d" % calls["n"])
check("C2 the stored reply is the RESULT, not the announcement",
      "Da ora procedo" not in reply.get("content", ""),
      "content=%s" % (reply.get("content", "")[:70]))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

