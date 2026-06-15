"""Generic URL scraper powered by OpenAI extraction."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

from scrapers.http import DEFAULT_HEADERS, fetch_html
from scrapers.openai_extractor import OpenAIExtractor


class OpenAIScraper:
    """Fetch web pages and extract product listings with OpenAI."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        max_pages: int = 1,
        delay_seconds: float = 1.0,
        instructions: str | None = None,
        verbose: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        self.extractor = OpenAIExtractor(api_key=api_key, model=model)
        self.max_pages = max(1, max_pages)
        self.delay_seconds = delay_seconds
        self.instructions = instructions
        self.verbose = verbose
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.start_url = ""

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

    @staticmethod
    def _build_page_url(base_url: str, page: int) -> str:
        if page == 1:
            return base_url

        parsed = urlparse(base_url)
        query = parse_qs(parsed.query)

        if "/str/" in parsed.path or "_pgn" in query:
            query["_pgn"] = [str(page)]
            query.setdefault("rt", ["nc"])
        elif "_ssn" in query or "/sch/" in parsed.path:
            query["_pgn"] = [str(page)]
        else:
            query["page"] = [str(page)]

        new_query = urlencode({key: values[-1] for key, values in query.items()})
        return urlunparse(parsed._replace(query=new_query))

    def scrape(self, url: str) -> list[dict[str, Any]]:
        self.start_url = url.rstrip("/")
        products: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for page in range(1, self.max_pages + 1):
            page_url = self._build_page_url(self.start_url, page)
            self._log(f"Fetching page {page}/{self.max_pages}: {page_url}")
            html = fetch_html(page_url, session=self.session)
            page_products = self.extractor.extract_products(
                html,
                page_url,
                instructions=self.instructions,
            )

            new_products: list[dict[str, Any]] = []
            for product in page_products:
                key = product.get("item_id") or product.get("url") or product["title"]
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                product["page"] = page
                new_products.append(product)

            self._log(
                f"Page {page}/{self.max_pages}: extracted {len(page_products)} listings "
                f"({len(new_products)} new, {len(products) + len(new_products)} total)"
            )

            if not new_products and page > 1:
                break

            products.extend(new_products)

            if page < self.max_pages and self.delay_seconds:
                time.sleep(self.delay_seconds)

        return products
