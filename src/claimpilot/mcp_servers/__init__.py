"""MCP tool servers — typed, validated, authz-at-boundary integrations.

Each server exposes tools via typed schemas; agents call them through the
interface.  Locally backed by fakes/fixtures; in prod by real services.
"""
