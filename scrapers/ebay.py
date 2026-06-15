"""Scraper for eBay shop/store listing pages."""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

EBAY_BASE_URL = "https://www.ebay.com"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
ITEM_ID_PATTERN = re.compile(r"/itm/(?P<item_id>\d+)")
PRICE_PATTERN = re.compile(r"[\$£€][\d,]+(?:\.\d{2})?")


@dataclass
class EbayListing:
    item_id: str
    title: str
    url: str
    price: str | None
    price_min: str | None
    price_max: str | None
    original_price: str | None
    image_url: str | None
    store_slug: str | None
    page: int
    categories: list[str] = field(default_factory=list)


class EbayShopScraper:
    """Scrape product listings from an eBay store (/str/{slug})."""

    def __init__(
        self,
        shop: str,
        session: requests.Session | None = None,
        items_per_page: int | None = None,
        max_pages: int | None = None,
        delay_seconds: float = 1.0,
        verbose: bool = False,
        use_openai: bool = False,
        openai_api_key: str | None = None,
        openai_model: str = "gpt-4o-mini",
    ) -> None:
        self.shop_input = shop.strip()
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.items_per_page = items_per_page
        self.max_pages = max_pages
        self.delay_seconds = delay_seconds
        self.verbose = verbose
        self.use_openai = use_openai
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self._openai_extractor = None
        self.store_url = self._resolve_store_url(self.shop_input)
        self.store_slug = self._extract_store_slug(self.store_url)

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

    @staticmethod
    def _extract_store_slug(url: str) -> str | None:
        match = re.search(r"/str/([^/?#]+)", url)
        return match.group(1) if match else None

    @staticmethod
    def _normalize_store_url(shop: str) -> str:
        if shop.startswith("http://") or shop.startswith("https://"):
            return shop.rstrip("/")

        slug = shop.strip("/")
        if slug.startswith("str/"):
            slug = slug.removeprefix("str/")
        return f"{EBAY_BASE_URL}/str/{slug}"

    def _resolve_store_url(self, shop: str) -> str:
        if shop.startswith("http://") or shop.startswith("https://"):
            parsed = urlparse(shop)
            if "/usr/" in parsed.path:
                return self._resolve_user_profile_to_store(shop)
            return shop.rstrip("/")

        if shop.startswith("usr/"):
            return self._resolve_user_profile_to_store(
                f"{EBAY_BASE_URL}/{shop.strip('/')}"
            )

        return self._normalize_store_url(shop)

    def _fetch_html(self, url: str) -> str:
        from scrapers.http import fetch_html

        return fetch_html(url, session=self.session)

    def _resolve_user_profile_to_store(self, profile_url: str) -> str:
        html = self._fetch_html(profile_url.rstrip("/"))
        soup = BeautifulSoup(html, "lxml")
        for link in soup.select('a[href*="/str/"]'):
            href = link.get("href")
            if not href:
                continue
            store_url = urljoin(EBAY_BASE_URL, href.split("?")[0].rstrip("/"))
            if "/str/" in store_url:
                return store_url
        raise RuntimeError(
            f"Could not find an eBay store link on seller profile: {profile_url}"
        )

    def _build_page_url(self, page: int) -> str:
        parsed = urlparse(self.store_url)
        query = parse_qs(parsed.query)
        query["_pgn"] = [str(page)]
        if self.items_per_page:
            query["_ipg"] = [str(self.items_per_page)]
        if page > 1:
            query.setdefault("rt", ["nc"])
        new_query = urlencode({key: values[-1] for key, values in query.items()})
        return urlunparse(parsed._replace(query=new_query))

    @staticmethod
    def _parse_prices(price_text: str, original_text: str | None) -> tuple[
        str | None,
        str | None,
        str | None,
        str | None,
    ]:
        amounts = PRICE_PATTERN.findall(price_text.replace("to", " "))
        if not amounts:
            return None, None, None, None

        price_min = amounts[0]
        price_max = amounts[-1] if len(amounts) > 1 else price_min
        price = f"{price_min} to {price_max}" if len(amounts) > 1 else price_min
        original_price = None
        if original_text:
            original_amounts = PRICE_PATTERN.findall(original_text)
            original_price = original_amounts[0] if original_amounts else original_text.strip()
        return price, price_min, price_max, original_price

    @staticmethod
    def _extract_item_id(card: Any, href: str | None) -> str | None:
        item_id = card.get("data-testid")
        if item_id and item_id.startswith("ig-"):
            return item_id.removeprefix("ig-")
        if href:
            match = ITEM_ID_PATTERN.search(href)
            if match:
                return match.group("item_id")
        return None

    def _parse_listing_card(self, card: Any, page: int) -> EbayListing | None:
        link = card.select_one("a.str-item-card__link")
        if not link:
            return None

        href = link.get("href")
        item_id = self._extract_item_id(card, href)
        if not item_id:
            return None

        title_element = card.select_one(".str-item-card__property-title span")
        title = (
            title_element.get_text(" ", strip=True)
            if title_element
            else link.get("aria-label")
        )
        if not title:
            return None

        price_element = card.select_one(".str-item-card__property-displayPrice")
        original_element = card.select_one(".str-item-card__property-additionalPrice")
        price_text = price_element.get_text(" ", strip=True) if price_element else ""
        original_text = (
            original_element.get_text(" ", strip=True) if original_element else None
        )
        price, price_min, price_max, original_price = self._parse_prices(
            price_text,
            original_text,
        )

        image = card.select_one("img")
        image_url = image.get("src") if image else None
        listing_url = urljoin(EBAY_BASE_URL, f"/itm/{item_id}")

        return EbayListing(
            item_id=item_id,
            title=title,
            url=listing_url,
            price=price,
            price_min=price_min,
            price_max=price_max,
            original_price=original_price,
            image_url=image_url,
            store_slug=self.store_slug,
            page=page,
        )

    def _parse_max_page(self, html: str) -> int | None:
        soup = BeautifulSoup(html, "lxml")
        page_numbers: list[int] = []
        for link in soup.select('a[href*="_pgn="]'):
            href = link.get("href") or ""
            match = re.search(r"_pgn=(\d+)", href)
            if match:
                page_numbers.append(int(match.group(1)))
        return max(page_numbers) if page_numbers else None

    def _get_openai_extractor(self):
        if self._openai_extractor is None:
            from scrapers.openai_extractor import OpenAIExtractor

            self._openai_extractor = OpenAIExtractor(
                api_key=self.openai_api_key,
                model=self.openai_model,
            )
        return self._openai_extractor

    def _parse_page_openai(self, html: str, page: int) -> list[EbayListing]:
        products = self._get_openai_extractor().extract_products(
            html,
            self._build_page_url(page),
            instructions=(
                "Extract eBay store product listing cards only. "
                "Include item_id when visible in URLs or data attributes."
            ),
        )
        listings: list[EbayListing] = []
        for product in products:
            item_id = product.get("item_id")
            url = product.get("url")
            if not item_id and url:
                match = ITEM_ID_PATTERN.search(url)
                if match:
                    item_id = match.group("item_id")
            if not item_id or not product.get("title"):
                continue

            price = product.get("price")
            listings.append(
                EbayListing(
                    item_id=item_id,
                    title=product["title"],
                    url=urljoin(EBAY_BASE_URL, f"/itm/{item_id}"),
                    price=price,
                    price_min=price,
                    price_max=price,
                    original_price=product.get("original_price"),
                    image_url=product.get("image_url"),
                    store_slug=self.store_slug,
                    page=page,
                )
            )
        return listings

    def _parse_page(self, html: str, page: int) -> list[EbayListing]:
        if self.use_openai:
            return self._parse_page_openai(html, page)

        soup = BeautifulSoup(html, "lxml")
        listings: list[EbayListing] = []
        for card in soup.select("article.StoreFrontItemCard, .StoreFrontItemCard"):
            listing = self._parse_listing_card(card, page)
            if listing:
                listings.append(listing)
        return listings

    def fetch_page(self, page: int = 1) -> list[EbayListing]:
        url = self._build_page_url(page)
        html = self._fetch_html(url)
        return self._parse_page(html, page)

    def fetch_products(self) -> list[EbayListing]:
        first_url = self._build_page_url(1)
        first_html = self._fetch_html(first_url)
        listings = self._parse_page(first_html, 1)
        seen_ids = {listing.item_id for listing in listings}

        detected_max_page = self._parse_max_page(first_html)
        last_page = self.max_pages or detected_max_page or 1

        self._log(f"Page 1/{last_page}: found {len(listings)} listings")

        if self.use_openai:
            self._log("Using OpenAI extraction")

        for page in range(2, last_page + 1):
            if self.delay_seconds:
                time.sleep(self.delay_seconds)

            page_listings = self.fetch_page(page)
            if not page_listings:
                self._log(f"Page {page}/{last_page}: no listings, stopping")
                break

            new_items = [
                listing
                for listing in page_listings
                if listing.item_id not in seen_ids
            ]
            if not new_items:
                self._log(f"Page {page}/{last_page}: no new listings, stopping")
                break

            listings.extend(new_items)
            seen_ids.update(listing.item_id for listing in new_items)
            self._log(
                f"Page {page}/{last_page}: found {len(new_items)} new listings "
                f"({len(listings)} total)"
            )

        return listings

    def scrape(self) -> list[dict[str, Any]]:
        return [asdict(listing) for listing in self.fetch_products()]
