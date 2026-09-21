"""Render a normalized recipe dict as a clean, static HTML page carrying
schema.org/JSON-LD Recipe markup -- the format umami.recipes' own importer
already knows how to parse reliably (confirmed empirically against its
/api/can-import endpoint). This is the page we publish to the relay and hand
to umami's importer, instead of trying to write into umami's database
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


def _meta_item(label: str, value: str) -> str:
    return f"<div><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>"


def render_recipe_html(recipe: dict) -> str:
    name = recipe.get("name") or "Untitled recipe"
    ingredients = recipe.get("ingredients") or []
    directions = recipe.get("directions") or []
    notes = recipe.get("notes") or []
    servings = recipe.get("servings") or ""
    active_time = recipe.get("active_time") or ""
    total_time = recipe.get("total_time") or ""
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
    prep_iso = _to_iso_duration(active_time)
    total_iso = _to_iso_duration(total_time)
    if prep_iso:
        json_ld["cookTime"] = prep_iso
    if total_iso:
        json_ld["totalTime"] = total_iso
    if image_url:
        json_ld["image"] = image_url
    if source_url:
        json_ld["url"] = source_url

    ingredients_html = "\n".join(f"      <li>{_esc(i)}</li>" for i in ingredients)
    directions_html = "\n".join(f"      <li>{_esc(d)}</li>" for d in directions)
    notes_html = (
        '<div class="notes">\n<h2>Notes</h2>\n<ul>\n'
        + "\n".join(f"  <li>{_esc(n)}</li>" for n in notes)
        + "\n</ul>\n</div>"
        if notes
        else ""
    )
    meta_html = "".join(
        item
        for item in (
            servings and _meta_item("Servings", servings),
            active_time and _meta_item("Active", active_time),
            total_time and _meta_item("Total", total_time),
        )
        if item
    )
    image_html = f'<img src="{_esc(image_url)}" alt="{_esc(name)}">' if image_url else ""
    source_html = (
        f'<p class="source"><a href="{_esc(source_url)}">Original source</a></p>' if source_url else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(name)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/style.css">
{f'<meta property="og:image" content="{_esc(image_url)}">' if image_url else ""}
<meta property="og:title" content="{_esc(name)}">
<script type="application/ld+json">
{json.dumps(json_ld, ensure_ascii=False, indent=2)}
</script>
</head>
<body>
<article class="recipe">
  <header class="recipe-header">
    {image_html}
    <h1>{_esc(name)}</h1>
    <div class="recipe-meta">
      {meta_html}
    </div>
  </header>

  <div class="recipe-body">
    <section class="ingredients">
      <h2>Ingredients</h2>
      <ul>
{ingredients_html}
      </ul>
    </section>
    <section class="directions">
      <h2>Directions</h2>
      <ol>
{directions_html}
      </ol>
    </section>
  </div>

  {notes_html}
  {source_html}
</article>
</body>
</html>
"""
