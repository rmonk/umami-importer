"""Web app: paste a recipe URL or upload a PDF, get back a link that
umami.recipes' own importer can parse reliably.

Run locally:  uv run flask --app app.main run
Run in prod:  gunicorn -w 2 -b 0.0.0.0:8000 app.main:app
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import quote

from flask import Flask, render_template, request

from extract_pdf import extract_from_pdf
from extract_url import extract_from_url
from publish_recipe import PublishError, publish_recipe_html
from render_recipe_html import render_recipe_html

app = Flask(__name__)

UMAMI_IMPORT_BASE = "https://www.umami.recipes/import"


def _is_complete(recipe: dict) -> bool:
    return bool(recipe.get("name") and recipe.get("ingredients") and recipe.get("directions"))


@app.get("/")
def index():
    return render_template("index.html", error=None)


@app.post("/import")
def do_import():
    url = (request.form.get("url") or "").strip()
    pdf_file = request.files.get("pdf")

    try:
        if url:
            recipe = extract_from_url(url)
        elif pdf_file and pdf_file.filename:
            with tempfile.TemporaryDirectory() as tmp:
                pdf_path = Path(tmp) / "upload.pdf"
                pdf_file.save(pdf_path)
                recipe = extract_from_pdf(str(pdf_path))
        else:
            return render_template("index.html", error="Provide a URL or upload a PDF.")
    except Exception as exc:  # extraction failures are expected (bad urls, unreadable pdfs, etc.)
        return render_template("index.html", error=f"Couldn't extract a recipe: {exc}")

    if not _is_complete(recipe):
        return render_template(
            "index.html",
            error="Couldn't find a complete recipe (missing title, ingredients, or instructions).",
        )

    html = render_recipe_html(recipe)
    try:
        relay_url = publish_recipe_html(html)
    except PublishError as exc:
        return render_template("index.html", error=f"Couldn't publish the recipe page: {exc}")

    umami_import_url = f"{UMAMI_IMPORT_BASE}?url={quote(relay_url, safe='')}"

    return render_template(
        "result.html",
        recipe=recipe,
        relay_url=relay_url,
        umami_import_url=umami_import_url,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
