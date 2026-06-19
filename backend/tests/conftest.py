import os

from cryptography.fernet import Fernet

# Must be configured before app modules import settings.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("INGEST_API_KEY", "test-ingest-key")
# Test client speaks plain HTTP, so a `secure` cookie is never sent back ->
# the refresh flow needs the cookie unsecured here (prod default stays true).
os.environ.setdefault("COOKIE_SECURE", "false")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.security import create_token, hash_password  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.models.user import GlobalRole  # noqa: E402


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    from app.core.rate_limit import login_rate_limiter

    login_rate_limiter._memory.clear()
    yield
    login_rate_limiter._memory.clear()


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(db_factory):
    async with db_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_factory):
    async def override_get_db():
        async with db_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def make_user(db, email: str, role: GlobalRole, password: str = "password123") -> User:
    user = User(
        email=email,
        username=email.split("@")[0],
        hashed_password=hash_password(password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin(db):
    return await make_user(db, "admin@example.com", GlobalRole.admin)


@pytest_asyncio.fixture
async def editor(db):
    return await make_user(db, "editor@example.com", GlobalRole.editor)


@pytest_asyncio.fixture
async def viewer(db):
    return await make_user(db, "viewer@example.com", GlobalRole.viewer)


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user.id, 'access')}"}


@pytest.fixture
def admin_headers(admin):
    return auth_headers(admin)


@pytest.fixture
def editor_headers(editor):
    return auth_headers(editor)


@pytest.fixture
def viewer_headers(viewer):
    return auth_headers(viewer)


class FakeRuler:
    """In-memory stand-in for MimirRulerClient used in sync tests."""

    def __init__(self, fail: bool = False):
        self.pushed: list[tuple[str, dict]] = []
        self.deleted: list[tuple[str, str]] = []
        self.fail = fail

    async def set_rule_group(self, namespace: str, payload: dict) -> None:
        if self.fail:
            raise RuntimeError("ruler down")
        self.pushed.append((namespace, payload))

    async def delete_rule_group(self, namespace: str, name: str) -> None:
        self.deleted.append((namespace, name))


@pytest.fixture
def fake_ruler():
    from app.api.v1.rules import get_ruler_client

    ruler = FakeRuler()
    app.dependency_overrides[get_ruler_client] = lambda: ruler
    yield ruler
    app.dependency_overrides.pop(get_ruler_client, None)
