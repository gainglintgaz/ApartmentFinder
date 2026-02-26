"""Scraper for NC Housing Search (SocialServe.com).

SocialServe powers the official NC Housing Search at nchousingsearch.org.
It is the primary resource for affordable and subsidized housing in North Carolina.
Listings include Section 8, LIHTC, public housing, and other income-restricted units.
"""

import re
from typing import List

from bs4 import BeautifulSoup

from models import Apartment, TYPE_SUBSIDIZED, TYPE_SENIOR
from scrapers.base import BaseScraper


class SocialServeScraper(BaseScraper):
    """Scrape affordable housing from NC Housing Search (SocialServe)."""

    SOURCE_NAME = "nchousingsearch.org"
    BASE_URL = "https://www.nchousingsearch.org"

    def _build_url(self, page: int = 1) -> str:
        """Build the search URL for NC Housing Search."""
        # NC Housing Search search endpoint
        params = {
            "city": self.city,
            "state": self.state,
            "zip": "",
            "radius": "30",
            "bedroom_min": "0",
            "bedroom_max": "2",
            "rent_min": str(self.min_rent),
            "rent_max": str(self.max_rent),
            "senior": "true",    # Include senior-designated housing
            "page": str(page),
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.BASE_URL}/listing.html?{query}"

    def _parse_listing(self, card) -> Apartment:
        """Parse a single listing from NC Housing Search."""
        apt = Apartment(source=self.SOURCE_NAME, housing_type=TYPE_SUBSIDIZED)

        # Title / property name
        title_el = card.select_one(
            ".listing-title, .property-name, h2 a, h3 a, "
            ".listing-result-title, a[href*='listing']"
        )
        if title_el:
            apt.title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = self.BASE_URL + "/" + href.lstrip("/")
            if href:
                apt.url = href

        # If no URL from title, try any link
        if not apt.url:
            link = card.select_one("a[href*='listing'], a[href*='detail']")
            if link:
                href = link.get("href", "")
                if not href.startswith("http"):
                    href = self.BASE_URL + "/" + href.lstrip("/")
                apt.url = href

        # Check if senior housing
        text_lower = card.get_text().lower()
        if any(kw in text_lower for kw in ("senior", "elderly", "62+", "55+", "age 62", "age 55")):
            apt.housing_type = TYPE_SENIOR

        # Price / rent
        price_el = card.select_one(".rent, .price, .listing-rent")
        if price_el:
            price_text = price_el.get_text(strip=True)
        else:
            price_text = text_lower

        prices = re.findall(r'\$[\d,]+', price_text if price_el else card.get_text())
        if prices:
            nums = [int(p.replace("$", "").replace(",", "")) for p in prices]
            apt.price = min(nums)

        # Bedrooms
        br_match = re.search(r'(\d+)\s*(?:bed|br|bedroom)', text_lower)
        if br_match:
            apt.bedrooms = br_match.group(1)
        elif "studio" in text_lower or "efficiency" in text_lower:
            apt.bedrooms = "Studio"

        # Address
        addr_el = card.select_one(".address, .listing-address, .property-address")
        if addr_el:
            apt.address = addr_el.get_text(strip=True)

        # Try to pull city/state/zip from address text
        full_text = card.get_text()
        nc_match = re.search(
            r'([A-Za-z\s]+),\s*NC\s*(\d{5})',
            full_text
        )
        if nc_match:
            apt.city = nc_match.group(1).strip().split("\n")[-1].strip()
            apt.state = "NC"
            apt.zip_code = nc_match.group(2)
        else:
            apt.city = self.city
            apt.state = self.state

        # Phone number
        phone_match = re.search(r'(\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4})', card.get_text())
        if phone_match:
            apt.phone = phone_match.group(1).strip()

        # Amenities keywords
        amenity_keywords = []
        for kw in ("laundry", "parking", "pool", "elevator", "accessible",
                    "wheelchair", "a/c", "dishwasher", "pets", "no pets"):
            if kw in text_lower:
                amenity_keywords.append(kw.title())
        apt.amenities = ", ".join(amenity_keywords)

        return apt

    def scrape(self) -> List[Apartment]:
        """Scrape listings from NC Housing Search."""
        all_listings = []

        for page in range(1, self.max_pages + 1):
            url = self._build_url(page)
            print(f"  [{self.SOURCE_NAME}] Page {page}: {url}")

            resp = self._get(url)
            soup = BeautifulSoup(resp.text, "lxml")

            cards = soup.select(
                ".listing-result, .search-result, .property-listing, "
                "div.result, tr.listing-row, .listing-item, "
                "div[class*='listing'], div[class*='result']"
            )

            if not cards:
                # Broader fallback: any container with rent/price info
                for container in soup.select("div, tr, li, article"):
                    text = container.get_text()
                    if re.search(r'\$\d+', text) and re.search(r'(?:bed|br|studio)', text, re.I):
                        cards.append(container)

            if not cards:
                print(f"  [{self.SOURCE_NAME}] No listings found on page {page}")
                break

            for card in cards:
                apt = self._parse_listing(card)
                if apt.url or apt.title:
                    all_listings.append(apt)

        return all_listings
