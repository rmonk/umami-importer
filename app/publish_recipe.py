"""Publish recipe pages (and their photo, and a tracking index) to the
umami-recipe-relay GitHub Pages repo via the GitHub Contents API (not
git/SSH), so this works from inside a container with just a token.

Recipe pages are permanent: umami stores importUrl pointing back here, so a
recipe's "view source" link in umami should keep working. A manifest.json +
generated index.html at the repo root give the user an easy, stable (but
unlisted -- not linked from any individual recipe page) way to find
everything that's been published.
"""

from __future__ import annotations

import base64
import html as html_module
import json
import mimetypes
import os
import secrets
import time
from datetime import datetime, timezone

import requests

from render_recipe_html import render_recipe_html

DEFAULT_REPO = "rmonk/umami-recipe-relay"
DEFAULT_PAGES_BASE = "https://rmonk.github.io/umami-recipe-relay"
MANIFEST_PATH = "manifest.json"
INDEX_PATH = "index.html"


class PublishError(RuntimeError):
    pass


def _repo() -> str:
    return os.environ.get("GITHUB_REPO", DEFAULT_REPO)


def _pages_base() -> str:
    return os.environ.get("GITHUB_PAGES_BASE", DEFAULT_PAGES_BASE)


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise PublishError(
            f"GITHUB_TOKEN is not set. It needs `repo` scope on {_repo()}."
        )
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _get_file(path: str) -> tuple[bytes | None, str | None]:
    resp = requests.get(
        f"https://api.github.com/repos/{_repo()}/contents/{path}",
        headers=_headers(),
        timeout=30,
    )
    if resp.status_code == 404:
        return None, None
    if not resp.ok:
        raise PublishError(f"GitHub read failed for {path} ({resp.status_code}): {resp.text}")
    body = resp.json()
    return base64.b64decode(body["content"]), body["sha"]


def _put_file(path: str, content: bytes, message: str, sha: str | None = None, _attempts: int = 4) -> None:
    """The Contents API isn't atomic across concurrent requests -- it reads
    the branch tip, builds a commit, then does a compare-and-swap on the ref.
    Two overlapping publishes (gunicorn runs multiple workers) can race that
    last step and get a 409 regardless of which files they're touching, not
    just genuine sha conflicts on the same path. Retry: for a new file (no
    sha) the same request is safe to resend; for an update, refresh the
    file's current sha first."""
    for attempt in range(_attempts):
        payload = {"message": message, "content": base64.b64encode(content).decode("ascii")}
        if sha:
            payload["sha"] = sha
        resp = requests.put(
            f"https://api.github.com/repos/{_repo()}/contents/{path}",
            headers=_headers(),
            json=payload,
            timeout=30,
        )
        if resp.ok:
            return
        if resp.status_code == 409 and attempt < _attempts - 1:
            time.sleep(0.5 * (2**attempt))
            if sha:
                _, sha = _get_file(path)
            continue
        raise PublishError(f"GitHub write failed for {path} ({resp.status_code}): {resp.text}")


def new_slug() -> str:
    return secrets.token_urlsafe(12).replace("_", "").replace("-", "")


def _rehost_image(image_url: str, slug: str) -> str | None:
    """Download the recipe's hero image and re-host it in the relay repo, so
    umami's client-side preview (which needs CORS to load it) isn't at the
    mercy of the source site's CDN, which usually sends no CORS headers at
    all. Returns None (rather than raising) if this fails -- a missing photo
    shouldn't block the rest of the import."""
    try:
        resp = requests.get(image_url, timeout=30)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        path = f"recipes/{slug}{ext}"
        _put_file(path, resp.content, f"Add photo for {slug}")
        return f"{_pages_base()}/{path}"
    except Exception:
        return None


def _update_index(slug: str, recipe: dict) -> None:
    """Best-effort: append this recipe to manifest.json and regenerate
    index.html. Never raises -- the recipe page itself is already published
    and working even if this fails."""
    try:
        entries_raw, sha = _get_file(MANIFEST_PATH)
        entries = json.loads(entries_raw) if entries_raw else []
        entries.append(
            {
                "slug": slug,
                "name": recipe.get("name") or "Untitled recipe",
                "source_url": recipe.get("source_url"),
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        _put_file(
            MANIFEST_PATH,
            json.dumps(entries, indent=2).encode("utf-8"),
            f"Track recipe {slug}",
            sha=sha,
        )
        _, index_sha = _get_file(INDEX_PATH)
        _put_file(
            INDEX_PATH,
            _render_index_html(entries).encode("utf-8"),
            f"Update index for {slug}",
            sha=index_sha,
        )
    except Exception:
        pass


def _render_index_html(entries: list[dict]) -> str:
    rows = []
    for entry in sorted(entries, key=lambda e: e["published_at"], reverse=True):
        name = html_module.escape(entry["name"])
        date = entry["published_at"][:10]
        recipe_link = f'<a href="recipes/{entry["slug"]}.html">{name}</a>'
        source = entry.get("source_url")
        source_link = f' &middot; <a href="{html_module.escape(source)}">source</a>' if source else ""
        rows.append(f"<li>{date} &mdash; {recipe_link}{source_link}</li>")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>umami-recipe-relay</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }}
li {{ margin-bottom: 0.4rem; }}
</style>
</head>
<body>
<h1>Recipe relay pages</h1>
<p>These pages exist so umami.recipes can import recipes cleanly. Not linked
from anywhere else -- keep this URL to yourself.</p>
<ul>
{chr(10).join(rows)}
</ul>
</body>
</html>
"""


def _wait_until_live(url: str, timeout: float = 20, interval: float = 2) -> bool:
    """GitHub Pages takes a while (seconds to ~a minute) to deploy after a
    commit. Poll until the page is actually reachable so we never hand the
    user a link that 404s. Returns False (not an error) on timeout -- the
    page will likely finish deploying moments later regardless.

    Kept short on purpose: this runs inside one synchronous HTTP request, and
    every second here adds to the odds of tripping a proxy's write timeout
    (see docker-compose.yml's tsbridge.service.write_timeout) before the
    -- otherwise successful -- response ever reaches the client."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if requests.head(url, timeout=10, allow_redirects=True).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(interval)
    return False


def publish(recipe: dict) -> tuple[str, dict, bool]:
    """Render, publish, and index a normalized recipe dict. Returns
    (relay_url, updated_recipe, is_live) -- updated_recipe has image_url
    rewritten to the re-hosted copy when a photo was published, and is_live
    is False if the page hadn't finished deploying by the timeout."""
    slug = new_slug()

    if recipe.get("image_url"):
        hosted = _rehost_image(recipe["image_url"], slug)
        if hosted:
            recipe = {**recipe, "image_url": hosted}

    html = render_recipe_html(recipe)
    path = f"recipes/{slug}.html"
    _put_file(path, html.encode("utf-8"), f"Add recipe {slug}")
    relay_url = f"{_pages_base()}/{path}"

    _update_index(slug, recipe)

    is_live = _wait_until_live(relay_url)

    return relay_url, recipe, is_live
