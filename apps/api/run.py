"""Development server entry point.

psycopg's async driver refuses to run on Windows' default Proactor event loop.
uvicorn 0.54 builds its loop through an explicit factory (``asyncio.run(...,
loop_factory=...)``), so setting the global event-loop policy is no longer
enough: the factory below is passed to uvicorn instead.

Usage:  uv run python run.py
"""

from __future__ import annotations

import asyncio
import selectors
import sys
from collections.abc import Callable


def selector_loop_factory(
    use_subprocess: bool = False,  # noqa: ARG001 - uvicorn passes this
) -> Callable[[], asyncio.AbstractEventLoop]:
    """Return a loop factory that psycopg's async driver accepts on Windows."""

    def factory() -> asyncio.AbstractEventLoop:
        return asyncio.SelectorEventLoop(selectors.SelectSelector())

    return factory


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        loop="run:selector_loop_factory" if sys.platform == "win32" else "auto",
    )
