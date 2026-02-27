"""Base scraper class with shared utilities."""

import json
import re
import random
import time
from abc import ABC, abstractmethod
from typing import List

import requests
from bs4 import BeautifulSoup

from models import Apartment


class BaseScraper(ABC):
    """Base class all scrapers inherit from."""

    SOURCE_NAME = "unknown"

    def __init__(self, config: dict):
        self.config = config
        self.search = config.get("search", {})
        self.scraping = config.get("scraping", {})
        self.session = requests.Session()
        self._request_count = 0

    @property
    def city(self) -> str:
        return self.search.get("city", "")

    @property
    def extra_cities(self) -> list:
        """Additional cities to search beyond the primary city.

        Includes all preferred cities (Midland, Concord, etc.) and
        larger expanded cities (Gastonia, Huntersville, Kannapolis, etc.).
        Skips tiny suburbs that would be covered by the metro search.
        """
        locations = self.config.get("locations", {})
        preferred = locations.get("preferred", {}).get("areas", [])
        expanded = locations.get("expanded", {}).get("areas", [])
        # Don't duplicate the primary city
        primary = self.city.lower().strip()
        seen = {primary}
        cities = []
        # All preferred cities (highest priority — user's target area)
        for c in preferred:
            key = c.lower().strip()
            if key not in seen:
                seen.add(key)
                cities.append(c)
        # Only larger expanded cities (small suburbs are covered by metro search)
        for c in expanded:
            key = c.lower().strip()
            if key not in seen:
                seen.add(key)
                cities.append(c)
        return cities

    @property
    def state(self) -> str:
        return self.search.get("state", "")

    @property
    def min_rent(self) -> int:
        return self.search.get("min_rent", 0)

    @property
    def max_rent(self) -> int:
        return self.search.get("max_rent", 10000)

    @property
    def bedrooms(self) -> list:
        return self.search.get("bedrooms", [])

    @property
    def max_pages(self) -> int:
        return self.scraping.get("max_pages_per_source", 5)

    @property
    def timeout(self) -> int:
        return self.scraping.get("request_timeout", 30)

    @property
    def rate_limit(self) -> float:
        return self.scraping.get("rate_limit_seconds", 2)

    def _get_headers(self) -> dict:
        """Return request headers with a rotated User-Agent."""
        agents = self.scraping.get("user_agents", [])
        ua = random.choice(agents) if agents else (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    def _rate_limit_wait(self):
        """Respect rate limiting between requests."""
        if self._request_count > 0:
            jitter = random.uniform(0, self.rate_limit * 0.5)
            time.sleep(self.rate_limit + jitter)
        self._request_count += 1

    def _get(self, url: str, params: dict = None, headers: dict = None) -> requests.Response:
        """Make a rate-limited GET request."""
        self._rate_limit_wait()
        hdrs = headers or self._get_headers()
        resp = self.session.get(url, params=params, headers=hdrs, timeout=self.timeout)
        resp.raise_for_status()
        return resp

    def _bedroom_params(self) -> list:
        """Convert config bedrooms to numeric values for URL params."""
        mapping = {"studio": 0, "1": 1, "2": 2, "3": 3, "4": 4}
        result = []
        for b in self.bedrooms:
            val = mapping.get(str(b).lower().strip())
            if val is not None:
                result.append(val)
        return result

    @staticmethod
    def _extract_phone(text: str) -> str:
        """Extract a US phone number from text."""
        match = re.search(r'(\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4})', text)
        return match.group(1).strip() if match else ""

    # ------------------------------------------------------------------
    # Shared extraction helpers — JSON-LD, script data, regex fallbacks
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_jsonld(soup: BeautifulSoup) -> list:
        """Extract all JSON-LD objects from the page."""
        results = []
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, list):
                    results.extend(data)
                elif isinstance(data, dict):
                    results.append(data)
            except (json.JSONDecodeError, TypeError):
                continue
        return results

    @staticmethod
    def _extract_script_json(soup: BeautifulSoup) -> list:
        """Extract JSON objects from inline scripts (e.g. __NEXT_DATA__, window.__data)."""
        results = []
        for script in soup.select("script"):
            text = script.string or ""
            if not text or len(text) < 50:
                continue
            # Look for __NEXT_DATA__ (Next.js apps like Rent.com, Zillow)
            if script.get("id") == "__NEXT_DATA__":
                try:
                    results.append(json.loads(text))
                except (json.JSONDecodeError, TypeError):
                    pass
                continue
            # Look for JSON assigned to window variables
            for match in re.finditer(
                r'(?:window\.__\w+__|window\.\w+Data)\s*=\s*(\{.+?\});',
                text, re.DOTALL
            ):
                try:
                    results.append(json.loads(match.group(1)))
                except (json.JSONDecodeError, TypeError):
                    continue
            # Look for large JSON objects that might contain listings
            if 'application/json' in script.get("type", ""):
                try:
                    results.append(json.loads(text))
                except (json.JSONDecodeError, TypeError):
                    pass
        return results

    def _apt_from_jsonld(self, item: dict) -> Apartment:
        """Create an Apartment from a Schema.org JSON-LD object."""
        apt = Apartment(source=self.SOURCE_NAME)

        # Schema.org types: ApartmentComplex, Apartment, Residence, Product, Place
        apt.title = (item.get("name", "") or item.get("headline", "")
                     or item.get("description", "")[:60])

        apt.url = item.get("url", "") or item.get("@id", "")

        # Price: look for offers.price, priceRange, etc.
        offers = item.get("offers", {})
        if isinstance(offers, list) and offers:
            offers = offers[0]
        if isinstance(offers, dict):
            price = offers.get("price") or offers.get("lowPrice")
            if price:
                try:
                    apt.price = int(float(str(price).replace(",", "").replace("$", "")))
                except (ValueError, TypeError):
                    pass
            apt.url = apt.url or offers.get("url", "")

        # Direct price fields
        if apt.price is None:
            for key in ("price", "priceRange", "lowPrice"):
                val = item.get(key, "")
                if val:
                    nums = re.findall(r'[\d,]+', str(val).replace("$", ""))
                    if nums:
                        try:
                            apt.price = int(nums[0].replace(",", ""))
                            break
                        except ValueError:
                            pass

        # Address
        address = item.get("address", {})
        if isinstance(address, dict):
            apt.address = address.get("streetAddress", "")
            apt.city = address.get("addressLocality", "") or self.city
            apt.state = address.get("addressRegion", "") or self.state
            apt.zip_code = address.get("postalCode", "")
        elif isinstance(address, str):
            apt.address = address

        # Beds/Baths from floorSize, numberOfRooms, etc.
        beds = item.get("numberOfBedrooms") or item.get("numberOfRooms")
        if beds is not None:
            try:
                apt.bedrooms = "Studio" if int(beds) == 0 else str(int(beds))
            except (ValueError, TypeError):
                pass

        baths = item.get("numberOfBathroomsTotal") or item.get("numberOfFullBathrooms")
        if baths is not None:
            try:
                apt.bathrooms = float(baths)
            except (ValueError, TypeError):
                pass

        sqft = item.get("floorSize", {})
        if isinstance(sqft, dict):
            val = sqft.get("value")
            if val:
                try:
                    apt.sqft = int(float(str(val).replace(",", "")))
                except (ValueError, TypeError):
                    pass

        # Phone
        phone = item.get("telephone", "") or item.get("phone", "")
        if phone:
            apt.phone = str(phone)

        # Image/description for additional info
        desc = item.get("description", "")
        if desc and not apt.bedrooms:
            br_match = re.search(r'(\d+)\s*(?:bed|br|bedroom)', desc, re.I)
            if br_match:
                apt.bedrooms = br_match.group(1)
            elif "studio" in desc.lower():
                apt.bedrooms = "Studio"

        return apt

    def _enrich_from_text(self, apt: Apartment, text: str):
        """Fill in missing fields by regex-scanning raw text."""
        text_lower = text.lower()

        if apt.price is None:
            prices = re.findall(r'\$[\d,]+', text)
            if prices:
                nums = [int(p.replace("$", "").replace(",", "")) for p in prices]
                reasonable = [n for n in nums if 50 <= n <= 3000]
                if reasonable:
                    apt.price = min(reasonable)

        if not apt.bedrooms:
            br_match = re.search(r'(\d+)\s*(?:bed|br|bd|bedroom)', text_lower)
            if br_match:
                apt.bedrooms = br_match.group(1)
            elif "studio" in text_lower or "efficiency" in text_lower:
                apt.bedrooms = "Studio"

        if apt.bathrooms is None:
            ba_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:bath|ba\b)', text_lower)
            if ba_match:
                try:
                    apt.bathrooms = float(ba_match.group(1))
                except ValueError:
                    pass

        if not apt.phone:
            apt.phone = self._extract_phone(text)

        if not apt.date_posted:
            date_match = re.search(
                r'(?:posted|listed|available|updated)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
                text_lower
            )
            if date_match:
                apt.date_posted = date_match.group(1)

    @staticmethod
    def _tag_search_city(listings: List[Apartment], search_city: str, primary_city: str):
        """Tag listings with the searched city when they defaulted to the primary city.

        When searching for a smaller city like "Midland" on a site that returns
        results under the metro area "Charlotte", the listing city will be
        "Charlotte" even though the user searched for "Midland". This tags
        those listings with the searched city in the neighborhood field so
        classify_location() can use the fuzzy address matching to categorize
        them correctly.
        """
        if search_city.lower().strip() == primary_city.lower().strip():
            return
        for apt in listings:
            city_lower = apt.city.lower().strip()
            if city_lower == primary_city.lower().strip() or not apt.city:
                # This listing was from a search for search_city but got
                # labeled as primary_city — store search_city for classification
                if not apt.neighborhood:
                    apt.neighborhood = search_city
                elif search_city.lower() not in apt.neighborhood.lower():
                    apt.neighborhood += f", {search_city}"

    @abstractmethod
    def scrape(self) -> List[Apartment]:
        """Scrape listings and return normalized Apartment objects."""
        ...

    def run(self) -> List[Apartment]:
        """Execute the scraper with error handling."""
        print(f"  [{self.SOURCE_NAME}] Starting scrape...")
        try:
            listings = self.scrape()
            print(f"  [{self.SOURCE_NAME}] Found {len(listings)} listing(s)")
            if not listings:
                print(f"  [{self.SOURCE_NAME}] WARNING: 0 listings — site may have changed or is blocking requests")
            return listings
        except requests.exceptions.HTTPError as e:
            print(f"  [{self.SOURCE_NAME}] HTTP error: {e}")
        except requests.exceptions.ConnectionError:
            print(f"  [{self.SOURCE_NAME}] Connection error — site may be blocking requests")
        except requests.exceptions.Timeout:
            print(f"  [{self.SOURCE_NAME}] Request timed out")
        except Exception as e:
            print(f"  [{self.SOURCE_NAME}] Error: {e}")
        return []
