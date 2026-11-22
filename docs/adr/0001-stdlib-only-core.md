# Core is stdlib-only

`src/longrun/` imports only the Python standard library. The one exception is PyYAML, and only to read the shipped `config/*.yaml` (JSON configs work without it). The core must not gain a runtime `pip` requirement.

We chose this so the harness has no framework to learn and no lock-in, and so a checkout runs on Linux x86_64, Linux arm64 (DGX Spark) and Windows x64 from the same code.

## Considered Options

- **A web framework (FastAPI/Flask) for the HTTP surface** — rejected: it would put a dependency tree between the operator and a running harness, and the stdlib `http.server` is sufficient for a single-process, local-first tool.
- **A richer config library (pydantic, dynaconf)** — rejected: PyYAML-plus-JSON covers the shipped config, and every extra dependency is a supply-chain and portability cost.

## Consequences

- Any new behaviour must be built from the stdlib; the constraint is load-bearing, not a stylistic preference.
- Platform-specific code is quarantined in one module so no POSIX assumption leaks into the core.
