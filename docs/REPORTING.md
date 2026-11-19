# Proposal report — procedure and exact format

This file owns the **proposal report**: a report that proposes one or more changes to Longrun, ranks
them, or shows a diagram. It supersedes item 2 of `project_rules.md` §"Reporting to the operator" for
that case. Parts 1, 3, 4 and 5 of that section still apply (In short, What I checked, Your decision,
Order).

A bugfix with a known root cause uses the short report in `project_rules.md`. A proposal that needs a
decision, a ranking, or a diagram uses this file. When in doubt, this file wins.

This file enforces, and does not replace: §"Golden rule — gap analysis", §"Harmonise or break the
dependents", §"Optimize only what is measured", §"Single source of truth", §"Improvement cycle".

The workflow below is **general**: it applies to any codebase. The Longrun rules are the local
enforcement of the general stages, not a special case of them.


**Source of the method.** The method itself lives in the research archive
(`anchored-research` — not part of this checkout): the twelve fields, the
entropy ledger, the six-axis ranking, the R0–R5 evidence levels, fidelity and traceability, the
rounds rule, and the subject grammar for code, document, dataset, running system and docs site.
This file is the local enforcement for Longrun: it owns the branch, the battery, the forbidden
writes, the test numbering and the Longrun numbers. Where the two disagree on *fields*, the archive
contract wins; on *local values*, this file wins.

---

## 0. The five gates before a single line of the report is written

A proposal may not be reported until all five gates are passed. A missing gate invalidates the report.

| Gate | What it proves | Where the method lives |
|---|---|---|
| **G0 — Gap analysis** | the thing is not already done, or the missing part is named | `project_rules.md` §Golden rule |
| **G1 — Codebase study** | the change is located, and every consumer is known | this file §3 |
| **G2 — Self-interrogation** | the value, the entropy, the risk and the alternatives are answered | this file §4 |
| **G3 — Entropy ledger** | the codebase is not made worse for an unmeasured return | this file §5 and §8 |
| **G4 — Fidelity and adherence** | the source claim is preserved or adapted with a test, and the change fits the architecture | this file §3.3–§3.5 |

If a gate cannot be passed, the proposal is `parked` or `dropped`, and the report says why. It is never
sent as "probably fine".

---

## 1. Phase order (do not reorder)

The eight phases below produce the report. §1.1 is the lifecycle the report plans and tracks; the two
are not alternatives.

1. **Phase 0 — Source intake**: read the source, label every claim (§2).
2. **Phase 1 — Gap analysis**: DONE / PARTIAL / MISSING, with `file:line` or a grep (§3.1).
3. **Phase 2 — Codebase study**: the impact map, from grep, including tests, API and UI (§3.2).
4. **Phase 3 — Self-interrogation**: the battery in §4, answered in writing.
5. **Phase 4 — Ranking**: the rubric in §5, six scores per proposal.
6. **Phase 5 — Report**: the exact section order and block format in §6.
7. **Phase 6 — Verification gate**: the checklist in §7.
8. **Phase 7 — Persist**: save and link, §8.

Skipping Phase 1 or 2 turns a hypothesis into a proposal. Skipping Phase 3 or 4 turns a proposal into
an opinion.

---

## 1.1 The general source → codebase update pipeline (R0–R5)

The report is the decision artifact, not the whole workflow. The workflow that turns a source into an
adherent codebase update has twelve stages, and every proposal states the level it has reached.

| Stage | What it produces | Exit check |
|---|---|---|
| 0 Source | the source, its claims, its setting | every claim has a label and a page |
| 1 Appraisal | relevance, quality, replication status | the claim's evidence grade is A–D |
| 2 Fit | does the source's setting match ours? | the mismatch is named |
| 3 Gap | DONE / PARTIAL / MISSING | `file:line` or grep |
| 4 Codebase | impact map + architecture fit | every consumer known |
| 5 Solution space | reproduce / adapt / drop | at least two alternatives |
| 6 Fidelity | what is preserved, adapted, dropped | every claim has a disposition |
| 7 Reproduction | the claim on our data | R1 reached or the proposal is parked |
| 8 Plan | atomic tasks, tests, rollback | each task has an acceptance test |
| 9 Execution | code, tests, docs, config | targeted battery green |
| 10 Rollout | live check, observation, rollback trigger | the operator sees the result |
| 11 Record | decision record, traceability, handoff | the next run can retrace it |

Levels, stated in every proposal block:

| Level | Meaning | Evidence required |
|---|---|---|
| **R0** | claim extracted | source id + page |
| **R1** | reproduced on our data | one local experiment, with the baseline |
| **R2** | adapted to our codebase | a spike or a test that pins the adaptation |
| **R3** | integrated | code + tests + docs, battery green |
| **R4** | validated in use | a live check or a measured outcome |
| **R5** | observed over time | a post-adoption measurement, with the date |

A proposal may target R1 (research) or R3 (implementation). It may not claim R4/R5 before the evidence
exists. The report states `current level → target level`.

**General, not Longrun-specific.** The stages are the general method; the Longrun rules are one
instance: gap analysis is stage 3, harmonisation is stage 4, measure-first is stage 7, the plan is
stage 8, the battery is stage 9, the live check is stage 10, the handoff is stage 11.

### 1.2 The execution loop (stages 9–11, exact)

For each approved item, one at a time:

1. Write the **red test**: the behaviour, not the shape.
2. Minimal implementation; no unrelated cleanup.
3. Run the targeted battery; every consumer in the impact map is covered.
4. Restart the service only for a runtime change; verify the loaded code.
5. Live check (REST, CLI, rendered WebUI) and record the evidence.
6. Commit one item; flip the plan row to `CLOSED` with the hash.
7. Complete the decision record and the traceability matrix (commit, plan row).
8. Add the handoff entry.
9. Run the post-adoption audit at the horizon stated in the return; if the return did not materialize,
   open a new item with the evidence.

### 1.3 Definition of done for the codebase update

- [ ] Behaviour pinned by a test that fails before and passes after.
- [ ] Every consumer from the impact map updated; no broken import, no second truth.
- [ ] Config values in config, not in code.
- [ ] Failure mode explicit; the boundary fail-closed.
- [ ] Observability: the change is visible in the event log, the run record or the UI.
- [ ] Docs: architecture doc, README badge and plan row updated in the same commit.
- [ ] Rollback named and tested.
- [ ] Decision record completed; traceability matrix filled.
- [ ] Handoff entry with the commit and the proof.
- [ ] Post-adoption measurement scheduled or run.

---

## 2. Phase 0 — Source intake

- Read the whole source, not the abstract or the summary. Note the pages, tables and figures that carry
  a claim.
- Extract only claims that could become a change. For each, record: source id, page/section, the claim,
  and its label.
- Labels, mandatory:
  - `locally observed` — measured or tested in Longrun, with the command or test.
  - `first-party` — the source's own experiment, not reproduced here.
  - `benchmark-reported` — a number from another system on another benchmark.
  - `paper-only hypothesis` — an idea the source argues but does not measure.
- A paper claim is **never** written as a local fact. If it was not reproduced here, the report says
  `not verified`.
- A source that contributes nothing is still listed, with "contributed nothing". Never silently drop a
  source.

### 2.1 Tacit knowledge recovery

Papers leave out what the authors knew. Before proposing, recover it explicitly and write it in the
report: dataset version and split, preprocessing, hyperparameters and search ranges, seeds and
repetitions, hardware, evaluation script and metric implementation, failure cases, and the code the
authors actually ran. If a detail is unavailable, write `unavailable — assumption: <x>` and mark the
claim's fidelity as reduced. Never fill a gap silently. ([6][8]; see §11.)

### 2.2 Semantic drift

An adaptation can be executable and still diverge from the source's meaning. This is *semantic drift*:
the code runs, the number looks plausible, and the mechanism is not the one the paper describes.
Prevent it with a claim-level test and a fidelity ledger, not with a whole-paper "it runs" check.
([7][9]; see §11.)

---

## 3. Phase 1 and 2 — Gap analysis and codebase study

### 3.1 Gap table (Phase 1)

One row per candidate:

| Candidate | Source claim | Where it would live | Verdict | Evidence |
|---|---|---|---|---|
| short name | one line, labelled | module or surface | DONE / PARTIAL / MISSING | `file:line` + test, or the grep |

Rules:

- **DONE** = a real implementation, with `file:line` and the test that pins it. Do not re-propose.
  If it looks regressed, open a new id with evidence; never reopen silently.
- **PARTIAL** = something exists; name the missing part in one line.
- **MISSING** = show the grep that proves absence: `grep -n "<symbol>" -r src/ webui/ benchmarks/ tests/`
  and the empty result.
- If the location cannot be found: `location not found — grep <term> before planning`. Never invent a
  file or a function.
- A KB or paper hit about Longrun is not evidence. The live `src/` is the only truth.

### 3.2 Impact map (Phase 2)

For every symbol, config key, field, event or endpoint the change touches:

1. **Owner**: the definition (`file:function` or `file:line`).
2. **Callers and consumers**: every hit in `src/`, `webui/`, `benchmarks/`, `tests/`, `config/`, `docs/`.
3. **Classify**: owner / caller / consumer / test / doc / dead.
4. **Must change in the same commit**: the list. Dead hits are removed, not kept "for safety".
5. **Two truths check**: a copied value, a second lookup, a duplicated owner, a parallel path. If the
   change adds one, stop or merge it into the existing owner.
6. **Blast radius**: hot path (every turn, every run, every page load), safety gate, shared object,
   daily surface.
7. **Data already available**: does the change need new collection, or does the run record / contrast /
   ledger already carry it? Cite `file:line`.
8. **Rollback**: revert, config flag, checkpoint, migration? Name the exact one.
9. **Test that will pin it**: the existing test file plus the planned new test id.

The impact map is the report-side of §"Harmonise or break the dependents". It is not a second
description of it.

### 3.3 Fidelity ledger

One row per source claim that the proposal adopts:

| Claim (source id, page) | Source setting | Our setting | Disposition | Why | Test that pins it |
|---|---|---|---|---|---|
| one line | benchmark, model, data | our benchmark, model, data | preserved / adapted / dropped | one line | test id or `not tested` |

Rules:

- Every adopted claim has a disposition. A dropped claim says why.
- An adapted claim names the adaptation and the boundary of validity.
- A claim with no test is `not tested`, never "verified".
- The ledger answers "did we implement the paper, or something that looks like it?".

### 3.4 Traceability matrix

One row per change, so a later reader can retrace the chain without guessing:

| Source claim | Gap verdict | Proposal | Task | Test | Commit | Plan row |
|---|---|---|---|---|---|---|
| id + page | DONE/PARTIAL/MISSING | letter | task id | test file | hash (after execution) | plan item |

Rules:

- No orphan claim: every adopted claim appears.
- No orphan test: every new test points at a claim or a behaviour.
- The matrix is embedded in the codebase or the plan ([11]: traces embedded in the codebase do not
  degrade silently; external traces do).
- The commit and plan row are filled at execution time; the proposal stage leaves them blank.

### 3.5 Architecture adherence gate (pass/fail)

A proposal does not enter the report unless it passes every line, or names the exception and why:

- **Boundaries**: the change lives in the module that owns the concern; no new cross-layer import.
- **Ownership**: one owner for each symbol, config key and event; no second lookup.
- **Dependency direction**: the change does not invert an existing dependency.
- **Naming**: the vocabulary matches the existing module; no synonym for an existing object.
- **Configuration**: no hardcoded path, model, threshold or secret; use the config owner.
- **Errors**: the failure mode is explicit; the default is fail-closed at the boundary.
- **Observability**: the change can be seen in the event log, the run record or the UI; no silent state.
- **Performance**: the hot path is measured or untouched; no unmeasured cost.
- **Security**: no new access, no secret in a prompt, no shortcut to evaluation data.
- **Accessibility** (UI): names, contrast, keyboard, reduced motion.
- **Docs**: the architecture doc, the README badge and the plan row are updated in the same commit.
- **Tests**: a deterministic test pins the behaviour, not only the shape.
- **Rollback**: a named revert, flag or checkpoint.

If a line fails, the proposal is `parked` with the failing line, not sent as "small".

### 3.6 Reproduction plan (the minimal experiment)

Before integrating a paper claim, define the smallest experiment that would show it holds on our data:

- the claim being tested, in one sentence;
- the baseline and the treatment;
- the metric and the threshold that would falsify it;
- the cost (tokens, minutes, money) and the sample size;
- the result: `R1 reached`, `not reached`, or `not run`.

A proposal that cannot afford the reproduction is a hypothesis, not an implementation. Say which.

---

## 4. Phase 3 — Self-interrogation battery

Answer the **[MUST]** questions in writing. Answer the rest in one line each. Put the answers in
**Appendix A** of the report, in this order, so the main page stays readable.

### A. Problem and evidence

1. **[MUST]** What exactly breaks or is wasted today, and who feels it? One sentence, operator terms.
2. **[MUST]** Is it already solved? Give the gap verdict and `file:line`.
3. **[MUST]** Is the evidence local, first-party, benchmark-reported, or a paper-only hypothesis?
4. What happens if we do nothing for 90 days? Is the cost growing or flat?
5. Is this a symptom of a different defect (missing owner, second truth, stale config)?
6. Can the problem be reproduced deterministically? If not, why not?

### B. Value and return

7. **[MUST]** What is the expected return, as a measurable outcome and a horizon? Not "better".
8. Who benefits daily: the operator, the agent, the maintainer? How often?
9. What is the smallest version that proves the value? Can it be report-only?
10. What result would falsify the claim and make us drop it?
11. Is the value already reachable through a config change or an existing tool? Name the cheaper path.
12. Is this a frontier capability or hygiene? Both are valid; say which.

### C. Entropy and cost

13. **[MUST]** What does it add: files, public symbols, config keys, API endpoints, events, UI
    surfaces, states, branches, dependencies, tests?
14. **[MUST]** Does it create a second truth: a copied value, a second lookup, a duplicate owner, a
    parallel path?
15. Does it add a concept the operator must learn? Can it reuse an existing one?
16. Does it touch the hot path? What is the measured cost? If not measured, say `not measured`.
17. Is the codebase simpler or more complex after it? What can be deleted in the same change?
18. Is the maintenance surface worth the return? State the net in one sentence.
19. Does the test pin behaviour, or only the new shape? Prefer behaviour.
20. Does it create a state that can go stale, or a branch that can rot?

### D. Placement and feasibility

21. **[MUST]** Where does it belong: config value, skill, tool, rule, module, or UI? Why not the
    cheaper one?
22. **[MUST]** What existing hook, field or data can it use? `file:line`.
23. What must be built from zero? Is that the minimum?
24. Does it require a model call, a benchmark, or network? Is that allowed now? See the benchmark
    policy.
25. Is it reversible? Name the rollback.
26. Can it be behind a config flag, or is the flag itself entropy? Prefer no flag when the change is
    safe.
27. Does it work on the DGX (ARM64) and on a fresh install?
28. Does it preserve the production contract (service restart, data home, no secrets in prompts)?

### E. Safety and failure

29. **[MUST]** What can break: promotion gate, sealed held-out check, approval gate, tool policy, UI
    truth?
30. What happens on bad input, missing config, a crashed subprocess, a rate limit, a partial write?
31. Does it widen what the agent can do or see? Is the approval path intact?
32. Does it introduce a shortcut to evaluation data (labels, tests, hidden files)?
33. Does it make a silent failure possible? How is it surfaced?
34. Is the default fail-closed at the boundary?

### F. Dependencies and blast radius

35. **[MUST]** What depends on it? The impact map, from grep.
36. What must change in the same commit, or the build breaks?
37. Does it depend on another proposal? Which, and why?
38. Does it conflict with an open plan item? Cite the id and status.
39. Does it duplicate a closed item? Cite the hash and test; do not reopen silently.
40. Does it need a migration or backfill? Is that a second project?

### G. Measurement and proof

41. **[MUST]** What is the proof it works: test, live check, benchmark, or screenshot?
42. Which deterministic gate runs it (battery test id)?
43. Which live check runs it (REST, CLI, rendered WebUI)?
44. What is the baseline and the after? Is n=1? Say so.
45. What does the proof cost (tokens, minutes, money)?
46. If the proof fails, what is the next action: fix, park, drop?

### H. Alternatives and non-goals

47. **[MUST]** What are the two or three alternatives, including "do nothing"?
48. Why is the chosen one better? State the trade-off.
49. What is explicitly out of scope?
50. What will a reviewer attack first? Answer it in the report.

### I. Decision and ranking

51. **[MUST]** What is the rank score and why? Show the six scores in §5.
52. What is the tie-break: impact, then reversibility, then lower entropy?
53. What is the decision the operator must make, one-word answerable?
54. What is the order, with one reason per position?

### J. Source-to-code transfer

55. **[MUST]** Does the source's setting match ours: model, data, benchmark, harness, budget, failure
    distribution? Name the mismatch.
56. **[MUST]** What is the claim, exactly, in one sentence that a test could falsify?
57. What is the minimal reproduction (R1), and what does it cost?
58. Which details are missing from the paper (tacit knowledge), and what is the assumption for each?
59. What is adapted, and what is the boundary where the adaptation stops being valid?
60. What is the fidelity grade of the evidence: A reproduced here, B first-party with code/data,
    C benchmark-reported, D paper-only?
61. What is the risk of semantic drift: where could our code run but mean something else?
62. Does the source's gain survive a matched baseline and a matched budget?
63. What would the authors say we got wrong? Answer it in the report.
64. Which part of the claim can be tested without a model or a benchmark? Do that first.
65. If the reproduction fails, is the proposal dropped, or is the claim parked with the evidence?
66. Does the adaptation add a second mechanism, or replace one? Prefer replace.

### K. Codebase adherence

67. **[MUST]** Which module owns this concern today? Does the change live there?
68. Does it invert a dependency, cross a layer, or create a cycle?
69. Does it use an existing name, or invent a synonym?
70. Is every path, threshold, model and secret in config, not in code?
71. Is the failure mode explicit, and is the boundary fail-closed?
72. Can the change be seen in the event log, the run record or the UI?
73. Is the hot path measured or untouched?
74. Does it widen access, leak a secret, or shortcut evaluation data?
75. Is there a deterministic test for the behaviour, not only the shape?
76. Is the rollback named, and is the documentation updated in the same commit?

---

## 5. Phase 4 — Ranking (exact rubric)

Score every proposal on six dimensions, 1–5. Show the six numbers; never only the total.

| Dimension | 1 | 5 | Direction |
|---|---|---|---|
| **Impact** | never felt | every turn / every run | higher is better |
| **Evidence** | paper only | locally measured + test | higher is better |
| **Reversibility** | irreversible / migration | one-line revert | higher is better |
| **Entropy** | removes a concept or a truth | adds many concepts / a second truth | lower is better |
| **Blast** | isolated report | hot path + safety gate | lower is better |
| **Depends** | standalone | needs three or more items first | lower is better |

`Priority = (Impact + Evidence + Reversibility) − (Entropy + Blast + Depends)`

Range: −12 to +12. The number is a forced-ranking aid, not a measurement.

Hard overrides, applied before the total:

- A proposal that adds a **second truth** or weakens a **safety gate** cannot rank above a proposal that
  removes entropy, whatever the total.
- A proposal with **no measurable return** cannot rank first.
- A proposal whose proof needs a paid benchmark ranks after every item whose proof is deterministic,
  unless the operator asked for the benchmark.
- A proposal that depends on another cannot rank above its prerequisite; the prerequisite's position is
  set by the dependency, not by its score. State this in the "Why this position" cell.

Tie-break order: higher impact, then higher reversibility, then lower entropy, then lower dependency.

Ranking table, exact columns:

| Rank | # | Proposal | Impact | Evidence | Reversible | Entropy | Blast | Depends | Total | Why this position |
|---|---|---|---|---|---|---|---|---|---|---|

The "Why this position" cell is one line, in operator terms. No narrative elsewhere.

---

## 6. Phase 5 — Report format (exact)

The report is one self-contained page. HTML is preferred (it carries Mermaid and the tables); Markdown
is allowed when no diagram is needed. The sections appear in this order, with these headings:

0. **Header** — title, date, source ids, base commit, one-line verdict.
1. **The decision asked** — one line, one-word answerable.
2. **The map** — one Mermaid diagram of the loop or system. Every changed node is labelled
   `Stage` + `<br/>` + `Letter · proposal title`. Every unchanged node says `no change`. Immediately
   after the diagram, a text table `stage → proposal → what changes`.
3. **The dependency map** — one Mermaid diagram. Every dependency edge carries a plain-language label
   (`needs the number first`, `needs the archive`). Immediately after it, the dependency table:
   `changed object → consumers to update → proof`.
4. **The proposals** — one block per proposal, in **rank order**. Each block has exactly these fields,
   in this order:
   1. **Rank + title** — the object that changes, not the benefit.
   2. **Status** — `new | carried | expanded | narrowed | superseded | parked`.
   3. **Problem today** — operator terms, one sentence.
   4. **Change** — one imperative sentence.
   5. **Subject of change** — objects/functions with `file:line`; one clause for what is NOT touched.
   6. **Impact map** — consumers to update in the same commit; the grep evidence; or
      `no other consumer found (<grep>)`.
   7. **Why it can be done** — existing hook/data/test/rollback, with `file:line`.
   8. **Expected return** — measurable outcome, horizon, who benefits.
   9. **Entropy ledger** — what it adds, what it removes, verdict `reduces | neutral | adds-low |
      adds-high`, and the net in one sentence.
   10. **Evidence and level** — `[n]` citation(s) + local proof + `current R-level → target level`;
       `not verified` when applicable.
   11. **Size / risk** — `small | medium | large` + what can break.
   12. **Depends on / blocks** — proposal ids, or `none`.
5. **The ranking table** — the six scores, the total and the one-line reason.
6. **The entropy ledger (summary)** — one row per proposal: category counts (files, symbols, config
   keys, API, UI, events, states, branches, dependencies, second truths), verdict, net sentence.
7. **Reconciliation** — every prior proposal: id, `valid | expanded | narrowed | superseded | dropped`,
   and why. Closed plan items cited with hash + test are not reopened.
8. **Dropped / parked** — with the reopen condition.
9. **What was checked / what was not** — two lines. Never claim more than was run.
10. **Decision** — the exact question(s), one-word answerable, plus "plan or stop".
11. **Order** — the build order, one dependency reason per position.
12. **Bibliography** — numbered `[1]`…`[n]`, one hyperlinked entry per source; every number used in
    the report appears here.
13. **Footer** — commit, audit result, date.
14. **Appendix A — self-interrogation answers** — the questions from §4, answered.
15. **Appendix B — fidelity ledger and traceability matrix** — the formats in §3.3 and §3.4.
16. **Appendix C — decision record** — the format in §6.3, drafted at proposal time and completed at
    execution.

### 6.1 Diagram rules (exact)

- A node label carries the proposal **title**, never a bare letter. The letter is an index, not an
  explanation.
- An edge that represents a dependency carries a label in plain words. Unlabelled edges are only the
  normal flow.
- Immediately after every diagram, the same information is repeated in a table. The diagram is never
  the only carrier of a fact.
- Maximum two diagrams: one "where it lands", one "what depends on what". More means split the report.
- Readable at 100% zoom on a 1440px screen. If not, split it.
- Mermaid: short labels, `<br/>` for line breaks, quote labels containing punctuation, only `<b>` and
  `<br/>` as HTML. Validate the source before sending.
- If the renderer is unavailable, the `<pre>` source and the adjacent table still explain the diagram.

### 6.2 Text rules

- No unexplained acronyms. No bare ids. An internal name is glossed in the same line.
- Bad news first, with its strongest evidence in the same paragraph.
- Say what the operator loses or gains, never what the code contains.
- A table is allowed only when every row is a decision or a thing to do.
- Raw measurements belong in `.agent/`; the report gets one plain-language sentence.

### 6.3 Decision record (draft at proposal time, complete at execution)

```
Decision: <title>
Status: proposed | accepted | rejected | superseded
Context: <problem, source claim, constraints>
Decision: <what will change, and what will not>
Alternatives: <option -> why rejected>
Consequences: <expected return, entropy added/removed, risks>
Evidence: <source ids, local proof, R-level>
Rollback: <named revert / flag / checkpoint>
Traceability: <matrix row ids>
Date / commit: <filled at execution>
```

The decision record is the ADR that survives the report. It is written in the plan or next to the
module, not only in the chat.

### 6.4 Citations and bibliography (exact)

Every proposal and every quantitative claim carries a numbered citation. The number is the key; the
bibliography at the end of the report is the only place where the link lives.

- Inline: `[1]`, `[2]`, ... numbered by first appearance in the report. A claim with two sources uses
  `[1][2]`; a range is `[1]–[3]`.
- Every proposal block's **Evidence and level** field starts with its citation numbers.
- Every fidelity-ledger row carries the citation in the claim cell.
- The traceability matrix has a **Source** column with the citation number.
- The bibliography is a numbered list, one entry per source, with author(s) when known, title, id, and a
  clickable URL. The agent must be able to open the source from the report during implementation.
- Local code evidence is `file:line`, not `[n]`; it may sit beside a citation.
- No orphan number: every `[n]` has an entry; every entry is used at least once.
- No uncited claim: a sentence without `[n]` and without `file:line` is `not verified`.

Bibliography format:

```
[1] Author(s). *Title*. arXiv:2611.07624. https://arxiv.org/abs/2611.07624
[2] ...
```

---

### 6.5 Rounds — a second proposal on the same topic

A proposal for a topic that already has a report is a **round inside that report**, never a second
page. The rule exists because a parallel page duplicates the bibliography, the ranking and the
entropy ledger, and the two copies then disagree about the rows they share.

- **Where**: the same file, a new section `## N · Round <n> — <date> (proposals X, Y, Z)` placed
  immediately after the existing proposal blocks, so a reader meets both rounds before the ranking.
- **What it carries**: the new proposal blocks in the same twelve-field format, a ranking table for
  the new rows only, a reconciliation table that names the status of every prior row it touches, the
  decision, and one line naming the plan file that executes it.
- **What it does not repeat**: the bibliography (it adds only the new `[n]` keys, numbered after the
  last one), the ranking of rows already ranked, and Appendix A (the self-interrogation belongs to
  the round that wrote it). Appendix B is extended only with the new traceability rows.
- **Decision state**: the decision section gains one line per round. The page must never hold two
  contradictory states; a later round that changes an earlier answer edits that line and says when.
- **Withdrawal**: a proposal that a round cancels is marked `superseded` in its own block and kept.
  Deleting it destroys the reason the round exists.
- **When a new page is right**: only when the topic is a different artifact or a different question.
  "Round 2 of the same question" is not a new page.


## 7. Phase 6 — Verification gate (checklist before sending)

- [ ] Every proposal has all 12 fields of §6, item 4, in order.
- [ ] Every DONE item is cited with `file:line` and its test; no DONE item is re-proposed.
- [ ] Every PARTIAL/MISSING has `file:line` or the grep that proves absence.
- [ ] Every changed symbol has its consumers listed, or `no other consumer found (<grep>)`.
- [ ] The two truths check is answered for every proposal.
- [ ] The ranking table's totals match the six scores; the hard overrides were applied.
- [ ] Every proposal has an entropy verdict and a net sentence.
- [ ] Every diagram has a text table immediately after it; every node carries a title, not only a letter.
- [ ] The Mermaid source is valid and the fallback is readable.
- [ ] The prior proposals are reconciled; no closed item is reopened silently.
- [ ] The decision is one-word answerable.
- [ ] "What was checked / what was not" is honest.
- [ ] Every proposal states `current R-level → target R-level` and the evidence for the current level.
- [ ] The fidelity ledger covers every adopted claim; no orphan claim, no orphan test.
- [ ] The traceability matrix has a row per change; commit and plan row are blank until execution.
- [ ] The architecture adherence gate passes, or the failing line is named and the proposal is parked.
- [ ] Every proposal starts its evidence with `[n]`; every quantitative claim has `[n]` or `file:line`.
- [ ] The bibliography has a working hyperlink for every `[n]`; no orphan number.
- [ ] The decision record is drafted.
- [ ] The report is saved and linked with `computer://`.

If any box is unchecked, the report is not sent.

---

## 8. Phase 7 — Persist

- Save at `.agent/docs/proposals/YYYY-MM-DD_<topic>.html` (self-contained; Mermaid from CDN or inline
  SVG; no other external asset).
- Link it in the chat with `computer://`, with human-readable text.
- If the operator approves an item, write `.agent/docs/plans/YYYY-MM-DD_<topic>.md` and register it in
  `.agent/docs/plans/longrun-upgrade-master.md` in the same session.
- Do not duplicate the report in two places. The HTML is the artifact; the chat is a summary.

---

## 9. Worked example (the exact shape, short)

```
Rank 1 · A · Report gains, losses and cost            [new]
Problem today   A change that fixes ten tasks and breaks nine reads as a small win.
Change          Add tasks gained/lost vs baseline, coverage, tokens and dollars per solved task.
Subject         benchmarks/lhb_compare.py:_aggregate · benchmarks/compare.py:verdict
                NOT touched: scoring, thresholds, gates.
Impact map      _report, compare.main, benchmarks/README.md, v831, v837, v667
                no other consumer found (grep "_aggregate").
Why it can do   the per-task rows and the baseline already exist (lhb_compare.py:300-332).
Return          the operator sees churn and cost per change; no new state.
Entropy         neutral: 0 files, 0 config keys, 2 report builders, 0 second truths.
Evidence        2611.07624 Table 1 + Fig. 2 (first-party); Evolver −24.24% tokens (first-party);
                not verified locally.
Size / risk     small; report only.
Depends / blocks none. Blocks E.
R-level         R0 → R3 (the report is the implementation; no paper claim adopted).
Fidelity        claim 1 (churn) preserved; claim 2 (token delta) adapted to our run record; R1 not run.
Traceability    claim 1 → gap A → proposal A → task A.1 → test vNNN → commit (blank) → plan row (blank).
```

Ranking row:

| Rank | # | Proposal | Impact | Evidence | Reversible | Entropy | Blast | Depends | Total | Why this position |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | A | report gains, losses, cost | 4 | 3 | 5 | 2 | 1 | 1 | 8 | no gate change; makes the rest checkable |

---

## 10. Anti-patterns (the report is wrong if any of these is true)

- A diagram of letters, with the text far below.
- A proposal with no consumer list, justified by "it's small".
- A ranking without the six scores, or with a total only.
- A paper claim presented as local evidence.
- A "small" change that adds a second truth or a new gate bypass.
- A report that lists DONE items as new work.
- A report that hides the rollback.
- A report that asks "should we?" without a measurable return.
- A report that grows the codebase without saying what it deletes.
- A claim with no `[n]` and no `file:line`.
- A bibliography with dead links, or a `[n]` with no entry.
- A report that adds a config flag to avoid deciding, when the decision is safe.

---

## 11. Bibliography (numbered, hyperlinked)

[1] Xiaobo Wang et al. *Beneath the Surface: What We Overlook When We Talk About Agent Evolution*.
arXiv:2611.07624. https://arxiv.org/abs/2611.07624

[2] Haoyang Zhang et al. *Evolver: Turning Agent Exploration into Evolving Capabilities*.
arXiv:2611.07595. https://arxiv.org/abs/2611.07595

[3] Sen Yang et al. *Reglos: A Self-Evolving Personal Memory Agent with Recursive Self-Improvement*.
arXiv:2611.06049. https://arxiv.org/abs/2611.06049

[4] Tianqi Gao et al. *DualEvolve: Dual-Level Self-Evolution of Mechanism and Orchestration for
Recommendation*. arXiv:2611.04439. https://arxiv.org/abs/2611.04439

[5] Zixiao Zhao et al. *Validation-Gated ML Pipeline Synthesis with Expert-Grounded Self-Evolving
Skills*. arXiv:2611.04180. https://arxiv.org/abs/2611.04180

[6] *What Papers Don't Tell You: Recovering Tacit Knowledge for Automated Paper Reproduction*.
arXiv:2603.01801. https://arxiv.org/abs/2603.01801

[7] *SA-Bench: Evaluating Semantic Alignment in LLM-Based Paper Reproduction*. arXiv:2608.24252.
https://arxiv.org/abs/2608.24252

[8] *From paper to benchmark: agentic, framework-based reproduction of under-specified methods*.
arXiv:2605.28371. https://arxiv.org/abs/2605.28371

[9] *Reflective Paper-to-Code Reproduction Enabled by Fine-Grained Verification*. arXiv:2508.16671.
https://arxiv.org/abs/2508.16671

[10] *Enhancing Automated Paper Reproduction via Prompt-Free Collaborative Agents*. arXiv:2512.02812.
https://arxiv.org/abs/2512.02812

[11] *ReqToCode: Embedding Requirements Traceability as a Structural Property of the Codebase*.
arXiv:2603.13999. https://arxiv.org/abs/2603.13999

[12] *Auxiliary Artifacts in Requirements Traceability: A Systematic Mapping Study*. arXiv:2504.19658.
https://arxiv.org/abs/2504.19658

[13] *Replications, Revisions, and Reanalyses: Managing Empirical Evidence in Software Engineering*.
arXiv:2609.05983. https://arxiv.org/abs/2609.05983

[14] *Evidence-Based Software Engineering*. https://ebse.webspace.durham.ac.uk/

[15] *Spec-Driven Development: From Vibe Coding to Structured AI Execution*.
https://productbuildershq.com/papers/spec-driven-development.pdf

[16] *What Is Spec-Driven Development? A Complete Guide*.
https://www.augmentcode.com/guides/what-is-spec-driven-development

[17] *How to Make Architecture Decisions: RFCs, ADRs, and Getting Everyone Aligned*.
https://www.lukasniessen.com/blog/149-architecture-decision-process/

[18] *RFC checklist*. https://bestpractice.unisbadri.com/en/team_management/rfc/

[19] *Engineering design docs*. https://designdoc.hashnode.dev/the-ultimate-guide-to-engineering-design-docs.md

[20] *Flowcharts — basic syntax*. https://mermaid.js.org/syntax/flowchart

[21] *Flowchart best practices*. https://www.simplemermaid.com/blog/flowchart-best-practices.html

[22] *Technical debt ratio*. https://www.trificient-digital.com/post/technical-debt-what-it-is-how-to-measure-it-and-what-it-s-costing-your-business

[23] *Modularity and architecture debt*.
https://synchronium.github.io/software-architecture-wiki/concepts/modularity.html
