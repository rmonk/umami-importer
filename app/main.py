"""Web app: paste a recipe URL or upload a PDF, get back a link that
umami.recipes' own importer can parse reliably.

Run locally:  uv run flask --app app.main run
Run in prod:  gunicorn -w 2 -b 0.0.0.0:8000 app.main:app
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from urllib.parse import quote

from flask import Flask, render_template, request

import publish_recipe
from extract_pdf import extract_from_pdf
from extract_url import extract_from_url, extract_schema_org, is_recipe_complete
from publish_recipe import PublishError
from sanitize_html import sanitize_for_clipping
from fetch_html import fetch_html, FetchError

app = Flask(__name__)

UMAMI_IMPORT_BASE = "https://www.umami.recipes/import"


def _publish_and_render(recipe: dict):
    try:
        relay_url, recipe, is_live = publish_recipe.publish(recipe)
    except PublishError as exc:
        return render_template("index.html", error=f"Couldn't publish the recipe page: {exc}")

    umami_import_url = f"{UMAMI_IMPORT_BASE}?url={quote(relay_url, safe='')}"

    return render_template(
        "result.html",
        recipe=recipe,
        relay_url=relay_url,
        umami_import_url=umami_import_url,
        is_live=is_live,
    )


@app.get("/")
def index():
    return render_template("index.html", error=None)


def _handle_url_import(url: str):
    """Free schema.org-only pass; complete -> publish immediately, otherwise
    let the user pick AI extraction vs. manual selection."""
    try:
        recipe = extract_schema_org(url)
    except FetchError as exc:
        return render_template("index.html", error=f"Couldn't fetch that page: {exc}")

    if is_recipe_complete(recipe):
        return _publish_and_render(recipe)

    return render_template("choose_method.html", url=url)


@app.get("/import")
def do_import_get():
    """Same as POST /import's URL path, reachable by plain navigation (e.g.
    an iOS Shortcut in the Share Sheet opening /import?url=<shared link>,
    since Shortcuts' "Open URL" action is much simpler than a POST)."""
    url = (request.args.get("url") or "").strip()
    if not url:
        return render_template("index.html", error="Missing URL.")
    return _handle_url_import(url)


@app.post("/import")
def do_import():
    """Home page entry point. URLs get the free schema.org-only pass first;
    PDFs go straight through the LLM (they never carry structured data)."""
    url = (request.form.get("url") or "").strip()
    pdf_file = request.files.get("pdf")

    if url:
        return _handle_url_import(url)

    if pdf_file and pdf_file.filename:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                pdf_path = Path(tmp) / "upload.pdf"
                pdf_file.save(pdf_path)
                recipe = extract_from_pdf(str(pdf_path))
        except Exception as exc:
            return render_template("index.html", error=f"Couldn't extract a recipe: {exc}")

        if not is_recipe_complete(recipe):
            return render_template(
                "index.html",
                error="Couldn't find a complete recipe (missing title, ingredients, or instructions).",
            )
        return _publish_and_render(recipe)

    return render_template("index.html", error="Provide a URL or upload a PDF.")


@app.post("/import/ai")
def do_import_ai():
    """Opt-in LLM fallback extraction, reached from choose_method.html after
    a free schema.org-only pass came up empty."""
    url = (request.form.get("url") or "").strip()
    if not url:
        return render_template("index.html", error="Missing URL.")

    try:
        recipe = extract_from_url(url)
    except Exception as exc:
        return render_template("index.html", error=f"Couldn't extract a recipe: {exc}")

    if not is_recipe_complete(recipe):
        return render_template(
            "index.html",
            error="Couldn't find a complete recipe (missing title, ingredients, or instructions).",
        )
    return _publish_and_render(recipe)


@app.get("/clip")
def clip():
    """Manual selection tool: shows a sanitized version of the page (no
    scripts, no third-party CSS, no navigation) alongside an editable recipe
    form. Never calls an LLM."""
    url = (request.args.get("url") or "").strip()
    if not url:
        return render_template("index.html", error="Missing URL.")

    try:
        html = fetch_html(url)
    except FetchError as exc:
        return render_template("index.html", error=f"Couldn't fetch that page: {exc}")

    try:
        prefill = extract_schema_org(url)
    except Exception:
        prefill = {"name": "", "servings": "", "active_time": "", "total_time": "",
                   "ingredients": [], "directions": [], "notes": [], "image_url": None}

    sanitized = sanitize_for_clipping(html, url)

    return render_template(
        "clip.html",
        url=url,
        sanitized_html=sanitized,
        prefill=prefill,
    )


@app.post("/import/manual")
def do_import_manual():
    """Publishes a recipe assembled by hand in the clip view -- no LLM call."""
    try:
        recipe = json.loads(request.form.get("recipe") or "{}")
    except json.JSONDecodeError:
        return render_template("index.html", error="Malformed manual recipe submission.")

    recipe = {
        "name": (recipe.get("name") or "").strip(),
        "servings": (recipe.get("servings") or "").strip(),
        "active_time": (recipe.get("active_time") or "").strip(),
        "total_time": (recipe.get("total_time") or "").strip(),
        "ingredients": [line for line in recipe.get("ingredients", []) if line.strip()],
        "directions": [line for line in recipe.get("directions", []) if line.strip()],
        "notes": [line for line in recipe.get("notes", []) if line.strip()],
        "source_url": (recipe.get("source_url") or "").strip() or None,
        "image_url": (recipe.get("image_url") or "").strip() or None,
    }

    if not is_recipe_complete(recipe):
        return render_template(
            "index.html",
            error="Couldn't publish: fill in at least a title, ingredients, and directions.",
        )

    return _publish_and_render(recipe)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
