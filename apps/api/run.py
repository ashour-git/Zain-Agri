"""Development server entry point.

psycopg's async driver refuses to run on Windows' default Proactor event loop.
uvicorn 0.54 takes a custom ``loop="module:attr"`` and uses that attribute
*directly* as the loop factory (it calls it with no arguments and expects an
event loop back), so ``selector_loop_factory`` returns a loop, not a factory.

Usage:  uv run python run.py
        API_PORT=8765 uv run python run.py   # when 8000 is taken or reserved

Production does not use this file; see apps/api/Dockerfile.
"""

from __future__ import annotations

import asyncio
import os
import selectors
import sys


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    """An event loop psycopg's async driver accepts on Windows."""
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=int(os.environ.get("API_PORT", "8000")),
        reload=True,
        loop="run:selector_loop_factory" if sys.platform == "win32" else "auto",
    )
