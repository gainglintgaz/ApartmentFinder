"""Scraper for Zillow rental listings."""

import json
import re
from typing import List

from bs4 import BeautifulSoup

from models import Apartment
from scrapers.base import BaseScraper


class ZillowScraper(BaseScraper):
    """Scrape rental listings from Zillow."""

    SOURCE_NAME = "zillow"
    BASE_URL = "https://www.zillow.com"

    def _build_url(self, page: int = 1, city: str = None) -> str:
        """Build the Zillow rental search URL."""
        search_city = city or self.city
        city_slug = search_city.lower().replace(" ", "-")
        state_slug = self.state.lower()
        path = f"/{city_slug}-{state_slug}/rentals"

        # Build filter string
        filters = []

        # Price
        filters.append(f"price%2F{self.min_rent}_{self.max_rent}")

        # Bedrooms
        br_nums = self._bedroom_params()
        if br_nums:
            beds_str = "%2C".join(str(b) for b in sorted(br_nums))
            filters.append(f"beds%2F{beds_str}")

        filter_path = ",".join(filters)
        if filter_path:
            path += f"/{filter_path}"

        if page > 1:
            path += f"/{page}_p"

        return self.BASE_URL + path + "/"

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

    def _extract_from_script_data(self, soup: BeautifulSoup) -> List[Apartment]:
        """Try to extract listing data from embedded JSON in the page."""
        listings = []

        # Zillow embeds search results as JSON in script tags
        for script in soup.select("script[type='application/json'], script#__NEXT_DATA__"):
            try:
                data = json.loads(script.string or "")
                results = self._find_search_results(data)
                for item in results:
                    apt = self._parse_json_listing(item)
                    if apt:
                        listings.append(apt)
            except (json.JSONDecodeError, TypeError):
                continue

        # Also try the generic script JSON extractor
        if not listings:
            for data in self._extract_script_json(soup):
                results = self._find_search_results(data)
                for item in results:
                    apt = self._parse_json_listing(item)
                    if apt:
                        listings.append(apt)

        return listings

    def _find_search_results(self, data, depth=0) -> list:
        """Recursively search JSON for listing results."""
        if depth > 10:
            return []

        results = []

        if isinstance(data, dict):
            # Look for common Zillow result keys
            for key in ("listResults", "searchResults", "cat1", "results",
                        "mapResults", "relaxedResults"):
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        results.extend(val)
                    elif isinstance(val, dict):
                        # cat1 -> searchResults -> listResults pattern
                        results.extend(self._find_search_results(val, depth + 1))

            if not results:
                for val in data.values():
                    if isinstance(val, (dict, list)):
                        results.extend(self._find_search_results(val, depth + 1))

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and any(
                    k in item for k in ("zpid", "price", "address", "detailUrl")
                ):
                    results.append(item)
                elif isinstance(item, (dict, list)):
                    results.extend(self._find_search_results(item, depth + 1))

        return results

    def _parse_json_listing(self, item: dict) -> Apartment:
        """Parse a listing from Zillow's JSON data."""
        if not isinstance(item, dict):
            return None

        apt = Apartment(source=self.SOURCE_NAME)

        # URL
        detail_url = item.get("detailUrl", "") or item.get("url", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = self.BASE_URL + detail_url
        apt.url = detail_url

        # Price — try multiple field patterns
        price = (item.get("price", "") or item.get("unformattedPrice", "")
                 or item.get("rentZestimate", ""))
        if isinstance(price, str):
            match = re.search(r'[\d,]+', price.replace("$", ""))
            if match:
                apt.price = int(match.group().replace(",", ""))
        elif isinstance(price, (int, float)):
            apt.price = int(price)

        # Also check nested price objects
        if apt.price is None:
            price_obj = item.get("hdpData", {}).get("homeInfo", {})
            if isinstance(price_obj, dict):
                for key in ("price", "rentZestimate", "zestimate"):
                    val = price_obj.get(key)
                    if isinstance(val, (int, float)) and val > 0:
                        apt.price = int(val)
                        break

        # Address
        addr = item.get("address", "")
        if isinstance(addr, dict):
            apt.address = addr.get("streetAddress", "")
            apt.city = addr.get("city", self.city)
            apt.state = addr.get("state", self.state)
            apt.zip_code = addr.get("zipcode", "") or addr.get("zip", "")
        elif isinstance(addr, str):
            apt.address = addr
            apt.city = self.city
            apt.state = self.state

        # Also try addressStreet, addressCity etc. (flat format)
        if not apt.address:
            apt.address = item.get("addressStreet", "") or item.get("streetAddress", "")
        if not apt.city or apt.city == self.city:
            apt.city = item.get("addressCity", "") or item.get("city", "") or self.city
        if not apt.state or apt.state == self.state:
            apt.state = item.get("addressState", "") or item.get("state", "") or self.state
        if not apt.zip_code:
            apt.zip_code = item.get("addressZipcode", "") or item.get("zipcode", "")

        # Title
        apt.title = (item.get("statusText", "") or item.get("title", "")
                     or item.get("buildingName", "") or apt.address)

        # Beds / Baths / Sqft
        beds = item.get("beds", None) or item.get("bedrooms", None)
        if beds is not None:
            try:
                apt.bedrooms = "Studio" if int(beds) == 0 else str(int(beds))
            except (ValueError, TypeError):
                pass

        baths = item.get("baths", None) or item.get("bathrooms", None)
        if baths is not None:
            try:
                apt.bathrooms = float(baths)
            except (ValueError, TypeError):
                pass

        area = item.get("area", None) or item.get("livingArea", None)
        if area is not None:
            try:
                apt.sqft = int(area)
            except (ValueError, TypeError):
                pass

        # Phone
        phone = (item.get("phone", "") or item.get("phoneNumber", "")
                 or item.get("contactPhone", ""))
        if isinstance(phone, dict):
            phone = phone.get("number", "")
        apt.phone = str(phone) if phone else ""

        # Date
        date_posted = item.get("datePosted", "") or item.get("listingDateTimeOnMarket", "")
        if date_posted:
            apt.date_posted = str(date_posted)

        return apt

    def _parse_html_listing(self, card) -> Apartment:
        """Fallback: parse listing from HTML card element."""
        apt = Apartment(source=self.SOURCE_NAME)

        # Link and URL
        link = card.select_one(
            "a[href*='/homedetails/'], a[href*='/b/'], "
            "a[data-test='property-card-link'], a[href*='/apartments/'], "
            "a[href*='zillow.com'], a[href]"
        )
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                href = self.BASE_URL + href
            apt.url = href
            apt.title = link.get_text(strip=True) or ""

        # Price
        price_el = card.select_one(
            "[data-test='property-card-price'], .list-card-price, "
            "span.PropertyCardWrapper__StyledPriceLine, "
            "[class*='price'], [class*='Price']"
        )
        if price_el:
            price_text = price_el.get_text(strip=True)
            match = re.search(r'\$[\d,]+', price_text)
            if match:
                apt.price = int(match.group().replace("$", "").replace(",", ""))

        # Address
        addr_el = card.select_one(
            "address, [data-test='property-card-addr'], "
            "[class*='address'], [class*='Address']"
        )
        if addr_el:
            apt.address = addr_el.get_text(strip=True)

        # Beds/Baths/Sqft
        details = card.select(
            "li, .list-card-details span, "
            "[data-test='property-card-details'] span, "
            "[class*='bed'], [class*='bath'], [class*='sqft']"
        )
        for detail in details:
            text = detail.get_text(strip=True).lower()
            if "bd" in text or "bed" in text or "br" in text:
                match = re.search(r'(\d+)', text)
                if match:
                    apt.bedrooms = match.group(1)
                elif "studio" in text:
                    apt.bedrooms = "Studio"
            elif "ba" in text or "bath" in text:
                match = re.search(r'[\d.]+', text)
                if match:
                    apt.bathrooms = float(match.group())
            elif "sqft" in text or "sq ft" in text:
                match = re.search(r'[\d,]+', text)
                if match:
                    apt.sqft = int(match.group().replace(",", ""))

        apt.city = self.city
        apt.state = self.state

        # Phone
        phone_el = card.select_one("a[href^='tel:'], [data-test='property-card-phone']")
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
        """Scrape rental listings for a single city."""
        listings = []

        for page in range(1, self.max_pages + 1):
            url = self._build_url(page, city=city)
            print(f"  [{self.SOURCE_NAME}] {city} page {page}: {url}")

            headers = self._get_headers()
            headers["Referer"] = "https://www.zillow.com/"
            resp = self._get(url, headers=headers)
            soup = BeautifulSoup(resp.text, "lxml")

            # Run ALL strategies and pick the one with the richest data
            candidates = {}

            # Strategy 1: JSON from scripts (richest data — prices, beds, sqft)
            json_listings = self._extract_from_script_data(soup)
            if json_listings:
                candidates['json'] = json_listings

            # Strategy 2: JSON-LD structured data
            jsonld_listings = self._extract_from_jsonld(soup)
            if jsonld_listings:
                candidates['jsonld'] = jsonld_listings

            # Strategy 3: HTML card parsing
            cards = soup.select(
                "article[data-test='property-card'], "
                "div.list-card, "
                "li.ListItem, "
                "[data-testid='search-result-list-item'], "
                "[class*='property-card'], [class*='ListItem']"
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
        """Scrape rental listings from Zillow across multiple cities."""
        all_listings = self._scrape_city(self.city)

        # Also search preferred area cities
        for city in self.extra_cities:
            city_listings = self._scrape_city(city)
            self._tag_search_city(city_listings, city, self.city)
            all_listings.extend(city_listings)

        return all_listings
