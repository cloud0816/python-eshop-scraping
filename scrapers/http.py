"""Shared HTTP helpers for scrapers."""

from __future__ import annotations

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_html(url: str, session: requests.Session | None = None) -> str:
    client = session or requests.Session()
    if session is None:
        client.headers.update(DEFAULT_HEADERS)
    response = client.get(url, timeout=30)
    response.raise_for_status()
    return response.text
