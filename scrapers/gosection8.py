"""Scraper for GoSection8.com listings.

GoSection8.com is a major marketplace for Section 8 / Housing Choice Voucher
accepted rentals. Landlords list properties that accept government vouchers.
"""

import re
from typing import List

from bs4 import BeautifulSoup

from models import Apartment, TYPE_SECTION8, TYPE_SENIOR
from scrapers.base import BaseScraper


class GoSection8Scraper(BaseScraper):
    """Scrape Section 8 accepted listings from GoSection8.com."""

    SOURCE_NAME = "gosection8.com"
    BASE_URL = "https://www.gosection8.com"

    def _build_url(self, page: int = 1) -> str:
        """Build GoSection8 search URL."""
        city_slug = self.city.lower().replace(" ", "-")
        state_slug = self.state.upper()
        path = f"/Section-8-housing-in-{city_slug}-{state_slug}"

        params = []
        params.append(f"rent_max={self.max_rent}")

        br_nums = self._bedroom_params()
        if br_nums:
            params.append(f"bedrooms={min(br_nums)}-{max(br_nums)}")

        params.append("radius=30")

        if page > 1:
            params.append(f"page={page}")

        query = "&".join(params)
        return f"{self.BASE_URL}{path}?{query}"

    def _parse_listing(self, card) -> Apartment:
        """Parse a GoSection8 listing card."""
        apt = Apartment(source=self.SOURCE_NAME, housing_type=TYPE_SECTION8)

        text = card.get_text()
        text_lower = text.lower()

        # Title and URL
        link = card.select_one(
            "a[href*='section-8'], a[href*='listing'], a[href*='rental'], "
            "h2 a, h3 a, a.title, a[href*='housing']"
        )
        if link:
            apt.title = link.get_text(strip=True)
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = self.BASE_URL + href if href.startswith("/") else self.BASE_URL + "/" + href
            apt.url = href

        if not apt.title:
            title_el = card.select_one("h2, h3, h4, .listing-title, .property-name")
            if title_el:
                apt.title = title_el.get_text(strip=True)

        # Senior detection
        if any(kw in text_lower for kw in ("senior", "elderly", "62+", "55+")):
            apt.housing_type = TYPE_SENIOR

        # Price
        price_el = card.select_one(".price, .rent, [class*='price'], [class*='rent']")
        price_text = price_el.get_text() if price_el else text
        prices = re.findall(r'\$[\d,]+', price_text)
        if prices:
            nums = [int(p.replace("$", "").replace(",", "")) for p in prices]
            reasonable = [n for n in nums if 0 < n <= 2000]
            if reasonable:
                apt.price = min(reasonable)

        # Bedrooms
        br_match = re.search(r'(\d+)\s*(?:bed|br|bedroom|bd)', text_lower)
        if br_match:
            apt.bedrooms = br_match.group(1)
        elif "studio" in text_lower or "efficiency" in text_lower:
            apt.bedrooms = "Studio"

        # Bathrooms
        ba_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:bath|ba)', text_lower)
        if ba_match:
            apt.bathrooms = float(ba_match.group(1))

        # Square footage
        sqft_match = re.search(r'([\d,]+)\s*(?:sq\s*ft|sqft|sf)', text_lower)
        if sqft_match:
            apt.sqft = int(sqft_match.group(1).replace(",", ""))

        # Address
        addr_el = card.select_one(".address, address, [class*='address'], [class*='location']")
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

        # Date posted
        date_match = re.search(
            r'(?:posted|listed|available|updated)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            text_lower
        )
        if date_match:
            apt.date_posted = date_match.group(1)

        return apt

    def scrape(self) -> List[Apartment]:
        """Scrape GoSection8 listings."""
        all_listings = []

        for page in range(1, self.max_pages + 1):
            url = self._build_url(page)
            print(f"  [{self.SOURCE_NAME}] Page {page}: {url}")

            try:
                resp = self._get(url)
                soup = BeautifulSoup(resp.text, "lxml")

                page_listings = []

                # Strategy 1: JSON-LD structured data
                from models import TYPE_SECTION8
                for item in self._extract_jsonld(soup):
                    apt = self._apt_from_jsonld(item)
                    apt.housing_type = TYPE_SECTION8
                    if apt.title or apt.url:
                        page_listings.append(apt)

                # Strategy 2: HTML card parsing
                if not page_listings:
                    cards = soup.select(
                        ".listing, .search-result, .property-card, .rental-listing, "
                        "div[class*='listing'], div[class*='result'], "
                        "tr[class*='listing'], article, .card"
                    )

                    if not cards:
                        for container in soup.select("div, tr, li"):
                            t = container.get_text()
                            if re.search(r'\$\d+', t) and re.search(r'(?:bed|br|studio|section)', t, re.I):
                                if len(t.strip()) > 30:
                                    cards.append(container)

                    for card in cards:
                        apt = self._parse_listing(card)
                        if apt.title or apt.url:
                            page_listings.append(apt)

                if not page_listings:
                    print(f"  [{self.SOURCE_NAME}] No listings on page {page}")
                    break

                all_listings.extend(page_listings)

            except Exception as e:
                print(f"  [{self.SOURCE_NAME}] Error on page {page}: {e}")
                break

        return all_listings
