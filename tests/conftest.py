from __future__ import annotations

import atexit
import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_ephemeral_postgres() -> None:
    """Postgres is the only supported storage (ROADMAP.md) — the suite needs
    a real server, not a stub. Spins up a disposable cluster for this test
    session alone (own data dir, own port, stopped at process exit) so
    `docker build --target test .` stays one self-contained stage with no
    sidecar container — the Dockerfile's `test` stage installs the `initdb`/
    `pg_ctl`/`createdb` binaries this calls. Skipped entirely when
    PROMHIS_DATABASE_URL is already set (e.g. a manual run against a real
    Postgres container, see ROADMAP.md §23)."""
    data_dir = tempfile.mkdtemp(prefix="promhis-test-pg-")
    port = _free_port()

    subprocess.run(
        ["initdb", "-D", data_dir, "-U", "promhis", "-A", "trust", "--no-sync"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "pg_ctl", "-D", data_dir, "-w", "-l", os.path.join(data_dir, "server.log"),
            "-o", f"-p {port} -h 127.0.0.1 -k {data_dir}",
            "start",
        ],
        check=True,
        capture_output=True,
    )

    def _stop() -> None:
        subprocess.run(["pg_ctl", "-D", data_dir, "-m", "fast", "stop"], capture_output=True)
        shutil.rmtree(data_dir, ignore_errors=True)

    atexit.register(_stop)

    subprocess.run(
        ["createdb", "-h", "127.0.0.1", "-p", str(port), "-U", "promhis", "promhis"],
        check=True,
        capture_output=True,
    )
    os.environ["PROMHIS_DATABASE_URL"] = f"postgresql+asyncpg://promhis@127.0.0.1:{port}/promhis"


# Environment must be set before `promhis.config` (and anything importing it)
# is first imported, since Settings() is instantiated — and promhis.db's
# engine created — at module load time.
if "PROMHIS_DATABASE_URL" not in os.environ:
    _start_ephemeral_postgres()
os.environ.setdefault("PROMHIS_ADMIN_USER", "testadmin")
os.environ.setdefault("PROMHIS_ADMIN_PASSWORD", "testpass")
os.environ.setdefault("PROMHIS_SESSION_SECRET", "test-secret")

from sqlmodel import delete  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from promhis import crud  # noqa: E402
from promhis.auth import hash_password  # noqa: E402
from promhis.config import settings  # noqa: E402
from promhis.db import async_session_factory, init_db  # noqa: E402
from promhis.main import app  # noqa: E402
from promhis.models import ApiToken, Alert, AlertAnnotation, AlertEvent, AppSetting, AuditLogEntry, NotificationIntegration, User  # noqa: E402

# PBKDF2 at auth.py's real iteration count is deliberately slow (that's the
# point) — computed once per test session instead of once per test, since
# every test using `client` would otherwise pay that cost on every single
# invocation (this turned a ~2s suite into a ~16s one before being cached).
_BOOTSTRAP_PASSWORD_HASH = hash_password(settings.admin_password)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    await init_db()
    # All tests share one Postgres database for the whole session (simplest
    # thing that works with the module-level engine singleton); without
    # this, a row inserted by one test leaks into another test's assertions
    # about totals/counts. Truncate before each test instead of giving every
    # test its own database.
    async with async_session_factory() as session:
        for model in (AuditLogEntry, AlertEvent, Alert, AlertAnnotation, NotificationIntegration, User, ApiToken, AppSetting):
            await session.execute(delete(model))
        await session.commit()
        # Mirrors main.py's lifespan — `sync_bootstrap_admin` normally runs
        # once at real app startup, but the test ASGI transport never
        # executes that startup, so login would otherwise fail for every
        # test (the User table truncated above would just stay empty).
        await crud.sync_bootstrap_admin(session, username=settings.admin_user, password_hash=_BOOTSTRAP_PASSWORD_HASH)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def authed_client(client: AsyncClient) -> AsyncClient:
    response = await client.post("/login", data={"username": "testadmin", "password": "testpass", "next": "/"})
    assert response.status_code == 303
    return client


@pytest_asyncio.fixture
async def anon_client() -> AsyncIterator[AsyncClient]:
    """A genuinely separate client with its own cookie jar — for tests that
    need both an authenticated session (`authed_client`) and a truly
    anonymous caller in the same test. `client` and `authed_client` are the
    *same* underlying AsyncClient/cookie jar (see `authed_client` above), so
    reusing `client` after also requesting `authed_client` in one test does
    NOT give you an unauthenticated caller — it's still carrying that
    session cookie. Use this fixture instead whenever that distinction
    actually matters (e.g. testing a dependency that checks the session
    first, falling back to something else, like `require_token_or_login`).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def webhook_auth() -> tuple[str, str]:
    return ("testadmin", "testpass")
