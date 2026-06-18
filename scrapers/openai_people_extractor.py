"""Extract founders and key people using the OpenAI API."""

from __future__ import annotations

import os
import re
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field

SYSTEM_PROMPT = """You identify company founders, owners, and key executives for e-commerce stores.
Use the store name, about page text, and seller profile details provided.
Return real people associated with the brand or business behind the store.
Do not return eBay seller usernames (like brand_official) unless they clearly refer to an individual person.
If the brand is well-known and founders are public knowledge, include them with role "founder".
If no people can be identified with reasonable confidence, return an empty list.
Do not invent people. Prefer empty results over guesses."""


class ExtractedPerson(BaseModel):
    name: str
    role: str = Field(
        description='One of: founder, co-founder, owner, ceo, executive, team, other'
    )
    details: str | None = None


class PeopleExtraction(BaseModel):
    company_name: str | None = None
    founded_year: str | None = None
    people: list[ExtractedPerson] = Field(default_factory=list)


class OpenAIPeopleExtractor:
    """Use OpenAI structured outputs to identify founders and key people."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
    ) -> None:
        resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved_key:
            raise ValueError(
                "OpenAI API key is required. Set OPENAI_API_KEY or pass --api-key."
            )
        self.client = OpenAI(api_key=resolved_key)
        self.model = model

    def extract_people(
        self,
        *,
        store_name: str | None,
        owner_username: str | None,
        about_text: str | None,
        seller_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile_lines = []
        if seller_profile:
            for key, value in seller_profile.items():
                if value and key != "card_summary":
                    profile_lines.append(f"{key}: {value}")

        user_prompt = "\n".join(
            part
            for part in [
                f"Store name: {store_name or 'Unknown'}",
                f"eBay seller username: {owner_username or 'Unknown'}",
                f"About page:\n{about_text}" if about_text else None,
                "Seller profile:\n" + "\n".join(profile_lines)
                if profile_lines
                else None,
            ]
            if part
        )

        completion = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format=PeopleExtraction,
        )

        message = completion.choices[0].message
        if message.refusal:
            raise RuntimeError(f"OpenAI refused the request: {message.refusal}")

        parsed = message.parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned no parsed people data")

        people: list[dict[str, str | None]] = []
        for person in parsed.people:
            name = person.name.strip()
            if not name:
                continue
            if owner_username and name.lower() == owner_username.lower():
                continue
            if re.fullmatch(r"[a-z0-9_\-]{3,}", name, re.I):
                continue
            people.append(
                {
                    "name": name,
                    "role": person.role.strip().lower(),
                    "details": person.details,
                    "source": "openai",
                }
            )

        return {
            "company_name": parsed.company_name,
            "founded_year": parsed.founded_year,
            "people": people,
        }
