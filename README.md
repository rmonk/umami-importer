# umami-recipe-importer

A small web app that takes a recipe URL or PDF, extracts the recipe more
reliably than umami.recipes' own importer, and hands you a link that
umami's importer can parse cleanly.

## How it works

umami.recipes has no published API, and its built-in URL importer often
fails on messy source pages (see `reference/umami_api.md` for the full
reverse-engineering notes). Rather than write into umami's database
directly, this tool:

1. Extracts the recipe itself — schema.org/JSON-LD first (free). If that
   comes up empty for a URL, you choose: fall back to an LLM (Claude or
   Gemini, configurable; also the only path for PDFs, which never have
   structured data), or select sections manually from a cleaned-up view of
   the real page (no API cost at all — see "Manual selection" below). Sites
   that block plain HTTP requests are retried with a headless browser.
2. Re-renders the recipe as a clean, minimal HTML page with well-formed
   schema.org markup.
3. Publishes that page to a public GitHub Pages repo
   (`github.com/rmonk/umami-recipe-relay`) under an unlisted random URL.
4. Gives you `https://www.umami.recipes/import?url=<relay page>` — the same
   URL scheme umami's own Chrome extension uses — so umami's own importer
   does the actual save, using its normal supported flow.

## Manual selection

For sites where automatic extraction is unreliable, click "Select sections
manually" (on the home page, or on the choice screen after a schema.org-only
pass finds nothing usable). This fetches and sanitizes the real page (no
scripts, no third-party CSS, no working links) and shows it next to an
editable recipe form: click any text into the currently-focused field,
click a bulleted/numbered list to add every item at once, or click an image
to set the photo. No LLM is ever called on this path.

## Configuration

| Env var | Required | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | yes | Token with `repo` scope on the relay repo, used via the GitHub Contents API to publish pages (no git/SSH needed). Locally, `gh auth token` works if you're logged in with the `gh` CLI. |
| `GITHUB_REPO` | no | Defaults to `rmonk/umami-recipe-relay`. |
| `GITHUB_PAGES_BASE` | no | Defaults to `https://rmonk.github.io/umami-recipe-relay`. |
| `LLM_PROVIDER` | no | `anthropic` (default) or `gemini` — picks which LLM does the fallback extraction. |
| `ANTHROPIC_API_KEY` | if `LLM_PROVIDER=anthropic` | Needed for pages without clean schema.org markup, and for all PDF imports. |
| `GEMINI_API_KEY` | if `LLM_PROVIDER=gemini` | Same purpose, via Google Gemini instead of Claude. |

## Run locally

```
uv sync
uv run playwright install chromium
GITHUB_TOKEN=$(gh auth token) ANTHROPIC_API_KEY=... uv run --directory app python main.py
```

## Run in a container

```
docker build -t umami-recipe-importer .
docker run -p 8000:8000 \
  -e GITHUB_TOKEN=$(gh auth token) \
  -e ANTHROPIC_API_KEY=... \
  umami-recipe-importer
```

Then open http://localhost:8000, paste a URL (or upload a PDF), and click
through to umami.recipes to finish the import.

## Deploying via Arcane (Git Sync)

This repo lives at `github.com/rmonk/umami-importer` (public).
`docker-compose.yml` at the repo root reads every secret as a `${VAR}`
placeholder — none of them live in this repo.

**The image is built by GitHub Actions, not by Arcane.** Arcane hosts
running on Podman talk to it through Podman's Docker-compatible API, which
doesn't implement the BuildKit gRPC session a `docker build` needs — trying
to build there fails with `failed to dial gRPC: unable to upgrade to h2c,
received 404` (a known Podman limitation:
[containers/podman#17836](https://github.com/containers/podman/issues/17836)).
`.github/workflows/publish.yml` builds and pushes the image to
`ghcr.io/rmonk/umami-importer` on every push to `main`, and
`docker-compose.yml` references that image directly (`image:`, no `build:`
key), so Arcane only ever needs to `docker pull` it.

Verified after the first Actions run: `ghcr.io/rmonk/umami-importer:latest`
pulls anonymously with no credentials at all, so Arcane doesn't need a GHCR
credential to pull it. (GHCR packages built from a public repo via the
default `GITHUB_TOKEN` came out public automatically here — if a future push
ever creates the package as private instead, its visibility can be changed
under github.com/users/rmonk/packages/container/umami-importer/settings.)

1. In Arcane: **Customization → Variables** — add `GITHUB_TOKEN`,
   `ANTHROPIC_API_KEY` and/or `GEMINI_API_KEY`, and optionally
   `GITHUB_REPO` / `GITHUB_PAGES_BASE` / `LLM_PROVIDER` / `HOST_PORT` if you
   want non-default values. These are stored encrypted in Arcane and written
   to `.env.global` at deploy time — never committed here.
2. In Arcane: **Customization → Git Repositories** — add
   `https://github.com/rmonk/umami-importer`. Being public, no
   authentication is required for Arcane to pull it (a PAT or SSH key only
   matters if you ever use Push mode, or later make the repo private).
3. Create a **Git Sync** in **Pull** mode against that repository: branch
   `main`, Compose file path `docker-compose.yml` (repo root). Enable Auto
   Sync, and enable the post-sync image pull option, so a new push both
   updates the compose file (rarely) and pulls the freshly-published image
   (on every real code change) — a bare Git Sync without that option only
   notices file changes, not new image content behind the same tag.
