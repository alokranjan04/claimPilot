# Spec-Driven Development with Claude Code — ClaimPilot

How to actually run this project in Claude Code. The idea: **specs and CLAUDE.md are the source of truth; Claude Code implements against them, one milestone at a time, test-first.** You stay the architect and reviewer.

## The loop (repeat per milestone)

1. **Point at the spec.** Open a Claude Code session in the repo root. Tell it which milestone and which spec section (the `Prompt:` line in `BUILD_PLAN.md` is ready to paste).
2. **Let it plan first.** Ask Claude Code to restate the milestone's acceptance criteria and propose an approach *before* coding. Correct the plan if needed — cheap to fix here.
3. **Test-first implementation.** Have it write failing tests, then code, then make them pass. Insist on small commits.
4. **Run the gate.** `make check` (ruff + mypy + pytest). Nothing is done until it's green.
5. **Review the diff.** You read the changes. Reject anything that violates a CLAUDE.md guardrail (untyped boundaries, provider imports leaking into core, missing trace, fabricated citations).
6. **Record decisions.** Non-obvious choice → an ADR in `docs/decisions/`.
7. **Commit, then next milestone.** Don't batch milestones.

## What makes this work

- **CLAUDE.md is auto-loaded** by Claude Code in this repo — it carries the guardrails into every session so you don't re-explain them.
- **One milestone = one focused context.** Keeps Claude Code's attention narrow and the diffs reviewable. Start fresh sessions between milestones to keep context clean.
- **Fakes-first means everything is testable offline** — Claude Code can run the full suite without cloud creds, so the feedback loop is fast and free.
- **Acceptance criteria are the contract.** If you can't check the boxes, the milestone isn't done — say so and let it continue.

## Good prompting patterns

- *"Before writing code, restate M3's acceptance criteria and list the files you'll create/modify. Wait for my OK."*
- *"Implement only the intake agent (M5). One commit. Unit tests with the fake LLM. Don't touch other agents."*
- *"`make check` is failing on mypy — fix the types, don't loosen the config or add `# type: ignore`."*
- *"This change imported `azure` into `agents/` — that violates CLAUDE.md. Move it behind the provider interface."*
- *"Write an ADR for why we chose hybrid retrieval over pure vector."*

## Anti-patterns to block

- Jumping ahead to a later milestone "while we're here." One at a time.
- Cloud SDKs appearing before M10. Core stays provider-agnostic.
- Untyped dicts crossing module boundaries. Everything is a Pydantic model.
- Tests that assert on a live model's output. Use the fake LLM with scripted responses.
- Silent broadening of `mypy`/`ruff` config to make errors disappear.

## Suggested cadence
- **M0–M2** in one sitting (skeleton, models, interfaces+fakes) — this is the foundation.
- **M3** (graph skeleton) is the first "wow" — a fake claim flowing START→END.
- **M4–M7** is the core build; after **M7** you have a demoable, test-gated system.
- **M8–M11** is productionization on Azure.

## Handy commands during a session
```bash
make check                         # the gate: ruff + mypy + pytest
uv run pytest tests/test_graph.py -q        # one test file
uv run pytest -k coverage_agent -q          # one test by name
PROVIDER=fake uv run uvicorn claimpilot.api.main:app --reload
git log --oneline -10                        # review what was built
```

## Your role vs Claude Code's
- **You:** own the specs, the architecture decisions, the milestone order, and the review. You decide when a milestone is truly done.
- **Claude Code:** implements against the spec, writes tests, keeps the gate green, surfaces ambiguities instead of guessing.

Keep the specs current. If reality diverges from a spec, update the spec first, then the code — the spec stays the source of truth.
