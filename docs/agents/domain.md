# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

**Layout: single-context.** `src/longrun/` is one bounded context (no monorepo
signals: no `pnpm-workspace.yaml`, no `packages/*`, no per-package `src/`). So there
is one glossary and one ADR folder, both at the repo root.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

```
/
├── GLOSSARY.md
├── docs/
│   ├── adr/
│   │   ├── 0001-stdlib-only-core.md
│   │   ├── 0002-data-home-outside-the-checkout.md
│   │   ├── 0003-one-adapter-for-checks-in-core-forge.md
│   │   ├── 0004-place-modules-by-runtime-role.md
│   │   ├── 0005-append-only-history-and-stable-prompt-prefix.md
│   │   └── 0006-cli-routes-declared-in-one-table.md
│   └── ARCHITECTURE.md          ← the living architectural map (prose, dated rules)
└── src/
    └── longrun/                 ← the one context
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0003 (one adapter for checks in `core/forge.py`), but worth reopening because…_
