"""Extract a normalized recipe dict from a PDF. PDFs essentially never carry
schema.org markup, so this goes straight to Claude for structuring."""

from __future__ import annotations

import pdfplumber

from llm_extract import structure_recipe_text


def extract_from_pdf(path: str) -> dict:
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    text = "\n\n".join(text_parts)

    if not text.strip():
        raise ValueError(
            f"No extractable text found in {path}. It may be a scanned image "
            "PDF that needs OCR, which this tool doesn't yet support."
        )

    recipe = structure_recipe_text(text, source_url=None)
    recipe["image_url"] = None
    return recipe
