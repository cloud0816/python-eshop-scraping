"""Extract structured product data from HTML using the OpenAI API."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from openai import OpenAI
from pydantic import BaseModel, Field

SYSTEM_PROMPT = """You extract product listings from e-commerce HTML snippets.
Each snippet usually represents one product card from a shop page.
Return every distinct product you can identify. Use absolute URLs when possible.
If a field is missing, leave it null. Do not invent products not present in the HTML."""


class ExtractedProduct(BaseModel):
    title: str
    price: str | None = None
    original_price: str | None = None
    url: str | None = None
    image_url: str | None = None
    description: str | None = None
    sku: str | None = None
    item_id: str | None = None


class ProductList(BaseModel):
    products: list[ExtractedProduct] = Field(default_factory=list)


def extract_relevant_html(html: str, max_chars: int = 250_000) -> str:
    """Keep product-card markup instead of truncating the page head."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "meta", "link"]):
        tag.decompose()

    selector_groups = [
        ["article.StoreFrontItemCard"],
        [".StoreFrontItemCard"],
        [".s-item"],
        [".srp-results .s-item"],
        [".product-card", ".product-item", ".grid-product", ".collection-product"],
        [".str-item-card"],
    ]

    for selectors in selector_groups:
        chunks: list[str] = []
        for selector in selectors:
            for element in soup.select(selector):
                chunks.append(str(element))
        if chunks:
            combined = "\n".join(dict.fromkeys(chunks))
            if len(combined) <= max_chars:
                return combined
            return combined[:max_chars] + "\n<!-- truncated -->"

    body = soup.body or soup
    fallback = str(body)
    if len(fallback) <= max_chars:
        return fallback
    return fallback[:max_chars] + "\n<!-- truncated -->"


def normalize_product(product: ExtractedProduct, source_url: str) -> dict[str, Any]:
    url = product.url
    if url and not url.startswith("http"):
        url = urljoin(source_url, url)

    image_url = product.image_url
    if image_url and not image_url.startswith("http"):
        image_url = urljoin(source_url, image_url)

    item_id = product.item_id
    if not item_id and url:
        match = re.search(r"/itm/(?P<item_id>\d+)", url)
        if match:
            item_id = match.group("item_id")

    return {
        "title": product.title.strip(),
        "price": product.price,
        "original_price": product.original_price,
        "url": url,
        "image_url": image_url,
        "description": product.description,
        "sku": product.sku,
        "item_id": item_id,
        "source_url": source_url,
    }


class OpenAIExtractor:
    """Use OpenAI structured outputs to parse product listings from HTML."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        max_html_chars: int = 250_000,
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
        relevant_html = extract_relevant_html(html, max_chars=self.max_html_chars)
        user_prompt = (
            f"Source URL: {source_url}\n\n"
            f"Extract all product listings from these HTML snippets:\n\n{relevant_html}"
        )
        if instructions:
            user_prompt += f"\n\nAdditional instructions:\n{instructions}"

        completion = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format=ProductList,
        )

        message = completion.choices[0].message
        if message.refusal:
            raise RuntimeError(f"OpenAI refused the request: {message.refusal}")

        parsed = message.parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned no parsed product data")

        return [normalize_product(product, source_url) for product in parsed.products]
