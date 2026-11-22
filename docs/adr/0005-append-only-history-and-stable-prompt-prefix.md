# Provider history is append-only, and the prompt prefix is kept stable

From the provider's point of view, a session's history is append-only: the exact text a user turn was sent with is stored beside the display text, and the next turn rebuilds that message from it rather than rewriting the history. Only text that does not change between turns may live in the system prompt; the two volatile blocks (the live task list and the memory index) ride the current user message instead.

We chose this because a stable prefix is what lets the provider reuse its cache. Measured: before the change the first call of each turn was 100% uncached; after it, a turn reuses ~85% of the prompt it already processed.

## Considered Options

- **Rewriting the history each turn for cleanliness** — rejected: it forced the provider to re-prefill the whole transcript every turn.

## Consequences

- The context meter must call the same assembly function the turn uses, so it measures exactly what is sent.
- The system card in the chat is shown only when the prompt really changed (a digest is stored on the session).
