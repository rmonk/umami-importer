"""Render a normalized recipe dict as a clean, static HTML page carrying
schema.org/JSON-LD Recipe markup -- the format umami.recipes' own importer
already knows how to parse reliably (confirmed empirically against its
/api/can-import endpoint). This is the page we publish to GitHub Pages and
hand to umami's importer, instead of trying to write into umami's database
ourselves.
"""

from __future__ import annotations

import html
import json
import re

_TIME_RE = re.compile(
    r"(?:(?P<hours>\d+)\s*(?:hours?|hrs?|h)\b)?\D*(?:(?P<minutes>\d+)\s*(?:minutes?|mins?|m)\b)?",
    re.IGNORECASE,
)


def _to_iso_duration(text: str | None) -> str | None:
    if not text:
        return None
    m = _TIME_RE.search(text)
    if not m:
        return None
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    if not hours and not minutes:
        return None
    parts = "PT"
    if hours:
        parts += f"{hours}H"
    if minutes:
        parts += f"{minutes}M"
    return parts


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def render_recipe_html(recipe: dict) -> str:
    name = recipe.get("name") or "Untitled recipe"
    ingredients = recipe.get("ingredients") or []
    directions = recipe.get("directions") or []
    notes = recipe.get("notes") or []
    servings = recipe.get("servings") or ""
    image_url = recipe.get("image_url")
    source_url = recipe.get("source_url")

    json_ld = {
        "@context": "https://schema.org/",
        "@type": "Recipe",
        "name": name,
        "recipeIngredient": ingredients,
        "recipeInstructions": [{"@type": "HowToStep", "text": step} for step in directions],
    }
    if servings:
        json_ld["recipeYield"] = servings
    prep_iso = _to_iso_duration(recipe.get("active_time"))
    total_iso = _to_iso_duration(recipe.get("total_time"))
    if prep_iso:
        json_ld["cookTime"] = prep_iso
    if total_iso:
        json_ld["totalTime"] = total_iso
    if image_url:
        json_ld["image"] = image_url
    if source_url:
        json_ld["url"] = source_url

    ingredients_html = "\n".join(f"    <li>{_esc(i)}</li>" for i in ingredients)
    directions_html = "\n".join(f"    <li>{_esc(d)}</li>" for d in directions)
    notes_html = (
        "<h2>Notes</h2>\n<ul>\n" + "\n".join(f"    <li>{_esc(n)}</li>" for n in notes) + "\n</ul>"
        if notes
        else ""
    )
    meta_bits = " &middot; ".join(
        b
        for b in (
            servings and f"Servings: {_esc(servings)}",
            recipe.get("active_time") and f"Active: {_esc(recipe['active_time'])}",
            recipe.get("total_time") and f"Total: {_esc(recipe['total_time'])}",
        )
        if b
    )
    image_html = f'<img src="{_esc(image_url)}" alt="{_esc(name)}" style="max-width:100%">' if image_url else ""
    source_html = f'<p><a href="{_esc(source_url)}">Original source</a></p>' if source_url else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(name)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
{f'<meta property="og:image" content="{_esc(image_url)}">' if image_url else ""}
<meta property="og:title" content="{_esc(name)}">
<script type="application/ld+json">
{json.dumps(json_ld, ensure_ascii=False, indent=2)}
</script>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
h1 {{ margin-bottom: 0.25rem; }}
.meta {{ color: #555; margin-bottom: 1.5rem; }}
</style>
</head>
<body>
<h1>{_esc(name)}</h1>
<p class="meta">{meta_bits}</p>
{image_html}
<h2>Ingredients</h2>
<ul>
{ingredients_html}
</ul>
<h2>Instructions</h2>
<ol>
{directions_html}
</ol>
{notes_html}
{source_html}
</body>
</html>
"""
