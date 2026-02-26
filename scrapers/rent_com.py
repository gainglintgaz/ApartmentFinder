"""Scraper for Rent.com apartment listings."""

import json
import re
from typing import List

from bs4 import BeautifulSoup

from models import Apartment
from scrapers.base import BaseScraper


class RentComScraper(BaseScraper):
    """Scrape apartment listings from Rent.com."""

    SOURCE_NAME = "rent.com"
    BASE_URL = "https://www.rent.com"

    def _build_url(self, page: int = 1) -> str:
        """Build Rent.com search URL."""
        city_slug = self.city.lower().replace(" ", "-")
        state_slug = self.state.lower()
        path = f"/north-carolina/{city_slug}/apartments_condos_townhouses"

        params = []
        params.append(f"price={self.min_rent}-{self.max_rent}")

        br_nums = self._bedroom_params()
        if br_nums:
            beds_str = "-".join(str(b) for b in sorted(br_nums))
            params.append(f"bedrooms={beds_str}")

        if page > 1:
            params.append(f"page={page}")

        query_str = "&".join(params)
        return f"{self.BASE_URL}{path}?{query_str}"

    def _extract_from_json(self, soup: BeautifulSoup) -> List[Apartment]:
        """Try to extract listings from embedded JSON data."""
        listings = []

        for script in soup.select("script[type='application/json'], script#__NEXT_DATA__"):
            try:
                data = json.loads(script.string or "")
                results = self._find_listings(data)
                for item in results:
                    apt = self._parse_json_listing(item)
                    if apt:
                        listings.append(apt)
            except (json.JSONDecodeError, TypeError):
                continue

        return listings

    def _find_listings(self, data, depth=0) -> list:
        """Recursively search JSON for listing data."""
        if depth > 10:
            return []

        results = []

        if isinstance(data, dict):
            for key in ("listings", "properties", "searchResults", "results"):
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        results.extend(val)
                    elif isinstance(val, dict):
                        results.extend(self._find_listings(val, depth + 1))

            if not results:
                for val in data.values():
                    if isinstance(val, (dict, list)):
                        results.extend(self._find_listings(val, depth + 1))

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and any(
                    k in item for k in ("rent", "price", "propertyName", "listingUrl", "name")
                ):
                    results.append(item)
                elif isinstance(item, (dict, list)):
                    results.extend(self._find_listings(item, depth + 1))

        return results

    def _parse_json_listing(self, item: dict) -> Apartment:
        """Parse a listing from Rent.com JSON data."""
        if not isinstance(item, dict):
            return None

        apt = Apartment(source=self.SOURCE_NAME)

        # Title / Name
        apt.title = item.get("propertyName", "") or item.get("name", "") or item.get("title", "")

        # URL
        url = item.get("listingUrl", "") or item.get("url", "") or item.get("detailUrl", "")
        if url and not url.startswith("http"):
            url = self.BASE_URL + url
        apt.url = url

        # Price
        rent = item.get("rent", {}) or {}
        if isinstance(rent, dict):
            apt.price = rent.get("min", None) or rent.get("max", None)
        else:
            price_val = item.get("price", "") or item.get("rent", "")
            if isinstance(price_val, (int, float)):
                apt.price = int(price_val)
            elif isinstance(price_val, str):
                match = re.search(r'[\d,]+', price_val)
                if match:
                    apt.price = int(match.group().replace(",", ""))

        # Beds
        beds = item.get("bedrooms", None) or item.get("beds", None)
        if isinstance(beds, dict):
            min_beds = beds.get("min", 0)
            apt.bedrooms = "Studio" if min_beds == 0 else str(min_beds)
        elif beds is not None:
            apt.bedrooms = "Studio" if beds == 0 else str(int(beds))

        # Baths
        baths = item.get("bathrooms", None) or item.get("baths", None)
        if isinstance(baths, dict):
            apt.bathrooms = float(baths.get("min", 0))
        elif baths is not None:
            apt.bathrooms = float(baths)

        # Sqft
        sqft = item.get("squareFeet", None) or item.get("sqft", None) or item.get("area", None)
        if isinstance(sqft, dict):
            apt.sqft = sqft.get("min", None)
        elif sqft is not None:
            try:
                apt.sqft = int(sqft)
            except (ValueError, TypeError):
                pass

        # Address
        address = item.get("address", {})
        if isinstance(address, dict):
            apt.address = address.get("streetAddress", "") or address.get("line1", "")
            apt.city = address.get("city", self.city)
            apt.state = address.get("state", self.state)
            apt.zip_code = address.get("zip", "") or address.get("postalCode", "")
        elif isinstance(address, str):
            apt.address = address

        if not apt.city:
            apt.city = self.city
        if not apt.state:
            apt.state = self.state

        # Pet policy
        apt.pet_policy = item.get("petPolicy", "") or item.get("pets", "")
        if isinstance(apt.pet_policy, dict):
            apt.pet_policy = "Cats/Dogs" if apt.pet_policy.get("allowed") else "No Pets"

        # Phone
        apt.phone = item.get("phone", "") or item.get("phoneNumber", "")

        return apt

    def _parse_html_listing(self, card) -> Apartment:
        """Fallback: parse listing from HTML."""
        apt = Apartment(source=self.SOURCE_NAME)

        # Title and URL
        link = card.select_one("a[href*='/apartments/'], a._3ouMn, a.property-link")
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                href = self.BASE_URL + href
            apt.url = href
            apt.title = link.get_text(strip=True)

        # Price
        price_el = card.select_one("[data-tid='price'], .price, ._1KxV6, .rent-price")
        if price_el:
            price_text = price_el.get_text(strip=True)
            match = re.search(r'\$[\d,]+', price_text)
            if match:
                apt.price = int(match.group().replace("$", "").replace(",", ""))

        # Beds/Bath/Sqft
        details = card.select("[data-tid='bed'], [data-tid='bath'], [data-tid='sqft'], .detail-item, ._1bZMX span")
        for detail in details:
            text = detail.get_text(strip=True).lower()
            if "bed" in text or "br" in text:
                match = re.search(r'(\d+)', text)
                if match:
                    apt.bedrooms = match.group(1)
                elif "studio" in text:
                    apt.bedrooms = "Studio"
            elif "bath" in text or "ba" in text:
                match = re.search(r'[\d.]+', text)
                if match:
                    apt.bathrooms = float(match.group())
            elif "sq" in text or "ft" in text:
                match = re.search(r'[\d,]+', text)
                if match:
                    apt.sqft = int(match.group().replace(",", ""))

        # Address
        addr_el = card.select_one("[data-tid='address'], .property-address, ._1dhrl")
        if addr_el:
            apt.address = addr_el.get_text(strip=True)

        apt.city = self.city
        apt.state = self.state

        return apt

    def scrape(self) -> List[Apartment]:
        """Scrape Rent.com listings."""
        all_listings = []

        for page in range(1, self.max_pages + 1):
            url = self._build_url(page)
            print(f"  [{self.SOURCE_NAME}] Page {page}: {url}")

            resp = self._get(url)
            soup = BeautifulSoup(resp.text, "lxml")

            # Try JSON extraction first
            json_listings = self._extract_from_json(soup)
            if json_listings:
                all_listings.extend(json_listings)
            else:
                # HTML fallback
                cards = soup.select(
                    "[data-tid='property-card'], "
                    "div._1y05u, "
                    "div.listing-card, "
                    "article.property-card"
                )
                for card in cards:
                    apt = self._parse_html_listing(card)
                    if apt.url or apt.title:
                        all_listings.append(apt)

            if not json_listings and not soup.select("[data-tid='property-card'], div.listing-card"):
                break

        return all_listings
