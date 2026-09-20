"""Strip a fetched page down to inert, styleable markup for the manual
"clip" view -- no scripts, no navigation, no third-party CSS. The page is
untrusted (arbitrary user-supplied URL); this is what keeps echoing it back
to the browser safe."""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

_STRIP_TAGS = ["script", "style", "link", "iframe", "object", "embed", "form", "noscript"]


def sanitize_for_clipping(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    for tag in soup.find_all("meta", attrs={"http-equiv": True}):
        tag.decompose()

    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.startswith("on") or attr == "style":
                del tag[attr]
            elif attr == "href" and str(tag.get(attr, "")).strip().lower().startswith("javascript:"):
                del tag[attr]

    for a in soup.find_all("a"):
        a.name = "span"
        a.attrs = {}

    for img in soup.find_all("img"):
        src = img.get("src")
        if src:
            img["src"] = urljoin(base_url, src)
        img.attrs.pop("srcset", None)

    return str(soup.body) if soup.body else str(soup)
