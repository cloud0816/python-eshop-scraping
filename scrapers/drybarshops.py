"""Scraper for https://www.drybarshops.com/ product catalog."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urljoin

import requests

BASE_URL = "https://www.drybarshops.com"
CONTENTFUL_GRAPHQL_URL = (
    "https://graphql.contentful.com/content/v1/spaces/13n1l6os99jz/environments/master"
)
# Public Contentful delivery token embedded in the site's client-side JavaScript.
CONTENTFUL_TOKEN = "TLufZkxA2nHOX_GfHqQVbWCt6jwztb3_ieYD6lg_twE"

PRODUCTS_QUERY = """
query Products($limit: Int!, $skip: Int!) {
  productCollection(limit: $limit, skip: $skip, order: title_ASC) {
    total
    items {
      sys { id }
      title
      subtitle
      slug
      price
      priceRange
      type
      bestFor
      serviceTime
      isNew
      productId
      bookerReference
      imagesCollection(limit: 5) {
        items {
          internalName
          desktopMedia { url title }
          mobileMedia { url title }
        }
      }
    }
  }
}
"""

PRODUCT_GROUPS_QUERY = """
query ProductGroups {
  marketingProductsCollection(limit: 20) {
    items {
      title
      subtitle
      internalName
      productsCollection(limit: 50) {
        items {
          sys { id }
          title
          slug
        }
      }
    }
  }
}
"""


@dataclass
class ProductImage:
    internal_name: str | None
    desktop_url: str | None
    mobile_url: str | None


@dataclass
class Product:
    id: str
    title: str
    slug: str | None
    subtitle: str | None
    price: float | None
    price_range: str | None
    type: str | None
    best_for: str | None
    service_time: int | None
    is_new: bool | None
    product_id: str | None
    booker_reference: str | None
    url: str
    images: list[ProductImage] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)


class DrybarShopsScraper:
    """Fetch Drybar shop services and add-ons from the Contentful product catalog."""

    def __init__(
        self,
        session: requests.Session | None = None,
        page_size: int = 50,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent",
            "python-eshop-scraping/1.0 (+https://www.drybarshops.com/)",
        )
        self.page_size = page_size

    def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.post(
            CONTENTFUL_GRAPHQL_URL,
            headers={
                "Authorization": f"Bearer {CONTENTFUL_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables or {}},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(json.dumps(payload["errors"], indent=2))
        return payload["data"]

    @staticmethod
    def _normalize_image(item: dict[str, Any]) -> ProductImage:
        desktop = item.get("desktopMedia") or {}
        mobile = item.get("mobileMedia") or {}
        return ProductImage(
            internal_name=item.get("internalName"),
            desktop_url=desktop.get("url"),
            mobile_url=mobile.get("url"),
        )

    def _normalize_product(self, item: dict[str, Any]) -> Product:
        slug = (item.get("slug") or "").strip()
        path = f"/service/add-ons/#{slug}" if item.get("type") == "Add On" else f"/booking/services"
        if slug and item.get("type") != "Add On":
            path = f"/the-styles/#{slug}" if item.get("type") == "Service" else path

        images = [
            self._normalize_image(image)
            for image in (item.get("imagesCollection") or {}).get("items") or []
        ]

        return Product(
            id=item["sys"]["id"],
            title=(item.get("title") or "").strip(),
            slug=slug or None,
            subtitle=(item.get("subtitle") or None),
            price=item.get("price"),
            price_range=item.get("priceRange"),
            type=item.get("type"),
            best_for=(item.get("bestFor") or None),
            service_time=item.get("serviceTime"),
            is_new=item.get("isNew"),
            product_id=item.get("productId"),
            booker_reference=item.get("bookerReference"),
            url=urljoin(BASE_URL, path),
            images=images,
        )

    def fetch_product_groups(self) -> dict[str, list[str]]:
        data = self._graphql(PRODUCT_GROUPS_QUERY)
        groups: dict[str, list[str]] = {}
        for group in (data.get("marketingProductsCollection") or {}).get("items") or []:
            title = (group.get("title") or "Uncategorized").strip()
            product_ids = [
                item["sys"]["id"]
                for item in (group.get("productsCollection") or {}).get("items") or []
                if item.get("sys", {}).get("id")
            ]
            groups[title] = product_ids
        return groups

    def fetch_products(self) -> list[Product]:
        products: list[Product] = []
        skip = 0

        while True:
            data = self._graphql(
                PRODUCTS_QUERY,
                {"limit": self.page_size, "skip": skip},
            )
            collection = data["productCollection"]
            items = collection.get("items") or []
            if not items:
                break

            products.extend(self._normalize_product(item) for item in items)
            skip += len(items)
            if skip >= collection.get("total", 0):
                break

        groups = self.fetch_product_groups()
        id_to_categories: dict[str, list[str]] = {}
        for category, product_ids in groups.items():
            for product_id in product_ids:
                id_to_categories.setdefault(product_id, []).append(category)

        for product in products:
            product.categories = id_to_categories.get(product.id, [])

        return products

    def scrape(self) -> list[dict[str, Any]]:
        return [asdict(product) for product in self.fetch_products()]
