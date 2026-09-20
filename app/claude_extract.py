"""Claude-based structured recipe extraction, used as a fallback when a page
has no (or incomplete) schema.org markup, and as the primary path for PDFs
(which essentially never carry structured recipe data)."""

from __future__ import annotations

import json
import os
import re

from anthropic import Anthropic

MODEL = "claude-sonnet-5"

_SYSTEM_PROMPT = """You extract recipes from raw page or document text into strict JSON.
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


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    return json.loads(text)


def structure_recipe_text(text: str, source_url: str | None = None) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Set it to enable Claude-based extraction "
            "for pages/PDFs without clean recipe markup."
        )

    client = Anthropic()
    truncated = text[:20000]
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": truncated}],
    )
    raw = "".join(block.text for block in response.content if block.type == "text")
    data = _extract_json(raw)

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
