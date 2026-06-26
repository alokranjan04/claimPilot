"""Shared base types for all MCP tool servers."""

from __future__ import annotations

from pydantic import BaseModel


class AuthContext(BaseModel):
    """Authorization context passed at the MCP boundary.

    The model never holds credentials; the MCP boundary does.
    """

    caller: str = ""
    scopes: list[str] = []


class ToolError(Exception):
    """Typed error raised by MCP tool servers — caught by the graph."""

    def __init__(self, tool: str, message: str) -> None:
        self.tool = tool
        super().__init__(f"[{tool}] {message}")
