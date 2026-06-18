"""Scrape store owner and people/founder information from eBay stores."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests

from scrapers.ebay import EBAY_BASE_URL, EbayShopScraper
from scrapers.ebay_metadata import (
    build_profile_url,
    extract_founded_year_from_text,
    extract_people_from_text,
    extract_seller_profile_metadata,
    extract_store_metadata,
    merge_people,
)
from scrapers.wikidata_people import normalize_company_query


@dataclass
class StorePerson:
    name: str
    role: str
    source: str
    details: str | None = None
    wikidata_id: str | None = None


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
    seller_badge: str | None = None
    seller_display_name: str | None = None
    company_name: str | None = None
    company_description: str | None = None
    founded_year: str | None = None
    wikidata_id: str | None = None
    wikidata_url: str | None = None
    people: list[StorePerson] = field(default_factory=list)


class EbayPeopleScraper:
    """Scrape seller/owner profile and people mentions from an eBay store."""

    def __init__(
        self,
        shop: str,
        session: requests.Session | None = None,
        verbose: bool = False,
        use_openai: bool = False,
        use_wikidata: bool = True,
        openai_api_key: str | None = None,
        openai_model: str = "gpt-4o-mini",
    ) -> None:
        self.shop_input = shop.strip()
        self.session = session or requests.Session()
        self.verbose = verbose
        self.use_openai = use_openai
        self.use_wikidata = use_wikidata
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self._openai_extractor = None
        self._wikidata_lookup = None
        self.store_scraper = EbayShopScraper(
            shop=self.shop_input,
            session=self.session,
            verbose=False,
            include_owner=False,
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

    def _get_openai_extractor(self):
        if self._openai_extractor is None:
            from scrapers.openai_people_extractor import OpenAIPeopleExtractor

            self._openai_extractor = OpenAIPeopleExtractor(
                api_key=self.openai_api_key,
                model=self.openai_model,
            )
        return self._openai_extractor

    def _get_wikidata_lookup(self):
        if self._wikidata_lookup is None:
            from scrapers.wikidata_people import WikidataPeopleLookup

            self._wikidata_lookup = WikidataPeopleLookup(session=self.session)
        return self._wikidata_lookup

    def _lookup_wikidata(
        self,
        store_name: str | None,
        display_name: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.use_wikidata:
            return None

        query = normalize_company_query(display_name, store_name)
        if not query:
            return None

        self._log(f"Looking up company on Wikidata: {query}")
        try:
            return self._get_wikidata_lookup().lookup(query)
        except requests.RequestException as error:
            self._log(f"Wikidata lookup failed: {error}")
            return None

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

        owner_username = metadata.get("owner_username")
        profile_url = metadata.get("profile_url") or build_profile_url(owner_username)
        seller_profile: dict[str, str | None] = {}

        if profile_url:
            self._log(f"Fetching seller profile: {profile_url}")
            profile_html = self._fetch_html(profile_url)
            seller_profile = extract_seller_profile_metadata(profile_html)
            if not metadata.get("feedback_summary"):
                metadata["feedback_summary"] = seller_profile.get("feedback_summary")
            if not metadata.get("owner_username"):
                metadata["owner_username"] = seller_profile.get("owner_username")
            if not metadata.get("store_name"):
                metadata["store_name"] = seller_profile.get("store_name")

        combined_about = " ".join(
            part
            for part in (
                metadata.get("about_intro"),
                metadata.get("about_description"),
                seller_profile.get("about_text"),
            )
            if part
        )

        people_groups = [
            metadata.get("people") or [],
            extract_people_from_text(combined_about, source="combined_text"),
        ]

        founded_year = metadata.get("founded_year") or extract_founded_year_from_text(
            combined_about
        )
        company_name = metadata.get("store_name")
        company_description = None
        wikidata_id = None
        wikidata_url = None

        wikidata_result = self._lookup_wikidata(
            metadata.get("store_name"),
            seller_profile.get("display_name"),
        )
        if wikidata_result:
            people_groups.append(wikidata_result.get("people") or [])
            company_name = wikidata_result.get("company_name") or company_name
            company_description = wikidata_result.get("company_description")
            if not founded_year:
                founded_year = wikidata_result.get("founded_year")
            wikidata_id = wikidata_result.get("wikidata_id")
            wikidata_url = wikidata_result.get("wikidata_url")

        if self.use_openai:
            self._log("Using OpenAI to identify founders and key people")
            openai_result = self._get_openai_extractor().extract_people(
                store_name=company_name or metadata.get("store_name"),
                owner_username=metadata.get("owner_username"),
                about_text=combined_about or None,
                seller_profile=seller_profile,
            )
            people_groups.append(openai_result.get("people") or [])
            company_name = openai_result.get("company_name") or company_name
            if not founded_year:
                founded_year = openai_result.get("founded_year")

        people = [
            StorePerson(**person)
            for person in merge_people(*people_groups)
        ]

        return EbayStoreProfile(
            store_slug=self.store_slug,
            store_url=self.store_url,
            store_name=metadata.get("store_name"),
            owner_username=metadata.get("owner_username"),
            seller_id=metadata.get("seller_id"),
            soid=metadata.get("soid"),
            profile_url=profile_url,
            location=metadata.get("location"),
            member_since=metadata.get("member_since"),
            about_intro=metadata.get("about_intro"),
            about_description=metadata.get("about_description"),
            feedback_summary=metadata.get("feedback_summary"),
            seller_badge=seller_profile.get("badge"),
            seller_display_name=seller_profile.get("display_name"),
            company_name=company_name,
            company_description=company_description,
            founded_year=founded_year,
            wikidata_id=wikidata_id,
            wikidata_url=wikidata_url,
            people=people,
        )

    def scrape(self) -> dict[str, Any]:
        return asdict(self.fetch_profile())
