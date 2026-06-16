"""Scrape store owner and people/founder information from eBay stores."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests

from scrapers.ebay import EBAY_BASE_URL, EbayShopScraper
from scrapers.ebay_metadata import extract_store_metadata


@dataclass
class StorePerson:
    name: str
    role: str
    source: str


@dataclass
class EbayStoreProfile:
    store_slug: str | None
    store_url: str
    store_name: str | None
    owner_username: str | None
    seller_id: str | None
    soid: str | None
    profile_url: str | None
    location: str | None
    member_since: str | None
    about_intro: str | None
    about_description: str | None
    feedback_summary: str | None
    people: list[StorePerson] = field(default_factory=list)


class EbayPeopleScraper:
    """Scrape seller/owner profile and people mentions from an eBay store."""

    def __init__(
        self,
        shop: str,
        session: requests.Session | None = None,
        verbose: bool = False,
    ) -> None:
        self.shop_input = shop.strip()
        self.session = session or requests.Session()
        self.verbose = verbose
        self.store_scraper = EbayShopScraper(
            shop=self.shop_input,
            session=self.session,
            verbose=False,
        )
        self.store_url = self.store_scraper.store_url
        self.store_slug = self.store_scraper.store_slug

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

    @staticmethod
    def _about_url(store_url: str) -> str:
        parsed = urlparse(store_url)
        path = parsed.path.rstrip("/")
        return f"{EBAY_BASE_URL}{path}?_tab=about"

    def _fetch_html(self, url: str) -> str:
        from scrapers.http import fetch_html

        return fetch_html(url, session=self.session)

    def fetch_profile(self) -> EbayStoreProfile:
        about_url = self._about_url(self.store_url)
        self._log(f"Fetching store about page: {about_url}")

        about_html = self._fetch_html(about_url)
        metadata = extract_store_metadata(about_html)

        if not metadata.get("feedback_summary"):
            self._log(f"Fetching store home for seller feedback: {self.store_url}")
            home_html = self._fetch_html(self.store_url)
            home_metadata = extract_store_metadata(home_html)
            metadata["feedback_summary"] = home_metadata.get("feedback_summary")
            for key in ("owner_username", "store_name", "seller_id", "soid"):
                if not metadata.get(key):
                    metadata[key] = home_metadata.get(key)

        people = [
            StorePerson(**person)
            for person in metadata.get("people") or []
        ]

        return EbayStoreProfile(
            store_slug=self.store_slug,
            store_url=self.store_url,
            store_name=metadata.get("store_name"),
            owner_username=metadata.get("owner_username"),
            seller_id=metadata.get("seller_id"),
            soid=metadata.get("soid"),
            profile_url=metadata.get("profile_url"),
            location=metadata.get("location"),
            member_since=metadata.get("member_since"),
            about_intro=metadata.get("about_intro"),
            about_description=metadata.get("about_description"),
            feedback_summary=metadata.get("feedback_summary"),
            people=people,
        )

    def scrape(self) -> dict[str, Any]:
        return asdict(self.fetch_profile())
