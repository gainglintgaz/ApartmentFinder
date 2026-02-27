"""Data models for apartment listings."""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus


# Housing type constants
TYPE_SUBSIDIZED = "subsidized"
TYPE_SENIOR = "senior"
TYPE_SECTION8 = "section8"
TYPE_MARKET = "market"

# Location tier constants
TIER_PREFERRED = "preferred"
TIER_EXPANDED = "expanded"
TIER_OTHER = "other"


@dataclass
class Apartment:
    """Normalized apartment listing from any source."""

    # Core fields
    title: str = ""
    price: Optional[int] = None
    bedrooms: str = ""          # "Studio", "1", "2", etc.
    bathrooms: Optional[float] = None
    sqft: Optional[int] = None

    # Location
    address: str = ""
    full_address: str = ""      # Full address with city, state, zip
    city: str = ""
    state: str = ""
    zip_code: str = ""
    neighborhood: str = ""
    directions_url: str = ""    # Google Maps directions link

    # Listing metadata
    url: str = ""
    source: str = ""            # e.g. "apartments.com", "socialserve"
    date_posted: str = ""
    date_scraped: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

    # Contact — critical for your mom
    phone: str = ""
    contact_name: str = ""

    # Extras
    amenities: str = ""
    pet_policy: str = ""

    # Classification (set after scraping)
    housing_type: str = TYPE_MARKET     # subsidized, senior, section8, market
    location_tier: str = TIER_OTHER     # preferred, expanded, other
    is_recent: bool = False             # Posted within last 48 hours

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def price_display(self) -> str:
        if self.price is not None:
            return f"${self.price:,}"
        return "Call"

    @property
    def type_label(self) -> str:
        labels = {
            TYPE_SUBSIDIZED: "Subsidized",
            TYPE_SENIOR: "Senior",
            TYPE_SECTION8: "Section 8",
            TYPE_MARKET: "Market",
        }
        return labels.get(self.housing_type, "Market")

    @property
    def tier_label(self) -> str:
        labels = {
            TIER_PREFERRED: "Midland/East CLT",
            TIER_EXPANDED: "Greater Charlotte",
            TIER_OTHER: "Other",
        }
        return labels.get(self.location_tier, "Other")

    @property
    def is_subsidized_or_senior(self) -> bool:
        return self.housing_type in (TYPE_SUBSIDIZED, TYPE_SENIOR, TYPE_SECTION8)

    def build_full_address(self):
        """Assemble full_address from parts and generate directions URL."""
        parts = [p for p in [self.address, self.city, self.state] if p]
        if self.zip_code:
            parts.append(self.zip_code)
        self.full_address = ", ".join(parts) if parts else self.address

        if self.full_address:
            encoded = quote_plus(self.full_address)
            self.directions_url = f"https://www.google.com/maps/dir/?api=1&destination={encoded}"


def classify_location(apt: Apartment, config: dict):
    """Set location_tier based on city/zip matching the config locations."""
    locations = config.get("locations", {})

    preferred = locations.get("preferred", {})
    pref_areas = {a.lower() for a in preferred.get("areas", [])}
    pref_zips = set(preferred.get("zip_codes", []))

    expanded = locations.get("expanded", {})
    exp_areas = {a.lower() for a in expanded.get("areas", [])}

    city_lower = apt.city.lower().strip()
    zip_code = apt.zip_code.strip()

    # If zip_code is empty, try to extract it from address/full_address text
    if not zip_code:
        import re
        for text in (apt.full_address, apt.address):
            if text:
                zip_match = re.search(r'\b(\d{5})(?:-\d{4})?\b', text)
                if zip_match:
                    zip_code = zip_match.group(1)
                    apt.zip_code = zip_code
                    break

    # Check preferred: city name OR zip code match
    if city_lower in pref_areas or zip_code in pref_zips:
        apt.location_tier = TIER_PREFERRED
        return

    # Check expanded: city name match (but prefer zip-based preferred over city-based expanded)
    # Don't short-circuit here — check fuzzy/address matching for preferred first
    is_expanded_city = city_lower in exp_areas

    # Fuzzy: check if any preferred area name appears in address/neighborhood
    addr_lower = (apt.address + " " + apt.neighborhood + " " + apt.full_address).lower()
    for area in pref_areas:
        # Use word boundary matching to avoid false positives
        if area in addr_lower:
            apt.location_tier = TIER_PREFERRED
            return

    if is_expanded_city:
        apt.location_tier = TIER_EXPANDED
        return

    for area in exp_areas:
        if area in addr_lower:
            apt.location_tier = TIER_EXPANDED
            return

    apt.location_tier = TIER_OTHER


def classify_recency(apt: Apartment, hours: int = 48):
    """Set is_recent flag if the listing was posted within the given hours."""
    if not apt.date_posted:
        apt.is_recent = False
        return

    cutoff = datetime.now() - timedelta(hours=hours)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y"):
        try:
            posted = datetime.strptime(apt.date_posted[:19], fmt)
            apt.is_recent = posted >= cutoff
            return
        except ValueError:
            continue
    apt.is_recent = False


def sort_key(apt: Apartment) -> tuple:
    """Sort key implementing the priority order:
    1. Subsidized / senior / Section 8 first
    2. Preferred location (Midland/East CLT) first
    3. Most recently posted first
    4. Then by price ascending
    """
    type_order = {TYPE_SUBSIDIZED: 0, TYPE_SENIOR: 0, TYPE_SECTION8: 0, TYPE_MARKET: 1}
    tier_order = {TIER_PREFERRED: 0, TIER_EXPANDED: 1, TIER_OTHER: 2}
    recent_order = 0 if apt.is_recent else 1
    price_val = apt.price if apt.price is not None else 99999

    return (
        type_order.get(apt.housing_type, 1),
        tier_order.get(apt.location_tier, 2),
        recent_order,
        price_val,
    )
