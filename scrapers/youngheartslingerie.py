"""Scraper for https://youngheartslingerie.com/ product catalog (Shopify)."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urljoin

import requests

BASE_URL = "https://youngheartslingerie.com"
PRODUCTS_JSON_URL = f"{BASE_URL}/products.json"
MAX_PAGE_SIZE = 250


@dataclass
class ProductVariant:
    id: int
    title: str
    sku: str | None
    price: str
    compare_at_price: str | None
    available: bool
    option1: str | None = None
    option2: str | None = None
    option3: str | None = None


@dataclass
class Product:
    id: int
    title: str
    handle: str
    url: str
    vendor: str | None
    product_type: str | None
    tags: list[str]
    description_html: str | None
    price: str | None
    price_min: str | None
    price_max: str | None
    compare_at_price: str | None
    image_url: str | None
    images: list[str] = field(default_factory=list)
    sku: str | None = None
    available: bool = False
    variants: list[ProductVariant] = field(default_factory=list)
    published_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class YoungHeartsLingerieScraper:
    """Fetch Young Hearts Lingerie products from the public Shopify products.json API."""

    def __init__(
        self,
        session: requests.Session | None = None,
        page_size: int = MAX_PAGE_SIZE,
        max_pages: int | None = None,
        delay_seconds: float = 0.5,
        verbose: bool = False,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent",
            "python-eshop-scraping/1.0 (+https://youngheartslingerie.com/)",
        )
        self.page_size = min(page_size, MAX_PAGE_SIZE)
        self.max_pages = max_pages
        self.delay_seconds = delay_seconds
        self.verbose = verbose

    def _fetch_page(self, page: int) -> list[dict[str, Any]]:
        response = self.session.get(
            PRODUCTS_JSON_URL,
            params={"limit": self.page_size, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("products") or []

    @staticmethod
    def _variant_prices(variants: list[dict[str, Any]]) -> tuple[str | None, str | None]:
        prices = [variant["price"] for variant in variants if variant.get("price")]
        if not prices:
            return None, None
        return min(prices), max(prices)

    @staticmethod
    def _normalize_variant(item: dict[str, Any]) -> ProductVariant:
        return ProductVariant(
            id=item["id"],
            title=(item.get("title") or "").strip(),
            sku=(item.get("sku") or None) or None,
            price=item.get("price") or "",
            compare_at_price=(item.get("compare_at_price") or None) or None,
            available=bool(item.get("available")),
            option1=item.get("option1"),
            option2=item.get("option2"),
            option3=item.get("option3"),
        )

    @staticmethod
    def _parse_tags(raw_tags: Any) -> list[str]:
        if isinstance(raw_tags, list):
            return [str(tag).strip() for tag in raw_tags if str(tag).strip()]
        if isinstance(raw_tags, str):
            return [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
        return []

    def _normalize_product(self, item: dict[str, Any]) -> Product:
        handle = (item.get("handle") or "").strip()
        variants = [self._normalize_variant(variant) for variant in item.get("variants") or []]
        price_min, price_max = self._variant_prices(item.get("variants") or [])
        images = [image["src"] for image in item.get("images") or [] if image.get("src")]
        tags = self._parse_tags(item.get("tags"))

        compare_prices = [
            variant.compare_at_price
            for variant in variants
            if variant.compare_at_price and variant.compare_at_price != variant.price
        ]

        return Product(
            id=item["id"],
            title=(item.get("title") or "").strip(),
            handle=handle,
            url=urljoin(BASE_URL, f"/products/{handle}"),
            vendor=(item.get("vendor") or None),
            product_type=(item.get("product_type") or None),
            tags=tags,
            description_html=(item.get("body_html") or None),
            price=price_min,
            price_min=price_min,
            price_max=price_max,
            compare_at_price=compare_prices[0] if compare_prices else None,
            image_url=images[0] if images else None,
            images=images,
            sku=variants[0].sku if variants else None,
            available=any(variant.available for variant in variants),
            variants=variants,
            published_at=item.get("published_at"),
            created_at=item.get("created_at"),
            updated_at=item.get("updated_at"),
        )

    def fetch_products(self) -> list[Product]:
        products: list[Product] = []
        seen_ids: set[int] = set()
        page = 1

        while True:
            if self.max_pages is not None and page > self.max_pages:
                break

            items = self._fetch_page(page)
            if not items:
                break

            if self.verbose:
                print(f"Fetched page {page}: {len(items)} products")

            for item in items:
                product_id = item.get("id")
                if product_id in seen_ids:
                    continue
                seen_ids.add(product_id)
                products.append(self._normalize_product(item))

            if len(items) < self.page_size:
                break

            page += 1
            if self.delay_seconds > 0:
                time.sleep(self.delay_seconds)

        return products

    def scrape(self) -> list[dict[str, Any]]:
        return [asdict(product) for product in self.fetch_products()]
