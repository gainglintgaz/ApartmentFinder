"""Export apartment listings to CSV and JSON with priority grouping."""

import csv
import json
import os
from datetime import datetime
from typing import List

from models import Apartment, TYPE_MARKET, TIER_PREFERRED, TIER_EXPANDED

# Column order for CSV — most important fields first
CSV_COLUMNS = [
    "housing_type",
    "location_tier",
    "is_recent",
    "title",
    "price",
    "bedrooms",
    "bathrooms",
    "sqft",
    "full_address",
    "address",
    "city",
    "state",
    "zip_code",
    "neighborhood",
    "directions_url",
    "phone",
    "contact_name",
    "url",
    "source",
    "date_posted",
    "date_scraped",
    "amenities",
    "pet_policy",
]


def _ensure_output_dir(directory: str):
    os.makedirs(directory, exist_ok=True)


def _make_filename(directory: str, prefix: str, ext: str, use_timestamp: bool) -> str:
    if use_timestamp:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{prefix}_{ts}.{ext}"
    else:
        name = f"{prefix}.{ext}"
    return os.path.join(directory, name)


def export_csv(listings: List[Apartment], config: dict) -> str:
    """Export listings to CSV with readable labels."""
    out_cfg = config.get("output", {})
    directory = out_cfg.get("directory", "output")
    use_ts = out_cfg.get("timestamp_filenames", True)

    _ensure_output_dir(directory)
    filepath = _make_filename(directory, "apartments", "csv", use_ts)

    type_labels = {"subsidized": "Subsidized", "senior": "Senior",
                   "section8": "Section 8", "market": "Market"}
    tier_labels = {"preferred": "Midland/East CLT", "expanded": "Greater Charlotte",
                   "other": "Other"}

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for apt in listings:
            row = apt.to_dict()
            row["price"] = apt.price_display
            row["housing_type"] = type_labels.get(row.get("housing_type", ""), "Market")
            row["location_tier"] = tier_labels.get(row.get("location_tier", ""), "Other")
            row["is_recent"] = "NEW (48h)" if row.get("is_recent") else ""
            writer.writerow(row)

    return filepath


def export_json(listings: List[Apartment], config: dict) -> str:
    """Export listings to JSON with full metadata."""
    out_cfg = config.get("output", {})
    directory = out_cfg.get("directory", "output")
    use_ts = out_cfg.get("timestamp_filenames", True)

    _ensure_output_dir(directory)
    filepath = _make_filename(directory, "apartments", "json", use_ts)

    search = config.get("search", {})
    resident = config.get("resident", {})

    # Group listings by category
    subsidized = [a.to_dict() for a in listings if a.is_subsidized_or_senior]
    preferred = [a.to_dict() for a in listings
                 if not a.is_subsidized_or_senior and a.location_tier == TIER_PREFERRED]
    expanded = [a.to_dict() for a in listings
                if not a.is_subsidized_or_senior and a.location_tier == TIER_EXPANDED]
    other = [a.to_dict() for a in listings
             if not a.is_subsidized_or_senior and a.location_tier not in (TIER_PREFERRED, TIER_EXPANDED)]

    data = {
        "metadata": {
            "resident": resident.get("name", ""),
            "resident_age": resident.get("age", ""),
            "monthly_income": resident.get("monthly_income", ""),
            "search_state": search.get("state", ""),
            "rent_range": f"${search.get('min_rent', 0)}-${search.get('max_rent', 0)}",
            "bedrooms": search.get("bedrooms", []),
            "total_results": len(listings),
            "scraped_at": datetime.now().isoformat(),
        },
        "priority_1_subsidized_senior": subsidized,
        "priority_2_preferred_location": preferred,
        "priority_3_greater_charlotte": expanded,
        "priority_4_other": other,
        "all_listings": [a.to_dict() for a in listings],
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return filepath


def export_markdown(listings: List[Apartment], config: dict) -> str:
    """Export listings to a RESULTS.md file readable on GitHub."""
    search = config.get("search", {})
    resident = config.get("resident", {})
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    # Group listings
    subsidized = [a for a in listings if a.is_subsidized_or_senior]
    preferred_market = [a for a in listings
                        if not a.is_subsidized_or_senior and a.location_tier == TIER_PREFERRED]
    expanded_market = [a for a in listings
                       if not a.is_subsidized_or_senior and a.location_tier == TIER_EXPANDED]
    other_market = [a for a in listings
                    if not a.is_subsidized_or_senior
                    and a.location_tier not in (TIER_PREFERRED, TIER_EXPANDED)]

    lines = []
    lines.append("# Apartment Search Results")
    lines.append("")
    lines.append(f"**Last updated:** {now}")
    lines.append("")
    lines.append(f"**Search:** ${search.get('min_rent', 0)}-${search.get('max_rent', 900)}/mo "
                 f"| {', '.join(str(b) for b in search.get('bedrooms', []))} bedroom(s) "
                 f"| {search.get('state', 'NC')}")
    lines.append("")
    lines.append(f"**Total listings found:** {len(listings)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Facebook reminder at top
    lines.append("> **Also check Facebook Marketplace** (can't be auto-searched):")
    lines.append("> [Click here to search Facebook Marketplace]"
                 "(https://www.facebook.com/marketplace/Midland-NC/propertyrentals"
                 "?minPrice=0&maxPrice=900&exact=false)")
    lines.append("")
    lines.append("---")
    lines.append("")

    groups = [
        ("Government / Subsidized / Senior Housing", subsidized),
        ("Midland & East Charlotte (Market Rentals)", preferred_market),
        ("Greater Charlotte (Market Rentals)", expanded_market),
        ("Other Areas (Market Rentals)", other_market),
    ]

    for group_name, group_listings in groups:
        lines.append(f"## {group_name} ({len(group_listings)})")
        lines.append("")

        if not group_listings:
            lines.append("_No listings found in this category._")
            lines.append("")
            continue

        # Table header
        lines.append("| Price | Beds | Address | Phone | Listed | Title | Link | Directions |")
        lines.append("|-------|------|---------|-------|--------|-------|------|------------|")

        for apt in group_listings:
            price = apt.price_display
            beds = apt.bedrooms or "?"
            address = apt.full_address or apt.address or apt.city or "?"
            phone = apt.phone or "-"
            listed = apt.date_posted or "-"
            title = apt.title[:40] + "..." if len(apt.title) > 40 else apt.title
            # Escape pipe characters in fields
            title = title.replace("|", "/")
            phone = phone.replace("|", "/")
            address = address.replace("|", "/")

            link = f"[View]({apt.url})" if apt.url else "-"
            directions = f"[Map]({apt.directions_url})" if apt.directions_url else "-"
            new_flag = " **NEW**" if apt.is_recent else ""

            lines.append(f"| {price}{new_flag} | {beds} | {address} | {phone} | {listed} | {title} | {link} | {directions} |")

        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append(f"_This page is automatically updated by GitHub Actions. "
                 f"Results are refreshed every 6 hours._")
    lines.append("")

    filepath = "RESULTS.md"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return filepath


def export_all(listings: List[Apartment], config: dict) -> dict:
    """Export to all enabled formats."""
    out_cfg = config.get("output", {})
    paths = {}
    if out_cfg.get("csv", True):
        paths["csv"] = export_csv(listings, config)
    if out_cfg.get("json", True):
        paths["json"] = export_json(listings, config)
    paths["markdown"] = export_markdown(listings, config)
    return paths


def print_summary_table(listings: List[Apartment], limit: int = 30):
    """Print grouped summary table to the terminal."""
    if not listings:
        print("\n  No listings found matching your criteria.\n")
        return

    subsidized = [a for a in listings if a.is_subsidized_or_senior]
    preferred_market = [a for a in listings
                        if not a.is_subsidized_or_senior and a.location_tier == TIER_PREFERRED]
    expanded_market = [a for a in listings
                       if not a.is_subsidized_or_senior and a.location_tier == TIER_EXPANDED]
    other_market = [a for a in listings
                    if not a.is_subsidized_or_senior
                    and a.location_tier not in (TIER_PREFERRED, TIER_EXPANDED)]

    total = len(listings)
    print(f"\n  Found {total} listing(s) total:\n")
    print(f"    Government/Subsidized/Senior: {len(subsidized)}")
    print(f"    Midland / East Charlotte:     {len(preferred_market)}")
    print(f"    Greater Charlotte:            {len(expanded_market)}")
    print(f"    Other NC:                     {len(other_market)}")

    groups = [
        ("GOVERNMENT / SUBSIDIZED / SENIOR HOUSING", subsidized),
        ("MIDLAND & EAST CHARLOTTE (Market)", preferred_market),
        ("GREATER CHARLOTTE (Market)", expanded_market),
        ("OTHER AREAS (Market)", other_market),
    ]

    for group_name, group_listings in groups:
        if not group_listings:
            continue

        print(f"\n  --- {group_name} ({len(group_listings)}) ---\n")
        _print_group(group_listings, limit=limit)

    print()


def _print_group(listings: List[Apartment], limit: int = 15):
    """Print a single group of listings as a table."""
    w_new = 6
    w_price = 10
    w_br = 6
    w_city = 16
    w_phone = 16
    w_source = 20
    w_title = 32

    header = (
        f"  {'New?':<{w_new}} "
        f"{'Price':<{w_price}} "
        f"{'Beds':<{w_br}} "
        f"{'City':<{w_city}} "
        f"{'Phone':<{w_phone}} "
        f"{'Source':<{w_source}} "
        f"{'Title':<{w_title}}"
    )
    sep_len = w_new + w_price + w_br + w_city + w_phone + w_source + w_title + 6
    separator = "  " + "-" * sep_len

    print(header)
    print(separator)

    for apt in listings[:limit]:
        new_flag = "* NEW" if apt.is_recent else ""
        price_str = apt.price_display
        br_str = apt.bedrooms or "?"
        city_str = apt.city or "?"
        phone_str = apt.phone or ""
        source_str = apt.source
        title_str = (apt.title[:w_title - 3] + "...") if len(apt.title) > w_title else apt.title

        if len(city_str) > w_city:
            city_str = city_str[:w_city - 2] + ".."
        if len(phone_str) > w_phone:
            phone_str = phone_str[:w_phone - 2] + ".."
        if len(source_str) > w_source:
            source_str = source_str[:w_source - 2] + ".."

        print(
            f"  {new_flag:<{w_new}} "
            f"{price_str:<{w_price}} "
            f"{br_str:<{w_br}} "
            f"{city_str:<{w_city}} "
            f"{phone_str:<{w_phone}} "
            f"{source_str:<{w_source}} "
            f"{title_str:<{w_title}}"
        )

    if len(listings) > limit:
        print(f"\n  ... and {len(listings) - limit} more (see output files for full results)")
