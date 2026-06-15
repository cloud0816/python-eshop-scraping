#!/usr/bin/env python3
"""CLI entry point for e-shop scrapers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scrapers.drybarshops import DrybarShopsScraper
from scrapers.ebay import EbayShopScraper


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
    ebay.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    return parser


def save_output(path: Path, products: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(products, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def format_ebay_price(product: dict) -> str:
    price = product.get("price") or product.get("price_min")
    original = product.get("original_price")
    if price and original:
        return f"{price} (was {original})"
    return price or "N/A"


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
    scraper = EbayShopScraper(
        shop=args.shop,
        max_pages=args.max_pages,
        items_per_page=args.items_per_page,
        delay_seconds=args.delay,
        verbose=True,
    )

    print(f"Scraping eBay store: {scraper.store_url}")
    products = scraper.scrape()

    output = args.output
    if output is None:
        slug = scraper.store_slug or "shop"
        output = Path(f"output/ebay_{slug}_products.json")

    save_output(output, products)

    print(f"\nSaved {len(products)} products to {output.as_posix()}")
    print("\nSample listings:")
    for product in products[:5]:
        print(f"  - {product['title']} [{format_ebay_price(product)}]")

    if args.pretty:
        print("\n" + json.dumps(products, indent=2, ensure_ascii=False))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "drybarshops":
        run_drybar(args)
    elif args.command == "ebay":
        run_ebay(args)
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
