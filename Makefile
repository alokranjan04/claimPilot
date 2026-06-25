.PHONY: install check lint type test run eval fmt

install:
	uv sync --extra dev

fmt:
	uv run ruff format .

lint:
	uv run ruff check .
	uv run ruff format --check .

type:
	uv run mypy src

test:
	uv run pytest

# The gate. Nothing is "done" until this is green.
check: lint type test

run:
	PROVIDER=fake uv run uvicorn claimpilot.api.main:app --reload

eval:
	uv run python evals/run_evals.py
