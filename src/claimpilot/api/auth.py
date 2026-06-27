"""Role-based auth — reads Container Apps EasyAuth headers or debug fallback.

In production (Container Apps with Entra ID EasyAuth enabled):
  - ``X-MS-CLIENT-PRINCIPAL-NAME`` → user display name
  - ``X-MS-CLIENT-PRINCIPAL`` → Base64-encoded JSON with ``claims`` array;
    roles come from the ``roles`` claim (configured as an App Role in the
    Entra ID app registration).

In local dev (no EasyAuth, no headers):
  - ``X-Debug-Role`` header selects a role (default ``adjuster``).
  - This lets tests and the demo UI work without any identity provider.

Usage in routes::

    from claimpilot.api.auth import get_caller, require_role, CallerIdentity

    @router.post("/admin-action")
    async def do_thing(caller: Annotated[CallerIdentity, Depends(require_role("admin"))]):
        ...
"""

from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field


class CallerIdentity(BaseModel):
    """The resolved identity of the current API caller."""

    user: str = Field(min_length=1)
    roles: list[str] = Field(default_factory=lambda: ["adjuster"])


def get_caller(request: Request) -> CallerIdentity:
    """Extract the caller identity from EasyAuth headers or debug fallback.

    Resolution order:
    1. ``X-MS-CLIENT-PRINCIPAL-NAME`` + ``X-MS-CLIENT-PRINCIPAL`` (EasyAuth)
    2. ``X-Debug-Role`` header (local dev / tests)
    3. Default: ``adjuster`` role
    """
    # --- EasyAuth path (production) ---
    principal_name = request.headers.get("x-ms-client-principal-name")
    principal_b64 = request.headers.get("x-ms-client-principal")

    if principal_name and principal_b64:
        roles = _extract_roles(principal_b64)
        return CallerIdentity(user=principal_name, roles=roles or ["adjuster"])

    # --- Debug / local-dev fallback ---
    debug_role = request.headers.get("x-debug-role", "adjuster")
    return CallerIdentity(user="dev-user", roles=[debug_role])


def _extract_roles(principal_b64: str) -> list[str]:
    """Decode the EasyAuth principal and extract the ``roles`` claim."""
    try:
        raw = base64.b64decode(principal_b64)
        principal: dict[str, Any] = json.loads(raw)
        claims: list[dict[str, str]] = principal.get("claims", [])
        return [c["val"] for c in claims if c.get("typ") == "roles"]
    except Exception:  # noqa: BLE001
        return []


class _RequireRole:
    """FastAPI dependency that enforces a minimum role.

    Usage::

        @router.post("/admin-action")
        async def act(caller: Annotated[CallerIdentity, Depends(require_role("admin"))]):
            ...
    """

    def __init__(self, role: str) -> None:
        self._role = role

    def __call__(
        self,
        caller: CallerIdentity = Depends(get_caller),  # noqa: B008
    ) -> CallerIdentity:
        if self._role not in caller.roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{self._role}' required. Your roles: {caller.roles}",
            )
        return caller


def require_role(role: str) -> _RequireRole:
    """Return a FastAPI dependency that enforces *role* on the caller."""
    return _RequireRole(role)
