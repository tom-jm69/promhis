"""Scheduled Postgres dumps (`pg_dump`) — off by default.

Writes a timestamped `.sql` file to `PROMHIS_DB_DUMP_PATH` every
`PROMHIS_DB_DUMP_INTERVAL_HOURS`. Runs `pg_dump` as a subprocess against the
same `database_url` the app itself uses; doesn't touch the app's own async
connection pool. `db_dump_path` needs to be a mounted volume for dumps to
outlive the container — see docs/self-hosting.md.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from promhis.auth import effective_db_dump_enabled
from promhis.config import settings
from promhis.db import async_session_factory

logger = logging.getLogger("promhis.db_dump")


class InsufficientDiskSpaceError(RuntimeError):
    """Raised instead of ever invoking pg_dump — never attempt a dump that
    might fill the volume or get truncated partway through.
    """


def _pg_dump_url(database_url: str) -> str:
    """`pg_dump`/libpq don't understand SQLAlchemy's `+asyncpg` driver
    suffix in the URL scheme — strip it down to plain `postgresql://`.
    """
    parts = urlsplit(database_url)
    scheme = parts.scheme.split("+")[0]
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def _free_mb(path: Path) -> float:
    return shutil.disk_usage(path).free / (1024 * 1024)


async def run_db_dump() -> Path:
    dump_dir = Path(settings.db_dump_path)
    dump_dir.mkdir(parents=True, exist_ok=True)

    free_mb = _free_mb(dump_dir)
    if free_mb < settings.db_dump_min_free_mb:
        raise InsufficientDiskSpaceError(
            f"only {free_mb:.0f}MiB free at {dump_dir} "
            f"(PROMHIS_DB_DUMP_MIN_FREE_MB requires {settings.db_dump_min_free_mb}MiB) — skipping"
        )

    filename = f"promhis-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sql"
    out_path = dump_dir / filename

    process = await asyncio.create_subprocess_exec(
        "pg_dump",
        "--no-owner",
        "--no-acl",
        "-f",
        str(out_path),
        _pg_dump_url(settings.database_url),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        # Covers pg_dump itself running the volume out of space mid-write
        # (ENOSPC) too — never leave a truncated, silently-corrupt dump
        # behind pretending to be a real backup.
        out_path.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump failed (exit {process.returncode}): {stderr.decode(errors='replace').strip()}")
    return out_path


async def run_db_dump_scheduler() -> None:
    # Always runs (not gated on settings.db_dump_enabled at startup) so that
    # toggling it on from the Settings page — when PROMHIS_DB_DUMP_ENABLED
    # isn't set — takes effect without a restart, same as metrics_enabled.
    while True:
        await asyncio.sleep(settings.db_dump_interval_hours * 3600)
        try:
            async with async_session_factory() as session:
                enabled = await effective_db_dump_enabled(session)
            if not enabled:
                continue
            path = await run_db_dump()
            logger.info("db dump: wrote %s", path)
        except InsufficientDiskSpaceError as exc:
            # Expected, actionable, not a bug — a plain warning, not a
            # scary traceback.
            logger.warning("db dump skipped: %s", exc)
        except Exception:
            # Broad on purpose, same reasoning as the other background
            # loops (retention/poller/digest) — a single failed dump must
            # never permanently kill the schedule.
            logger.exception("db dump failed")
