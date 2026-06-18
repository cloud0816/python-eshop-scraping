"""Look up company founders and executives from Wikidata."""

from __future__ import annotations

import re
import time
from typing import Any

import requests

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "python-eshop-scraper/1.0 (https://github.com/cloud0816/python-eshop-scraping; contact@example.com)"

ORG_DESCRIPTION_KEYWORDS = (
    "company",
    "corporation",
    "business",
    "brand",
    "retailer",
    "organization",
    "organisation",
    "multinational",
    "manufacturer",
    "enterprise",
    "firm",
    "store",
    "shop",
)

NEGATIVE_DESCRIPTION_KEYWORDS = (
    "video game",
    "given name",
    "family name",
    "film",
    "album",
    "song",
    "television",
    "anime",
    "fictional",
    "wikimedia",
    "trade mark",
    "trademark",
)

PERSON_CLAIM_ROLES: dict[str, str] = {
    "P112": "founder",
    "P169": "ceo",
    "P488": "chairperson",
    "P1037": "director",
    "P3320": "board member",
}


def normalize_company_query(*names: str | None) -> str | None:
    """Pick the best company name for external lookup."""
    candidates: list[str] = []
    for name in names:
        if not name:
            continue
        cleaned = re.sub(r"\s+", " ", name).strip()
        if not cleaned:
            continue
        if re.fullmatch(r"[a-z0-9_\-]{3,}", cleaned, re.I):
            spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
            spaced = re.sub(r"[_\-]+", " ", spaced)
            cleaned = spaced.strip()
            cleaned = re.sub(r"(usa|uk|official|store|shop|outlet)+$", "", cleaned, flags=re.I)
        cleaned = re.sub(
            r"\b(usa|uk|official|store|shop|outlet|inc|llc|ltd|co)\b",
            "",
            cleaned,
            flags=re.I,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    if not candidates:
        return None

    def rank(name: str) -> tuple[int, int]:
        readable = 10 if " " in name else 0
        title_case = 2 if name[:1].isupper() else 0
        return (readable + title_case, len(name))

    return max(candidates, key=rank)


def _score_search_result(item: dict[str, Any]) -> int:
    description = (item.get("description") or "").lower()
    score = 0
    for keyword in ORG_DESCRIPTION_KEYWORDS:
        if keyword in description:
            score += 2
    for keyword in NEGATIVE_DESCRIPTION_KEYWORDS:
        if keyword in description:
            score -= 6
    if item.get("match", {}).get("type") == "label":
        score += 1
    return score


def _parse_wikidata_year(value: dict[str, Any]) -> str | None:
    time_value = value.get("time")
    if not time_value:
        return None
    match = re.search(r"\+(\d{4})", time_value)
    return match.group(1) if match else None


def _entity_id(value: dict[str, Any]) -> str | None:
    if value.get("entity-type") != "item":
        return None
    return value.get("id")


class WikidataPeopleLookup:
    """Resolve company founders and key people from Wikidata."""

    def __init__(
        self,
        session: requests.Session | None = None,
        request_delay: float = 1.0,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            }
        )
        self.request_delay = request_delay
        self._last_request_at = 0.0

    def _get(self, **params: Any) -> dict[str, Any]:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)

        last_error: requests.RequestException | None = None
        for attempt in range(3):
            try:
                response = self.session.get(WIKIDATA_API, params=params, timeout=20)
                self._last_request_at = time.monotonic()
                if response.status_code in (429, 403) and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                response.raise_for_status()
                return response.json()
            except requests.RequestException as error:
                last_error = error
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise last_error from error

        raise RuntimeError("Wikidata request failed")

    def _search_entity(self, query: str) -> dict[str, Any] | None:
        payload = self._get(
            action="wbsearchentities",
            search=query,
            language="en",
            format="json",
            limit=5,
            type="item",
        )
        results = payload.get("search") or []
        if not results:
            return None

        ranked = sorted(results, key=_score_search_result, reverse=True)
        best = ranked[0]
        if _score_search_result(best) < 0:
            return None
        return best

    def _fetch_entities(self, entity_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not entity_ids:
            return {}

        payload = self._get(
            action="wbgetentities",
            ids="|".join(entity_ids),
            props="labels",
            format="json",
        )
        return payload.get("entities") or {}

    @staticmethod
    def _english_label(entity: dict[str, Any]) -> str | None:
        labels = entity.get("labels") or {}
        if "en" in labels:
            return labels["en"].get("value")
        if labels:
            return next(iter(labels.values())).get("value")
        return None

    def lookup(self, store_name: str) -> dict[str, Any] | None:
        query = store_name.strip()
        if not query:
            return None

        match = self._search_entity(query)
        if not match:
            return None

        entity_id = match.get("id")
        if not entity_id:
            return None

        payload = self._get(
            action="wbgetentities",
            ids=entity_id,
            props="claims|labels|descriptions",
            format="json",
        )
        entity = (payload.get("entities") or {}).get(entity_id)
        if not entity or entity.get("missing"):
            return None

        company_name = self._english_label(entity) or match.get("label")
        claims = entity.get("claims") or {}

        founded_years: list[str] = []
        for claim in claims.get("P571", []):
            datavalue = claim.get("mainsnak", {}).get("datavalue")
            if not datavalue:
                continue
            year = _parse_wikidata_year(datavalue.get("value") or {})
            if year:
                founded_years.append(year)

        person_ids: list[str] = []
        person_roles: dict[str, str] = {}
        for property_id, role in PERSON_CLAIM_ROLES.items():
            for claim in claims.get(property_id, []):
                datavalue = claim.get("mainsnak", {}).get("datavalue")
                if not datavalue:
                    continue
                person_id = _entity_id(datavalue.get("value") or {})
                if not person_id:
                    continue
                person_ids.append(person_id)
                person_roles.setdefault(person_id, role)

        label_entities = self._fetch_entities(sorted(set(person_ids)))
        people: list[dict[str, str | None]] = []
        for person_id in sorted(set(person_ids), key=lambda pid: person_roles.get(pid, "z")):
            label = self._english_label(label_entities.get(person_id) or {})
            if not label:
                continue
            people.append(
                {
                    "name": label,
                    "role": person_roles.get(person_id, "executive"),
                    "details": company_name,
                    "source": "wikidata",
                    "wikidata_id": person_id,
                }
            )

        return {
            "company_name": company_name,
            "company_description": (entity.get("descriptions") or {}).get("en", {}).get("value"),
            "founded_year": min(founded_years) if founded_years else None,
            "wikidata_id": entity_id,
            "wikidata_url": f"https://www.wikidata.org/wiki/{entity_id}",
            "people": people,
        }
