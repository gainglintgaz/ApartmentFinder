"""Scraper for Apartments.com listings."""

import json
import re
from typing import List

from bs4 import BeautifulSoup

from models import Apartment
from scrapers.base import BaseScraper


class ApartmentsComScraper(BaseScraper):
    """Scrape apartment listings from Apartments.com."""

    SOURCE_NAME = "apartments.com"
    BASE_URL = "https://www.apartments.com"

    def _build_url(self, page: int = 1, city: str = None) -> str:
        """Build the search URL for Apartments.com."""
        search_city = city or self.city
        city_slug = search_city.lower().replace(" ", "-")
        state_slug = self.state.lower()
        path = f"/{city_slug}-{state_slug}"

        # Add bedroom filter
        br_nums = self._bedroom_params()
        if br_nums:
            br_parts = []
            for b in sorted(br_nums):
                if b == 0:
                    br_parts.append("studios")
                else:
                    br_parts.append(f"{b}-bedrooms")
            path += "/" + "-".join(br_parts)

        # Add rent filter
        path += f"/{self.min_rent}-to-{self.max_rent}"

        if page > 1:
            path += f"/{page}"

        return self.BASE_URL + path + "/"

    def _parse_listing(self, card) -> Apartment:
        """Parse a single listing card into an Apartment object."""
        apt = Apartment(source=self.SOURCE_NAME)

        # Title — try multiple selector patterns
        title_el = card.select_one(
            ".property-title, [data-testid='property-title'], .js-placardTitle, "
            "span.js-placardTitle, .listing-title, a .title, h2, h3"
        )
        if title_el:
            apt.title = title_el.get_text(strip=True)

        # URL — try multiple link patterns
        link = card.select_one(
            "a.property-link, a[data-testid='property-link'], "
            "a[href*='/apartments/'], a[href*='.apartments.com/'], a[href]"
        )
        if link and link.get("href"):
            href = link["href"]
            if href.startswith("/"):
                href = self.BASE_URL + href
            apt.url = href
            if not apt.title:
                apt.title = link.get_text(strip=True)

        # Price — multiple selectors plus regex fallback on card text
        price_el = card.select_one(
            ".property-pricing, [data-testid='property-pricing'], .price-range, "
            ".rent-range, [class*='price'], [class*='rent'], .pricing"
        )
        if price_el:
            price_text = price_el.get_text(strip=True)
            prices = re.findall(r'\$[\d,]+', price_text)
            if prices:
                nums = [int(p.replace("$", "").replace(",", "")) for p in prices]
                apt.price = min(nums)

        # Bedrooms — multiple selectors plus regex fallback
        beds_el = card.select_one(
            ".property-beds, [data-testid='property-beds'], .bed-range, "
            "[class*='bed'], .beds"
        )
        if beds_el:
            beds_text = beds_el.get_text(strip=True).lower()
            if "studio" in beds_text:
                apt.bedrooms = "Studio"
            else:
                match = re.search(r'(\d+)\s*(?:bed|br|bd)', beds_text)
                if match:
                    apt.bedrooms = match.group(1)

        # Bathrooms
        baths_el = card.select_one(
            ".property-baths, [data-testid='property-baths'], .bath-range, "
            "[class*='bath']"
        )
        if baths_el:
            match = re.search(r'(\d+(?:\.\d+)?)', baths_el.get_text(strip=True))
            if match:
                try:
                    apt.bathrooms = float(match.group(1))
                except ValueError:
                    pass

        # Square footage
        sqft_el = card.select_one(".property-sqft, [data-testid='property-sqft']")
        if sqft_el:
            sqft_text = sqft_el.get_text(strip=True)
            match = re.search(r'([\d,]+)\s*(?:sq\s*ft|sqft)', sqft_text, re.IGNORECASE)
            if match:
                apt.sqft = int(match.group(1).replace(",", ""))

        # Address / location
        addr_el = card.select_one(
            ".property-address, [data-testid='property-address'], "
            "[class*='address'], .listing-address"
        )
        if addr_el:
            addr_text = addr_el.get_text(strip=True)
            apt.address = addr_text
            parts = addr_text.rsplit(",", 2)
            if len(parts) >= 2:
                apt.city = parts[-2].strip() if len(parts) >= 3 else self.city
                state_zip = parts[-1].strip().split()
                if state_zip:
                    apt.state = state_zip[0]
                if len(state_zip) > 1:
                    apt.zip_code = state_zip[1]

        if not apt.city:
            apt.city = self.city
        if not apt.state:
            apt.state = self.state

        # Phone number
        phone_el = card.select_one(
            ".property-phone, [data-testid='property-phone'], "
            "a[href^='tel:'], [class*='phone']"
        )
        if phone_el:
            if phone_el.get("href", "").startswith("tel:"):
                apt.phone = phone_el["href"].replace("tel:", "").strip()
            else:
                apt.phone = self._extract_phone(phone_el.get_text())
        if not apt.phone:
            apt.phone = self._extract_phone(card.get_text())

        # Use regex fallback for any fields still missing
        self._enrich_from_text(apt, card.get_text())

        return apt

    def _extract_from_jsonld(self, soup: BeautifulSoup) -> List[Apartment]:
        """Extract listings from JSON-LD structured data."""
        listings = []
        for item in self._extract_jsonld(soup):
            if "@graph" in item:
                for node in item["@graph"]:
                    if isinstance(node, dict):
                        apt = self._try_jsonld_listing(node)
                        if apt:
                            listings.append(apt)
            else:
                apt = self._try_jsonld_listing(item)
                if apt:
                    listings.append(apt)
        return listings

    def _try_jsonld_listing(self, item: dict) -> Apartment:
        """Attempt to create an Apartment from a JSON-LD item."""
        ld_type = item.get("@type", "")
        if isinstance(ld_type, list):
            ld_type = " ".join(ld_type)
        housing_types = ("apartment", "residence", "place", "lodging",
                         "product", "realestatelisting", "singlefamilyresidence")
        has_listing_data = item.get("address") or item.get("name")
        if not any(t in ld_type.lower() for t in housing_types) and not has_listing_data:
            return None
        apt = self._apt_from_jsonld(item)
        if apt.title or apt.url:
            return apt
        return None

    def _extract_from_scripts(self, soup: BeautifulSoup) -> List[Apartment]:
        """Extract listing data from embedded JavaScript objects."""
        listings = []

        # Also try mining JSON from all script tags using regex
        for script in soup.select("script"):
            text = script.string or ""
            if not text or len(text) < 100:
                continue
            # Look for listing-like JSON arrays/objects
            for match in re.finditer(r'"placards?"?\s*:\s*(\[.+?\])', text, re.DOTALL):
                try:
                    items = json.loads(match.group(1))
                    for item in items:
                        if isinstance(item, dict):
                            apt = self._parse_script_listing(item)
                            if apt and (apt.title or apt.url):
                                listings.append(apt)
                except (json.JSONDecodeError, TypeError):
                    continue

        for data in self._extract_script_json(soup):
            found = self._find_listing_objects(data)
            for item in found:
                apt = self._parse_script_listing(item)
                if apt and (apt.title or apt.url):
                    listings.append(apt)
        return listings

    def _find_listing_objects(self, data, depth=0) -> list:
        """Recursively find listing-like objects in JSON data."""
        if depth > 10:
            return []
        results = []
        if isinstance(data, dict):
            if any(k in data for k in ("listingName", "propertyName", "name", "title")):
                if any(k in data for k in ("rent", "price", "address", "location")):
                    results.append(data)
            for key in ("listings", "properties", "searchResults", "results",
                        "placards", "listResults"):
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        results.extend(val)
                    elif isinstance(val, dict):
                        results.extend(self._find_listing_objects(val, depth + 1))
            if not results:
                for val in data.values():
                    if isinstance(val, (dict, list)):
                        results.extend(self._find_listing_objects(val, depth + 1))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and any(
                    k in item for k in ("rent", "price", "propertyName",
                                        "listingName", "name")
                ):
                    results.append(item)
                elif isinstance(item, (dict, list)):
                    results.extend(self._find_listing_objects(item, depth + 1))
        return results

    def _parse_script_listing(self, item: dict) -> Apartment:
        """Parse a listing from embedded script data."""
        if not isinstance(item, dict):
            return None
        apt = Apartment(source=self.SOURCE_NAME)

        apt.title = (item.get("propertyName", "") or item.get("listingName", "")
                     or item.get("name", "") or item.get("title", ""))

        url = (item.get("listingUrl", "") or item.get("url", "")
               or item.get("detailUrl", "") or item.get("link", ""))
        if url and not url.startswith("http"):
            url = self.BASE_URL + url
        apt.url = url

        # Price
        rent = item.get("rent", {}) or item.get("pricing", {}) or {}
        if isinstance(rent, dict):
            apt.price = rent.get("min") or rent.get("low") or rent.get("max")
        if apt.price is None:
            price_val = item.get("price", "") or item.get("rentRange", "")
            if isinstance(price_val, (int, float)):
                apt.price = int(price_val)
            elif isinstance(price_val, str):
                nums = re.findall(r'[\d,]+', price_val.replace("$", ""))
                if nums:
                    try:
                        apt.price = int(nums[0].replace(",", ""))
                    except ValueError:
                        pass

        # Beds
        beds = item.get("bedrooms", None) or item.get("beds", None)
        if isinstance(beds, dict):
            min_beds = beds.get("min", 0) or beds.get("low", 0)
            apt.bedrooms = "Studio" if min_beds == 0 else str(int(min_beds))
        elif beds is not None:
            try:
                apt.bedrooms = "Studio" if int(beds) == 0 else str(int(beds))
            except (ValueError, TypeError):
                pass

        # Baths
        baths = item.get("bathrooms", None) or item.get("baths", None)
        if isinstance(baths, dict):
            apt.bathrooms = float(baths.get("min", 0) or baths.get("low", 0))
        elif baths is not None:
            try:
                apt.bathrooms = float(baths)
            except (ValueError, TypeError):
                pass

        # Address
        address = item.get("address", {}) or item.get("location", {})
        if isinstance(address, dict):
            apt.address = (address.get("streetAddress", "") or address.get("street", "")
                          or address.get("line1", ""))
            apt.city = (address.get("city", "") or address.get("addressLocality", "")
                       or self.city)
            apt.state = (address.get("state", "") or address.get("addressRegion", "")
                        or self.state)
            apt.zip_code = (address.get("zip", "") or address.get("postalCode", "")
                           or address.get("zipCode", ""))
        elif isinstance(address, str):
            apt.address = address

        if not apt.city:
            apt.city = self.city
        if not apt.state:
            apt.state = self.state

        # Phone
        phone = item.get("phone", "") or item.get("phoneNumber", "") or item.get("contactPhone", "")
        if isinstance(phone, dict):
            phone = phone.get("number", "")
        apt.phone = str(phone) if phone else ""

        return apt

    def _scrape_city(self, city: str) -> List[Apartment]:
        """Scrape listing pages for a single city."""
        listings = []

        for page in range(1, self.max_pages + 1):
            url = self._build_url(page, city=city)
            print(f"  [{self.SOURCE_NAME}] {city} page {page}: {url}")

            resp = self._get(url)
            soup = BeautifulSoup(resp.text, "lxml")

            page_listings = []

            # Strategy 1: JSON-LD structured data (most reliable)
            jsonld_listings = self._extract_from_jsonld(soup)
            if jsonld_listings:
                page_listings.extend(jsonld_listings)

            # Strategy 2: Embedded script JSON data
            if not page_listings:
                script_listings = self._extract_from_scripts(soup)
                if script_listings:
                    page_listings.extend(script_listings)

            # Strategy 3: HTML card parsing (fallback)
            if not page_listings:
                cards = soup.select(
                    "li.mortar-wrapper, "
                    "article[data-testid='property-card'], "
                    "div.placard, "
                    "section.placard-content"
                )

                if not cards:
                    cards = soup.select(
                        "[data-listingid], [data-url], "
                        "[data-listing-id], [data-property-id], "
                        "article[class*='placard'], div[class*='placard']"
                    )

                if not cards:
                    print(f"  [{self.SOURCE_NAME}] No more listings in {city} on page {page}")
                    break

                for card in cards:
                    apt = self._parse_listing(card)
                    if apt.url or apt.title:
                        page_listings.append(apt)

            listings.extend(page_listings)

            # Check for next page
            next_link = soup.select_one(
                "a.next, [data-testid='next-page'], a[title='Next'], "
                "a[aria-label='Next'], .pagination .next"
            )
            if not next_link:
                break

        return listings

    def scrape(self) -> List[Apartment]:
        """Scrape listings from Apartments.com across multiple cities."""
        all_listings = self._scrape_city(self.city)

        # Also search preferred area cities (Midland, Concord, etc.)
        for city in self.extra_cities:
            all_listings.extend(self._scrape_city(city))

        return all_listings
