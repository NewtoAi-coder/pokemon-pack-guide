#!/usr/bin/env python3
"""Rebuild data/sets.json top_cards from the binder JSONs.

Why this exists: the original fetch-sets.py + enrich-ebay.py pipeline
left every modern set with a hard cap of ~10 priced top_cards, sorted
by Cardmarket's averageSellPrice (which has poor coverage for newer
Special Illustration Rares). Result: home page leaderboards showed
cheap commons/rares while the actual $1,000+ chase cards (Umbreon ex
SIR, Sylveon ex SIR, etc.) were absent or marked "Pricing pending".

Meanwhile, scripts/enrich_binder_prices.py was already fetching the
correct prices from pokemontcg.io's tcgplayer integration into the
per-set binder JSONs. This script reuses that data — no extra API
calls — to rebuild a fresh, properly-sorted top_cards array per set.

For each set:
  1. Read data/binder/<setId>.json
  2. Collapse variant slots back to one entry per card (keeping the
     highest raw price across that card's variants — typically the
     holofoil/SIR variant for premium cards)
  3. Sort priced cards by raw_value desc, keep top 50
  4. Preserve any existing ebay_data on existing top_cards entries
     (matched by card number)
  5. Write back into sets.json

After this runs, fallback_chase_by_rarity.py merges rarity-tier
additions for cards still missing prices, and regenerate_set_pages.py
rebuilds the root per-set HTML pages.

Usage:
  scripts/refresh_top_cards.py                     # all sets
  scripts/refresh_top_cards.py sv8pt5 me3 me2pt5   # specific sets only
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETS_FILE = ROOT / "data" / "sets.json"
BINDER_DIR = ROOT / "data" / "binder"

PSA10_MULTIPLIER = 3.5
GRADE_RAW_THRESHOLD = 50.0
TOP_LIMIT = 50


def collapse_variants(binder_cards):
    """Group variant slots by underlying cardId, keeping the variant with
    the highest raw price. Returns list of unique-card dicts."""
    by_card = {}
    for c in binder_cards:
        cid = c.get("cardId") or c["id"].split("__", 1)[0]
        raw = c.get("raw")
        existing = by_card.get(cid)
        if existing is None:
            by_card[cid] = c
            continue
        existing_raw = existing.get("raw") or 0
        cur_raw = raw or 0
        if cur_raw > existing_raw:
            by_card[cid] = c
    return list(by_card.values())


def build_top_cards(binder_cards, existing_top_cards):
    """Build a top_cards array from binder JSON cards. Preserves ebay_data
    where it was previously enriched (matched by card number)."""
    unique = collapse_variants(binder_cards)
    priced = [c for c in unique if (c.get("raw") or 0) > 0]
    priced.sort(key=lambda c: -(c.get("raw") or 0))
    top = priced[:TOP_LIMIT]

    # Carry over ebay_data from prior top_cards (keyed on number)
    ebay_lookup = {}
    for t in existing_top_cards:
        n = str(t.get("number")) if t.get("number") is not None else None
        if n and t.get("ebay_data"):
            ebay_lookup[n] = t["ebay_data"]

    out = []
    for c in top:
        raw = float(c["raw"])
        entry = {
            "name": c.get("name", ""),
            "number": c.get("n", ""),
            "rarity": c.get("rarity", ""),
            "image": c.get("large") or c.get("img", ""),
            "raw_value": round(raw, 2),
            "psa10_value": round(raw * PSA10_MULTIPLIER, 2),
            "grade_worthy": raw >= GRADE_RAW_THRESHOLD,
        }
        n = str(c.get("n", ""))
        if n in ebay_lookup:
            entry["ebay_data"] = ebay_lookup[n]
        out.append(entry)
    return out


def main():
    only = set(sys.argv[1:]) or None

    with open(SETS_FILE) as f:
        sets_data = json.load(f)

    targets = sets_data if only is None else [s for s in sets_data if s["id"] in only]
    print(f"Refreshing top_cards for {len(targets)} set(s)...", flush=True)

    changes = []
    skipped = 0
    for s in targets:
        binder_path = BINDER_DIR / f"{s['id']}.json"
        if not binder_path.exists():
            skipped += 1
            continue
        with open(binder_path) as f:
            bd = json.load(f)
        new_top = build_top_cards(bd.get("cards", []), s.get("top_cards", []))
        old_priced = sum(
            1 for c in s.get("top_cards", [])
            if (c.get("raw_value") or 0) > 0 and not c.get("pricing_pending")
        )
        new_priced = len(new_top)
        s["top_cards"] = new_top
        changes.append((s["id"], s["name"], old_priced, new_priced,
                        new_top[0]["name"] if new_top else None,
                        new_top[0]["raw_value"] if new_top else None))

    # Sort changes by biggest jump (most-improved sets first) for the report
    changes.sort(key=lambda c: -(c[3] - c[2]))
    print(f"\n{'set_id':<12} {'name':<28}  {'old':>4} -> {'new':>4}  top card", flush=True)
    print("-" * 100, flush=True)
    for sid, name, old, new, top_name, top_price in changes[:30]:
        top_str = f"{top_name} ${top_price:,.2f}" if top_name else "(no priced cards)"
        print(f"  {sid:<10} {name[:28]:<28}  {old:>4} -> {new:>4}  {top_str}", flush=True)
    if len(changes) > 30:
        print(f"  ... ({len(changes) - 30} more)", flush=True)

    with open(SETS_FILE, "w") as f:
        json.dump(sets_data, f, indent=2)
    print(f"\nUpdated {SETS_FILE}", flush=True)
    print(f"  {len(changes)} sets refreshed, {skipped} skipped (no binder JSON)", flush=True)


if __name__ == "__main__":
    main()
