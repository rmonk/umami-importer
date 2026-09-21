"""Publish recipe pages (and their photo, and a tracking manifest) to a
shared volume served by the relay-static container (see docker-compose.yml)
-- a file is visible the instant it's written, with no deploy/build lag and
no external API calls (unlike the earlier GitHub Pages approach).

Recipe pages are permanent: umami stores importUrl pointing back here, so a
recipe's "view source" link in umami should keep working. manifest.json (fed
to the static index.html/index.js bundled in relay_static/, copied onto the
volume once per publish) gives an easy, stable (but unlisted -- not linked
from any individual recipe page) way to find everything published.
"""

from __future__ import annotations

import fcntl
import json
import mimetypes
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

import requests

from render_recipe_html import render_recipe_html

DEFAULT_RELAY_DIR = "/srv/relay"
DEFAULT_PUBLIC_BASE = "https://recipes.example.com"
MANIFEST_NAME = "manifest.json"

_STATIC_ASSETS_DIR = Path(__file__).resolve().parent / "relay_static"


class PublishError(RuntimeError):
    pass


def _relay_dir() -> Path:
    path = Path(os.environ.get("RELAY_DIR", DEFAULT_RELAY_DIR))
    (path / "recipes").mkdir(parents=True, exist_ok=True)
    return path


def _public_base() -> str:
    return os.environ.get("RELAY_PUBLIC_BASE", DEFAULT_PUBLIC_BASE).rstrip("/")


def _ensure_static_assets(relay_dir: Path) -> None:
    """Copies the bundled index.html/index.js (the manifest-browsing UI)
    onto the shared volume. Safe to call on every publish -- it's just an
    overwrite, which keeps them in sync with whatever app version is
    running."""
    for name in ("index.html", "index.js"):
        shutil.copyfile(_STATIC_ASSETS_DIR / name, relay_dir / name)


def new_slug() -> str:
    return secrets.token_urlsafe(12).replace("_", "").replace("-", "")


def _rehost_image(image_url: str, slug: str, relay_dir: Path) -> str | None:
    """Download the recipe's hero image and re-host it alongside the recipe
    page, so umami's client-side preview (which needs CORS to load it) isn't
    at the mercy of the source site's CDN, which usually sends no CORS
    headers at all -- relay-static's nginx.conf adds one for everything it
    serves. Returns None (rather than raising) if this fails -- a missing
    photo shouldn't block the rest of the import."""
    try:
        resp = requests.get(image_url, timeout=30)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        dest = relay_dir / "recipes" / f"{slug}{ext}"
        dest.write_bytes(resp.content)
        return f"{_public_base()}/recipes/{slug}{ext}"
    except Exception:
        return None


def _update_manifest(slug: str, recipe: dict, relay_dir: Path) -> None:
    """File-locked read-modify-write -- local disk, so a lock is cheap, and
    avoids losing an entry when two publishes land concurrently (gunicorn
    runs multiple workers). Best-effort: never raises, since the recipe page
    itself is already published and working even if this fails."""
    try:
        manifest_path = relay_dir / MANIFEST_NAME
        manifest_path.touch(exist_ok=True)
        with open(manifest_path, "r+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                raw = f.read()
                entries = json.loads(raw) if raw.strip() else []
                entries.append(
                    {
                        "slug": slug,
                        "name": recipe.get("name") or "Untitled recipe",
                        "source_url": recipe.get("source_url"),
                        "published_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                f.seek(0)
                f.truncate()
                json.dump(entries, f, indent=2)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        pass


def publish(recipe: dict) -> tuple[str, dict]:
    """Render and publish a normalized recipe dict to the shared volume.
    Returns (relay_url, updated_recipe) -- updated_recipe has image_url
    rewritten to the re-hosted copy when a photo was published."""
    relay_dir = _relay_dir()
    _ensure_static_assets(relay_dir)
    slug = new_slug()

    if recipe.get("image_url"):
        hosted = _rehost_image(recipe["image_url"], slug, relay_dir)
        if hosted:
            recipe = {**recipe, "image_url": hosted}

    html = render_recipe_html(recipe)
    dest = relay_dir / "recipes" / f"{slug}.html"
    try:
        dest.write_text(html, encoding="utf-8")
    except OSError as exc:
        raise PublishError(f"Couldn't write {dest}: {exc}") from exc

    relay_url = f"{_public_base()}/recipes/{slug}.html"

    _update_manifest(slug, recipe, relay_dir)

    return relay_url, recipe
