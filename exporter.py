"""Export apartment listings to CSV and JSON."""

import csv
import json
import os
from datetime import datetime
from typing import List

from models import Apartment

# Column order for CSV output
CSV_COLUMNS = [
    "title",
    "price",
    "bedrooms",
    "bathrooms",
    "sqft",
    "address",
    "city",
    "state",
    "zip_code",
    "neighborhood",
    "url",
    "source",
    "date_posted",
    "date_scraped",
    "amenities",
    "pet_policy",
    "phone",
]


def _ensure_output_dir(directory: str):
    """Create the output directory if it doesn't exist."""
    os.makedirs(directory, exist_ok=True)


def _make_filename(directory: str, prefix: str, ext: str, use_timestamp: bool) -> str:
    """Build an output filename."""
    if use_timestamp:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{prefix}_{ts}.{ext}"
    else:
        name = f"{prefix}.{ext}"
    return os.path.join(directory, name)


def export_csv(listings: List[Apartment], config: dict) -> str:
    """Export listings to a CSV file. Returns the file path."""
    out_cfg = config.get("output", {})
    directory = out_cfg.get("directory", "output")
    use_ts = out_cfg.get("timestamp_filenames", True)

    _ensure_output_dir(directory)
    filepath = _make_filename(directory, "apartments", "csv", use_ts)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for apt in listings:
            row = apt.to_dict()
            # Format price for readability
            if row.get("price") is not None:
                row["price"] = f"${row['price']:,}"
            writer.writerow(row)

    return filepath


def export_json(listings: List[Apartment], config: dict) -> str:
    """Export listings to a JSON file. Returns the file path."""
    out_cfg = config.get("output", {})
    directory = out_cfg.get("directory", "output")
    use_ts = out_cfg.get("timestamp_filenames", True)

    _ensure_output_dir(directory)
    filepath = _make_filename(directory, "apartments", "json", use_ts)

    data = {
        "metadata": {
            "search_city": config.get("search", {}).get("city", ""),
            "search_state": config.get("search", {}).get("state", ""),
            "rent_range": f"${config.get('search', {}).get('min_rent', 0)}-${config.get('search', {}).get('max_rent', 0)}",
            "bedrooms": config.get("search", {}).get("bedrooms", []),
            "total_results": len(listings),
            "scraped_at": datetime.now().isoformat(),
        },
        "listings": [apt.to_dict() for apt in listings],
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return filepath


def export_all(listings: List[Apartment], config: dict) -> dict:
    """Export listings to all enabled formats. Returns dict of format -> filepath."""
    out_cfg = config.get("output", {})
    paths = {}

    if out_cfg.get("csv", True):
        paths["csv"] = export_csv(listings, config)

    if out_cfg.get("json", True):
        paths["json"] = export_json(listings, config)

    return paths


def print_summary_table(listings: List[Apartment], limit: int = 20):
    """Print a formatted summary table to the terminal."""
    if not listings:
        print("\n  No listings found matching your criteria.\n")
        return

    # Column widths
    w_price = 10
    w_br = 8
    w_sqft = 8
    w_city = 18
    w_source = 16
    w_title = 36

    header = (
        f"  {'Price':<{w_price}} "
        f"{'Beds':<{w_br}} "
        f"{'Sq Ft':<{w_sqft}} "
        f"{'City':<{w_city}} "
        f"{'Source':<{w_source}} "
        f"{'Title':<{w_title}}"
    )
    separator = "  " + "-" * (w_price + w_br + w_sqft + w_city + w_source + w_title + 5)

    print(f"\n  Found {len(listings)} listing(s):\n")
    print(header)
    print(separator)

    displayed = listings[:limit]
    for apt in displayed:
        price_str = apt.price_display
        br_str = apt.bedrooms or "N/A"
        sqft_str = f"{apt.sqft:,}" if apt.sqft else "N/A"
        city_str = apt.city or "N/A"
        source_str = apt.source
        title_str = (apt.title[:w_title - 3] + "...") if len(apt.title) > w_title else apt.title

        print(
            f"  {price_str:<{w_price}} "
            f"{br_str:<{w_br}} "
            f"{sqft_str:<{w_sqft}} "
            f"{city_str:<{w_city}} "
            f"{source_str:<{w_source}} "
            f"{title_str:<{w_title}}"
        )

    if len(listings) > limit:
        print(f"\n  ... and {len(listings) - limit} more (see output files for full results)")

    print()
