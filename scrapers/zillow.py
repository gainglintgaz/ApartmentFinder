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

    def _build_url(self, page: int = 1) -> str:
        """Build the Zillow rental search URL."""
        city_slug = self.city.lower().replace(" ", "-")
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

        return listings

    def _find_search_results(self, data, depth=0) -> list:
        """Recursively search JSON for listing results."""
        if depth > 10:
            return []

        results = []

        if isinstance(data, dict):
            # Look for common Zillow result keys
            for key in ("listResults", "searchResults", "cat1", "results"):
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

        # Price
        price = item.get("price", "") or item.get("unformattedPrice", "")
        if isinstance(price, str):
            match = re.search(r'[\d,]+', price.replace("$", ""))
            if match:
                apt.price = int(match.group().replace(",", ""))
        elif isinstance(price, (int, float)):
            apt.price = int(price)

        # Address
        addr = item.get("address", "")
        if isinstance(addr, dict):
            apt.address = addr.get("streetAddress", "")
            apt.city = addr.get("city", self.city)
            apt.state = addr.get("state", self.state)
            apt.zip_code = addr.get("zipcode", "")
        elif isinstance(addr, str):
            apt.address = addr
            apt.city = self.city
            apt.state = self.state

        # Title
        apt.title = item.get("statusText", "") or item.get("title", "") or apt.address

        # Beds / Baths / Sqft
        beds = item.get("beds", None) or item.get("bedrooms", None)
        if beds is not None:
            apt.bedrooms = "Studio" if beds == 0 else str(int(beds))

        baths = item.get("baths", None) or item.get("bathrooms", None)
        if baths is not None:
            apt.bathrooms = float(baths)

        area = item.get("area", None) or item.get("livingArea", None)
        if area is not None:
            try:
                apt.sqft = int(area)
            except (ValueError, TypeError):
                pass

        return apt

    def _parse_html_listing(self, card) -> Apartment:
        """Fallback: parse listing from HTML card element."""
        apt = Apartment(source=self.SOURCE_NAME)

        # Link and URL
        link = card.select_one("a[href*='/homedetails/'], a[href*='/b/'], a[data-test='property-card-link']")
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                href = self.BASE_URL + href
            apt.url = href
            apt.title = link.get_text(strip=True) or ""

        # Price
        price_el = card.select_one("[data-test='property-card-price'], .list-card-price, span.PropertyCardWrapper__StyledPriceLine")
        if price_el:
            price_text = price_el.get_text(strip=True)
            match = re.search(r'\$[\d,]+', price_text)
            if match:
                apt.price = int(match.group().replace("$", "").replace(",", ""))

        # Address
        addr_el = card.select_one("address, [data-test='property-card-addr']")
        if addr_el:
            apt.address = addr_el.get_text(strip=True)

        # Beds/Baths/Sqft
        details = card.select("li, .list-card-details span, [data-test='property-card-details'] span")
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

        return apt

    def scrape(self) -> List[Apartment]:
        """Scrape rental listings from Zillow."""
        all_listings = []

        for page in range(1, self.max_pages + 1):
            url = self._build_url(page)
            print(f"  [{self.SOURCE_NAME}] Page {page}: {url}")

            headers = self._get_headers()
            headers["Referer"] = "https://www.zillow.com/"
            resp = self._get(url, headers=headers)
            soup = BeautifulSoup(resp.text, "lxml")

            # Try JSON extraction first (most reliable)
            json_listings = self._extract_from_script_data(soup)
            if json_listings:
                all_listings.extend(json_listings)
            else:
                # Fallback to HTML parsing
                cards = soup.select(
                    "article[data-test='property-card'], "
                    "div.list-card, "
                    "li.ListItem, "
                    "[data-testid='search-result-list-item']"
                )
                for card in cards:
                    apt = self._parse_html_listing(card)
                    if apt.url or apt.title:
                        all_listings.append(apt)

            if not json_listings and not soup.select("article, div.list-card, li.ListItem"):
                break

        return all_listings
