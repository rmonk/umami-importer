"""Publish recipe pages (and their photo, and a tracking manifest) to a
shared volume served by the relay-static container (see docker-compose.yml)
-- a file is visible the instant it's written, with no deploy/build lag and
no external API calls (unlike the earlier GitHub Pages approach).

Recipe pages are permanent: umami stores importUrl pointing back here, so a
recipe's "view source" link in umami should keep working. manifest.json (fed
to the static index.html/index.js bundled in relay_static/, copied onto the
volume once per publish) gives an easy, stable (but unlisted -- not linked
from any individual recipe page) way to find everything published.

Duplicates (the same source_url published more than once -- e.g. a client
retrying a request that had actually already succeeded) are handled two
ways: publish() reuses the existing slug for a source_url it's already seen,
overwriting that recipe's page in place rather than creating a second one;
cleanup_duplicates() is a self-healing pass (run once at app startup) that
merges any duplicate manifest entries and deletes their now-redundant files,
in case any slipped through before this existed, or some other path ever
reintroduces one.
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
# Only a fallback for ad-hoc local testing without the relay-static
# container (see README "Run locally") -- real deployments must set
# RELAY_PUBLIC_BASE explicitly; docker-compose.yml requires it outright.
DEFAULT_PUBLIC_BASE = "http://localhost:8081"
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


def _find_duplicate_slug(source_url: str, relay_dir: Path) -> str | None:
    """The slug of an already-published recipe with this source_url, if
    any -- so publish() can overwrite it in place instead of creating a
    second copy. Best-effort: a read failure just means no duplicate is
    detected, same as if there genuinely wasn't one."""
    manifest_path = relay_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                raw = f.read()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        entries = json.loads(raw) if raw.strip() else []
    except Exception:
        return None

    matches = [e for e in entries if e.get("source_url") == source_url and e.get("slug")]
    if not matches:
        return None
    return max(matches, key=lambda e: e.get("published_at", ""))["slug"]


def _upsert_manifest(slug: str, recipe: dict, relay_dir: Path) -> None:
    """File-locked read-modify-write -- local disk, so a lock is cheap, and
    avoids losing an entry when two publishes land concurrently (gunicorn
    runs multiple workers). Replaces the entry for `slug` if one already
    exists (re-publishing an already-seen source_url), otherwise appends.
    Best-effort: never raises, since the recipe page itself is already
    published and working even if this fails."""
    try:
        manifest_path = relay_dir / MANIFEST_NAME
        manifest_path.touch(exist_ok=True)
        with open(manifest_path, "r+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                raw = f.read()
                entries = json.loads(raw) if raw.strip() else []
                entries = [e for e in entries if e.get("slug") != slug]
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


def cleanup_duplicates(relay_dir: Path | None = None) -> int:
    """Keeps only the most-recently-published manifest entry per
    source_url, deleting the redundant recipe/photo files. Meant to be
    called once at app startup as a self-healing pass over whatever's
    already on the volume; safe to call repeatedly -- a no-op once nothing's
    left to merge. Returns how many duplicate entries were removed."""
    relay_dir = relay_dir or _relay_dir()
    manifest_path = relay_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return 0

    manifest_path.touch(exist_ok=True)
    with open(manifest_path, "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            raw = f.read()
            entries = json.loads(raw) if raw.strip() else []

            best_by_source: dict[str, dict] = {}
            keep: list[dict] = []
            for entry in entries:
                source_url = entry.get("source_url")
                if not source_url:
                    keep.append(entry)
                    continue
                current = best_by_source.get(source_url)
                if current is None or entry.get("published_at", "") > current.get("published_at", ""):
                    best_by_source[source_url] = entry
            keep.extend(best_by_source.values())

            keep_slugs = {e.get("slug") for e in keep}
            removed = [e for e in entries if e.get("slug") not in keep_slugs]

            if removed:
                for entry in removed:
                    slug = entry.get("slug")
                    if slug:
                        for path in (relay_dir / "recipes").glob(f"{slug}.*"):
                            path.unlink(missing_ok=True)
                f.seek(0)
                f.truncate()
                json.dump(keep, f, indent=2)

            return len(removed)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def publish(recipe: dict) -> tuple[str, dict]:
    """Render and publish a normalized recipe dict to the shared volume.
    Returns (relay_url, updated_recipe) -- updated_recipe has image_url
    rewritten to the re-hosted copy when a photo was published.

    Re-publishing a source_url that's already been published overwrites
    that recipe's existing page/photo in place (same slug, same URL) rather
    than creating a new one, so a client retrying a request -- even many
    times -- can't pile up duplicates."""
    relay_dir = _relay_dir()
    _ensure_static_assets(relay_dir)

    source_url = recipe.get("source_url")
    slug = (_find_duplicate_slug(source_url, relay_dir) if source_url else None) or new_slug()

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

    _upsert_manifest(slug, recipe, relay_dir)

    return relay_url, recipe
