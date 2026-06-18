#!/usr/bin/env python3
"""CLI entry point for e-shop scrapers."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from scrapers.drybarshops import DrybarShopsScraper
from scrapers.ebay import EbayShopScraper
from scrapers.ebay_people import EbayPeopleScraper
from scrapers.openai_scraper import OpenAIScraper

load_dotenv()


def resolve_openai_api_key(explicit_key: str | None) -> str:
    api_key = (explicit_key or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError(
            "OpenAI API key is required. Set OPENAI_API_KEY in your environment "
            "or .env file, or pass --api-key."
        )
    return api_key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape product listings from e-shops.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    drybar = subparsers.add_parser("drybarshops", help="Scrape drybarshops.com catalog")
    drybar.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output/drybarshops_products.json"),
        help="Path to write JSON output",
    )
    drybar.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    ebay = subparsers.add_parser("ebay", help="Scrape an eBay store product list")
    ebay.add_argument(
        "shop",
        help="Store slug, /str/{slug} URL, or /usr/{seller} profile URL",
    )
    ebay.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Path to write JSON output (default: output/ebay_{shop}_products.json)",
    )
    ebay.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum number of store pages to scrape (default: all detected pages)",
    )
    ebay.add_argument(
        "--items-per-page",
        type=int,
        default=None,
        help="Items per page via _ipg query param (24, 48, or 72)",
    )
    ebay.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between page requests (default: 1.0)",
    )
    ebay.add_argument(
        "--openai",
        action="store_true",
        help="Use OpenAI to extract listings from HTML instead of CSS parsing",
    )
    ebay.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="OpenAI model when --openai is set (default: gpt-4o-mini)",
    )
    ebay.add_argument(
        "--api-key",
        default=None,
        help="OpenAI API key (default: OPENAI_API_KEY env var)",
    )
    ebay.add_argument(
        "--no-owner",
        action="store_true",
        help="Skip attaching store owner/seller fields to each listing",
    )
    ebay.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    people = subparsers.add_parser(
        "people",
        help="Scrape eBay store owner profile and people/founder mentions",
    )
    people.add_argument(
        "shop",
        help="Store slug, /str/{slug} URL, or /usr/{seller} profile URL",
    )
    people.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Path to write JSON output (default: output/ebay_{shop}_people.json)",
    )
    people.add_argument(
        "--openai",
        action="store_true",
        help="Also use OpenAI to identify founders and key people for the brand",
    )
    people.add_argument(
        "--no-wikidata",
        action="store_true",
        help="Skip Wikidata lookup for company founders and executives",
    )
    people.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="OpenAI model when --openai is set (default: gpt-4o-mini)",
    )
    people.add_argument(
        "--api-key",
        default=None,
        help="OpenAI API key (default: OPENAI_API_KEY env var)",
    )
    people.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    openai_cmd = subparsers.add_parser(
        "openai",
        help="Scrape any shop page using OpenAI extraction",
    )
    openai_cmd.add_argument(
        "url",
        help="Shop or product listing page URL",
    )
    openai_cmd.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Path to write JSON output (default: output/openai_{host}_products.json)",
    )
    openai_cmd.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Number of pages to scrape (default: 1)",
    )
    openai_cmd.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between page requests (default: 1.0)",
    )
    openai_cmd.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="OpenAI model (default: gpt-4o-mini)",
    )
    openai_cmd.add_argument(
        "--api-key",
        default=None,
        help="OpenAI API key (default: OPENAI_API_KEY env var)",
    )
    openai_cmd.add_argument(
        "--instructions",
        default=None,
        help="Extra instructions passed to the OpenAI extractor",
    )
    openai_cmd.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    return parser


def save_output(path: Path, products: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(products, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def format_ebay_price(product: dict) -> str:
    price = product.get("price") or product.get("price_min")
    original = product.get("original_price")
    if price and original:
        return f"{price} (was {original})"
    return price or "N/A"


def format_openai_price(product: dict) -> str:
    price = product.get("price")
    original = product.get("original_price")
    if price and original:
        return f"{price} (was {original})"
    return price or "N/A"


def default_openai_output(url: str) -> Path:
    host = urlparse(url).netloc.replace("www.", "")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", host).strip("_") or "shop"
    return Path(f"output/openai_{slug}_products.json")


def run_drybar(args: argparse.Namespace) -> None:
    products = DrybarShopsScraper().scrape()
    save_output(args.output, products)

    print(f"Saved {len(products)} products to {args.output.as_posix()}")
    print("\nSample products:")
    for product in products[:5]:
        price = product.get("price_range") or product.get("price")
        categories = ", ".join(product.get("categories") or []) or "Uncategorized"
        print(f"  - {product['title']} ({price}) [{categories}]")

    if args.pretty:
        print("\n" + json.dumps(products, indent=2, ensure_ascii=False))


def run_ebay(args: argparse.Namespace) -> None:
    api_key = resolve_openai_api_key(args.api_key) if args.openai else args.api_key
    scraper = EbayShopScraper(
        shop=args.shop,
        max_pages=args.max_pages,
        items_per_page=args.items_per_page,
        delay_seconds=args.delay,
        verbose=True,
        use_openai=args.openai,
        openai_api_key=api_key,
        openai_model=args.model,
        include_owner=not args.no_owner,
    )

    mode = "OpenAI" if args.openai else "HTML"
    print(f"Scraping eBay store ({mode}): {scraper.store_url}")
    products = scraper.scrape()

    output = args.output
    if output is None:
        slug = scraper.store_slug or "shop"
        output = Path(f"output/ebay_{slug}_products.json")

    save_output(output, products)

    print(f"\nSaved {len(products)} products to {output.as_posix()}")
    if products and products[0].get("owner_username"):
        print(
            f"Store owner: {products[0]['owner_username']} "
            f"({products[0].get('store_name') or 'N/A'})"
        )
    print("\nSample listings:")
    for product in products[:5]:
        print(f"  - {product['title']} [{format_ebay_price(product)}]")

    if args.pretty:
        print("\n" + json.dumps(products, indent=2, ensure_ascii=False))


def run_people(args: argparse.Namespace) -> None:
    api_key = resolve_openai_api_key(args.api_key) if args.openai else args.api_key
    scraper = EbayPeopleScraper(
        shop=args.shop,
        verbose=True,
        use_openai=args.openai,
        use_wikidata=not args.no_wikidata,
        openai_api_key=api_key,
        openai_model=args.model,
    )
    sources = []
    if not args.no_wikidata:
        sources.append("Wikidata")
    sources.append("eBay")
    if args.openai:
        sources.append("OpenAI")
    print(
        f"Scraping eBay store people/founders ({' + '.join(sources)}): "
        f"{scraper.store_url}"
    )
    profile = scraper.scrape()

    output = args.output
    if output is None:
        slug = scraper.store_slug or "shop"
        output = Path(f"output/ebay_{slug}_people.json")

    save_json(output, profile)

    print(f"\nSaved store profile to {output.as_posix()}")
    print(f"  Store: {profile.get('store_name') or profile.get('store_slug')}")
    if profile.get("company_name") and profile.get("company_name") != profile.get("store_name"):
        print(f"  Company: {profile['company_name']}")
    if profile.get("company_description"):
        print(f"  Company info: {profile['company_description']}")
    if profile.get("founded_year"):
        print(f"  Founded: {profile['founded_year']}")
    if profile.get("wikidata_url"):
        print(f"  Wikidata: {profile['wikidata_url']}")
    print(f"  Owner: {profile.get('owner_username') or 'N/A'}")
    if profile.get("seller_display_name"):
        print(f"  Display name: {profile['seller_display_name']}")
    if profile.get("seller_badge"):
        print(f"  Badge: {profile['seller_badge']}")
    if profile.get("location"):
        print(f"  Location: {profile['location']}")
    if profile.get("member_since"):
        print(f"  Member since: {profile['member_since']}")
    if profile.get("feedback_summary"):
        print(f"  Feedback: {profile['feedback_summary']}")

    people = profile.get("people") or []
    print(f"\nPeople ({len(people)}):")
    if not people:
        print("  (none found)")
        if not args.openai and not args.no_wikidata:
            print("  Tip: pass --openai for additional enrichment when Wikidata has no match")
        elif args.no_wikidata and not args.openai:
            print("  Tip: Wikidata is enabled by default; pass --openai for brand knowledge fallback")
    for person in people:
        details = person.get("details")
        suffix = f" — {details}" if details else ""
        wikidata = person.get("wikidata_id")
        if wikidata:
            suffix = f"{suffix} [{wikidata}]" if suffix else f" [{wikidata}]"
        print(
            f"  - {person['name']} ({person['role']}) "
            f"[{person.get('source')}]{suffix}"
        )

    if profile.get("about_intro"):
        intro = profile["about_intro"]
        print(f"\nAbout: {intro[:200]}{'...' if len(intro) > 200 else ''}")

    if args.pretty:
        print("\n" + json.dumps(profile, indent=2, ensure_ascii=False))


def run_openai(args: argparse.Namespace) -> None:
    api_key = resolve_openai_api_key(args.api_key)
    scraper = OpenAIScraper(
        api_key=api_key,
        model=args.model,
        max_pages=args.max_pages,
        delay_seconds=args.delay,
        instructions=args.instructions,
        verbose=True,
    )

    print(f"Scraping with OpenAI ({args.model}): {args.url}")
    products = scraper.scrape(args.url)

    output = args.output or default_openai_output(args.url)
    save_output(output, products)

    print(f"\nSaved {len(products)} products to {output.as_posix()}")
    print("\nSample listings:")
    for product in products[:5]:
        print(f"  - {product['title']} [{format_openai_price(product)}]")

    if args.pretty:
        print("\n" + json.dumps(products, indent=2, ensure_ascii=False))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "drybarshops":
            run_drybar(args)
        elif args.command == "ebay":
            run_ebay(args)
        elif args.command == "people":
            run_people(args)
        elif args.command == "openai":
            run_openai(args)
        else:
            parser.error(f"Unknown command: {args.command}")
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
