---
name: pr-review
description: "Review a pull request or branch diff: what it claims, what it actually changes, and what a maintainer must decide before merging. Trigger on 'review this PR', 'review my branch', 'is this ready to merge', 'code review', 'what should I fix before merging'."
---

# PR review — claim, evidence, decision

A review answers three questions in order: **does the change do what it says**, **is it
safe**, **what must a human decide**. Style opinions come last and only when they change
behaviour.

## 1. Read the claim

- The PR title and body, then `git log <base>..<head>` and `git diff <base>..<head>`.
- Restate the claim in one sentence of your own. If you cannot, the PR does not have a
  claim — that is the first finding.

## 2. Check the claim against the diff

| question | finding when the answer is no |
|---|---|
| Is every claimed behaviour present in the diff? | "claims X, the diff does Y" |
| Does every changed file belong to the claim? | "unrelated change in <file>" |
| Does a test fail before and pass after? | "no test pins the new behaviour" |
| Is the dependent test re-pointed rather than weakened? | "assertion relaxed at <file>:<line>" |

## 3. Check the seam

- **One owner** per value, lookup and store: a second copy is a finding even today.
- **Fail closed** at the boundary; a new fallback that succeeds on bad input is a finding.
- **No dead surface**: a route, config key or UI control with no caller or no writer.
- **Rollback** exists and is named; "revert the commit" counts only when the change is
  one commit and touches no store.

## 4. Decide

```
CLAIM: <one sentence>
AGREES: yes | partly | no — <the specific divergence>
BLOCKING
- <file>:<line> — <what breaks, in one sentence> — <the smallest fix>
NON-BLOCKING
- <what improves but does not block>
DECISION: merge | merge after fixes | needs design | reject — <why, in one line>
```

Never approve a diff you did not read in full, and never block on taste. If the only
objections are stylistic, say so and let the maintainer choose.
