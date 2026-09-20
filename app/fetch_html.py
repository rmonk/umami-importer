"""Fetch a page's HTML, falling back to a real (headless) browser for sites
that block plain HTTP clients (Cloudflare/Akamai-style bot checks, common on
recipe sites). Plain requests is tried first since it's much faster/cheaper."""

from __future__ import annotations

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class FetchError(RuntimeError):
    pass


def _fetch_with_browser(url: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)  # let client-side rendering/JSON-LD injection settle
            return page.content()
        finally:
            browser.close()


def fetch_html(url: str) -> str:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        if resp.ok and len(resp.text) > 2000:
            return resp.text
    except requests.RequestException:
        pass

    try:
        return _fetch_with_browser(url)
    except Exception as exc:
        raise FetchError(f"Could not fetch {url} with plain HTTP or a headless browser: {exc}") from exc
