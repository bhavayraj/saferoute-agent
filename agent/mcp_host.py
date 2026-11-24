"""MCP host: starts the three SafeRoute MCP servers and talks to them over stdio.

The agent never imports server code directly — every capability is reached
through the Model Context Protocol (list_tools / call_tool), exactly as an
MCP-compatible assistant would use them.
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent

SERVERS = {
    "routes": "servers.routes_mcp",
    "safety": "servers.safety_mcp",
    "emergency": "servers.emergency_mcp",
}


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    """Read an attribute that is snake_case in mcp 2.x and camelCase in mcp 1.x."""
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


class MCPHost:
    """Async context manager holding one ClientSession per MCP server."""

    def __init__(self, servers: dict[str, str] | None = None):
        self.server_modules = servers or SERVERS
        self.sessions: dict[str, ClientSession] = {}
        self.tools: dict[str, dict] = {}  # tool name -> {"server", "description", "input_schema"}
        self.trace: list[dict] = []
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "MCPHost":
        env = {"PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
        for key in ("SAFEROUTE_DATA_MODE", "SAFEROUTE_HTTP_TIMEOUT", "HTTPS_PROXY", "HTTP_PROXY", "SSL_CERT_FILE"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        try:
            for name, module in self.server_modules.items():
                params = StdioServerParameters(command=sys.executable, args=["-m", module], cwd=str(ROOT), env=env)
                read, write = await self._stack.enter_async_context(stdio_client(params))
                session = await self._stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self.sessions[name] = session
                listed = await session.list_tools()
                for t in listed.tools:
                    self.tools[t.name] = {
                        "server": name,
                        "description": t.description or "",
                        "input_schema": _attr(t, "input_schema", "inputSchema", default={}) or {},
                    }
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._stack.aclose()

    async def call(self, tool: str, args: dict) -> dict:
        """Call an MCP tool by name and return its JSON result as a dict."""
        if tool not in self.tools:
            raise KeyError(f"Unknown tool: {tool}")
        server = self.tools[tool]["server"]
        start = time.perf_counter()
        result = await self.sessions[server].call_tool(tool, args)
        ms = round((time.perf_counter() - start) * 1000)
        text = "".join(getattr(c, "text", "") for c in (result.content or []))
        try:
            payload = json.loads(text) if text else {}
        except json.JSONDecodeError:
            payload = {"raw": text}
        if _attr(result, "is_error", "isError", default=False):
            payload = {"error": text or "tool error"}
        self.trace.append({"server": server, "tool": tool, "args": _summarise_args(args), "ms": ms,
                           "ok": "error" not in payload})
        return payload


def _summarise_args(args: dict) -> dict:
    """Keep traces readable: replace long coordinate lists with a point count."""
    out = {}
    for k, v in args.items():
        if isinstance(v, list) and len(v) > 4:
            out[k] = f"<{len(v)} points>"
        else:
            out[k] = v
    return out
