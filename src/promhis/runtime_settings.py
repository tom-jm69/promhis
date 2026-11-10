"""Generic "env wins, else a runtime `AppSetting` override, else a default"
helpers — the same pattern `auth.py`'s `metrics_*`/`db_dump_enabled`
functions already use by hand. Extracted here once a third independent
settings group (digest/SMTP) needed the identical shape, rather than
hand-copying a near-identical pair of functions per field again.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession

from promhis import crud
from promhis.config import settings


def setting_env_locked(env_var: str) -> bool:
    return env_var in os.environ


async def effective_str(session: AsyncSession, *, key: str, env_var: str, default: str | None) -> str | None:
    if setting_env_locked(env_var):
        return getattr(settings, key)
    stored = await crud.get_app_setting(session, key)
    return stored if stored is not None else default


async def effective_int(session: AsyncSession, *, key: str, env_var: str, default: int) -> int:
    if setting_env_locked(env_var):
        return getattr(settings, key)
    stored = await crud.get_app_setting(session, key)
    return int(stored) if stored is not None else default


async def effective_bool(session: AsyncSession, *, key: str, env_var: str, default: bool) -> bool:
    if setting_env_locked(env_var):
        return getattr(settings, key)
    stored = await crud.get_app_setting(session, key)
    return (stored == "true") if stored is not None else default
