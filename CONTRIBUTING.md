# Contributing to Longrun

Thanks for your interest! Longrun is a **stdlib-only** harness — that constraint is
deliberate and load-bearing, so please respect it.

## Ground rules

- **No third-party runtime dependencies.** The core (`src/longrun/`) imports only the
  Python standard library. New behaviour must not add a `pip` requirement to the core.
  The single exception is **PyYAML** (pure-Python), used only to read the shipped
  `config/*.yaml`; JSON configs work without it.
- **Keep it cross-platform.** Platform-specific code lives in `src/longrun/util/osutil.py`.
  No POSIX assumption may leak into the core — Longrun runs on Linux x86_64,
  Linux arm64/aarch64 (NVIDIA DGX Spark) and Windows x64 from the same code.
- **No secrets in the repo.** Keys live in a local `.env` / `~/.hermes/.env` (gitignored).
  `.env.template` is the only tracked env file.
- **Standards live elsewhere.** The judgement-call standards a reviewer enforces are in
  [`CODING_STANDARDS.md`](CODING_STANDARDS.md); the vocabulary is in [`GLOSSARY.md`](GLOSSARY.md);
  the hard-to-reverse decisions are in [`docs/adr/`](docs/adr/).

## Set up

Install and run instructions live in the [README](README.md) quick-start sections
(clone, then `./run.sh` on Linux or `.\run.ps1` on Windows — the launcher installs
PyYAML; secrets are entered in the WebUI and written to the gitignored `.env`). Then
verify your checkout:

```bash
bash tests/battery.sh          # FAST gate; reports the current pass count
```

## The loop

1. **Branch.** Short-lived, descriptive: `feature/…`, `fix/…`, `docs/…`, `refactor/…`, cut from
   the working branch (see [Branches and releases](#branches-and-releases)).
2. **Change one thing.** Keep PRs focused; ~100–300 lines is a good size.
3. **Test.** Add or update a test under `tests/acceptance/v<NNN>_<topic>.py` (the battery
   auto-discovers `tests/acceptance/v*.py`). Tests must be deterministic — no wall-clock
   races, no live model, no fixed data dirs (use `tempfile.mkdtemp()` and point every
   `LONGRUN_*` var at it).
4. **Run the gate.** `bash tests/battery.sh` must be **GREEN** before you open a PR.
5. **Commit** atomically with a typed message (`feat:`, `fix:`, `refactor:`, `test:`,
   `docs:`, `chore:`) explaining the *why*.
6. **Open a PR** using the template.

## Tests

Everything is stdlib Python — no framework, no network, no model for the gate.

```bash
bash tests/battery.sh      # the gate: all acceptance tests, isolated, deterministic
python3 tests/acceptance/vNNN_<topic>.py   # one test
pytest tests/properties/   # Hypothesis property tests
```

- `tests/acceptance/` — the live battery (`v140..`), auto-discovered; **add new tests here**.
- `tests/live/` — need a running server; run by hand.
- `tests/properties/` — Hypothesis over pure logic.
- `battery.sh` points every `LONGRUN_*` var at a throwaway `mktemp` dir, so a run never
  touches `data/` or the live transcripts.
- A test is `vNNN_topic.py`: it does `sys.path.insert(0, REPO/src)`, imports `longrun`,
  defines `check(name, ok, detail="")`, prints `PASS`/`FAIL` and exits non-zero on any `FAIL`.

## Guardrail (lint + types, in seconds)

Run this after an edit. It is the cheap deterministic check the battery is too heavy to be:

```bash
bash scripts/check.sh          # syntax + lint (ruff) + types (mypy)
bash scripts/check.sh --fast   # skip the slow mypy step
```

The mechanical rules it owns — the ones a reviewer no longer has to police:

- **syntax** — every file under `src/longrun/` must parse, and **no bytecode is left
  next to the source** (a stale `.pyc` has made a test assert on an old function body).
- **pyflakes class** (ruff `F`) — unused imports and variables, undefined names,
  redefinitions. This is the class of mistake that used to be caught only by the full battery.
- **types** (mypy, lenient) — it must not get *worse* (`--ignore-missing-imports`; only
  the modules named are reported).

It is a **ratchet**: the tree carries a known number of findings
([`scripts/guardrail-baseline.txt`](scripts/guardrail-baseline.txt)), so the check fails
only when a count **increases**. Lower a number when you pay findings down; never raise
one to make the check pass. Style/upgrade rules are deliberately **not** fatal yet — the
selection is `select = ["F", "E9"]` in [`pyproject.toml`](pyproject.toml), and widening it
is a later, deliberate step.

Wiring: CI runs `bash scripts/check.sh --require-tools`
([`.github/workflows/check.yml`](.github/workflows/check.yml)); an optional local hook is
[`.pre-commit-config.yaml`](.pre-commit-config.yaml). `tests/mega_test.sh` calls the same
script, so the static analysis has one definition.

## Branches and releases

- **`Experimental-Refactor` is the working branch.** Every change lands here and is pushed.
  A short-lived branch is cut from it, and merged back into it.
- **`master` is the backup branch.** It is NOT the integration branch and it is normally
  BEHIND the working branch: aligning it is a deliberate, recorded act, never a side effect of
  a normal change. Do not reset, rebase or force-push it.
- **A release is a tag on the working branch** (`vX.Y.Z`). The same commit adds the release
  section to [`CHANGELOG.md`](CHANGELOG.md), so a tag never ships without notes; work that is
  not released yet lives under `## [Unreleased]`.
- **The battery count lives in two places** — the README badge and the `battery N/N` line
  under [Tests](README.md#tests). A new test file bumps both in the commit that adds it;
  `v354` fails otherwise.

## House style

[`CODING_STANDARDS.md`](CODING_STANDARDS.md) is the single list of coding standards — the
judgement calls no tool can check, read by the **review** agent. Mechanical rules are
enforced by the guardrail above, so do not restate them here. Two operational rules stay
in this file because they govern the *contribution process*, not the code:

- Inspect `git status` and diffs before restoring files. Never discard uncommitted
  user work with `git reset --hard`, `git checkout --`, or `git clean`.
- Write a `## [Unreleased]` entry in [`CHANGELOG.md`](CHANGELOG.md) with any user-visible
  change.

## Where things live

| Path | What |
|---|---|
| `src/longrun/` | the harness package, organised in 15 subpackages (`agent/`, `core/`, `evolve/`, `gen/`, `harness/`, `integrations/`, `interop/`, `memory/`, `model/`, `orbit/`, `orchestrate/`, `plan/`, `research/`, `tools/`, `util/`) |
| `src/longrun/orbit/` | the Orbit command deck (`/orbit`) |
| `webui/` | the main single-file WebUI |
| `tests/acceptance/` | the deterministic gate (auto-discovered) |
| `docs/` | architecture, CLI, testing playbook, and the historical record |
| `GLOSSARY.md` | the domain vocabulary — the single source of truth for names |
| `docs/adr/` | decisions that are hard to reverse, with the rejected alternative |
| `CODING_STANDARDS.md` | the judgement-call standards the reviewer enforces |
| `docs/agents/` | how the engineering flow reads this repo (issue tracker, domain docs) |
| `scripts/check.sh` | the fast guardrail: syntax + lint + types, ratcheted |
| `.agent/` | maintainer's local working notes: `handoff/`, `runbooks/`, `docs/`, `plans/`, `reports/` (untracked) |
| `.scratch/` | the local issue tracker (one spec + tickets per feature), gitignored |

## License

By contributing you agree your contribution is licensed under the project's
[AGPL-3.0](LICENSE) license.
