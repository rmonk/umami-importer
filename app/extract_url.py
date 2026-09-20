"""Extract a normalized recipe dict from a URL.

Primary path: parse schema.org/JSON-LD Recipe markup (what most recipe sites
publish, and all umami.recipes' own importer relies on). Fallback: when
JSON-LD is missing or clearly incomplete, ask Claude to read the page text
and structure it -- this is the case that trips up umami's own importer.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from llm_extract import structure_recipe_text
from fetch_html import fetch_html

_DURATION_RE = re.compile(
    r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?"
)


def _duration_to_text(value) -> str:
    if not value or not isinstance(value, str):
        return ""
    m = _DURATION_RE.fullmatch(value.strip())
    if not m:
        return value
    parts = []
    days = int(m.group("days") or 0)
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hr{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} min")
    return " ".join(parts) if parts else value


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value
    return [value]


def _flatten_instructions(value) -> list[str]:
    steps: list[str] = []
    for item in _as_list(value):
        if isinstance(item, str):
            steps.append(item)
        elif isinstance(item, dict):
            item_type = item.get("@type", "")
            if item_type == "HowToSection":
                steps.extend(_flatten_instructions(item.get("itemListElement")))
            else:
                text = item.get("text") or item.get("name")
                if text:
                    steps.append(text)
    return steps


def _find_recipe_jsonld(soup: BeautifulSoup) -> dict | None:
    for tag in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data.get("@graph", [data]) if isinstance(data, dict) else data
        if not isinstance(candidates, list):
            candidates = [candidates]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            types = candidate.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(t == "Recipe" for t in types):
                return candidate
    return None


def _jsonld_to_recipe(data: dict, url: str) -> dict:
    name = data.get("name") or ""
    yield_value = data.get("recipeYield") or ""
    if isinstance(yield_value, list):
        yield_value = yield_value[0] if yield_value else ""

    image = data.get("image")
    if isinstance(image, dict):
        image = image.get("url")
    elif isinstance(image, list):
        image = image[0]
        if isinstance(image, dict):
            image = image.get("url")

    return {
        "name": name,
        "servings": str(yield_value),
        "active_time": _duration_to_text(data.get("cookTime") or data.get("prepTime")),
        "total_time": _duration_to_text(data.get("totalTime")),
        "ingredients": [str(i) for i in _as_list(data.get("recipeIngredient"))],
        "directions": _flatten_instructions(data.get("recipeInstructions")),
        "notes": [],
        "source_url": url,
        "image_url": image,
    }


def _is_complete(recipe: dict) -> bool:
    return bool(recipe["name"] and recipe["ingredients"] and recipe["directions"])


def _page_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "nav", "footer", "header", "svg"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))


def _og_image(soup: BeautifulSoup) -> str | None:
    tag = soup.find("meta", {"property": "og:image"})
    return tag.get("content") if tag else None


def extract_from_url(url: str) -> dict:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    jsonld = _find_recipe_jsonld(soup)
    recipe = _jsonld_to_recipe(jsonld, url) if jsonld else None

    if recipe is None or not _is_complete(recipe):
        text = _page_text(soup)
        structured = structure_recipe_text(text, source_url=url)
        if recipe is None:
            recipe = structured
        else:
            # keep whatever schema.org gave us; fill gaps from Claude
            for key in ("name", "servings", "active_time", "total_time", "ingredients", "directions", "notes"):
                if not recipe.get(key):
                    recipe[key] = structured.get(key)

    if not recipe.get("image_url"):
        recipe["image_url"] = _og_image(soup)

    return recipe
