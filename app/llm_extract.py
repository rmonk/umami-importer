"""LLM-based structured recipe extraction, used as a fallback when a page
has no (or incomplete) schema.org markup, and as the primary path for PDFs
(which essentially never carry structured recipe data).

Supports two providers, selected via the LLM_PROVIDER env var:
- "anthropic" (default): Claude, via the `anthropic` SDK, ANTHROPIC_API_KEY.
- "gemini": Google Gemini, via the `google-genai` SDK, GEMINI_API_KEY.
"""

from __future__ import annotations

import json
import os
import re

from pydantic import BaseModel

ANTHROPIC_MODEL = "claude-opus-5"
GEMINI_MODEL = "gemini-3.8-flash"

_INSTRUCTIONS = """You extract recipes from raw page or document text into strict JSON.
Output ONLY a JSON object (no markdown fences, no commentary) with exactly these keys:
{
  "name": string,
  "servings": string,
  "active_time": string,
  "total_time": string,
  "ingredients": [string, ...],
  "directions": [string, ...],
  "notes": [string, ...]
}
Rules:
- "ingredients" is one entry per ingredient line, preserving quantities as written.
- "directions" is one entry per instruction step, in order.
- "notes" holds any tips, substitutions, or author commentary that isn't a step or ingredient. Use [] if none.
- "servings", "active_time", "total_time" are short free-text strings (e.g. "4 servings", "20 min"). Use "" if not stated.
- If the text contains no recipe at all, return all fields empty/blank.
- Ignore site navigation, ads, comments, and unrelated boilerplate.
"""


class RecipeExtraction(BaseModel):
    name: str
    servings: str
    active_time: str
    total_time: str
    ingredients: list[str]
    directions: list[str]
    notes: list[str]


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    return json.loads(text)


def _structure_with_anthropic(text: str) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Set it, or set LLM_PROVIDER=gemini with "
            "GEMINI_API_KEY, to enable extraction for pages/PDFs without clean markup."
        )

    from anthropic import Anthropic

    client = Anthropic()
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8000,
        system=_INSTRUCTIONS,
        messages=[{"role": "user", "content": text[:20000]}],
    )
    raw = "".join(block.text for block in response.content if block.type == "text")
    return _extract_json(raw)


def _structure_with_gemini(text: str) -> dict:
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Set it, or set LLM_PROVIDER=anthropic with "
            "ANTHROPIC_API_KEY, to enable extraction for pages/PDFs without clean markup."
        )

    from google import genai

    client = genai.Client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"{_INSTRUCTIONS}\n\n{text[:20000]}",
        config={"response_mime_type": "application/json", "response_schema": RecipeExtraction},
    )
    parsed: RecipeExtraction = response.parsed
    return parsed.model_dump()


def structure_recipe_text(text: str, source_url: str | None = None) -> dict:
    provider = _provider()
    if provider == "anthropic":
        data = _structure_with_anthropic(text)
    elif provider == "gemini":
        data = _structure_with_gemini(text)
    else:
        raise RuntimeError(f"Unknown LLM_PROVIDER {provider!r}; use 'anthropic' or 'gemini'.")

    return {
        "name": data.get("name") or "",
        "servings": data.get("servings") or "",
        "active_time": data.get("active_time") or "",
        "total_time": data.get("total_time") or "",
        "ingredients": list(data.get("ingredients") or []),
        "directions": list(data.get("directions") or []),
        "notes": list(data.get("notes") or []),
        "source_url": source_url,
        "image_url": None,
    }
