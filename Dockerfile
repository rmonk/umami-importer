FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /srv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN uv run playwright install --with-deps chromium

COPY app/ ./app/

ENV PATH="/srv/.venv/bin:${PATH}"
WORKDIR /srv/app

EXPOSE 8000
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "main:app"]
