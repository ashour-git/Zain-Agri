"""Set a new password for a user who is locked out, and end all their sessions.

    DATABASE_URL=postgresql+psycopg://zain_app@HOST/DB?sslmode=require \\
    uv run python reset_password.py owner@example.com

The new password is typed at a hidden prompt (twice), never passed on the
command line, so it does not end up in shell history or process lists.
Same password rules as registration. Tell the user to change it afterwards
in «الحساب والأمان».
"""

from __future__ import annotations

import asyncio
import getpass
import sys

from app.infrastructure.db.session import dispose_engine, get_session_factory
from app.modules.auth.service import reset_password


async def _run(email: str, password: str) -> bool:
    try:
        async with get_session_factory()() as session:
            return await reset_password(session, email=email, new_password=password)
    finally:
        await dispose_engine()


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: uv run python reset_password.py EMAIL", file=sys.stderr)
        return 2
    email = sys.argv[1]

    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Repeat it: "):
        print("The two passwords do not match. Nothing changed.", file=sys.stderr)
        return 1

    if sys.platform == "win32":
        # Async psycopg refuses Windows' default Proactor loop.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        found = asyncio.run(_run(email, password))
    except ValueError as exc:
        print(f"Password refused: {exc}. Nothing changed.", file=sys.stderr)
        return 1

    if not found:
        print(f"No account with the email {email}. Nothing changed.", file=sys.stderr)
        return 1
    print(f"Password reset for {email}. All their sessions were signed out.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
