# Contributing to Longrun

Thanks for your interest! Longrun is a **stdlib-only** harness — that constraint is
deliberate and load-bearing, so please respect it.

## Ground rules

- **No third-party runtime dependencies.** The core (`src/longrun/`) imports only the
  Python standard library. New behaviour must not add a `pip` requirement to the core.
  The single exception is **PyYAML** (pure-Python), used only to read the shipped
  `config/*.yaml`; JSON configs work without it.
- **Keep it cross-platform.** Platform-specific code lives in `src/longrun/osutil.py`.
  No POSIX assumption may leak into the core — Longrun runs on Linux x86_64,
  Linux arm64/aarch64 (NVIDIA DGX Spark) and Windows x64 from the same code.
- **No secrets in the repo.** Keys live in a local `.env` / `~/.hermes/.env` (gitignored).
  `.env.template` is the only tracked env file.
- **Evidence over belief.** Every claim in a PR should come with a number: a test count,
  an HTTP status, a file field.

## Set up

Install and run instructions live in
[README → Install & run](README.md#install--run) (clone, `cp .env.template .env`,
`./run.sh` on Linux or `.\run.ps1` on Windows). Then verify your checkout:

```bash
bash tests/battery.sh          # FAST gate; reports the current pass count
```

## The loop

1. **Branch.** Short-lived, descriptive: `feature/…`, `fix/…`, `docs/…`, `refactor/…`.
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

## House style

- English only in code, comments, docstrings, log messages, UI strings and commits.
- Explicit type hints and structured docstrings for functions.
- Log lines: `[Level] | [Timestamp] | [Module]`.
- Temp/one-off agent scripts go to `.agent/trash/` (gitignored), not the application
  data directory `trash/`, repo root, or `scripts/`.
- Inspect `git status` and diffs before restoring files. Never discard uncommitted
  user work with `git reset --hard`, `git checkout --`, or `git clean`.
- Write a `## [Unreleased]` entry in [`CHANGELOG.md`](CHANGELOG.md) with any user-visible
  change.

## Where things live

| Path | What |
|---|---|
| `src/longrun/` | the harness package, organised in subpackages (`core/`, `agent/`, `orchestrate/`, `plan/`, `tools/`, `model/`, `memory/`, `interop/`, `util/`) |
| `src/longrun/orbit/` | the Orbit command deck (`/orbit`) |
| `webui/` | the main single-file WebUI |
| `tests/acceptance/` | the deterministic gate (auto-discovered) |
| `docs/` | architecture, CLI, testing playbook, and the historical record |
| `.agent/` | maintainer's local working notes + debugging manual (untracked) |

## License

By contributing you agree your contribution is licensed under the project's
[AGPL-3.0](LICENSE) license.
