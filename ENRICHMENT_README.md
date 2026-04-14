# Pokemon Pack Guide - eBay Enrichment System

## Overview
This system automatically enriches Pokemon card pricing data by scraping eBay sold listings for cards that lack pricing information from the Pokemon TCG API.

## Components

### 1. eBay Enrichment Script (`scripts/enrich-ebay.py`)
**What it does:**
- Identifies sets with missing or incomplete pricing data
- Fetches card lists from the Pokemon TCG API
- Searches eBay sold listings for each card (raw and PSA 10 graded)
- Extracts sold prices and calculates statistics (average, median, high)
- Updates `data/sets.json` with eBay pricing data
- Caches HTML files in `data/ebay_cache/` for debugging

**Priority sets:**
- Perfect Order (me3)
- Ascended Heroes (me2pt5)
- Any other sets with 0 top_cards

**Usage:**
```bash
cd ~/.openclaw/workspace/pokemon-pack-guide
./venv/bin/python3 scripts/enrich-ebay.py
```

**Output:**
- Updates `data/sets.json` with eBay pricing under `ebay_data` field
- Each card gets: `raw` (raw card prices) and `psa10` (PSA 10 graded prices)
- Statistics: average, median, high, sample_size
- Uses median prices as the primary value

### 2. Complete Refresh Pipeline (`scripts/refresh-all.sh`)
**What it does:**
1. Fetches all set data from Pokemon TCG API
2. Enriches with eBay sold listing data
3. Regenerates the HTML site

**Usage:**
```bash
cd ~/.openclaw/workspace/pokemon-pack-guide
./scripts/refresh-all.sh
```

### 3. Weekly Auto-Refresh Cron Job
**Schedule:** Every Sunday at midnight ET
**Cron ID:** `dbe579bc-7bd7-4fc7-8639-3750f8107916`
**Name:** `pokemon-pack-guide-weekly-refresh`

**What it does:**
- Runs the complete refresh pipeline automatically
- Keeps the site up-to-date with latest pricing from both TCG API and eBay

**Manage the cron job:**
```bash
# List all cron jobs
openclaw cron list

# Run immediately (for testing)
openclaw cron run pokemon-pack-guide-weekly-refresh

# View run history
openclaw cron runs pokemon-pack-guide-weekly-refresh

# Disable/enable
openclaw cron disable pokemon-pack-guide-weekly-refresh
openclaw cron enable pokemon-pack-guide-weekly-refresh
```

## How eBay Enrichment Works

### Search Strategy
For each card, the script performs two searches:
1. **Raw card search:** `Pokemon [Card Name] [Set Name]`
2. **PSA 10 search:** `Pokemon [Card Name] [Set Name] PSA 10`

### Price Extraction
- Searches eBay sold listings (category: 183454 - Pokemon Trading Cards)
- Sorts by most recent sold
- Extracts prices using multiple methods:
  - Regex pattern matching for dollar amounts
  - Structured data (JSON-LD) when available
- Filters prices between $0.01 and $100,000 (sanity check)
- Calculates statistics from all found prices

### Data Storage Format
```json
{
  "name": "Dewgong",
  "number": "11",
  "rarity": "Rare",
  "image": "https://images.pokemontcg.io/me3/11_hires.png",
  "raw_value": 2.0,
  "psa10_value": 70.0,
  "grade_worthy": false,
  "ebay_data": {
    "raw": {
      "average": 501.0,
      "median": 2.0,
      "high": 1500.0,
      "sample_size": 3
    },
    "psa10": {
      "average": 45.56,
      "median": 70.0,
      "high": 76.99,
      "sample_size": 9
    },
    "last_updated": "2026-04-13"
  }
}
```

## Results

### Perfect Order (me3)
- ✅ **2 cards enriched** with eBay pricing
  - Decidueye ex: $5 raw (3 samples)
  - Dewgong: $2 raw, $70 PSA 10 (3 raw samples, 9 PSA 10 samples)

### Ascended Heroes (me2pt5)
- ❌ **0 cards enriched** - No eBay sold listings found
  - Likely too new or set name doesn't match eBay listings
  - May improve over time as more listings appear

## Debugging

### Check cached HTML
If prices aren't being found, check the cached eBay HTML:
```bash
ls -la ~/.openclaw/workspace/pokemon-pack-guide/data/ebay_cache/
open data/ebay_cache/[card_name].html
```

### Test a single card search manually
Open the search URL in a browser to see what eBay returns:
```
https://www.ebay.com/sch/i.html?_nkw=Pokemon+[Card+Name]+[Set+Name]&_sacat=183454&LH_Complete=1&LH_Sold=1&_sop=13
```

### Improve the scraper
If eBay changes their HTML structure, update `scripts/enrich-ebay.py`:
- Add new CSS selectors
- Add new regex patterns
- Adjust the extraction logic

## Future Improvements

1. **Better set name matching:** Map official set names to eBay search terms
2. **Card number/rarity filtering:** Filter eBay results by card number to avoid wrong variants
3. **Rate limit handling:** Add more sophisticated retry logic
4. **Price validation:** Cross-reference multiple sources (TCGPlayer, CardMarket, eBay)
5. **Historical tracking:** Save price history over time
6. **Notification on anomalies:** Alert when prices spike or drop significantly
