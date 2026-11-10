from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from promhis import db_dump
from promhis.config import settings


def test_pg_dump_url_strips_asyncpg_driver_suffix() -> None:
    assert db_dump._pg_dump_url("postgresql+asyncpg://user:pass@host:5432/db") == "postgresql://user:pass@host:5432/db"


def test_pg_dump_url_leaves_plain_url_unchanged() -> None:
    assert db_dump._pg_dump_url("postgresql://user:pass@host:5432/db") == "postgresql://user:pass@host:5432/db"


@pytest.mark.asyncio
async def test_run_db_dump_writes_a_real_dump(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "db_dump_path", str(tmp_path))
    out_path = await db_dump.run_db_dump()
    assert out_path.exists()
    content = out_path.read_text()
    assert "PostgreSQL database dump" in content
    assert "alert" in content.lower()  # the Alert table, proof this dumped the real schema


@pytest.mark.asyncio
async def test_run_db_dump_skips_when_disk_nearly_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "db_dump_path", str(tmp_path))
    monkeypatch.setattr(settings, "db_dump_min_free_mb", 10**9)  # no real disk has an exabyte free

    with pytest.raises(db_dump.InsufficientDiskSpaceError):
        await db_dump.run_db_dump()

    assert list(tmp_path.iterdir()) == []  # pg_dump was never even started


@pytest.mark.asyncio
async def test_scheduler_logs_warning_not_exception_when_disk_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "db_dump_enabled", True)
    monkeypatch.setattr(settings, "db_dump_path", str(tmp_path))
    monkeypatch.setattr(settings, "db_dump_min_free_mb", 10**9)
    monkeypatch.setattr(settings, "db_dump_interval_hours", 0)

    with caplog.at_level("WARNING", logger="promhis.db_dump"):
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(db_dump.run_db_dump_scheduler(), timeout=0.5)

    assert any("db dump skipped" in record.message for record in caplog.records)
    assert all(record.levelname == "WARNING" for record in caplog.records)
