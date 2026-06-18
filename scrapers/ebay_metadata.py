"""Extract store owner and profile metadata from eBay store HTML."""

from __future__ import annotations

import codecs
import re
from typing import Any

from bs4 import BeautifulSoup

EBAY_BASE_URL = "https://www.ebay.com"

JSON_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "owner_username": re.compile(r'"ownerUsername":"([^"]+)"'),
    "store_name": re.compile(r'"storeName":"([^"]+)"'),
    "seller_id": re.compile(r'"sellerId":"([^"]+)"'),
    "soid": re.compile(r'"soid":"([^"]+)"'),
}

SELLER_INFO_LABELS = ("Location", "Member since", "Seller", "Feedback")

PLACEHOLDER_ABOUT_MARKERS = (
    "use this space to tell other eBay members",
    "give people more reasons to follow you",
)

FOUNDER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\bfounded by\s+([A-Z][a-zA-Z\.\'-]+(?:\s+[A-Z][a-zA-Z\.\'-]+){0,3})",
            re.I,
        ),
        "founder",
    ),
    (
        re.compile(
            r"\b(?:co-?)?founders?\s*(?:is|are|:)\s+"
            r"([A-Z][a-zA-Z\.\'-]+(?:\s+[A-Z][a-zA-Z\.\'-]+){0,3})",
            re.I,
        ),
        "founder",
    ),
    (
        re.compile(
            r"\b(?:co-?)?founders?\s+"
            r"([A-Z][a-zA-Z\.\'-]+(?:\s+[A-Z][a-zA-Z\.\'-]+){0,3})",
            re.I,
        ),
        "founder",
    ),
    (
        re.compile(
            r"\bestablished by\s+([A-Z][a-zA-Z\.\'-]+(?:\s+[A-Z][a-zA-Z\.\'-]+){0,3})",
            re.I,
        ),
        "founder",
    ),
    (
        re.compile(
            r"\bCEO\s*(?:is|:)\s+([A-Z][a-zA-Z\.\'-]+(?:\s+[A-Z][a-zA-Z\.\'-]+){0,3})",
            re.I,
        ),
        "ceo",
    ),
    (
        re.compile(
            r"\b(?:president|director)\s*(?:is|:)\s+"
            r"([A-Z][a-zA-Z\.\'-]+(?:\s+[A-Z][a-zA-Z\.\'-]+){0,3})",
            re.I,
        ),
        "executive",
    ),
)

TRAILING_NAME_PATTERN = re.compile(
    r"\s+(?:in|leads|and|who|with|of|at|for|the|was|has|have|from)\b.*",
    re.I,
)


def _first_match(pattern: re.Pattern[str], html: str) -> str | None:
    match = pattern.search(html)
    return match.group(1) if match else None


def _decode_json_text(text: str) -> str:
    decoded = codecs.decode(text, "unicode_escape")
    return decoded.replace("\r\n", "\n").replace("\r", "\n").strip()


def _is_placeholder_about(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in PLACEHOLDER_ABOUT_MARKERS)


def extract_json_fields(html: str) -> dict[str, str | None]:
    return {
        field: _first_match(pattern, html)
        for field, pattern in JSON_FIELD_PATTERNS.items()
    }


def extract_feedback_summary(html: str) -> str | None:
    match = re.search(
        r'"sellerInfo":\{"_type":"IconAndText","text":\{"_type":"TextualDisplay",'
        r'"textSpans":\[\{"_type":"TextSpan","text":"([^"]+)"',
        html,
    )
    return match.group(1) if match else None


def extract_about_from_json(html: str) -> str | None:
    candidates: list[str] = []
    for match in re.finditer(
        r'"textSpans":\[\{"_type":"TextSpan","text":"([^"]{40,})"',
        html,
    ):
        text = _decode_json_text(match.group(1))
        if _is_placeholder_about(text):
            continue
        if len(text.split()) < 8:
            continue
        candidates.append(text)

    if not candidates:
        return None

    return max(candidates, key=len)


def parse_seller_info_block(soup: BeautifulSoup) -> dict[str, str | None]:
    info_element = soup.select_one(".str-about-description__seller-info")
    if not info_element:
        return {}

    lines = [line.strip() for line in info_element.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]
    parsed: dict[str, str | None] = {
        "location": None,
        "member_since": None,
        "seller": None,
    }

    index = 0
    while index < len(lines):
        label = lines[index].rstrip(":")
        if label in SELLER_INFO_LABELS and index + 1 < len(lines):
            value = lines[index + 1]
            if label == "Location":
                parsed["location"] = value
            elif label == "Member since":
                parsed["member_since"] = value
            elif label == "Seller":
                parsed["seller"] = value
            index += 2
            continue
        index += 1

    return parsed


def extract_about_text(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    intro_element = soup.select_one(".str-about-description__about-intro")
    description_element = soup.select_one(".str-about-description__description")

    intro = intro_element.get_text(" ", strip=True) if intro_element else None
    description = (
        description_element.get_text(" ", strip=True) if description_element else None
    )

    if intro and intro.lower().startswith("about us"):
        intro = intro[8:].strip(" :-")

    if description and description.lower().startswith("about us"):
        description = description[8:].strip(" :-")

    if intro and description and intro == description:
        description = None

    return intro, description


def _looks_like_ebay_username(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_\-]{3,}", name, re.I))


def _clean_person_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name).strip(" .,-")
    cleaned = TRAILING_NAME_PATTERN.sub("", cleaned).strip(" .,-")
    cleaned = re.split(r"[.,;]", cleaned, maxsplit=1)[0].strip()
    cleaned = re.split(r"\band\b", cleaned, maxsplit=1, flags=re.I)[0].strip()
    return cleaned


def extract_people_from_text(text: str, source: str) -> list[dict[str, str | None]]:
    people: list[dict[str, str | None]] = []
    seen: set[tuple[str, str]] = set()

    for pattern, role in FOUNDER_PATTERNS:
        for match in pattern.finditer(text):
            name = _clean_person_name(match.group(1))
            if len(name) < 3 or len(name.split()) > 5:
                continue
            if _looks_like_ebay_username(name):
                continue
            key = (name.lower(), role)
            if key in seen:
                continue
            seen.add(key)
            people.append({"name": name, "role": role, "details": None, "source": source})

    return people


def extract_seller_profile_metadata(html: str) -> dict[str, str | None]:
    soup = BeautifulSoup(html, "lxml")
    fields = extract_json_fields(html)

    card = soup.select_one(".str-seller-card")
    card_text = card.get_text(" | ", strip=True) if card else None

    title_element = soup.select_one(".str-seller-card h1, .str-seller-card__title")
    store_name_element = soup.select_one(".str-seller-card__store-name")
    badge = None
    display_name = title_element.get_text(strip=True) if title_element else None

    if store_name_element:
        store_name_text = store_name_element.get_text(" ", strip=True)
        if display_name and store_name_text.startswith(display_name):
            badge = store_name_text[len(display_name) :].strip() or None
        elif not display_name:
            display_name = store_name_text

    return {
        "display_name": display_name,
        "badge": badge,
        "card_summary": card_text,
        "owner_username": fields.get("owner_username"),
        "store_name": fields.get("store_name") or display_name,
        "feedback_summary": extract_feedback_summary(html),
    }


def build_profile_url(username: str | None) -> str | None:
    if not username:
        return None
    return f"{EBAY_BASE_URL}/usr/{username}"


def merge_people(
    *groups: list[dict[str, str | None]],
) -> list[dict[str, str | None]]:
    merged: list[dict[str, str | None]] = []
    seen: set[tuple[str, str]] = set()

    for group in groups:
        for person in group:
            name = (person.get("name") or "").strip()
            role = (person.get("role") or "other").strip().lower()
            if not name:
                continue
            key = (name.lower(), role)
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                {
                    "name": name,
                    "role": role,
                    "details": person.get("details"),
                    "source": person.get("source") or "unknown",
                }
            )

    return merged


def extract_store_metadata(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    fields = extract_json_fields(html)
    seller_info = parse_seller_info_block(soup)
    about_intro, about_description = extract_about_text(soup)
    json_about = extract_about_from_json(html)
    feedback_summary = extract_feedback_summary(html)

    if json_about:
        if not about_intro or len(json_about) > len(about_intro):
            about_intro = json_about
        elif about_description and len(json_about) > len(about_description):
            about_description = json_about

    owner_username = fields.get("owner_username") or seller_info.get("seller")
    store_name = fields.get("store_name")
    seller_id = fields.get("seller_id") or owner_username

    combined_text = " ".join(
        part for part in (about_intro, about_description) if part
    )
    people = extract_people_from_text(combined_text, source="about_text")

    return {
        "store_name": store_name,
        "owner_username": owner_username,
        "seller_id": seller_id,
        "soid": fields.get("soid"),
        "profile_url": build_profile_url(owner_username),
        "location": seller_info.get("location"),
        "member_since": seller_info.get("member_since"),
        "about_intro": about_intro,
        "about_description": about_description,
        "feedback_summary": feedback_summary,
        "people": people,
    }
