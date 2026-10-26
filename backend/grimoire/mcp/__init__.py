"""Read-only Model Context Protocol access to the library.

Thin adapters over the services the HTTP routes already use, served from the
same FastAPI process at ``/mcp``. Design:
``docs/superpowers/specs/2026-10-21-mcp-server-design.md``.
"""
