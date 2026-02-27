"""Scraper for Apartments.com listings."""

import re
from typing import List
from urllib.parse import quote

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

        # Title
        title_el = card.select_one(".property-title, [data-testid='property-title'], .js-placardTitle")
        if title_el:
            apt.title = title_el.get_text(strip=True)

        # URL
        link = card.select_one("a.property-link, a[data-testid='property-link'], a[href]")
        if link and link.get("href"):
            href = link["href"]
            if href.startswith("/"):
                href = self.BASE_URL + href
            apt.url = href

        # Price
        price_el = card.select_one(".property-pricing, [data-testid='property-pricing'], .price-range")
        if price_el:
            price_text = price_el.get_text(strip=True)
            prices = re.findall(r'\$[\d,]+', price_text)
            if prices:
                # Take the lowest price listed
                nums = [int(p.replace("$", "").replace(",", "")) for p in prices]
                apt.price = min(nums)

        # Bedrooms
        beds_el = card.select_one(".property-beds, [data-testid='property-beds'], .bed-range")
        if beds_el:
            beds_text = beds_el.get_text(strip=True).lower()
            if "studio" in beds_text:
                apt.bedrooms = "Studio"
            else:
                match = re.search(r'(\d+)\s*(?:bed|br|bd)', beds_text)
                if match:
                    apt.bedrooms = match.group(1)

        # Square footage
        sqft_el = card.select_one(".property-sqft, [data-testid='property-sqft']")
        if sqft_el:
            sqft_text = sqft_el.get_text(strip=True)
            match = re.search(r'([\d,]+)\s*(?:sq\s*ft|sqft)', sqft_text, re.IGNORECASE)
            if match:
                apt.sqft = int(match.group(1).replace(",", ""))

        # Address / location
        addr_el = card.select_one(".property-address, [data-testid='property-address']")
        if addr_el:
            addr_text = addr_el.get_text(strip=True)
            apt.address = addr_text
            # Try to extract city/state/zip
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
        phone_el = card.select_one(".property-phone, [data-testid='property-phone'], a[href^='tel:']")
        if phone_el:
            if phone_el.get("href", "").startswith("tel:"):
                apt.phone = phone_el["href"].replace("tel:", "").strip()
            else:
                apt.phone = self._extract_phone(phone_el.get_text())
        if not apt.phone:
            apt.phone = self._extract_phone(card.get_text())

        return apt

    def _scrape_city(self, city: str) -> List[Apartment]:
        """Scrape listing pages for a single city."""
        listings = []

        for page in range(1, self.max_pages + 1):
            url = self._build_url(page, city=city)
            print(f"  [{self.SOURCE_NAME}] {city} page {page}: {url}")

            resp = self._get(url)
            soup = BeautifulSoup(resp.text, "lxml")

            # Find listing cards
            cards = soup.select(
                "li.mortar-wrapper, "
                "article[data-testid='property-card'], "
                "div.placard, "
                "section.placard-content"
            )

            if not cards:
                # Try broader selectors
                cards = soup.select("[data-listingid], [data-url]")

            if not cards:
                print(f"  [{self.SOURCE_NAME}] No more listings in {city} on page {page}")
                break

            for card in cards:
                apt = self._parse_listing(card)
                if apt.url or apt.title:
                    listings.append(apt)

            # Check for next page
            next_link = soup.select_one("a.next, [data-testid='next-page'], a[title='Next']")
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
