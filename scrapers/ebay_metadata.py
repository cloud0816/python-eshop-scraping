"""Extract store owner and profile metadata from eBay store HTML."""

from __future__ import annotations

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

FOUNDER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:co-?)?founders?\s+(?:is\s+|are\s+|:\s*)([A-Z][\w\s\.\'-]{1,60})", re.I), "founder"),
    (re.compile(r"founded by\s+([A-Z][\w\s\.\'-]{1,60})", re.I), "founder"),
    (re.compile(r"established by\s+([A-Z][\w\s\.\'-]{1,60})", re.I), "founder"),
    (re.compile(r"\bCEO\s+(?:is\s+|:\s*)([A-Z][\w\s\.\'-]{1,60})", re.I), "ceo"),
    (re.compile(r"\bowner\s+(?:is\s+|:\s*)([A-Z][\w\s\.\'-]{1,60})", re.I), "owner"),
    (re.compile(r"\b(?:president|director)\s+(?:is\s+|:\s*)([A-Z][\w\s\.\'-]{1,60})", re.I), "executive"),
)


def _first_match(pattern: re.Pattern[str], html: str) -> str | None:
    match = pattern.search(html)
    return match.group(1) if match else None


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

    if intro and description and intro == description:
        description = None

    return intro, description


def _clean_person_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name).strip(" .,-")
    cleaned = re.split(r"\band\b|\,", cleaned, maxsplit=1, flags=re.I)[0].strip()
    return cleaned


def extract_people_from_text(text: str, source: str) -> list[dict[str, str]]:
    people: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for pattern, role in FOUNDER_PATTERNS:
        for match in pattern.finditer(text):
            name = _clean_person_name(match.group(1))
            if len(name) < 3 or len(name.split()) > 5:
                continue
            key = (name.lower(), role)
            if key in seen:
                continue
            seen.add(key)
            people.append({"name": name, "role": role, "source": source})

    return people


def build_profile_url(username: str | None) -> str | None:
    if not username:
        return None
    return f"{EBAY_BASE_URL}/usr/{username}"


def extract_store_metadata(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    fields = extract_json_fields(html)
    seller_info = parse_seller_info_block(soup)
    about_intro, about_description = extract_about_text(soup)
    feedback_summary = extract_feedback_summary(html)

    owner_username = fields.get("owner_username") or seller_info.get("seller")
    store_name = fields.get("store_name")
    seller_id = fields.get("seller_id") or owner_username

    combined_text = " ".join(
        part for part in (about_intro, about_description) if part
    )
    people = extract_people_from_text(combined_text, source="about_text")

    if owner_username:
        people.insert(
            0,
            {
                "name": owner_username,
                "role": "seller",
                "source": "store_owner",
            },
        )

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
