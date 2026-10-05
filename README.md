# ApartmentFinder

Senior & affordable housing search tool for Charlotte, NC. Scrapes government/subsidized housing sources first, then market rentals. Prioritizes Midland & East Charlotte. Exports structured data to CSV and JSON with Google Maps directions, phone numbers, and original listing links.

## Who this is for

Configured for a 64-year-old woman on a $1,300/month pension looking for affordable housing ($0-$900/month) in the Charlotte, NC / Midland area. Studio through 2-bedroom units with room for a sleeper sofa.

## Search Priority Order

| Priority | What | Sources | Listing Age |
|---|---|---|---|
| 1st | Government / Subsidized / Senior housing | NC Housing Search, HUD, AffordableHousing, GoSection8 | Up to 90 days |
| 2nd | Market rentals in Midland & East Charlotte | Apartments.com, Craigslist, Zillow, Rent.com | Last 48h first, up to 7 days |
| 3rd | Market rentals in Greater Charlotte (30 min) | Same market sources | Last 48h first, up to 7 days |

## Quick Start

```bash
pip install -r requirements.txt

# Full search (government + market, all areas)
python apartment_finder.py

# Only government/subsidized/senior housing
python apartment_finder.py --subsidized-only

# Only market rentals
python apartment_finder.py --market-only

# Override rent ceiling
python apartment_finder.py --max-rent 700
```

## Monitor for New Listings

The monitor watches for new apartments and alerts you when they appear:

```bash
# Run continuously (checks every 60 minutes by default)
python monitor.py

# Check once and exit
python monitor.py --once
```

To get email alerts, fill in the `monitor.email` section in `config.yaml`.

## What Each Listing Includes

Every listing in the output contains:

- **Title** — property name
- **Type** — Subsidized / Senior / Section 8 / Market
- **Price** — monthly rent (or "Call" / "Income-Based")
- **Bedrooms / Bathrooms / Sq Ft**
- **Full Address** — street, city, state, zip
- **Google Maps Directions** — clickable link
- **Phone Number** — when available
- **Original Listing URL** — direct link to the source
- **Source** — which website it came from
- **Date Posted** — when available
- **Location Tier** — Midland/East CLT, Greater Charlotte, or Other
- **Recency Flag** — "NEW (48h)" for listings posted in the last 2 days

## Output

Results go to the `output/` directory:

- **CSV** — Open in Excel or Google Sheets. Sorted by priority (subsidized first, then by location, then by date).
- **JSON** — Grouped into `priority_1_subsidized_senior`, `priority_2_preferred_location`, `priority_3_greater_charlotte`, `priority_4_other`.

## Sources

### Priority 1: Government / Subsidized / Senior
| Source | What it covers |
|---|---|
| nchousingsearch.org (SocialServe) | Official NC affordable housing locator |
| hud.gov | Federal affordable housing directory |
| affordablehousingonline.com | Subsidized & income-based listings |
| gosection8.com | Section 8 / voucher-accepted rentals |

### Priority 2: Market Rentals
| Source | What it covers |
|---|---|
| Apartments.com | Major apartment listing site |
| Craigslist | Charlotte-area classified rentals |
| Zillow | Rental listings with embedded data |
| Rent.com | Apartment & rental search |

## Location Tiers

**Preferred (Tier 1):** Midland, Mint Hill, Harrisburg, Concord, Albemarle, Locust, Stanfield, Oakboro, Indian Trail, Stallings, Matthews, Monroe

**Expanded (Tier 2):** Charlotte, Huntersville, Cornelius, Davidson, Pineville, Gastonia, Kannapolis, Mooresville, Waxhaw, Belmont, Mount Holly

## Configuration

Edit `config.yaml` to change any search parameters: budget, bedrooms, locations, which sources to enable, monitor interval, email alerts, etc.

## Project Structure

```
ApartmentFinder/
├── apartment_finder.py      # Main CLI — run searches
├── monitor.py               # Watch for new listings
├── config.yaml              # All search parameters
├── models.py                # Apartment data model
├── exporter.py              # CSV + JSON export with grouping
├── scrapers/
│   ├── base.py              # Base scraper (rate limiting, UA rotation)
│   ├── socialserve.py       # NC Housing Search
│   ├── hud.py               # HUD affordable housing
│   ├── affordablehousing.py # AffordableHousing.com
│   ├── gosection8.py        # GoSection8.com
│   ├── apartments_com.py    # Apartments.com
│   ├── craigslist.py        # Craigslist
│   ├── zillow.py            # Zillow
│   └── rent_com.py          # Rent.com
├── requirements.txt
└── .gitignore
```
