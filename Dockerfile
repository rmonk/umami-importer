FROM ghcr.io/astral-sh/uv:latest AS uv

FROM python:3.14-slim

COPY --from=uv /uv /uvx /bin/

# Debian security updates on top of the base image, and no system pip: the app runs from
# the uv venv, and pip's vendored urllib3/msgpack were most of the image's fixable findings.
# Playwright's bundled Node driver (>=1.65) links against libatomic, which the slim image
# doesn't ship; it must be present before `playwright install` can even run
# (--with-deps installs Chromium's libs, not the driver's).
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/python3.*/site-packages/pip \
              /usr/local/lib/python3.*/site-packages/pip-*.dist-info \
              /usr/local/bin/pip /usr/local/bin/pip3*

# No uv cache left in the image, and Chromium outside /root so the non-root user can run it.
ENV UV_NO_CACHE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /srv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN uv run playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY app/ ./app/

# Runs as an unprivileged user. /srv/relay (the shared volume) must be writable by it:
# a new named volume starts out owned by it; an existing one written by the old root
# image needs a one-time `chown -R 10001:10001` on the host.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin app \
    && mkdir -p /srv/relay \
    && chown app:app /srv/relay

ENV PATH="/srv/.venv/bin:${PATH}" \
    HOME=/tmp
WORKDIR /srv/app
USER 10001:10001

EXPOSE 8000
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "90", "main:app"]
