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

    def _build_url(self, page: int = 1, city: str = None) -> str:
        """Build Rent.com search URL."""
        search_city = city or self.city
        city_slug = search_city.lower().replace(" ", "-")
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

    def _extract_from_jsonld(self, soup: BeautifulSoup) -> List[Apartment]:
        """Extract listings from JSON-LD structured data."""
        listings = []
        for item in self._extract_jsonld(soup):
            if "@graph" in item:
                for node in item["@graph"]:
                    if isinstance(node, dict) and node.get("address"):
                        apt = self._apt_from_jsonld(node)
                        if apt.title or apt.url:
                            listings.append(apt)
            elif item.get("address") or item.get("name"):
                apt = self._apt_from_jsonld(item)
                if apt.title or apt.url:
                    listings.append(apt)
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
        link = card.select_one(
            "a[href*='/apartments/'], a._3ouMn, a.property-link, "
            "a[href*='/rent/'], a[data-testid='property-link'], a[href]"
        )
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                href = self.BASE_URL + href
            apt.url = href
            apt.title = link.get_text(strip=True)

        # Price
        price_el = card.select_one(
            "[data-tid='price'], .price, ._1KxV6, .rent-price, "
            "[class*='price'], [class*='rent']"
        )
        if price_el:
            price_text = price_el.get_text(strip=True)
            match = re.search(r'\$[\d,]+', price_text)
            if match:
                apt.price = int(match.group().replace("$", "").replace(",", ""))

        # Beds/Bath/Sqft
        details = card.select(
            "[data-tid='bed'], [data-tid='bath'], [data-tid='sqft'], "
            ".detail-item, ._1bZMX span, [class*='bed'], [class*='bath']"
        )
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
        addr_el = card.select_one(
            "[data-tid='address'], .property-address, ._1dhrl, "
            "[class*='address']"
        )
        if addr_el:
            apt.address = addr_el.get_text(strip=True)

        apt.city = self.city
        apt.state = self.state

        # Phone
        phone_el = card.select_one("a[href^='tel:'], [data-tid='phone'], .phone")
        if phone_el:
            if phone_el.get("href", "").startswith("tel:"):
                apt.phone = phone_el["href"].replace("tel:", "").strip()
            else:
                apt.phone = self._extract_phone(phone_el.get_text())
        if not apt.phone:
            apt.phone = self._extract_phone(card.get_text())

        # Regex fallback for missing fields
        self._enrich_from_text(apt, card.get_text())

        return apt

    @staticmethod
    def _data_quality(listings: list) -> tuple:
        """Score a list of listings by data completeness (priced count, total)."""
        if not listings:
            return (0, 0)
        priced = sum(1 for a in listings if a.price is not None)
        bedded = sum(1 for a in listings if a.bedrooms)
        return (priced, bedded, len(listings))

    def _scrape_city(self, city: str) -> List[Apartment]:
        """Scrape Rent.com listings for a single city."""
        listings = []

        for page in range(1, self.max_pages + 1):
            url = self._build_url(page, city=city)
            print(f"  [{self.SOURCE_NAME}] {city} page {page}: {url}")

            resp = self._get(url)
            soup = BeautifulSoup(resp.text, "lxml")

            # Run ALL strategies and pick the one with the richest data
            candidates = {}

            # Strategy 1: JSON from script tags (richest data)
            json_listings = self._extract_from_json(soup)
            if json_listings:
                candidates['json'] = json_listings

            # Strategy 2: JSON-LD structured data
            jsonld_listings = self._extract_from_jsonld(soup)
            if jsonld_listings:
                candidates['jsonld'] = jsonld_listings

            # Strategy 3: HTML fallback
            cards = soup.select(
                "[data-tid='property-card'], "
                "div._1y05u, "
                "div.listing-card, "
                "article.property-card, "
                "[data-testid='property-card'], "
                "div[class*='listing'], div[class*='property']"
            )
            html_listings = []
            for card in cards:
                apt = self._parse_html_listing(card)
                if apt.url or apt.title:
                    html_listings.append(apt)
            if html_listings:
                candidates['html'] = html_listings

            # Pick the strategy with the best data quality
            if candidates:
                best_key = max(candidates, key=lambda k: self._data_quality(candidates[k]))
                page_listings = candidates[best_key]
            else:
                page_listings = []

            listings.extend(page_listings)

            if not page_listings:
                break

        return listings

    def scrape(self) -> List[Apartment]:
        """Scrape Rent.com listings across multiple cities."""
        all_listings = self._scrape_city(self.city)

        # Also search preferred area cities
        for city in self.extra_cities:
            city_listings = self._scrape_city(city)
            self._tag_search_city(city_listings, city, self.city)
            all_listings.extend(city_listings)

        return all_listings
