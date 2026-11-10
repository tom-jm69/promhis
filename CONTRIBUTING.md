# Contributing to Promhis

Thanks for considering a contribution. This project runs its entire dev loop through Docker — there is no supported way to run the app or its tests directly on the host.

## Dev setup

```bash
git clone <this repo>
cd promhis
cp .env.example .env   # fill in a real PROMHIS_ADMIN_PASSWORD and PROMHIS_SESSION_SECRET
docker compose up --build
```

The dashboard is then at `http://localhost:8000`.

## Running checks before you open a PR

```bash
# Type checking (must report 0 errors — the whole codebase is typed on purpose)
uv run basedpyright

# Test suite (runs inside a container — never natively)
docker build --target test .
```

CI runs both of these on every push and PR; a PR that doesn't pass both won't be merged.

## Code conventions

- **Everything async.** Database access, routes, background tasks — `async def`/`await` throughout. Don't introduce sync I/O on a hot path.
- **basedpyright clean.** If SQLModel's class-level field typing confuses the checker (this happens with `.desc()`/`.ilike()`/`.is_not()` on a model field used in a query), wrap it with `sqlmodel.col(...)` rather than reaching for `# type: ignore`.
- **New integrations are interface + registry, not branching.** See `ROADMAP.md`'s "Design principle: extensible by construction" section — this applies to notification channels, auth schemes, and anything else in that shape. A PR that adds a new integration via an `if/elif` chain will be asked to restructure.
- **No build step for the frontend.** Any JS/CSS dependency is a CDN `<script>`/`<link>` pinned with a Subresource Integrity hash (see `templates/base.html` for the pattern), not an npm package. Don't introduce a bundler.
- **Dashboard UI changes should respect `DESIGN.md`.** The dashboard deliberately mirrors the real Prometheus/Alertmanager UI's visual language — read `DESIGN.md` before touching `static/css/style.css` or the templates. The marketing site under `website/` is a separate, intentionally different design system; `DESIGN.md` doesn't apply there.
- **Don't add speculative abstraction.** Prefer the interface+registry pattern only where there's already a concrete second case (multiple notification channels, multiple auth schemes) — not preemptively elsewhere.

## Commit / PR expectations

- Keep PRs scoped to one change; unrelated cleanup belongs in its own PR.
- Add or update tests for behavior changes — `tests/` mirrors `src/promhis/` by concern (webhook ingest, dashboard pages, etc.).
- If you're picking up a `ROADMAP.md` item, check its box in the same PR that completes it.
