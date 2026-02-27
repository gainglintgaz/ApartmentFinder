"""Scraper for AffordableHousing.com listings.

AffordableHousing.com aggregates subsidized, low-income, and income-restricted
apartment listings including LIHTC, Section 8, and public housing.
"""

import re
from typing import List

from bs4 import BeautifulSoup

from models import Apartment, TYPE_SUBSIDIZED, TYPE_SENIOR
from scrapers.base import BaseScraper


class AffordableHousingScraper(BaseScraper):
    """Scrape listings from AffordableHousing.com."""

    SOURCE_NAME = "affordablehousing.com"
    BASE_URL = "https://affordablehousingonline.com"

    def _build_url(self, page: int = 1, city: str = None) -> str:
        """Build search URL for AffordableHousing."""
        search_city = city or self.city
        city_slug = search_city.lower().replace(" ", "-")
        state_slug = self.state.lower()
        path = f"/housing-search/{state_slug}/{city_slug}"
        params = []
        if page > 1:
            params.append(f"page={page}")
        query = "?" + "&".join(params) if params else ""
        return self.BASE_URL + path + query

    def _build_senior_url(self, city: str = None) -> str:
        """Build URL specifically for senior housing."""
        search_city = city or self.city
        city_slug = search_city.lower().replace(" ", "-")
        state_slug = self.state.lower()
        return f"{self.BASE_URL}/housing-search/{state_slug}/{city_slug}/senior-housing"

    def _parse_listing(self, card, is_senior: bool = False) -> Apartment:
        """Parse a single listing card."""
        htype = TYPE_SENIOR if is_senior else TYPE_SUBSIDIZED
        apt = Apartment(source=self.SOURCE_NAME, housing_type=htype)

        text = card.get_text()
        text_lower = text.lower()

        # Title and URL
        link = card.select_one("a[href*='housing'], a[href*='property'], h2 a, h3 a, a.title")
        if link:
            apt.title = link.get_text(strip=True)
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = self.BASE_URL + "/" + href.lstrip("/")
            apt.url = href

        if not apt.title:
            title_el = card.select_one("h2, h3, h4, .property-name, .title")
            if title_el:
                apt.title = title_el.get_text(strip=True)

        # Senior detection
        if any(kw in text_lower for kw in ("senior", "elderly", "62+", "55+", "age 62")):
            apt.housing_type = TYPE_SENIOR

        # Price
        prices = re.findall(r'\$[\d,]+', text)
        if prices:
            nums = [int(p.replace("$", "").replace(",", "")) for p in prices]
            reasonable = [n for n in nums if 0 < n <= 2000]
            if reasonable:
                apt.price = min(reasonable)

        # Look for "income-based" or "30% of income" indicators
        if re.search(r'(?:income[- ]based|30%\s*of\s*income|based on income)', text_lower):
            if apt.price is None:
                apt.price = 0  # Will display as "Income-Based"

        # Bedrooms
        br_match = re.search(r'(\d+)\s*(?:bed|br|bedroom)', text_lower)
        if br_match:
            apt.bedrooms = br_match.group(1)
        elif "studio" in text_lower or "efficiency" in text_lower:
            apt.bedrooms = "Studio"

        # Address
        addr_el = card.select_one(".address, .property-address, address")
        if addr_el:
            apt.address = addr_el.get_text(strip=True)

        csz_match = re.search(r'([A-Za-z\s]+),\s*NC\s*(\d{5})', text)
        if csz_match:
            apt.city = csz_match.group(1).strip().split("\n")[-1].strip()
            apt.state = "NC"
            apt.zip_code = csz_match.group(2)
        else:
            apt.city = self.city
            apt.state = self.state

        # Phone
        phone_match = re.search(r'(\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4})', text)
        if phone_match:
            apt.phone = phone_match.group(1).strip()

        return apt

    def _scrape_city(self, city: str) -> List[Apartment]:
        """Scrape affordable housing listings for a single city."""
        listings = []

        # General affordable housing search
        for page in range(1, self.max_pages + 1):
            url = self._build_url(page, city=city)
            print(f"  [{self.SOURCE_NAME}] {city} page {page}: {url}")

            try:
                resp = self._get(url)
                soup = BeautifulSoup(resp.text, "lxml")

                cards = soup.select(
                    ".property-listing, .search-result, .listing-card, "
                    "div[class*='property'], div[class*='listing'], "
                    "article, .result-card"
                )

                if not cards:
                    for container in soup.select("div, section"):
                        t = container.get_text().lower()
                        if ("apartment" in t or "housing" in t) and re.search(r'(?:nc|north carolina)', t, re.I):
                            if len(container.get_text().strip()) > 30:
                                cards.append(container)

                if not cards:
                    break

                for card in cards:
                    apt = self._parse_listing(card)
                    if apt.title or apt.url:
                        listings.append(apt)
            except Exception as e:
                print(f"  [{self.SOURCE_NAME}] Error on {city} page {page}: {e}")
                break

        # Senior-specific search
        url = self._build_senior_url(city=city)
        print(f"  [{self.SOURCE_NAME}] {city} senior housing: {url}")
        try:
            resp = self._get(url)
            soup = BeautifulSoup(resp.text, "lxml")

            cards = soup.select(
                ".property-listing, .search-result, .listing-card, "
                "div[class*='property'], div[class*='listing'], article"
            )

            for card in cards:
                apt = self._parse_listing(card, is_senior=True)
                if apt.title or apt.url:
                    listings.append(apt)
        except Exception as e:
            print(f"  [{self.SOURCE_NAME}] {city} senior search error: {e}")

        return listings

    def scrape(self) -> List[Apartment]:
        """Scrape affordable housing listings across multiple cities."""
        all_listings = self._scrape_city(self.city)

        # Also search preferred area cities
        for city in self.extra_cities:
            all_listings.extend(self._scrape_city(city))

        return all_listings
