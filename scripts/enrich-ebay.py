#!/usr/bin/env python3
"""Enrich sets.json with eBay sold listing data for cards missing TCG API prices."""

import requests
from bs4 import BeautifulSoup
import json
import time
import re
from pathlib import Path
from urllib.parse import quote_plus

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_DIR = DATA_DIR / "ebay_cache"
CACHE_DIR.mkdir(exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

def search_ebay_sold(card_name, set_name, psa_grade=None, max_results=10):
    """Search eBay for sold listings of a Pokemon card."""
    # Build search query
    query_parts = ["Pokemon", card_name, set_name]
    if psa_grade:
        query_parts.append(f"PSA {psa_grade}")
    
    query = " ".join(query_parts)
    
    # eBay sold listings URL with Pokemon category
    url = f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(query)}&_sacat=183454&LH_Complete=1&LH_Sold=1&_sop=13&_ipg=60"
    
    print(f"  Searching: {query}", flush=True)
    
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        
        # Save HTML for debugging
        cache_file = CACHE_DIR / f"{card_name.replace(' ', '_')[:30]}.html"
        with open(cache_file, 'w', encoding='utf-8') as f:
            f.write(r.text)
        
        soup = BeautifulSoup(r.text, 'lxml')
        
        # Extract prices from sold listings - try multiple patterns
        prices = []
        
        # Pattern 1: Look for sold price text patterns
        text = r.text
        # Match patterns like "$123.45" in sold context
        price_matches = re.findall(r'\$([0-9,]+\.?[0-9]*)', text)
        if price_matches:
            for match in price_matches[:max_results]:
                try:
                    price = float(match.replace(',', ''))
                    if 0.01 <= price <= 100000:  # Sanity check
                        prices.append(price)
                except:
                    pass
        
        # Pattern 2: Try to find price elements in structured data
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and 'offers' in data:
                    offers = data['offers']
                    if isinstance(offers, list):
                        for offer in offers:
                            if 'price' in offer:
                                try:
                                    prices.append(float(offer['price']))
                                except:
                                    pass
            except:
                pass
        
        # Remove duplicates and sort
        prices = sorted(set(prices), reverse=True)[:max_results]
        
        if prices:
            print(f"    Found {len(prices)} sold prices: ${min(prices):.2f} - ${max(prices):.2f}", flush=True)
        else:
            print(f"    No prices found", flush=True)
        
        return prices
        
    except Exception as e:
        print(f"    Error: {e}", flush=True)
        return []

def calculate_price_stats(prices):
    """Calculate average, median, and high from price list."""
    if not prices:
        return None
    
    sorted_prices = sorted(prices)
    avg = sum(prices) / len(prices)
    median = sorted_prices[len(sorted_prices) // 2]
    high = max(prices)
    
    return {
        'average': round(avg, 2),
        'median': round(median, 2),
        'high': round(high, 2),
        'sample_size': len(prices)
    }

def enrich_card_with_ebay(card, set_name, set_id):
    """Enrich a single card with eBay pricing data."""
    card_name = card.get('name', '')
    if not card_name:
        return False
    
    # Search for raw card prices
    raw_prices = search_ebay_sold(card_name, set_name, psa_grade=None)
    time.sleep(2)  # Be respectful
    
    # Search for PSA 10 prices
    psa10_prices = search_ebay_sold(card_name, set_name, psa_grade=10)
    time.sleep(2)
    
    # Calculate stats
    raw_stats = calculate_price_stats(raw_prices)
    psa10_stats = calculate_price_stats(psa10_prices)
    
    # Update card data if we found prices
    if raw_stats or psa10_stats:
        card['ebay_data'] = {
            'raw': raw_stats,
            'psa10': psa10_stats,
            'last_updated': time.strftime('%Y-%m-%d')
        }
        
        # Use eBay median as raw_value if missing
        if not card.get('raw_value') and raw_stats:
            card['raw_value'] = raw_stats['median']
        
        # Use eBay PSA 10 median if missing
        if not card.get('psa10_value') and psa10_stats:
            card['psa10_value'] = psa10_stats['median']
        
        # Determine grade worthiness
        raw_val = card.get('raw_value', 0)
        card['grade_worthy'] = raw_val >= 50
        
        return True
    
    return False

def main():
    """Main enrichment process."""
    sets_file = DATA_DIR / "sets.json"
    
    if not sets_file.exists():
        print("❌ sets.json not found!")
        return
    
    with open(sets_file) as f:
        sets_data = json.load(f)
    
    # Find sets with empty or missing top_cards
    empty_sets = [s for s in sets_data if len(s.get('top_cards', [])) == 0]
    print(f"Found {len(empty_sets)} sets with no pricing data", flush=True)
    
    # Focus on recent sets (Ascended Heroes, Perfect Order)
    priority_sets = [s for s in empty_sets if s['id'] in ('me2pt5', 'me3')]
    
    if not priority_sets:
        print("No priority sets need enrichment")
        return
    
    # Fetch cards from TCG API and enrich with eBay
    for set_data in priority_sets:
        set_id = set_data['id']
        set_name = set_data['name']
        
        print(f"\n{'='*60}")
        print(f"Processing: {set_name} ({set_id})")
        print(f"{'='*60}")
        
        # Fetch cards from TCG API
        try:
            url = "https://api.pokemontcg.io/v2/cards"
            params = {
                'q': f'set.id:{set_id}',
                'pageSize': 20,  # Start with top 20 cards by number
                'orderBy': 'number'
            }
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            cards_data = r.json()
            
            cards = cards_data.get('data', [])
            print(f"Fetched {len(cards)} cards from TCG API")
            
            enriched_cards = []
            
            # Focus on rare/ultra rare cards
            rare_cards = [c for c in cards if c.get('rarity') in ('Rare', 'Ultra Rare', 'Double Rare', 'Hyper Rare', 'Special Illustration Rare')]
            
            print(f"Found {len(rare_cards)} rare+ cards to price")
            
            for idx, card in enumerate(rare_cards[:10], 1):  # Limit to 10 to avoid rate limits
                print(f"\n[{idx}/{min(10, len(rare_cards))}] {card.get('name')} #{card.get('number')}")
                
                enriched = {
                    'name': card.get('name'),
                    'number': card.get('number'),
                    'rarity': card.get('rarity'),
                    'image': card.get('images', {}).get('large'),
                }
                
                # Try to enrich with eBay
                if enrich_card_with_ebay(enriched, set_name, set_id):
                    enriched_cards.append(enriched)
                    print(f"  ✓ Enriched: ${enriched.get('raw_value', 0):.2f} raw, ${enriched.get('psa10_value', 0):.2f} PSA 10")
                else:
                    print(f"  ✗ No eBay data found")
            
            # Update set data
            if enriched_cards:
                # Sort by raw value
                enriched_cards.sort(key=lambda x: x.get('raw_value', 0), reverse=True)
                set_data['top_cards'] = enriched_cards
                print(f"\n✅ Added {len(enriched_cards)} priced cards to {set_name}")
            
        except Exception as e:
            print(f"❌ Error processing {set_name}: {e}")
            continue
    
    # Save updated data
    print(f"\n{'='*60}")
    print("Saving updated sets.json...")
    with open(sets_file, 'w') as f:
        json.dump(sets_data, f, indent=2)
    
    print("✅ Enrichment complete!")
    print(f"Cached HTML files saved to: {CACHE_DIR}")

if __name__ == "__main__":
    main()
