# UserPrompts.md — concise development manual from operator prompts

Raw chat prompts are never pasted here. Each section is the distilled
normative spec those prompts contained, in English (the product is
English-only). Partial by construction: a section lands here only when the
operator stated a rule that holds for the WHOLE app. One-off fixes and
workflow notes stay in `HANDOFF.md`; agent workflow stays in project rules.

How to rebuild from zero with this file: implement §1–§4 literally; every
MUST below is load-bearing. Dates mark when each rule was agreed.

## 1. Object identity — every id resolves against its owning store (2026-10-25)

Stores and their namespaces (single source of truth, no overlaps):

| Object | Store (truth) | Label | Example |
|---|---|---|---|
| Designated agent | roster (`/api/agents`) | `A<agent#>` | A49 |
| Chat session | session record (`JAG-169` number) | `J<session#>` | J155 = A49's session |
| Team job | jobs registry (`/api/jobs`) | `J<job#>` | J21 (registry only: J12–J22) |
| Subjob | parent job (`subjobs`) | `J<job>.<sub>` | J21.1 |
| Todo node | graph (`id` field is the ONLY key) | `<owner>.n<seq>` | A49.n40 |

1.1 Todo labels name the owner, resolved live: designated session goes to
its agent id (`A49.n40`); plain session goes to its own session number
(`J180.n87`); never a fabricated id, never a bare `A?` (v604).
1.2 The Plan header carries no session/job number: a bare `J155` prefix
read as a team job that does not exist (registry holds J12–J22). The run
id identifies the run; the session lives in the sidebar — roster `A49`
or honest `J189` (v606/v607). Kept: run-start goal label on moved-on
plans, 80-char word-boundary preview (v601/v602).
1.3 Per-row job context renders ONLY from node fields (`jid`/`subjob`);
goal prose never counts as structure (v602).
1.4 Node identity for resolution is the raw `id` (`n40`); display
prefixes MUST NOT leak into stored ids (JAG-194).
1.5 Session Jobs (`SJ<n>` / `SJ<n>.<k>`) live in `data/session_jobs/<sid>.json`
and die with their session; team jobs (`J<n>`) live in the registry. A
`batch` with subagent items becomes ONE SJ; a bare `subagent` spawn leaves
no SJ record (pinned, v611). `describe` falls back to the latest open job
on unknown id, never a traceback.
Rationale: `A155.n40` was a phantom — node `n40`, agent A49, session J155;
no A155 exists anywhere.

## 2. Navigation — one panel, one shared opener (2026-10-25)

2.1 Cross-panel "go to chat session" buttons in EVERY panel route
through the deck's shared `onOpenAgent` callback; rows carry the id, never
a second opener, no duplicated open logic (JAG-335/484, v600).
2.2 Row clicks must not leak through action buttons (`stopPropagation`);
destructive row actions confirm in place.
2.3 A J-chip in the RH Plan panel opens the TEAM job, not the todo: job
text from the same `GET /api/jobs/<id>` the Control deck renders, plus an
"open in Control Jobs" button that hands the deck the id via
`longrun-focus-job` (deck expands + scrolls + rings it, stacked board never
stolen). Job and subjob are different entities (J17 rings the job row, J17.4
its subjob row); ids are full store ids end to end, bare digits normalised
at lookup (v609/v610). Row click still shows the todo.
2.4 Batch lanes never mix: tool calls run inline, `subagent`/goal items
become the ONE Session Job, dispatches (any spelling, never a `subagent`
action) run as real turns in the peer session. A dispatch never becomes an
SJ subjob (v612). Inter-session chat validates first: missing args → 64,
unknown session → clean error, no self-send (v613).
2.5 Old plans delete in bulk, per session AND per team: graph nodes ARE
the plan (panel, model prompt and constellation read the one session
graph — nothing is display-only), so deleting clears all three at once.
One `✕ all` per session plus `Drop OLD plans…` in the deck team kebab;
the current plan, chats and agents are never touched — wiping everything
is the session reset (v614).
2.6 Permits are two systems, and FULL is only one of them: approval mode
FULL never bypasses the dual-permission gate — exclusive tools
(job/team/agent/session/webui/kb) need the per-session Teamorg grant
(session menu), decided AND worded by the ONE function both paths call.
Operator secret VALUES never reach the model: one scrub at the tool
execute choke point redacts them from every observation, so a stolen
token can't curl around the gate (v616).

## 3. Knowledge & research — web → notebook contract (2026-10-25)

3.1 Research is a backend capability (plan + executor + notebook
import), not an agent: it runs inline in the caller's turn with the
configured research model, and lands results as notebook sources.
3.2 Every research claim carries inline `[title](url)` citations plus
a link-only Sources section — in the researcher role brief AND in the
summary prompt. "Cited summary" is a contract, not a wish (v603).
3.3 The research model is operator-settable in Settings ▸ Models AND the
Knowledge panel picker (same `POST /api/research/model` writer, one truth,
documented in `config/index.yaml`); out-of-the-box default is
`local:default` (DGX router, no key needed), stored in the index overlay
(v609; was KB-picker-only defaulting to key-gated `perplexity:sonar-pro`).
Launch paths are Knowledge panel (manual discover / auto agent), `POST
/api/knowledge/research`, and `forge knowledge research`.
3.4 Search providers are an explicit ordered fall-through chain
(tavily → brave → duckduckgo, one function per provider), overridable via
`search_providers` in `config/index.yaml` or the per-call `providers`
argument; unknown names are ignored, a dead provider never kills the search
— never a single hardcoded call (v605).
3.5 Verified live 2026-10-25: search + fetch + import + notebook UI all
work (shallow run, 5 sources, zero console errors). The summary step needs
a LIVE model: no key or a retired catalogue id degrades it to the stub
`Research summary about: …` (observed: missing `PERPLEXITY_API_KEY`,
retired `openai/gpt-4o-mini-search-preview` 404). Keep catalogue ids live
and the default key present, or the "cited summary" contract of 3.2 is void.

## 4. Themes — completeness contract (2026-10-25)

4.1 Every theme ships FULL token sets in WebUI + Bridge + swatch
preview (text `Aa` + accent dot); light/dark counts and solid-aside
invariants are pinned by tests (v352/v364 evolved with each addition).
4.2 Pastels are backgrounds, never text; accents are darkened to WCAG
AA; dark themes use desaturated surfaces and off-white text.

## Admission criterion

A generic operator prompt becomes a section here only if it states a rule
that holds for the WHOLE app across sessions (identity, navigation, truth
sources, UI contracts). One-off fixes go to tests + CHANGELOG. Workflow goes
to project rules.
