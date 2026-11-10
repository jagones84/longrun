#!/usr/bin/env python3
"""v956 — the composer's ✨ drafts the OPERATOR's message, never the agent's.

Reported 2026-11-11. The operator clicked the AI-draft control in the chat composer
and got back:

  "Hai la prova che il gate è solo su `sessions.read` e non sui file. Quale dei due
   vuoi come prossimo passo: chiudere il buco … oppure proseguire l'audit sulle altre
   sessioni?"

That is the AGENT asking the OPERATOR a question — the exact opposite of what the
field is. Two causes, both read in the code:

  * `gen/surfaces.py`'s `chat.prompt` system prompt never named the VOICE: it said
    "write the NEXT message that moves the work forward — ask for the missing
    decision", and its opening branch said "asks the operator what they want to work
    on". A model that is not told whose message it writes takes the side that owns a
    question, so it echoed the assistant;
  * the ✨'s empty-state name said "write this field with AI", which reads as a prompt
    FOR the agent. It now says it drafts MY message.

Locked here:
  * the prompt states the voice first (operand → agent), and forbids the agent's
    voice / a question to the operator / a copy of the agent's words;
  * the continuation branch makes the operator DECIDE the agent's open question;
  * the opening branch has the operator state what they want done;
  * the surface keeps its shape (generate, session-scoped on the chat's own model,
    replace), which `v772` also pins;
  * the ✨ name in the empty state says whose message it writes, and the name is both
    the tooltip and the accessible name.

Deterministic: no live model, no network, no server.
Run: python3 tests/acceptance/v956_chat_draft_voice.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.gen import surfaces as S  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as _f:
    HTML = _f.read()

CHAT = S.SURFACES["chat.prompt"]
SYS = CHAT.system

# --- A: the voice is stated before anything else -----------------------------
check("A1 the prompt names the field as the OPERATOR's message to the AGENT",
      "the message the OPERATOR sends to the AGENT" in SYS)
check("A2 the operator's voice is required, the agent's voice forbidden",
      "in the OPERATOR's voice" in SYS and "never in the agent's voice" in SYS)
check("A3 a question TO the operator is refused",
      "never as a question to the operator" in SYS)
check("A4 the agent's words are never copied back as the operator's",
      "never a copy, summary or rephrase of the agent's own words" in SYS)
check("A5 the opening branch states what the OPERATOR wants done",
      "the operator states what they want done" in SYS
      and "asks the operator what they want to work on" not in SYS)
check("A6 the continuation branch makes the operator DECIDE the open question",
      "the operator DECIDES it" in SYS and "answer it (pick the option" in SYS)
check("A7 the filled-field branch still OPTIMIZES the draft (no regression)",
      "OPTIMIZE the operator's draft" in SYS
      and "Overlap with the draft is intended" in SYS)
check("A8 the reply-only contract is still appended",
      SYS.rstrip().endswith("otherwise in English."))

# --- B: the shape v772 pins is untouched ------------------------------------
check("B1 the surface is still a generate surface",
      CHAT.kind == S.GENERATE, CHAT.kind)
check("B2 it still runs on the chat's own model + chat context",
      CHAT.session_scoped is True and CHAT.role == S.SESSION_ROLE and CHAT.ctx == "chat.prompt")
check("B3 it still REPLACES the field (a draft is never appended)",
      CHAT.apply == "replace", CHAT.apply)
check("B4 it is still offered to the UI by the public registry",
      any(r["id"] == "chat.prompt" for r in S.registry()))

# --- C: the control says whose text it writes -------------------------------
check("C1 the composer ✨ carries an EMPTY-state name of its own",
      "draft MY next message to the agent" in HTML)
check("C2 the name is passed as the control's title",
      "title: emptyTitle || \"\"" in HTML)
check("C3 genBar uses that title for BOTH the tooltip and the accessible name",
      "const _idleName = opts.title ||" in HTML
      and 'btn.setAttribute("aria-label", t)' in HTML)
check("C4 the filled-state name still says it optimizes what was typed",
      "optimize what I typed" in HTML)

ok = sum(1 for r in results if r)
print("\n%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
