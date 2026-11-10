FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY src ./src
COPY README.md ./

# `docker build --target test .` — runs the test suite in-container; this
# stage is never part of the default build and ships nothing to the image
# `docker build .` produces. Postgres is the only supported storage (see
# db.py/config.py), so the suite needs a real server, not a stub — installed
# here and spun up by tests/conftest.py's own `initdb`/`pg_ctl` bootstrap (a
# throwaway cluster per test session, not the distro's own default cluster
# the package postinst creates; that one is simply never started).
# `initdb` refuses to run as root, hence the dedicated non-root user.
FROM base AS test
RUN apt-get update && apt-get install -y --no-install-recommends postgresql \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/lib/postgresql/*/bin/* /usr/local/bin/ \
    && useradd --create-home --shell /bin/bash testrunner \
    && chown -R testrunner:testrunner /app
USER testrunner
RUN uv sync --locked --group dev
COPY --chown=testrunner:testrunner tests ./tests
RUN uv run pytest -q

FROM base AS runtime
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# A numeric USER (not just a name) so Kubernetes' `runAsNonRoot` pod security
# check — which reads the image's own USER, not /etc/passwd — can actually
# verify it without needing a matching runAsUser override in every caller.
RUN useradd --create-home --shell /bin/false --uid 1000 promhis \
    && chown -R promhis:promhis /app
USER 1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["promhis"]
