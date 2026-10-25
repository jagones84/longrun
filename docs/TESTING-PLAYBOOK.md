# Longrun — Harness Testing Playbook

How we test the harness **the smart way**: drive the real thing, distrust the happy
path, and verify the seams (reload, session swap, concurrent turns, topic pivot).
Written down so a future session does not have to rediscover it.

> Origin: this file exists because driving the live WebUI (not just unit tests) is
> what surfaced the real bugs — truncated observations (JAG-181), the unreachable
> subagent + stale-plan hijack (JAG-189), and the "reload eats the chat"
> regression (JAG-190). Static tests were green the whole time.

---

## 1. Ground rules (the mindset)

1. **Evidence over belief.** Never say "works" without a number/proof: a DOM count,
   a session-JSON field, an HTTP status, a screenshot. If a claim has no evidence,
   it is a guess.
2. **Test the seams, not the straight line.** The bugs live in transitions:
   refresh, session switch, switching *while* a turn runs, a new message arriving
   *while* a plan is open, a big observation, a deleted session, an approval.
3. **Drive the app through its real controls.** Use Chrome DevTools MCP `fill` /
   `click` / keyboard actions on a disposable test session. Use `evaluate_script`
   only for read-only inspection; never call UI mutation functions from page JS.
4. **Know the three layers** (test all three, they fail independently):
   - **Static** — unit tests / the battery (`tests/battery.sh`).
   - **Runtime data** — the artifacts on disk, all RELATIVE TO THE DATA HOME
     (`~/.longrun/data`, resolved by `util/paths.py`; never inside the checkout):
     `sessions/<sid>.json`, `graphs/<sid>.json`, `runs/`, `edits/`, `events.db`,
     `offload/<sid>/`.
   - **Live UI** — the browser: DOM, console, network, screenshots (chrome-devtools MCP).
5. **Always restore state.** Delete throwaway sessions/test artifacts when done;
   never leave the harness polluted (that was itself a past complaint).
6. **Never test inside the harness repo.** Bind every live test session to a
   dedicated workspace under `/home/jagones/Repositories/TESTS/`
   (e.g. `TESTS/harness-e2e`) — **not** `Repositories/longrun`. Driving an
   agent/tool loop in the harness's own repo pollutes `data/`, risks edits to the
   source and muddies git state.
7. Before a browser reload, check `/api/chat/live` and the editor's dirty/save
   state. Never reload a page with an unsaved editor buffer.

---

## 2. The gate (run this first, after every change)

Static layer — the ONLY canonical regression set:

```bash
bash tests/battery.sh                          # FAST gate: ~12s, heavy tests skipped, PARALLEL
LONGRUN_BATTERY_FULL=1 bash tests/battery.sh   # FULL suite (~1min)
LONGRUN_BATTERY_JOBS=1 bash tests/battery.sh   # force sequential (debug a flaky test)
```

- `v183_chat_core` is the chat-loop contract test (LLM + tool gate mocked):
  normal turn, anti-loop (JAG-183), subagent delegation (JAG-189), stale-plan
  pivot (D), harness-card persistence (E).
- Also useful helpers in `trash/` (gitignored): `jscheck.sh` (extract + `node --check`
  the WebUI `<script>` blocks), `sf_push.sh`.

Green here is necessary, **not sufficient** — the battery was green while the live
chat silently lost its cards. That is why section 4 exists.

---

## 3. Live probes (copy-paste, read-only)

Run these in the authenticated tab via the chrome-devtools `evaluate_script` tool.
They are the "eyes" for the seams.

**A. DOM census + "what is hidden inside collapsed nodes"**
```js
() => {
  const log = document.getElementById('log');
  const inClosed = el => { let d = el.parentElement && el.parentElement.closest('details');
    while (d) { if (!d.open) return true; d = d.parentElement && d.parentElement.closest('details'); } return false; };
  const cards = [...log.querySelectorAll('.toolcard')];
  const ai = [...log.querySelectorAll('.msg.ai')];
  const nodes = [...log.querySelectorAll('details.tctree')];
  return { cards: cards.length, hidden_cards: cards.filter(inClosed).length,
           ai: ai.length, hidden_ai: ai.filter(inClosed).length,
           nodes: nodes.map(d => ({ id: d.dataset.id, open: d.open,
             st: d.querySelector('.st').textContent, kids: d.querySelector('.tc-kids').children.length })) };
}
```
> `hidden_* > 0` means a reload/regression is hiding turn content inside a collapsed
> todo node — the exact JAG-190 failure (measured 10 cards / 13 replies all hidden).

**B. Which server-side turns are running** (multi-session, background work)
```js
async () => await api("GET", "/api/chat/live")   // {active:[sid,...]}
```

**C. Session state in one shot**
```js
() => ({ selected: document.querySelector('.sess.active')?.dataset.sid || null,
         sessions: [...document.querySelectorAll('.sess[data-sid]')].map(d => ({
           sid: d.dataset.sid, t: (d.querySelector('.t')||{}).textContent,
           running: d.classList.contains('running') })) })
```

**D. Console + network** — `list_console_messages` (expect **zero error/warn**) and
`list_network_requests` (must show **no 404 churn**; watch for repeated
`/api/status` + `/api/approvals`).

**E. Static files on disk** — read `data/sessions/<sid>.json`: does `tool_cards`
contain the cards you just saw? (`todo.write` / `todo.update` / `subagent` cards
must be there, not only `shell`.) This catches "shown live, never persisted".

---

## 4. High-risk scenarios — what to try, what to watch

For each: **trigger → what to watch → pass criteria**. These are the seams that
have actually broken.

1. **Refresh after a turn.** → reload the tab; run probe A. Pass: `hidden_* === 0`
   and the card/reply/node counts match the pre-refresh counts. Watch: harness-action
   cards (`todo.write`, `todo.update`, `subagent`) must survive (they are usually the
   first to vanish).
2. **Refresh WHILE a turn runs.** In a disposable session, send through the composer
   with MCP `fill` + `click`, immediately reload that same test tab, then poll probes
   B + A. Pass: `/api/chat/live` still lists the session right after reload, and the
   final reply + cards appear without a second send (JAG-181 re-attach).
3. **Session switch away and back.** → click session B, then A. Pass: B is clean
   (0 cards/0 nodes), A is fully restored (counts equal to before). Watch: no
   cross-session bleed, no stale plan from A painted into B.
4. **Switch away DURING a running turn.** In a disposable test session A, submit via
   MCP controls, click B, wait, check probe B (`active` still contains A) and the A
   row has class `running`; click A again. Pass: the turn was NOT interrupted and its
   output is there on return (JAG-168). Never interrupt a user's active turn.
5. **Topic pivot with an open plan.** → with ≥1 open todo, send an unrelated
   question ("ignore the plan, answer …"). Pass: a direct answer, the plan is left
   untouched, and NO `CONTINUE — your TASK LIST still has …` is forced (JAG-189).
   Verify in `data/sessions/<sid>.json`: new injects of kind `continue` should not
   appear for that turn.
6. **Goal to completion.** In a disposable test session, submit `/goal <task>` via
   MCP controls. Pass: the current plan closes with evidence and the loop stops on
   `goal_reached`. A configured wall-clock cap, blocker, error, or Stop is explicitly
   incomplete, never completion. Watch `plan.stopped` and the persisted result.
7. **Two sessions, two turns at once.** In disposable sessions A and B, start a
   turn in A, switch to B, then start a turn in B. Pass: both streams stay
   independent; output never paints into the wrong log (JAG-168); both appear in
   probe B.
8. **Big observation (offload).** → a command with >6 KB output. Pass: the model
   gets a head+tail preview + a `FULL OUTPUT FILE: data/offload/<sid>/…` reference;
   nothing is truncated in the file (JAG-181).
9. **Approval gate.** → a `required` tool (e.g. `fs.write`). Pass: an inline
   Approve card appears, the turn does NOT freeze (bounded wait), and approving
   re-runs it. Watch: `pending`/`denied`/`executed` handling.
10. **Delete a session with artifacts.** → delete a session that has a graph /
    edits / offload. Pass: all artifacts removed (v177), UI drops the dead id, no
    404 churn afterwards (JAG-189/JAG-190).
11. **Slash commands / skills.** Use MCP controls for the `/` palette and a skill read.
    Pass: no raw JSON reaches the chat and the command is parsed, not sent as text.
12. **Model / provider swap + context meter.** → change model, run a turn. Pass:
    the `ctx` meter grows with real `prompt_tokens` and never lies (JAG-98/172).
13. **Responsive / small viewport.** → `resize_page` narrow. Pass: rail and panels
    collapse sanely, the composer row stays aligned (JAG-188).

---

## 5. Smells — the instant "something is wrong" tells

- Cards on screen but missing from `tool_cards` in the session JSON → live-only,
  will vanish on reload.
- `hidden_* > 0` in probe A → content trapped in a collapsed node.
- Console `400/404/500`, or the same `/api/status` poll erroring → endpoint/poll bug.
- `ctx` meter not growing after tool calls → observations not persisted to the prompt.
- A reply that is a PROMISE ("Procedo con…") with no tool run → act-don't-announce broke.
- The same tool card appearing twice → reload/live duplication.
- Output from session A in session B's log → cross-session bleed.
- Any raw `{"action": ...}` JSON visible in a chat bubble → JSON-leak guard broke.

---

## 6. Rules of thumb (being smart about it)

- **Reproduce through the actual UI**: fill the composer and click Send with DevTools
  MCP, or select `.sess[data-sid="…"]`. It exercises the real wiring; internal
  shortcuts can hide integration defects.
- **Measure before and after**, and report the numbers (cards, nodes, `active`).
- **Prefer a scripted async probe** that triggers + waits + measures in one call
  (fewer round-trips, no races): `const sleep=ms=>new Promise(r=>setTimeout(r,ms));`.
- **Read the artifact, not just the screen**: the session JSON is the ground truth
  for what was persisted vs merely streamed.
- **One scenario per probe**; if it fails, capture the decisive line (status, count,
  reason) and stop — do not pile on.
- **Clean up** throwaway sessions and stop stray turns (`POST /api/chat/abort`).

---

## 7. Regression invariants (keep these true)

- Exactly one `done` per turn; a reply is ALWAYS persisted (never an orphan user turn).
- The model's todo list is the single plan; `done` requires evidence.
- A new user message can always supersede a stale plan (no forced hijack).
- The subagent action is reachable from the model and returns its summary.
- Reload reconstructs the FULL turn (cards + injects + replies + nodes), nothing hidden.
- No 404s for "not yet created" graph endpoints; no polling a deleted session.
- Switching sessions never interrupts a running turn and never bleeds state.
