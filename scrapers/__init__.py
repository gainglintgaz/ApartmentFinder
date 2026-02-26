"""Apartment listing scrapers."""

from scrapers.base import BaseScraper

# Priority 1: Government / Subsidized / Senior
from scrapers.socialserve import SocialServeScraper
from scrapers.hud import HUDScraper
from scrapers.affordablehousing import AffordableHousingScraper
from scrapers.gosection8 import GoSection8Scraper

# Priority 2: Market Rentals
from scrapers.apartments_com import ApartmentsComScraper
from scrapers.craigslist import CraigslistScraper
from scrapers.zillow import ZillowScraper
from scrapers.rent_com import RentComScraper

__all__ = [
    "BaseScraper",
    # Priority 1
    "SocialServeScraper",
    "HUDScraper",
    "AffordableHousingScraper",
    "GoSection8Scraper",
    # Priority 2
    "ApartmentsComScraper",
    "CraigslistScraper",
    "ZillowScraper",
    "RentComScraper",
]
