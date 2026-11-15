---
name: release-notes
description: "Turn a commit range into release notes a reader can act on: what changed, why it matters, what breaks. Trigger on 'release notes', 'changelog for this release', 'summarise these commits', 'what changed since <ref>', 'write the changelog'."
---

# Release notes — from commits to what a reader needs

The unit is a CHANGE a user can recognise, never a commit. Ten commits that fix one
defect are one line. One commit that changes a contract is ten lines if it must be.

## 1. Gather, do not guess

1. `git log --oneline <from>..<to>` — the full range.
2. `git diff --stat <from>..<to>` — the size and the touched areas.
3. For each candidate change, open the commit that carries the behaviour, not the
   follow-up that renames a variable.

## 2. Group by the reader's question

- **Added** — a capability that did not exist.
- **Changed** — the same capability behaves differently.
- **Fixed** — it was broken in a way someone could hit.
- **Removed** — it existed and no longer does.
- **Upgrade notes** — what the operator must do: a config key, a migration, a restart.

## 3. Write each line as consequence

- Good: "`/api/market/audit` reports an installed record whose owner is gone."
- Bad: "refactor market module", "various fixes", "improve performance".

Every line carries its evidence: the commit hash or the test id. If you cannot name
either, the change is not ready to be announced.

## 4. Rules

- **No promise the code does not keep.** "Faster" needs a number; "safer" needs the
  gate that now refuses.
- **Breaking changes first**, in their own block, with the exact old and new shape.
- **Never list internal churn** (renames, formatting) unless it changes a public name.
- **Skip the padding.** A release with two real changes is two lines.

## 5. Output

```
## <version or date range>

### Breaking
- <what changed> — <old → new> (commit <hash>)

### Added / Changed / Fixed
- <consequence a reader recognises> (<hash> · <test id>)

### Upgrade notes
- <the one action the operator must take>
```
