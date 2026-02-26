#!/usr/bin/env python3
"""
ApartmentFinder — Senior & Affordable Housing Search

Searches government/subsidized sources first, then market rentals.
Prioritizes Midland & East Charlotte, then Greater Charlotte area.
Outputs to both CSV and JSON with Google Maps directions links.

Usage:
    python apartment_finder.py                   # Full search
    python apartment_finder.py --subsidized-only  # Only government/senior housing
    python apartment_finder.py --market-only      # Only market rentals
    python apartment_finder.py --max-rent 700     # Override max rent
"""

import argparse
import os
import sys
from datetime import datetime

import yaml

from exporter import export_all, print_summary_table
from models import (
    Apartment, classify_location, classify_recency, sort_key,
    TYPE_SUBSIDIZED, TYPE_SENIOR, TYPE_SECTION8, TYPE_MARKET,
)
from scrapers import (
    SocialServeScraper,
    HUDScraper,
    AffordableHousingScraper,
    GoSection8Scraper,
    ApartmentsComScraper,
    CraigslistScraper,
    RentComScraper,
    ZillowScraper,
)

BANNER = """
╔═══════════════════════════════════════════════════════════╗
║            ApartmentFinder v2.0                           ║
║   Senior & Affordable Housing Search                      ║
║   Charlotte NC / Midland / East Charlotte                 ║
╚═══════════════════════════════════════════════════════════╝
"""

# Map source config keys to scraper classes and their priority
SCRAPER_MAP = {
    # Priority 1: Government / Subsidized / Senior
    "socialserve":       (SocialServeScraper, 1),
    "hud":               (HUDScraper, 1),
    "affordablehousing": (AffordableHousingScraper, 1),
    "gosection8":        (GoSection8Scraper, 1),
    # Priority 2: Market Rentals
    "apartments_com":    (ApartmentsComScraper, 2),
    "craigslist":        (CraigslistScraper, 2),
    "zillow":            (ZillowScraper, 2),
    "rent_com":          (RentComScraper, 2),
}


def load_config(path: str) -> dict:
    if not os.path.isfile(path):
        print(f"Error: Config file not found: {path}")
        sys.exit(1)
    with open(path, "r") as f:
        return yaml.safe_load(f)


def apply_cli_overrides(config: dict, args: argparse.Namespace) -> dict:
    search = config.setdefault("search", {})
    if args.max_rent is not None:
        search["max_rent"] = args.max_rent
    if args.min_rent is not None:
        search["min_rent"] = args.min_rent
    if args.bedrooms:
        search["bedrooms"] = args.bedrooms
    return config


def deduplicate(listings: list) -> list:
    """Remove duplicate listings based on URL or title+price."""
    seen_urls = set()
    seen_keys = set()
    unique = []

    for apt in listings:
        if apt.url:
            url_clean = apt.url.rstrip("/").lower()
            if url_clean in seen_urls:
                continue
            seen_urls.add(url_clean)

        key = (apt.title.lower().strip(), apt.price)
        if key in seen_keys and apt.title:
            continue
        seen_keys.add(key)

        unique.append(apt)

    return unique


def run_scrapers(config: dict, priority_filter: int = None) -> list:
    """Run enabled scrapers, optionally filtering by priority."""
    sources = config.get("sources", {})
    all_listings = []

    # Sort by priority so Priority 1 runs first
    ordered = sorted(SCRAPER_MAP.items(), key=lambda x: x[1][1])

    for name, (scraper_cls, priority) in ordered:
        source_cfg = sources.get(name, {})

        # Handle both old-style (bool) and new-style (dict) config
        if isinstance(source_cfg, bool):
            enabled = source_cfg
        elif isinstance(source_cfg, dict):
            enabled = source_cfg.get("enabled", False)
        else:
            enabled = False

        if not enabled:
            print(f"  [{name}] Skipped (disabled)")
            continue

        if priority_filter is not None and priority != priority_filter:
            continue

        scraper = scraper_cls(config)
        listings = scraper.run()
        all_listings.extend(listings)

    return all_listings


def filter_results(listings: list, config: dict) -> list:
    """Apply search filters to combined results."""
    search = config.get("search", {})
    min_rent = search.get("min_rent", 0)
    max_rent = search.get("max_rent", 99999)
    bedrooms = search.get("bedrooms", [])
    state = search.get("state", "")
    restrict = search.get("restrict_to_state", False)

    # Normalize bedroom labels
    br_labels = set()
    for b in bedrooms:
        b_str = str(b).lower().strip()
        if b_str in ("0", "studio"):
            br_labels.add("studio")
            br_labels.add("0")
        else:
            br_labels.add(b_str)

    filtered = []
    for apt in listings:
        # Subsidized/senior listings: relax price filter (some are income-based)
        if apt.is_subsidized_or_senior:
            if apt.price is not None and apt.price > max_rent * 1.5:
                continue
        else:
            # Market listings: strict price filter
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


def classify_all(listings: list, config: dict):
    """Classify location tier and recency for all listings."""
    search = config.get("search", {})
    recent_hours = search.get("highlight_recent_hours", 48)

    for apt in listings:
        apt.build_full_address()
        classify_location(apt, config)
        classify_recency(apt, recent_hours)


def main():
    parser = argparse.ArgumentParser(
        description="Senior & Affordable Housing Search — Charlotte NC area"
    )
    parser.add_argument("--config", "-c", default="config.yaml",
                        help="Path to YAML config file")
    parser.add_argument("--min-rent", type=int, help="Override minimum rent")
    parser.add_argument("--max-rent", type=int, help="Override maximum rent")
    parser.add_argument("--bedrooms", nargs="+",
                        help="Override bedrooms (e.g., studio 1 2)")
    parser.add_argument("--subsidized-only", action="store_true",
                        help="Only search government/subsidized/senior sources")
    parser.add_argument("--market-only", action="store_true",
                        help="Only search market rental sources")
    args = parser.parse_args()

    print(BANNER)

    config = load_config(args.config)
    config = apply_cli_overrides(config, args)

    search = config.get("search", {})
    resident = config.get("resident", {})

    print(f"  Resident: {resident.get('name', 'N/A')}, age {resident.get('age', '?')}")
    print(f"  Income:   ${resident.get('monthly_income', 0):,}/mo")
    print(f"  Rent:     ${search.get('min_rent', 0):,} – ${search.get('max_rent', 0):,}")
    print(f"  Beds:     {', '.join(str(b) for b in search.get('bedrooms', []))}")
    print(f"  State:    {search.get('state', 'NC')} only")
    print()

    # Determine priority filter
    priority_filter = None
    if args.subsidized_only:
        priority_filter = 1
        print("  Mode: Subsidized/Senior sources only")
    elif args.market_only:
        priority_filter = 2
        print("  Mode: Market rental sources only")
    else:
        print("  Mode: All sources (government first, then market)")
    print()

    # ---- PHASE 1: Scrape ----
    print("=" * 55)
    print("  PHASE 1: Scraping sources...")
    print("=" * 55)
    raw_listings = run_scrapers(config, priority_filter)

    # ---- PHASE 2: Filter ----
    print("\n  Filtering results...")
    filtered = filter_results(raw_listings, config)

    # ---- PHASE 3: Deduplicate ----
    results = deduplicate(filtered)

    # ---- PHASE 4: Classify & Sort ----
    classify_all(results, config)
    results.sort(key=sort_key)

    # ---- PHASE 5: Display ----
    print_summary_table(results)

    # ---- PHASE 6: Export ----
    if results:
        print("  Exporting results...")
        paths = export_all(results, config)
        for fmt, path in paths.items():
            print(f"    {fmt.upper()}: {path}")

        print(f"\n  Total: {len(results)} listings")
        subsidized_count = sum(1 for a in results if a.is_subsidized_or_senior)
        if subsidized_count:
            print(f"  Government/Subsidized/Senior: {subsidized_count}")
        recent_count = sum(1 for a in results if a.is_recent)
        if recent_count:
            print(f"  Posted in last 48h: {recent_count}")

        # Remind about monitor
        monitor_cfg = config.get("monitor", {})
        if monitor_cfg.get("enabled", False):
            print("\n  To watch for NEW listings as they appear:")
            print("    python monitor.py")
            print("    python monitor.py --once   (check once and exit)")

        print("\n  Done!")
    else:
        print("  No results to export.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
