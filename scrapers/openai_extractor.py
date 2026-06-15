"""Extract structured product data from HTML using the OpenAI API."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from openai import OpenAI

PRODUCT_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "price": {"type": ["string", "null"]},
                    "original_price": {"type": ["string", "null"]},
                    "url": {"type": ["string", "null"]},
                    "image_url": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "sku": {"type": ["string", "null"]},
                    "item_id": {"type": ["string", "null"]},
                },
                "required": [
                    "title",
                    "price",
                    "original_price",
                    "url",
                    "image_url",
                    "description",
                    "sku",
                    "item_id",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["products"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You extract product listings from e-commerce HTML.
Return every distinct product or service you can identify on the page.
Use absolute URLs when possible. If a field is missing in the HTML, use null.
Do not invent products that are not present in the provided HTML."""


def simplify_html(html: str, max_chars: int = 100_000) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "meta", "link"]):
        tag.decompose()
    simplified = str(soup)
    if len(simplified) > max_chars:
        return simplified[:max_chars] + "\n<!-- truncated -->"
    return simplified


def normalize_product(product: dict[str, Any], source_url: str) -> dict[str, Any]:
    url = product.get("url")
    if url and not url.startswith("http"):
        url = urljoin(source_url, url)

    image_url = product.get("image_url")
    if image_url and not image_url.startswith("http"):
        image_url = urljoin(source_url, image_url)

    return {
        "title": product["title"].strip(),
        "price": product.get("price"),
        "original_price": product.get("original_price"),
        "url": url,
        "image_url": image_url,
        "description": product.get("description"),
        "sku": product.get("sku"),
        "item_id": product.get("item_id"),
        "source_url": source_url,
    }


class OpenAIExtractor:
    """Use OpenAI structured outputs to parse product listings from HTML."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        max_html_chars: int = 100_000,
    ) -> None:
        resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved_key:
            raise ValueError(
                "OpenAI API key is required. Set OPENAI_API_KEY or pass --api-key."
            )
        self.client = OpenAI(api_key=resolved_key)
        self.model = model
        self.max_html_chars = max_html_chars

    def extract_products(
        self,
        html: str,
        source_url: str,
        instructions: str | None = None,
    ) -> list[dict[str, Any]]:
        simplified = simplify_html(html, max_chars=self.max_html_chars)
        user_prompt = (
            f"Source URL: {source_url}\n\n"
            f"Extract all product listings from this HTML:\n\n{simplified}"
        )
        if instructions:
            user_prompt += f"\n\nAdditional instructions:\n{instructions}"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "product_list",
                    "strict": True,
                    "schema": PRODUCT_LIST_SCHEMA,
                },
            },
        )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI returned an empty response")

        payload = json.loads(content)
        products = payload.get("products") or []
        return [normalize_product(product, source_url) for product in products]
