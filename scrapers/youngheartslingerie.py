"""Scraper for https://youngheartslingerie.com/ product catalog (Shopify)."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

import requests

from scrapers.http import DEFAULT_HEADERS

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
        if not session:
            self.session.headers.update(DEFAULT_HEADERS)
        self.session.headers.setdefault(
            "Accept",
            "application/json",
        )
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

        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type.lower():
            raise RuntimeError(
                f"Expected JSON from {PRODUCTS_JSON_URL} (page {page}), "
                f"got {content_type or 'unknown content type'}"
            )

        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"Invalid JSON from {PRODUCTS_JSON_URL} (page {page}): {error}"
            ) from error

        products = payload.get("products")
        if products is None:
            raise RuntimeError(
                f"Missing 'products' key in Shopify response for page {page}"
            )
        if not isinstance(products, list):
            raise RuntimeError(
                f"Expected 'products' to be a list on page {page}, got {type(products).__name__}"
            )
        return products

    @staticmethod
    def _parse_price(value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @staticmethod
    def _format_price(value: Decimal) -> str:
        return f"{value.quantize(Decimal('0.01'))}"

    @classmethod
    def _variant_prices(
        cls,
        variants: list[dict[str, Any]],
    ) -> tuple[str | None, str | None, str | None]:
        priced_variants: list[tuple[Decimal, dict[str, Any]]] = []
        for variant in variants:
            price = cls._parse_price(variant.get("price"))
            if price is not None:
                priced_variants.append((price, variant))

        if not priced_variants:
            return None, None, None

        price_values = [price for price, _ in priced_variants]
        price_min = min(price_values)
        price_max = max(price_values)

        compare_at_price = None
        for price, variant in priced_variants:
            if price != price_min:
                continue
            compare_at = cls._parse_price(variant.get("compare_at_price"))
            if compare_at is not None and compare_at > price:
                compare_at_price = cls._format_price(compare_at)
                break

        if compare_at_price is None:
            for _, variant in priced_variants:
                price = cls._parse_price(variant.get("price"))
                compare_at = cls._parse_price(variant.get("compare_at_price"))
                if (
                    price is not None
                    and compare_at is not None
                    and compare_at > price
                ):
                    compare_at_price = cls._format_price(compare_at)
                    break

        return (
            cls._format_price(price_min),
            cls._format_price(price_max),
            compare_at_price,
        )

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
        price_min, price_max, compare_at_price = self._variant_prices(item.get("variants") or [])
        images = [image["src"] for image in item.get("images") or [] if image.get("src")]
        tags = self._parse_tags(item.get("tags"))

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
            compare_at_price=compare_at_price,
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
                if page == 1:
                    raise RuntimeError(
                        f"No products returned from {PRODUCTS_JSON_URL}. "
                        "The store API may be unavailable or blocking requests."
                    )
                break

            if self.verbose:
                print(f"Fetched page {page}: {len(items)} products")

            for item in items:
                product_id = item.get("id")
                if not product_id:
                    continue
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
