"""Enterprise-only code (ROADMAP.md §22).

Everything under `promhis.ee` requires a valid license to use in production
— see `ee/LICENSE` (separate from the repository root's MIT license, which
covers everything outside this package) and `docs/licensing.md`.

Modules here still check `promhis.licensing.has_feature(flag)`/
`require_feature(flag)` themselves — being in this package is an
organizational/licensing-text boundary, not a code-level enforcement
mechanism by itself. A thin gate inline in an otherwise-free-tier file
(e.g. `routers/dashboard.py`'s API-token cap check) does NOT need to move
here just because it's licensed — this package is for Enterprise features
substantial enough to warrant their own module, starting with the Admin
Users management UI (`promhis.ee.admin_users`).
"""

from __future__ import annotations
