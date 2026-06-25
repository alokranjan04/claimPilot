# ADR 002 — Checkpointer vs LangGraph BaseCheckpointSaver

**Status:** accepted
**Date:** 2026-06-25
**Context:** M2 defines a custom `Checkpointer` protocol; LangGraph ships its own `BaseCheckpointSaver` for graph pause/resume.

## Decision

**Option (a): thin adapter.**  Keep our `Checkpointer` protocol as the canonical persistence interface and write a `LangGraphCheckpointAdapter(BaseCheckpointSaver)` in `src/claimpilot/infra/adapters/` at M3 that delegates to whichever `Checkpointer` the DI factory provides.

## Rationale

- Our `Checkpointer` is provider-agnostic (fake / Azure Cosmos / Redis / Postgres) and already has conformance tests. Duplicating that behind a second interface adds maintenance cost.
- LangGraph's `BaseCheckpointSaver` requires `put`, `get`, `list` with `CheckpointTuple` wrappers. An adapter is ~30 lines and keeps our core code decoupled from LangGraph internals, making a future framework swap cheap.
- The adapter lives at the graph boundary, not inside agents or core, so it doesn't pollute the rest of the codebase.

## Consequences

- M3 must create `infra/adapters/langgraph_saver.py` implementing `BaseCheckpointSaver` over our `Checkpointer`.
- `build_graph()` receives the adapter via DI — never imports a concrete checkpointer.
- If LangGraph changes its saver contract, only the adapter needs updating.
- The `FakeCheckpointer` remains the test-time implementation for both paths.

## Alternatives considered

**(b) Keep both separately:** Use `Checkpointer` for explicit state snapshots (e.g., audit trail) and LangGraph's built-in saver for graph pause/resume. Rejected because two checkpoint stores for the same claim state is confusing and introduces consistency risk.
