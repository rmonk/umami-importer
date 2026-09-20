"""Fetch a page's HTML, falling back to a real (headless) browser for sites
that block plain HTTP clients (Cloudflare/Akamai/Reddit-style bot checks and
JS proof-of-work challenges, common on recipe sites and anything linking to
Reddit). Plain requests is tried first since it's much faster/cheaper."""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Below this much visible text, a "200 OK" response is almost certainly a bot
# challenge / consent / loading shell rather than real content -- raw HTML
# byte length is not a reliable signal, since challenge pages are often
# padded with large inline SVGs/CSS well past a few KB.
_MIN_VISIBLE_TEXT_CHARS = 200


class FetchError(RuntimeError):
    pass


def _visible_text_len(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return len(soup.get_text(strip=True))


def _looks_like_real_page(html: str) -> bool:
    return _visible_text_len(html) >= _MIN_VISIBLE_TEXT_CHARS


def _fetch_with_browser(url: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, timeout=30000, wait_until="domcontentloaded")

            # Give client-side rendering time to settle, then keep waiting a
            # bit longer if we're still looking at a bot-check/loading shell
            # (e.g. Reddit's JS proof-of-work challenge, which redirects to
            # the real page only after running and submitting a script).
            html = ""
            for _ in range(6):  # up to ~9s total beyond the initial 1.5s
                page.wait_for_timeout(1500)
                html = page.content()
                if _looks_like_real_page(html):
                    break
            return html
        finally:
            browser.close()


def fetch_html(url: str) -> str:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        if resp.ok and _looks_like_real_page(resp.text):
            return resp.text
    except requests.RequestException:
        pass

    try:
        return _fetch_with_browser(url)
    except Exception as exc:
        raise FetchError(f"Could not fetch {url} with plain HTTP or a headless browser: {exc}") from exc
