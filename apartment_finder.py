#!/usr/bin/env python3
"""
ApartmentFinder — Scrape structured rental data from reputable sources.

Usage:
    python apartment_finder.py                   # Use config.yaml defaults
    python apartment_finder.py --config my.yaml  # Use a custom config file
    python apartment_finder.py --city "Raleigh" --state NC --max-rent 1200
"""

import argparse
import os
import sys
from datetime import datetime

import yaml

from exporter import export_all, print_summary_table
from models import Apartment
from scrapers import (
    ApartmentsComScraper,
    CraigslistScraper,
    RentComScraper,
    ZillowScraper,
)

BANNER = """
╔══════════════════════════════════════════════╗
║           ApartmentFinder v1.0               ║
║   Structured rental data from the web        ║
╚══════════════════════════════════════════════╝
"""

# Map config keys to scraper classes
SCRAPER_MAP = {
    "apartments_com": ApartmentsComScraper,
    "craigslist": CraigslistScraper,
    "zillow": ZillowScraper,
    "rent_com": RentComScraper,
}


def load_config(path: str) -> dict:
    """Load and return the YAML config file."""
    if not os.path.isfile(path):
        print(f"Error: Config file not found: {path}")
        sys.exit(1)

    with open(path, "r") as f:
        return yaml.safe_load(f)


def apply_cli_overrides(config: dict, args: argparse.Namespace) -> dict:
    """Override config values with any CLI arguments provided."""
    search = config.setdefault("search", {})

    if args.city:
        search["city"] = args.city
    if args.state:
        search["state"] = args.state
    if args.min_rent is not None:
        search["min_rent"] = args.min_rent
    if args.max_rent is not None:
        search["max_rent"] = args.max_rent
    if args.bedrooms:
        search["bedrooms"] = args.bedrooms
    if args.radius is not None:
        search["radius_miles"] = args.radius

    return config


def deduplicate(listings: list) -> list:
    """Remove duplicate listings based on URL or title+price."""
    seen_urls = set()
    seen_keys = set()
    unique = []

    for apt in listings:
        # Deduplicate by URL first
        if apt.url:
            url_clean = apt.url.rstrip("/").lower()
            if url_clean in seen_urls:
                continue
            seen_urls.add(url_clean)

        # Then by title + price combo
        key = (apt.title.lower().strip(), apt.price)
        if key in seen_keys and apt.title:
            continue
        seen_keys.add(key)

        unique.append(apt)

    return unique


def run_scrapers(config: dict) -> list:
    """Run all enabled scrapers and return combined results."""
    sources = config.get("sources", {})
    all_listings = []

    for name, scraper_cls in SCRAPER_MAP.items():
        if sources.get(name, False):
            scraper = scraper_cls(config)
            listings = scraper.run()
            all_listings.extend(listings)
        else:
            print(f"  [{name}] Skipped (disabled in config)")

    return all_listings


def filter_results(listings: list, config: dict) -> list:
    """Apply search filters to the combined results."""
    search = config.get("search", {})
    min_rent = search.get("min_rent", 0)
    max_rent = search.get("max_rent", 99999)
    bedrooms = search.get("bedrooms", [])
    state = search.get("state", "")
    restrict = search.get("restrict_to_state", False)

    # Normalize bedroom labels
    br_labels = []
    for b in bedrooms:
        b_str = str(b).lower().strip()
        if b_str in ("0", "studio"):
            br_labels.append("studio")
            br_labels.append("0")
        else:
            br_labels.append(b_str)

    filtered = []
    for apt in listings:
        # Price filter
        if apt.price is not None:
            if apt.price < min_rent or apt.price > max_rent:
                continue

        # Bedroom filter
        if br_labels:
            br_val = apt.bedrooms.lower().strip()
            if br_val and br_val not in br_labels:
                continue

        # State restriction
        if restrict and state and apt.state:
            if apt.state.upper() != state.upper():
                continue

        filtered.append(apt)

    return filtered


def main():
    parser = argparse.ArgumentParser(
        description="Scrape structured apartment rental data from reputable sources."
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to the YAML config file (default: config.yaml)"
    )
    parser.add_argument("--city", help="Override search city")
    parser.add_argument("--state", help="Override search state (2-letter code)")
    parser.add_argument("--min-rent", type=int, help="Override minimum rent")
    parser.add_argument("--max-rent", type=int, help="Override maximum rent")
    parser.add_argument(
        "--bedrooms", nargs="+",
        help="Override bedrooms (e.g., studio 1 2)"
    )
    parser.add_argument("--radius", type=int, help="Override search radius in miles")
    args = parser.parse_args()

    print(BANNER)

    # Load config
    config = load_config(args.config)
    config = apply_cli_overrides(config, args)

    search = config.get("search", {})
    print(f"  Search: {search.get('city', '?')}, {search.get('state', '?')}")
    print(f"  Rent:   ${search.get('min_rent', 0):,} – ${search.get('max_rent', 0):,}")
    print(f"  Beds:   {', '.join(str(b) for b in search.get('bedrooms', []))}")
    print(f"  Radius: {search.get('radius_miles', 'N/A')} miles")
    print()

    # Scrape
    print("Scraping sources...")
    raw_listings = run_scrapers(config)

    # Filter
    print("\nFiltering results...")
    filtered = filter_results(raw_listings, config)

    # Deduplicate
    results = deduplicate(filtered)
    results.sort(key=lambda a: (a.price if a.price is not None else 99999))

    # Display summary table
    print_summary_table(results)

    # Export
    if results:
        print("Exporting results...")
        paths = export_all(results, config)
        for fmt, path in paths.items():
            print(f"  {fmt.upper()}: {path}")
        print("\nDone!")
    else:
        print("No results to export.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
