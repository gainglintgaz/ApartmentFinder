"""Data models for apartment listings."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Apartment:
    """Normalized apartment listing from any source."""

    # Core fields
    title: str = ""
    price: Optional[int] = None
    bedrooms: str = ""          # "Studio", "1", "2", "3", etc.
    bathrooms: Optional[float] = None
    sqft: Optional[int] = None

    # Location
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    neighborhood: str = ""

    # Listing metadata
    url: str = ""
    source: str = ""            # e.g. "apartments.com", "craigslist"
    date_posted: str = ""
    date_scraped: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

    # Extras
    amenities: str = ""         # Comma-separated list
    pet_policy: str = ""
    phone: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def price_display(self) -> str:
        if self.price is not None:
            return f"${self.price:,}"
        return "N/A"

    def matches_filters(self, min_rent: int, max_rent: int,
                        bedrooms: list, state: str) -> bool:
        """Check if this listing matches the search filters."""
        if self.price is not None:
            if self.price < min_rent or self.price > max_rent:
                return False

        if bedrooms:
            br_lower = self.bedrooms.lower().strip()
            allowed = {b.lower().strip() for b in bedrooms}
            if br_lower not in allowed and br_lower != "":
                return False

        if state and self.state:
            if self.state.upper() != state.upper():
                return False

        return True
