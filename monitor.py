"""Listing monitor — watches for new apartments and sends alerts.

Run this as a long-running process:
    python monitor.py
    python monitor.py --config config.yaml

It will check all sources on the configured interval and alert you
when new listings appear that match your criteria.
"""

import argparse
import hashlib
import json
import os
import smtplib
import sys
import time
from datetime import datetime
from email.mime.text import MIMEText
from typing import List

import yaml

from models import (
    Apartment, classify_location, classify_recency, sort_key,
    TYPE_MARKET,
)


def _listing_id(apt: Apartment) -> str:
    """Generate a unique ID for a listing based on URL or title+price."""
    if apt.url:
        return hashlib.md5(apt.url.lower().encode()).hexdigest()
    key = f"{apt.title.lower()}|{apt.price}|{apt.address.lower()}"
    return hashlib.md5(key.encode()).hexdigest()


def load_seen_db(path: str) -> dict:
    """Load the seen-listings database."""
    if os.path.isfile(path):
        with open(path, "r") as f:
            return json.load(f)
    return {"seen": {}, "last_check": ""}


def save_seen_db(path: str, db: dict):
    """Save the seen-listings database."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(db, f, indent=2)


def find_new_listings(listings: List[Apartment], db: dict) -> List[Apartment]:
    """Return only listings not already in the seen database."""
    new = []
    for apt in listings:
        lid = _listing_id(apt)
        if lid not in db.get("seen", {}):
            new.append(apt)
    return new


def mark_seen(listings: List[Apartment], db: dict):
    """Mark listings as seen in the database."""
    for apt in listings:
        lid = _listing_id(apt)
        db["seen"][lid] = {
            "title": apt.title,
            "price": apt.price,
            "url": apt.url,
            "source": apt.source,
            "first_seen": datetime.now().isoformat(),
        }
    db["last_check"] = datetime.now().isoformat()


def format_alert_console(listings: List[Apartment]) -> str:
    """Format new listings for console output."""
    lines = [
        "",
        "=" * 70,
        f"  NEW LISTINGS FOUND — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"  {len(listings)} new listing(s) matching your criteria",
        "=" * 70,
    ]

    for i, apt in enumerate(listings, 1):
        lines.append("")
        lines.append(f"  [{i}] {apt.title}")
        lines.append(f"      Type:     {apt.type_label}")
        lines.append(f"      Price:    {apt.price_display}/mo")
        lines.append(f"      Beds:     {apt.bedrooms or 'N/A'}")
        lines.append(f"      Location: {apt.full_address or apt.address or apt.city}")
        lines.append(f"      Area:     {apt.tier_label}")
        if apt.phone:
            lines.append(f"      Phone:    {apt.phone}")
        lines.append(f"      Link:     {apt.url}")
        if apt.directions_url:
            lines.append(f"      Directions: {apt.directions_url}")
        lines.append(f"      Source:   {apt.source}")

    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)


def format_alert_email(listings: List[Apartment]) -> str:
    """Format new listings for email body."""
    lines = [
        f"ApartmentFinder — {len(listings)} New Listing(s)",
        f"Checked at {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    for i, apt in enumerate(listings, 1):
        lines.append(f"--- Listing {i} ---")
        lines.append(f"Name:      {apt.title}")
        lines.append(f"Type:      {apt.type_label}")
        lines.append(f"Price:     {apt.price_display}/mo")
        lines.append(f"Beds:      {apt.bedrooms or 'N/A'}")
        lines.append(f"Address:   {apt.full_address or apt.address}")
        lines.append(f"Area:      {apt.tier_label}")
        if apt.phone:
            lines.append(f"Phone:     {apt.phone}")
        lines.append(f"Link:      {apt.url}")
        if apt.directions_url:
            lines.append(f"Directions: {apt.directions_url}")
        lines.append(f"Source:    {apt.source}")
        lines.append("")

    return "\n".join(lines)


def send_email(config: dict, subject: str, body: str):
    """Send an email alert."""
    email_cfg = config.get("monitor", {}).get("email", {})
    server = email_cfg.get("smtp_server", "")
    port = email_cfg.get("smtp_port", 587)
    sender = email_cfg.get("sender", "")
    password = email_cfg.get("password", "")
    recipient = email_cfg.get("recipient", "")

    if not all([server, sender, password, recipient]):
        print("  [monitor] Email not configured — skipping email alert")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    try:
        with smtplib.SMTP(server, port) as smtp:
            smtp.starttls()
            smtp.login(sender, password)
            smtp.send_message(msg)
        print(f"  [monitor] Email sent to {recipient}")
    except Exception as e:
        print(f"  [monitor] Email failed: {e}")


def notify(config: dict, new_listings: List[Apartment]):
    """Send notifications for new listings."""
    method = config.get("monitor", {}).get("notify_method", "console")

    if method in ("console", "both"):
        alert = format_alert_console(new_listings)
        print(alert)

    if method in ("email", "both"):
        subject = f"ApartmentFinder: {len(new_listings)} New Listing(s)"
        body = format_alert_email(new_listings)
        send_email(config, subject, body)


def run_check(config: dict, db: dict) -> List[Apartment]:
    """Run one check cycle: scrape, filter, find new, notify."""
    # Import here to avoid circular imports
    from apartment_finder import run_scrapers, filter_results, deduplicate

    print(f"\n  [monitor] Checking at {datetime.now().strftime('%H:%M:%S')}...")

    raw = run_scrapers(config)
    filtered = filter_results(raw, config)
    results = deduplicate(filtered)

    # Classify each listing
    search = config.get("search", {})
    recent_hours = search.get("highlight_recent_hours", 48)
    for apt in results:
        apt.build_full_address()
        classify_location(apt, config)
        classify_recency(apt, recent_hours)

    results.sort(key=sort_key)

    # Find new ones
    new_listings = find_new_listings(results, db)

    if new_listings:
        print(f"  [monitor] {len(new_listings)} NEW listing(s) found!")
        notify(config, new_listings)
        mark_seen(new_listings, db)
    else:
        print(f"  [monitor] No new listings (checked {len(results)} total)")

    return new_listings


def main():
    parser = argparse.ArgumentParser(description="Monitor for new apartment listings.")
    parser.add_argument("--config", "-c", default="config.yaml", help="Config file path")
    parser.add_argument("--once", action="store_true", help="Run once and exit (don't loop)")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    monitor_cfg = config.get("monitor", {})
    seen_path = monitor_cfg.get("seen_db", "output/seen_listings.json")
    interval = monitor_cfg.get("check_interval_minutes", 60)

    print(f"  ApartmentFinder Monitor")
    print(f"  Checking every {interval} minutes")
    print(f"  Seen DB: {seen_path}")
    print(f"  Notify:  {monitor_cfg.get('notify_method', 'console')}")

    db = load_seen_db(seen_path)

    if args.once:
        run_check(config, db)
        save_seen_db(seen_path, db)
        return 0

    # Continuous monitoring loop
    try:
        while True:
            run_check(config, db)
            save_seen_db(seen_path, db)
            print(f"  [monitor] Next check in {interval} minutes...")
            time.sleep(interval * 60)
    except KeyboardInterrupt:
        print("\n  [monitor] Stopped.")
        save_seen_db(seen_path, db)

    return 0


if __name__ == "__main__":
    sys.exit(main())
