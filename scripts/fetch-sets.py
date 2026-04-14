#!/usr/bin/env python3
"""Fetch all Pokemon TCG sets and their top chase cards."""

import requests
import json
import time
from pathlib import Path

API_BASE = "https://api.pokemontcg.io/v2"
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

def fetch_all_sets():
    """Fetch all sets from Pokemon TCG API."""
    print("Fetching all sets...")
    response = requests.get(f"{API_BASE}/sets", timeout=30)
    response.raise_for_status()
    sets_data = response.json()["data"]
    
    # Sort by release date (newest first)
    sets_data.sort(key=lambda x: x.get("releaseDate", ""), reverse=True)
    
    print(f"Found {len(sets_data)} sets")
    return sets_data

def fetch_top_cards(set_id, limit=50):
    """Fetch cards $20+ raw from a set, sorted by market price (highest first)."""
    print(f"  Fetching cards from {set_id}...")
    
    # Get cards from the set (up to 50)
    params = {
        "q": f"set.id:{set_id}",
        "orderBy": "-cardmarket.prices.averageSellPrice",
        "pageSize": limit
    }
    
    response = requests.get(f"{API_BASE}/cards", params=params, timeout=30)
    response.raise_for_status()
    cards = response.json()["data"]
    
    # Filter and clean card data
    top_cards = []
    for card in cards:
        # Try multiple price sources
        tcg_prices = card.get("tcgplayer", {}).get("prices", {})
        tcg_price = None
        for variant in ["holofoil", "reverseHolofoil", "normal", "1stEditionHolofoil", "unlimitedHolofoil"]:
            if variant in tcg_prices and tcg_prices[variant].get("market"):
                tcg_price = tcg_prices[variant]["market"]
                break
        
        cm_price = card.get("cardmarket", {}).get("prices", {}).get("averageSellPrice")
        raw_price = tcg_price or cm_price or 0
        
        # Include all cards with pricing data
        if raw_price > 0:
            card_data = {
                "name": card.get("name"),
                "number": card.get("number"),
                "rarity": card.get("rarity"),
                "image": card.get("images", {}).get("large"),
                "raw_value": round(raw_price, 2),
                "psa10_value": round(raw_price * 3.5, 2),
                "grade_worthy": raw_price >= 50,
            }
            top_cards.append(card_data)
    
    # Sort by raw value, highest first
    top_cards.sort(key=lambda x: x["raw_value"], reverse=True)
    
    return top_cards

def main():
    """Main execution."""
    sets = fetch_all_sets()
    
    all_data = []
    
    for idx, set_data in enumerate(sets, 1):
        set_id = set_data["id"]
        set_name = set_data["name"]
        
        print(f"\n[{idx}/{len(sets)}] Processing: {set_name}")
        
        # Get top cards
        top_cards = fetch_top_cards(set_id)
        
        # Build set entry
        entry = {
            "id": set_id,
            "name": set_name,
            "series": set_data.get("series"),
            "release_date": set_data.get("releaseDate"),
            "total_cards": set_data.get("total"),
            "set_logo": set_data.get("images", {}).get("logo"),
            "set_symbol": set_data.get("images", {}).get("symbol"),
            "top_cards": top_cards
        }
        
        all_data.append(entry)
        
        # Rate limiting
        time.sleep(0.3)
    
    # Save to JSON
    output_file = DATA_DIR / "sets.json"
    with open(output_file, "w") as f:
        json.dump(all_data, f, indent=2)
    
    print(f"\n✅ Saved {len(all_data)} sets to {output_file}")

if __name__ == "__main__":
    main()
