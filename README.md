# umami-recipe-importer

A small web app that takes a recipe URL or PDF, extracts the recipe more
reliably than umami.recipes' own importer, and hands you a link that
umami's importer can parse cleanly.

## How it works

umami.recipes has no published API, and its built-in URL importer often
fails on messy source pages (see `reference/umami_api.md` for the full
reverse-engineering notes). Rather than write into umami's database
directly, this tool:

1. Extracts the recipe itself — schema.org/JSON-LD first, falling back to
   Claude for pages without clean structured data (and for PDFs, which
   never have it). Sites that block plain HTTP requests are retried with a
   headless browser.
2. Re-renders the recipe as a clean, minimal HTML page with well-formed
   schema.org markup.
3. Publishes that page to a public GitHub Pages repo
   (`github.com/rmonk/umami-recipe-relay`) under an unlisted random URL.
4. Gives you `https://www.umami.recipes/import?url=<relay page>` — the same
   URL scheme umami's own Chrome extension uses — so umami's own importer
   does the actual save, using its normal supported flow.

## Configuration

| Env var | Required | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | yes | Token with `repo` scope on the relay repo, used via the GitHub Contents API to publish pages (no git/SSH needed). Locally, `gh auth token` works if you're logged in with the `gh` CLI. |
| `GITHUB_REPO` | no | Defaults to `rmonk/umami-recipe-relay`. |
| `GITHUB_PAGES_BASE` | no | Defaults to `https://rmonk.github.io/umami-recipe-relay`. |
| `ANTHROPIC_API_KEY` | for the fallback path | Needed for pages without clean schema.org markup, and for all PDF imports. Without it, only sites with good structured data will work. |

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
