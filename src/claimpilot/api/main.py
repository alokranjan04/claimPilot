"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(
    title="ClaimPilot",
    description="Autonomous insurance claims adjudication API.",
    version="0.1.0",
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    """Readiness probe — returns 200 when the service can accept traffic."""
    return JSONResponse(content={"status": "ready"})
