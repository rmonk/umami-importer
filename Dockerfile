FROM ghcr.io/astral-sh/uv:latest AS uv

FROM python:3.14-slim

COPY --from=uv /uv /uvx /bin/

WORKDIR /srv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# Playwright's bundled Node driver (>=1.65) links against libatomic, which
# the slim image doesn't ship; it must be present before `playwright install`
# can even run (--with-deps installs Chromium's libs, not the driver's).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*
RUN uv run playwright install --with-deps chromium

COPY app/ ./app/

ENV PATH="/srv/.venv/bin:${PATH}"
WORKDIR /srv/app

EXPOSE 8000
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "90", "main:app"]
