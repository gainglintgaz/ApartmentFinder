"""Base scraper class with shared utilities."""

import random
import time
from abc import ABC, abstractmethod
from typing import List

import requests

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
