"""Bootstrap the first admin account.

Usage:
    uv run python scripts/create_admin.py admin@example.com admin <password>
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db import async_session_factory
from app.models import User
from app.models.user import GlobalRole


async def main() -> None:
    if len(sys.argv) != 4:
        print(__doc__)
        raise SystemExit(1)
    email, username, password = sys.argv[1], sys.argv[2], sys.argv[3]

    async with async_session_factory() as db:
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            print(f"user {email} already exists")
            return
        db.add(
            User(
                email=email,
                username=username,
                hashed_password=hash_password(password),
                role=GlobalRole.admin,
            )
        )
        await db.commit()
        print(f"admin {email} created")


if __name__ == "__main__":
    asyncio.run(main())
