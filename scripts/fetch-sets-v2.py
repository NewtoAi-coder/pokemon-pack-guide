#!/usr/bin/env python3
"""Fetch all Pokemon TCG sets and their top chase cards. v2 - handles rate limits."""

import requests
import json
import time
import sys
from pathlib import Path

API_BASE = "https://api.pokemontcg.io/v2"
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

def fetch_with_retry(url, params=None, max_retries=3):
    """Fetch with retry and rate limit handling."""
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 5))
                print(f"    Rate limited, waiting {wait}s...", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            print(f"    Timeout (attempt {attempt+1}/{max_retries})", flush=True)
            time.sleep(2)
        except Exception as e:
            print(f"    Error: {e} (attempt {attempt+1}/{max_retries})", flush=True)
            time.sleep(2)
    return None

def main():
    print("Fetching all sets...", flush=True)
    data = fetch_with_retry(f"{API_BASE}/sets")
    if not data:
        print("Failed to fetch sets!", flush=True)
        sys.exit(1)
    
    sets = data["data"]
    sets.sort(key=lambda x: x.get("releaseDate", ""), reverse=True)
    print(f"Found {len(sets)} sets", flush=True)
    
    all_data = []
    
    for idx, s in enumerate(sets, 1):
        set_id = s["id"]
        set_name = s["name"]
        print(f"[{idx}/{len(sets)}] {set_name}", flush=True)
        
        # Fetch top 10 cards by cardmarket price
        params = {
            "q": f"set.id:{set_id}",
            "orderBy": "-cardmarket.prices.averageSellPrice",
            "pageSize": 10
        }
        
        card_data = fetch_with_retry(f"{API_BASE}/cards", params=params)
        
        top_cards = []
        if card_data and "data" in card_data:
            for card in card_data["data"]:
                # Try multiple price sources
                tcg_prices = card.get("tcgplayer", {}).get("prices", {})
                raw_price = None
                
                # Check holofoil, then 1stEditionHolofoil, then normal, then reverseHolofoil
                for variant in ["holofoil", "1stEditionHolofoil", "normal", "reverseHolofoil", "unlimitedHolofoil"]:
                    p = tcg_prices.get(variant, {}).get("market")
                    if p and p > 0:
                        raw_price = p
                        break
                
                # Fallback to cardmarket
                if not raw_price:
                    raw_price = card.get("cardmarket", {}).get("prices", {}).get("averageSellPrice", 0)
                
                if raw_price and raw_price > 0:
                    top_cards.append({
                        "name": card.get("name"),
                        "number": card.get("number"),
                        "rarity": card.get("rarity"),
                        "image": card.get("images", {}).get("large"),
                        "raw_value": round(raw_price, 2),
                        "psa10_value": round(raw_price * 3.5, 2),
                        "grade_worthy": raw_price >= 50
                    })
        
        # Sort by raw value descending
        top_cards.sort(key=lambda x: x["raw_value"], reverse=True)
        
        entry = {
            "id": set_id,
            "name": set_name,
            "series": s.get("series"),
            "release_date": s.get("releaseDate"),
            "total_cards": s.get("total"),
            "set_logo": s.get("images", {}).get("logo"),
            "set_symbol": s.get("images", {}).get("symbol"),
            "top_cards": top_cards[:10]
        }
        all_data.append(entry)
        
        # Save progress every 20 sets
        if idx % 20 == 0:
            with open(DATA_DIR / "sets.json", "w") as f:
                json.dump(all_data, f, indent=2)
            print(f"  [checkpoint saved: {idx} sets]", flush=True)
        
        time.sleep(1)  # Be respectful without API key
    
    # Final save
    with open(DATA_DIR / "sets.json", "w") as f:
        json.dump(all_data, f, indent=2)
    
    total_cards = sum(len(s["top_cards"]) for s in all_data)
    print(f"\n✅ Done! {len(all_data)} sets, {total_cards} chase cards saved.", flush=True)

if __name__ == "__main__":
    main()
