"""System tests of the running Compose stack, through its own frontend (frontend/e2e/stack.spec.ts).

    python scripts/stack_system_test.py

1. Creates a throwaway Developer account inside the backend container, through the app's own
   models and password hashing. Its address is made up and its password random, held in memory
   only and never printed.
2. Runs `npx playwright test` with STACK=1 against http://127.0.0.1:5173, the stack's own frontend.
3. Deactivates the account, whatever the result, and writes an audit entry saying why.

The stack must be up (`docker compose up -d`). Nothing here reads .env or uses the seeded Admin.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = REPO_ROOT / "frontend"

# Run by `python -` inside the backend container. The account's details arrive in its environment.
CREATE = """
import asyncio, os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.core.security import hash_password
from app.core.settings import get_settings
from app.db.models import AuditLog, Role, User
from app.db.session import create_engine

async def main():
    engine = create_engine(get_settings())
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        email = os.environ["STACK_EMAIL"]
        session.add(User(email=email, password_hash=hash_password(os.environ["STACK_PASSWORD"]),
                         role=Role.DEVELOPER.value, active=True))
        session.add(AuditLog(actor_id=None, action="system_test.account.created", target=email,
                             details={"by": "scripts/stack_system_test.py"}))
        await session.commit()
    await engine.dispose()
    print("created", email)

asyncio.run(main())
"""

DEACTIVATE = """
import asyncio, os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.core.settings import get_settings
from app.db.models import AuditLog, User
from app.db.session import create_engine

async def main():
    engine = create_engine(get_settings())
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        email = os.environ["STACK_EMAIL"]
        user = await session.scalar(select(User).where(User.email == email))
        if user is not None:
            user.active = False
            session.add(AuditLog(actor_id=None, action="system_test.account.deactivated",
                                 target=email, details={"by": "scripts/stack_system_test.py"}))
            await session.commit()
    await engine.dispose()
    print("deactivated", email)

asyncio.run(main())
"""


def in_backend(code: str, email: str, password: str = "") -> None:
    """Run Python in the backend container with the account's details in its environment only."""
    environment = {**os.environ, "STACK_EMAIL": email, "STACK_PASSWORD": password}
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "-e", "STACK_EMAIL", "-e", "STACK_PASSWORD",
         "-w", "/app", "backend", "python", "-"],
        input=code, text=True, capture_output=True, cwd=REPO_ROOT, env=environment, check=False,
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith(("created", "deactivated"))]
    if result.returncode != 0 or not lines:
        raise SystemExit(f"the backend container refused: {result.stderr.strip()[-400:]}")
    print(lines[-1])


def main() -> int:
    email = f"system-test-{secrets.token_hex(4)}@example.com"
    password = secrets.token_urlsafe(24)
    npx = "npx.cmd" if os.name == "nt" else "npx"
    in_backend(CREATE, email, password)
    try:
        environment = {**os.environ, "STACK": "1", "STACK_EMAIL": email, "STACK_PASSWORD": password}
        return subprocess.run(
            [npx, "playwright", "test", *sys.argv[1:]], cwd=FRONTEND, env=environment, check=False
        ).returncode
    finally:
        in_backend(DEACTIVATE, email)


if __name__ == "__main__":
    sys.exit(main())
