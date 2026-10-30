"""Development server entry point.

psycopg's async driver refuses to run on Windows' default Proactor event loop,
so the selector policy must be installed before uvicorn creates the loop.
The call sits at module level on purpose: uvicorn's reloader re-imports this
module inside a spawned child process, which then inherits the policy too.

Usage:  uv run python run.py
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
