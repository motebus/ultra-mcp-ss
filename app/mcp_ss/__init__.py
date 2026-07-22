"""
Ultra MCP SmartScreen package

FastAPI app lifecycle and MCP initialization are owned by app/main.py. Package
imports stay side-effect free so environment-specific transport settings can be
loaded before the server instance is created.
"""


def __getattr__(name: str):
    if name == "mcp":
        from .server import mcp

        return mcp
    raise AttributeError(name)


__all__ = ["mcp"]
