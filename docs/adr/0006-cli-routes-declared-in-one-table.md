# 0006 — A CLI route is declared once, in `ROUTES`

- **Status:** accepted (2026-11-22)
- **Context:** `core/forge.py` is ~6,000 lines with ~190 `cmd_*` handlers, 39 of which
  perform an HTTP call. Each call wrote its own `(method, path)` inline: 97 sites over 91
  distinct routes, with duplicates (`GET /api/agents/tree` appeared in four handlers). A
  renamed server route could therefore drift from the CLI silently — nothing tied the two
  together except a source-regex parity test that pinned *syntax*, not contract.
- **Decision:** `core/forge.py` holds a single `ROUTES` mapping — one `(method, path)`
  per route — plus `_route(name)` / `_path(name)`. Handlers call the table:
  `req(*_route("api_status"))`. Every **static** route is declared (97 call sites across
  39 handlers collapse to 91 entries). Paths built at call time (`"/api/runs/" + id`,
  `"%s" % x`, f-strings) stay inline until a shape is deliberately designed for them.
- **Consequences:**
  - Adding a command means adding its route to the table, in one place.
  - `v588` (route parity) asserts every declared route is served by the server **under the
    declared method**, and it reads the table — so migrating a command *increases* its
    coverage instead of silently removing it.
  - `v1276` asserts the CLI contract (help completeness, the required surface) against the
    **live parser**, so the requirement survives any internal reorganisation.
  - A migrated call is equivalent by construction: the declared tuple *is* the literal it
    replaced, which is why the 964-test battery is the right oracle for the migration.
- **Rejected:**
  - *(a) Leave the literals inline and keep regexing them.* The status quo — what let routes
    drift, and it pins syntax that any refactor deletes.
  - *(b) Generate `ROUTES` from the server's route files.* One truth spread over two files,
    and the CLI surface would become *derived*, so a CLI-only route could not be added
    without touching the server.
  - *(c) A positional placeholder per call site ("name + args" form).* More mechanism than
    the 43 genuinely varied dynamic paths justify; they stay inline instead.
