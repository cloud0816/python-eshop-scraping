#!/usr/bin/env python3
"""CLI entry point for scraping https://www.drybarshops.com/."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scrapers.drybarshops import DrybarShopsScraper


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape the Drybar Shops product/service catalog.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output/drybarshops_products.json"),
        help="Path to write JSON output (default: output/drybarshops_products.json)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scraper = DrybarShopsScraper()
    products = scraper.scrape()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(products, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(f"Saved {len(products)} products to {args.output}")
    if args.pretty:
        print(json.dumps(products, indent=2, ensure_ascii=False))

    for product in products[:5]:
        price = product.get("price_range") or product.get("price")
        categories = ", ".join(product.get("categories") or []) or "Uncategorized"
        print(f"- {product['title']} ({price}) [{categories}]")


if __name__ == "__main__":
    main()
