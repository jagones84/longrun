# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/`. No external
tracker, no `gh`/`glab` — a solo, local-first convention that matches Longrun's
"the code is the source of truth" posture.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`, never a single combined tickets file
- Triage state is recorded as a `Status:` line near the top of each issue file
- Comments and conversation history append to the bottom of the file under a `## Comments` heading
- Tracer-bullet tickets also carry a `Blocked by:` line: the numbers/titles that must complete first (`None (can start immediately)` when there are none)

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` (the Notes / Decisions-so-far / Fog body).
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`grilling`/`task`); a `Status:` line records `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every file it lists is `resolved`.
- **Frontier**: scan `.scratch/<effort>/issues/` for files that are open, unblocked, and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.

## Notes for Longrun

- `.scratch/` is **gitignored**, like `.agent/`: the tracker is one run's working
  plan, not shipped source. Write tickets there freely; they never reach a clone.
  What a run ships is the tracked docs it produces (`GLOSSARY.md`, `docs/adr/`,
  `CODING_STANDARDS.md`) — those are deliverables and are committed normally.
- A ticket that changes `src/` must respect `CONTRIBUTING.md` (the gate is
  `bash tests/battery.sh`; new acceptance tests are `tests/acceptance/vNNN_topic.py`).
