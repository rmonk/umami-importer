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
3. Publishes that page to a shared volume, served publicly by a second,
   very plain static-file-server container (`relay-static` in
   `docker-compose.yml`) under an unlisted random URL. A file is visible the
   instant it's written — no deploy pipeline, no external API calls, no
   propagation delay (an earlier version of this used GitHub Pages for this;
   that involved a real build-and-deploy step on every publish, which was
   slow enough to trip proxy timeouts — see `reference/umami_api.md` for the
   history if curious).
4. Gives you `https://www.umami.recipes/import?url=<relay page>` — the same
   URL scheme umami's own Chrome extension uses — so umami's own importer
   does the actual save, using its normal supported flow.

## Architecture: two containers, one volume

`umami-recipe-importer` (the Flask app) and `relay-static` (a bare
`nginx:alpine`) share a volume (`relay-data` in `docker-compose.yml`). The
app writes recipe pages, re-hosted photos, and `manifest.json` into it;
nginx just serves whatever's there, plus a small `index.html`/`index.js`
(bundled with the app, copied onto the volume on every publish) that fetches
`manifest.json` client-side to show a browsable list — a page like that
**can't** be how individual recipe pages work, though: umami.recipes fetches
them with a plain server-side HTTP request that never runs JavaScript, so
each recipe's schema.org/JSON-LD has to be present in the HTML bytes nginx
serves, not injected afterward.

`relay-static` needs to be reachable from the public internet (umami's
backend fetches from there), which the app container itself isn't — it's
only exposed over Tailscale via tsbridge. Point a real public hostname
(`RELAY_PUBLIC_BASE`, e.g. `https://recipes.example.com`) at
`relay-static`'s port however you already expose public services (reverse
proxy, tunnel, etc.) — that's separate from, and unrelated to, tsbridge's
Tailscale-only exposure of the app itself.

`relay-static/nginx.conf` adds `Access-Control-Allow-Origin: *` to every
response, which nginx doesn't send by default — umami's client-side photo
preview needs it to load the re-hosted image cross-origin (GitHub Pages,
the earlier host for this content, sent that header automatically; plain
nginx doesn't).

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
| `RELAY_PUBLIC_BASE` | yes | Public URL the `relay-static` container is reachable at, e.g. `https://recipes.example.com`. Used to build the links handed to umami.recipes. |
| `RELAY_DIR` | no | Path the app writes recipe pages to. Defaults to `/srv/relay`, which is also where `docker-compose.yml` mounts the shared volume — only change both together. |
| `RELAY_PORT` | no | Host port `relay-static` listens on. Defaults to `8081`; point your public hostname's reverse proxy/tunnel at this port. |
| `LLM_PROVIDER` | no | `anthropic` (default) or `gemini` — picks which LLM does the fallback extraction. |
| `ANTHROPIC_API_KEY` | if `LLM_PROVIDER=anthropic` | Needed for pages without clean schema.org markup, and for all PDF imports. |
| `GEMINI_API_KEY` | if `LLM_PROVIDER=gemini` | Same purpose, via Google Gemini instead of Claude. |
| `TSBRIDGE_SERVICE_NAME` | no | Tailscale hostname [tsbridge](https://github.com/jtdowney/tsbridge) exposes this service as. Defaults to `umami-importer`. |
| `TSBRIDGE_SERVICE_TAGS` | no | Comma-separated Tailscale tags (e.g. `tag:home,tag:media`) for the [tsbridge](https://github.com/jtdowney/tsbridge) label. Empty by default. |

Compose does `${VAR}` substitution across the whole file, not just
`environment:` — so the `labels:` block (for
[tsbridge](https://github.com/jtdowney/tsbridge), which reads Docker labels
to auto-expose services on a Tailnet) uses the exact same pattern as every
secret above. Any tsbridge label whose value you don't want sitting in a
public repo (hostname, tags, anything else from tsbridge's [full label
reference](https://github.com/jtdowney/tsbridge/blob/main/docs/docker-labels.md))
can be swapped for a `${SOME_VAR}` placeholder the same way and set via
Arcane's Variables feature — nothing tsbridge-specific about the mechanism.

## Run locally

```
uv sync
uv run playwright install chromium
ANTHROPIC_API_KEY=... uv run --directory app python main.py
```

Without `relay-static` running alongside it, publishing still writes to
`RELAY_DIR` (`/srv/relay` by default) fine, but nothing serves those files —
enough to confirm extraction and file-writing work, not enough to actually
hand umami a working link. For that, run the full stack:

```
docker build -t umami-recipe-importer .
docker network create relay-net
docker volume create relay-data
docker run -d --name relay-static --network relay-net \
  -v relay-data:/usr/share/nginx/html \
  -v ./relay-static/nginx.conf:/etc/nginx/conf.d/default.conf:ro \
  -p 8081:80 nginx:alpine
docker run -d --name umami-recipe-importer --network relay-net \
  -v relay-data:/srv/relay \
  -e RELAY_PUBLIC_BASE=http://localhost:8081 \
  -e ANTHROPIC_API_KEY=... \
  -p 8000:8000 umami-recipe-importer
```

Then open http://localhost:8000, paste a URL (or upload a PDF), and click
through to umami.recipes to finish the import. (The Arcane deployment below
does this same two-container, one-volume shape via `docker-compose.yml`
directly, rather than raw `docker run`.)

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

`relay-static` uses the stock `nginx:alpine` image directly (no building
involved there either, just a pull), so the whole stack only ever needs
Arcane to pull images, never build one — the point of the GHCR setup above.

1. In Arcane: **Customization → Variables** — add `ANTHROPIC_API_KEY`
   and/or `GEMINI_API_KEY`, and `RELAY_PUBLIC_BASE` (your actual public
   hostname, e.g. `https://recipes.example.com`), plus optionally
   `LLM_PROVIDER` / `HOST_PORT` / `RELAY_PORT` if you want non-default
   values. These are stored encrypted in Arcane and written to `.env.global`
   at deploy time — never committed here.
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
4. Point `RELAY_PUBLIC_BASE`'s hostname at `relay-static`'s published port
   (`RELAY_PORT`, default `8081`) however you already expose public
   services on this host — a reverse proxy entry, a tunnel, whatever you use
   for other public domains. This is separate from tsbridge, which only
   reaches `umami-recipe-importer` itself over Tailscale.
