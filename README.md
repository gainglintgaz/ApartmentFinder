# ApartmentFinder

Scrape structured apartment rental data from reputable sources and export it to CSV and JSON. Configured for Charlotte, NC — easily customizable for any US city.

## Sources

| Source | Type |
|---|---|
| Apartments.com | HTML scraping |
| Craigslist | HTML scraping |
| Zillow | Embedded JSON + HTML fallback |
| Rent.com | Embedded JSON + HTML fallback |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run with default config (Charlotte, NC | Studios/1BR/2BR | $400-$900)
python apartment_finder.py

# Run with a custom config file
python apartment_finder.py --config my_config.yaml

# Override specific parameters via CLI
python apartment_finder.py --city "Raleigh" --state NC --max-rent 1200 --bedrooms studio 1 2
```

## Configuration

All search parameters live in `config.yaml`:

```yaml
search:
  city: "Charlotte"
  state: "NC"
  radius_miles: 30
  restrict_to_state: true
  bedrooms: [studio, 1, 2]
  min_rent: 400
  max_rent: 900
  max_listing_age_days: 7
```

### Key settings

| Setting | Description |
|---|---|
| `search.city` | Target city name |
| `search.state` | Two-letter state code |
| `search.bedrooms` | List: `studio`, `1`, `2`, `3`, `4` |
| `search.min_rent` / `max_rent` | Monthly rent range in USD |
| `sources.*` | Enable/disable individual scrapers |
| `scraping.rate_limit_seconds` | Delay between requests (be polite) |
| `scraping.max_pages_per_source` | Cap pages scraped per source |
| `output.csv` / `output.json` | Toggle output formats |

## CLI Options

```
--config, -c     Path to YAML config (default: config.yaml)
--city           Override search city
--state          Override search state
--min-rent       Override minimum rent
--max-rent       Override maximum rent
--bedrooms       Override bedrooms (e.g., studio 1 2)
--radius         Override search radius in miles
```

## Output

Results are written to the `output/` directory:

- **CSV** — Open directly in Excel or Google Sheets. Each row is one listing with columns for price, bedrooms, sqft, address, source, URL, etc.
- **JSON** — Structured data with search metadata and a `listings` array. Ready for programmatic use.

A summary table is also printed to the terminal.

## Project Structure

```
ApartmentFinder/
├── apartment_finder.py      # Main CLI entry point
├── config.yaml              # Search parameters
├── models.py                # Apartment data model
├── exporter.py              # CSV + JSON export
├── scrapers/
│   ├── base.py              # Base scraper with rate limiting
│   ├── apartments_com.py    # Apartments.com scraper
│   ├── craigslist.py        # Craigslist scraper
│   ├── zillow.py            # Zillow scraper
│   └── rent_com.py          # Rent.com scraper
├── requirements.txt
└── .gitignore
```

## Notes

- Scrapers use User-Agent rotation and rate limiting to be respectful.
- Some sites may block or CAPTCHA automated requests — results will vary.
- The tool filters, deduplicates, and sorts results by price before exporting.
- All output files are gitignored. Only config and code are tracked.
