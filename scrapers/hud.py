"""Scraper for HUD (U.S. Department of Housing and Urban Development) resources.

HUD maintains a directory of affordable housing, public housing authorities,
and subsidized apartment listings. This scraper pulls from the HUD resource
locator for the Charlotte/Mecklenburg area.
"""

import re
from typing import List

from bs4 import BeautifulSoup

from models import Apartment, TYPE_SUBSIDIZED, TYPE_SENIOR
from scrapers.base import BaseScraper


class HUDScraper(BaseScraper):
    """Scrape affordable housing listings from HUD resources."""

    SOURCE_NAME = "hud.gov"
    BASE_URL = "https://resources.hud.gov"

    def _build_url(self) -> str:
        """Build the HUD resource locator URL for NC."""
        return (
            f"{self.BASE_URL}/resource"
            f"?city={self.city}&state={self.state}"
            f"&query=affordable+rental+housing"
            f"&radius=30"
        )

    def _build_affordable_url(self, page: int = 1) -> str:
        """Build URL for HUD affordable apartment search."""
        return (
            "https://www.hud.gov/apps/section8/step2.cfm"
            f"?state={self.state}"
            f"&city={self.city}"
            f"&page={page}"
        )

    def _parse_resource(self, item) -> Apartment:
        """Parse a HUD resource listing."""
        apt = Apartment(source=self.SOURCE_NAME, housing_type=TYPE_SUBSIDIZED)

        text = item.get_text()
        text_lower = text.lower()

        # Title
        title_el = item.select_one("h3, h4, .title, a, strong, b")
        if title_el:
            apt.title = title_el.get_text(strip=True)

        # URL
        link = item.select_one("a[href]")
        if link:
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = self.BASE_URL + "/" + href.lstrip("/")
            apt.url = href
            if not apt.title:
                apt.title = link.get_text(strip=True)

        # Senior detection
        if any(kw in text_lower for kw in ("senior", "elderly", "62+", "55+", "older adults")):
            apt.housing_type = TYPE_SENIOR

        # Address
        addr_match = re.search(
            r'(\d+\s+[A-Za-z\s.]+(?:St|Ave|Blvd|Dr|Rd|Ln|Way|Ct|Pl|Cir)[^,]*)',
            text, re.IGNORECASE
        )
        if addr_match:
            apt.address = addr_match.group(1).strip()

        # City/State/Zip
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

        # Price (if mentioned)
        price_match = re.findall(r'\$[\d,]+', text)
        if price_match:
            nums = [int(p.replace("$", "").replace(",", "")) for p in price_match]
            reasonable = [n for n in nums if 0 < n <= 2000]
            if reasonable:
                apt.price = min(reasonable)

        return apt

    def scrape(self) -> List[Apartment]:
        """Scrape HUD affordable housing resources."""
        all_listings = []

        # Scrape HUD resource locator
        url = self._build_url()
        print(f"  [{self.SOURCE_NAME}] Resource locator: {url}")
        try:
            resp = self._get(url)
            soup = BeautifulSoup(resp.text, "lxml")

            # Strategy 1: JSON-LD
            for item in self._extract_jsonld(soup):
                apt = self._apt_from_jsonld(item)
                apt.housing_type = TYPE_SUBSIDIZED
                combined = (item.get("name", "") + item.get("description", "")).lower()
                if any(kw in combined for kw in ("senior", "elderly", "62+", "55+")):
                    apt.housing_type = TYPE_SENIOR
                if apt.title or apt.url:
                    all_listings.append(apt)

            # Strategy 2: HTML parsing
            if not all_listings:
                items = soup.select(
                    ".resource-result, .listing, .result-item, "
                    "div[class*='result'], tr, li.resource, "
                    "article, .card, div[class*='listing']"
                )

                for item in items:
                    text = item.get_text().lower()
                    if any(kw in text for kw in ("housing", "apartment", "rental", "senior", "subsidiz")):
                        apt = self._parse_resource(item)
                        if apt.title or apt.url:
                            all_listings.append(apt)
        except Exception as e:
            print(f"  [{self.SOURCE_NAME}] Resource locator error: {e}")

        # Also try the Section 8 apartment search
        for page in range(1, min(self.max_pages, 3) + 1):
            url = self._build_affordable_url(page)
            print(f"  [{self.SOURCE_NAME}] Section 8 page {page}: {url}")
            try:
                resp = self._get(url)
                soup = BeautifulSoup(resp.text, "lxml")

                # Try JSON-LD first
                for item in self._extract_jsonld(soup):
                    apt = self._apt_from_jsonld(item)
                    apt.housing_type = TYPE_SUBSIDIZED
                    if apt.title or apt.url:
                        all_listings.append(apt)

                # HTML fallback
                items = soup.select(
                    "table tr, .property, .listing, div[class*='result'], "
                    "article, .card"
                )

                for item in items:
                    text = item.get_text().strip()
                    if len(text) > 20 and re.search(r'(?:NC|north carolina)', text, re.I):
                        apt = self._parse_resource(item)
                        apt.housing_type = TYPE_SUBSIDIZED
                        if apt.title or apt.url:
                            all_listings.append(apt)
            except Exception as e:
                print(f"  [{self.SOURCE_NAME}] Section 8 search error: {e}")
                break

        return all_listings
