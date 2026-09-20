"""Publish a rendered recipe page to the umami-recipe-relay GitHub Pages repo
via the GitHub Contents API (not git/SSH), so this works from inside a
container with just a token -- no git binary, no SSH keys, no local clone.

One-time setup (already done for this repo): a public GitHub repo with Pages
enabled serving from the `main` branch root. See reference/umami_api.md.
"""

from __future__ import annotations

import base64
import os
import secrets

import requests

DEFAULT_REPO = "rmonk/umami-recipe-relay"
DEFAULT_PAGES_BASE = "https://rmonk.github.io/umami-recipe-relay"


class PublishError(RuntimeError):
    pass


def _github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise PublishError(
            "GITHUB_TOKEN is not set. It needs `repo` scope on the relay repo "
            f"({os.environ.get('GITHUB_REPO', DEFAULT_REPO)})."
        )
    return token


def publish_recipe_html(html: str, slug: str | None = None) -> str:
    """Commit `html` to recipes/<slug>.html on the relay repo's default
    branch and return its public GitHub Pages URL."""
    repo = os.environ.get("GITHUB_REPO", DEFAULT_REPO)
    pages_base = os.environ.get("GITHUB_PAGES_BASE", DEFAULT_PAGES_BASE)
    slug = slug or secrets.token_urlsafe(12).replace("_", "").replace("-", "")
    path = f"recipes/{slug}.html"

    resp = requests.put(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers={
            "Authorization": f"Bearer {_github_token()}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "message": f"Add recipe page {slug}",
            "content": base64.b64encode(html.encode("utf-8")).decode("ascii"),
        },
        timeout=30,
    )
    if not resp.ok:
        raise PublishError(f"GitHub publish failed ({resp.status_code}): {resp.text}")

    return f"{pages_base}/{path}"
