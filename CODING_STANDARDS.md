# Longrun — Coding Standards

**Who reads this:** the **review** agent, and a human reviewer. It is the list of
*judgement calls* — the rules no tool can check for you.

**What is deliberately NOT here:**

- **Mechanical rules** — unused imports, unused variables, undefined names, syntax —
  are enforced by the guardrail: `bash scripts/check.sh`. Never restate one here; if a
  rule can be decided by a program, add it to the guardrail instead (see `CONTRIBUTING.md`).
- **Architectural decisions** live in `docs/adr/`. This file does not overrule them.
- **Process** — branching, releases, the PR loop — lives in `CONTRIBUTING.md`.
- **Vocabulary** lives in `GLOSSARY.md`.

Every rule below is a judgement call, so each one says *what it is* and *why it exists*.

## Language and naming

- **English only** — code, comments, docstrings, log messages, UI strings and commit
  messages. The repo is read by shared agents and by contributors; a second language
  taxes every read and every search.
- **One concept, one word.** Use the term `GLOSSARY.md` defines and respect its `_Avoid_`
  list. Do not introduce a synonym for a concept the project already names — synonym
  drift (`job` vs `task`, `run` vs `turn`) is the single largest navigability tax this
  codebase pays.

## Interfaces

- **Explicit type hints and structured docstrings on functions.** The reader is often an
  agent with a small context window; the annotation *is* the interface. mypy runs in a
  lenient ratchet, so this is a judgement call, not a check — treat a missing annotation
  on a public function as a review finding.
- **Prefer a deep module: a lot of behaviour behind a small interface.** If a caller must
  know several facts to use a function correctly, the interface is too wide — hide the
  complexity inside, or move the seam. (Vocabulary: `docs/adr/0004`.)
- **Accept dependencies, don't create them; return results, don't produce side effects.**
  A module that reaches for its own collaborators cannot be tested through its interface.

## Change shape

- **A module changes for one reason** (divergent change), and **one logical change does
  not force edits across many files** (shotgun surgery). If either is happening, gather
  what changes together into one module *before* making the change.
- **Make the change easy, then make the easy change.** Prefactor first; a refactor that
  lands green on its own is what lets the next change land green too.
- **Comment the why, not the what.** Record the constraint, the measurement or the
  rejected alternative — the repo's own style is a dated piece of evidence
  (*"measured 2026-11-10: the first call of each turn was 100% uncached"*), never an
  adjective.

## Behaviour at the boundary

- **Fail open at the harness boundary; fail loud in the core.** An extension point
  (Matrix, a hook, a plugin) must be wrapped so a broken extension is reported and
  skipped, never allowed to crash the harness. Code that *owns* a fact must raise rather
  than silently substitute a default.
- **Evidence over belief.** A claim in a PR or a report carries a number — a test count,
  an HTTP status, a file field, measured characters — not an assertion. "It works" is not
  evidence; `939/952` is.
- **Never discard another contributor's work.** Inspect `git status` and the diff before
  restoring a file; never use `git reset --hard`, `git checkout --` or `git clean` over a
  dirty worktree.
