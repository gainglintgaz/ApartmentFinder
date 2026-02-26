"""Scraper for Craigslist apartment listings."""

import re
from typing import List

from bs4 import BeautifulSoup

from models import Apartment
from scrapers.base import BaseScraper


# Craigslist subdomains for NC cities within ~30 miles of Charlotte
CHARLOTTE_CL_REGIONS = [
    "charlotte",
]


class CraigslistScraper(BaseScraper):
    """Scrape apartment listings from Craigslist."""

    SOURCE_NAME = "craigslist"
    BASE_URL = "https://{region}.craigslist.org"

    def _build_url(self, region: str, page_offset: int = 0) -> str:
        """Build a Craigslist search URL."""
        base = self.BASE_URL.format(region=region)
        path = "/search/apa"

        params = []

        # Price range
        params.append(f"min_price={self.min_rent}")
        params.append(f"max_price={self.max_rent}")

        # Bedrooms
        br_nums = self._bedroom_params()
        if br_nums:
            min_br = min(br_nums)
            max_br = max(br_nums)
            params.append(f"min_bedrooms={min_br}")
            params.append(f"max_bedrooms={max_br}")

        # Pagination
        if page_offset > 0:
            params.append(f"s={page_offset}")

        query_str = "&".join(params)
        return f"{base}{path}?{query_str}"

    def _parse_listing(self, item, region: str) -> Apartment:
        """Parse a single Craigslist listing into an Apartment."""
        apt = Apartment(source=self.SOURCE_NAME)
        base = self.BASE_URL.format(region=region)

        # Title and URL
        title_link = item.select_one("a.titlestring, a.posting-title, .result-title a, a.cl-app-anchor")
        if title_link:
            apt.title = title_link.get_text(strip=True)
            href = title_link.get("href", "")
            if href.startswith("/"):
                href = base + href
            apt.url = href

        # Price
        price_el = item.select_one(".priceinfo, .result-price, .price")
        if price_el:
            price_text = price_el.get_text(strip=True)
            match = re.search(r'\$[\d,]+', price_text)
            if match:
                apt.price = int(match.group().replace("$", "").replace(",", ""))

        # Housing info (beds/sqft) — often in a tag like "2br - 900ft²"
        meta_el = item.select_one(".meta .housing, .result-meta .housing, .post-bedrooms")
        if meta_el:
            meta_text = meta_el.get_text(strip=True)
        else:
            # Try the entire meta area
            meta_all = item.select_one(".meta, .result-meta")
            meta_text = meta_all.get_text(strip=True) if meta_all else ""

        # Bedrooms
        br_match = re.search(r'(\d+)\s*br', meta_text, re.IGNORECASE)
        if br_match:
            apt.bedrooms = br_match.group(1)
        elif "studio" in meta_text.lower():
            apt.bedrooms = "Studio"

        # Square footage
        sqft_match = re.search(r'([\d,]+)\s*ft', meta_text, re.IGNORECASE)
        if sqft_match:
            apt.sqft = int(sqft_match.group(1).replace(",", ""))

        # Location / neighborhood
        hood_el = item.select_one(".result-hood, .nearby, .supertitle")
        if hood_el:
            hood_text = hood_el.get_text(strip=True).strip("() ")
            apt.neighborhood = hood_text
            apt.address = hood_text

        # Date posted
        date_el = item.select_one("time, .date, [datetime]")
        if date_el:
            apt.date_posted = date_el.get("datetime", "") or date_el.get_text(strip=True)

        apt.city = self.city
        apt.state = self.state

        return apt

    def scrape(self) -> List[Apartment]:
        """Scrape Craigslist listings for Charlotte area."""
        all_listings = []

        for region in CHARLOTTE_CL_REGIONS:
            for page_num in range(self.max_pages):
                offset = page_num * 120
                url = self._build_url(region, offset)
                print(f"  [{self.SOURCE_NAME}] {region} offset={offset}: {url}")

                resp = self._get(url)
                soup = BeautifulSoup(resp.text, "lxml")

                # Find listing rows
                items = soup.select(
                    "li.cl-static-search-result, "
                    "li.result-row, "
                    ".cl-search-result, "
                    "div.result-node"
                )

                if not items:
                    # Try gallery view items
                    items = soup.select("[data-pid], .gallery-card")

                if not items:
                    print(f"  [{self.SOURCE_NAME}] No listings found at offset {offset}")
                    break

                for item in items:
                    apt = self._parse_listing(item, region)
                    if apt.url or apt.title:
                        all_listings.append(apt)

                # Check if there are more results
                next_btn = soup.select_one("a.next, .cl-next-page, button.bd-button[title='next']")
                total_el = soup.select_one(".totalcount, .cl-page-number")
                if total_el:
                    total_text = total_el.get_text(strip=True)
                    total_match = re.search(r'of\s+([\d,]+)', total_text)
                    if total_match:
                        total = int(total_match.group(1).replace(",", ""))
                        if offset + 120 >= total:
                            break
                elif not next_btn:
                    break

        return all_listings
