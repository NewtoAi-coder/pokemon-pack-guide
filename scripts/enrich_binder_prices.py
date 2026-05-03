#!/usr/bin/env python3
"""Enrich binder JSON files with variant detection + tcgplayer-sourced pricing.

For each set in data/binder/, fetches pokemontcg.io with select=id,tcgplayer
and rewrites the cards array so each finish variant gets its own slot:

  - normal              -> "Regular"
  - holofoil            -> "Holo"
  - unlimitedHolofoil   -> "Holo"   (collapsed; vintage equivalent)
  - reverseHolofoil     -> "Reverse Holo"

1st-Edition variants are intentionally excluded (separate collector category).

Each variant entry carries:
  - id           unique slot ID. Bare card ID when only one variant exists for
                 that card; composite "<cardId>__<variant>" when 2+ variants.
                 Stable across reruns. Used as the localStorage tracking key.
  - cardId       underlying card ID (always present; equals id for single-variant)
  - variant      "normal" | "holofoil" | "reverseHolo"   (only when card is multi-variant)
  - variantLabel "Regular" | "Holo" | "Reverse Holo"     (only when card is multi-variant)
  - raw          tcgplayer market for this variant
  - psa10        raw * 3.5  (matches the chase-page convention)
  - grade_worthy raw >= 50.0

Sort within a set: card-number ascending, then variant priority (Regular, Holo,
Reverse Holo) so variants of card #N land in adjacent slots on the same binder
page.

Cards with no tcgplayer data fall back to a single entry with raw/psa10 null.

Re-runnable. Idempotent shape: a clean rerun produces the same JSON for the
same upstream tcgplayer data.

Usage:
  scripts/enrich_binder_prices.py             # all sets
  scripts/enrich_binder_prices.py base1 me3   # specific sets only
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BINDER_DIR = Path(__file__).resolve().parent.parent / "data" / "binder"
PSA10_MULTIPLIER = 3.5
GRADE_RAW_THRESHOLD = 50.0

# Map raw tcgplayer key -> (normalized_variant_key, human_label, sort_order)
# Order is the canonical master-set checklist order.
VARIANT_MAP = {
    "normal":            ("normal",       "Regular",      0),
    "holofoil":          ("holofoil",     "Holo",         1),
    "unlimitedHolofoil": ("holofoil",     "Holo",         1),
    "reverseHolofoil":   ("reverseHolo",  "Reverse Holo", 2),
}


def fetch_set_tcgplayer(set_id):
    """Return {card_id: tcgplayer_prices_dict_or_None} for every card in the set."""
    out = {}
    page = 1
    while True:
        q = urllib.parse.urlencode({
            "q": f"set.id:{set_id}",
            "pageSize": 250,
            "page": page,
            "select": "id,tcgplayer",
        })
        url = f"https://api.pokemontcg.io/v2/cards?{q}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "pokemon-pack-guide/1.0 (price enrichment)",
            "Accept": "application/json",
        })
        last_err = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read())
                last_err = None
                break
            except Exception as e:
                last_err = e
                time.sleep(1 + attempt * 2)
        if last_err is not None:
            print(f"  ERROR fetching page {page}: {last_err}", flush=True)
            return None
        cards = data.get("data", [])
        for c in cards:
            cid = c["id"]
            out[cid] = (c.get("tcgplayer") or {}).get("prices") or None
        total = data.get("totalCount", len(out))
        if len(out) >= total or not cards:
            return out
        page += 1
        time.sleep(0.3)


def variants_for_card(tcg_prices):
    """Return ordered list of variant dicts. Empty list = no priceable variant."""
    if not tcg_prices:
        return []
    by_key = {}
    for raw_key, (norm_key, label, order) in VARIANT_MAP.items():
        v = tcg_prices.get(raw_key)
        if not v:
            continue
        market = v.get("market") or v.get("mid")
        if not market or market <= 0:
            continue
        # If we've already mapped this normalized key (e.g. holofoil and
        # unlimitedHolofoil both folding to "holofoil"), keep the first.
        if norm_key in by_key:
            continue
        by_key[norm_key] = {
            "variant": norm_key,
            "variantLabel": label,
            "order": order,
            "raw": round(float(market), 2),
        }
    return sorted(by_key.values(), key=lambda x: x["order"])


def number_sort_key(n):
    """Stable sort for card.number: numeric where possible, alpha-numeric fallback."""
    if not n:
        return (3, 0, "")
    if n.isdigit():
        return (0, int(n), "")
    m = re.search(r"\d+", n)
    if m:
        return (1, int(m.group()), n)
    return (2, 0, n)


def build_slot(base_card, variant, multi):
    """Build a single slot entry from an existing card record + variant info."""
    out = dict(base_card)  # copy id, n, name, rarity, img, large, types, supertype
    out.pop("raw", None)
    out.pop("psa10", None)
    out.pop("grade_worthy", None)
    out.pop("variant", None)
    out.pop("variantLabel", None)
    out.pop("cardId", None)
    out["cardId"] = base_card["id"]
    if multi:
        out["id"] = f"{base_card['id']}__{variant['variant']}"
        out["variant"] = variant["variant"]
        out["variantLabel"] = variant["variantLabel"]
    raw = variant["raw"]
    out["raw"] = raw
    out["psa10"] = round(raw * PSA10_MULTIPLIER, 2)
    out["grade_worthy"] = raw >= GRADE_RAW_THRESHOLD
    return out


def build_unpriced_slot(base_card):
    """Single slot for a card with no tcgplayer data."""
    out = dict(base_card)
    out.pop("variant", None)
    out.pop("variantLabel", None)
    # Reset to canonical schema
    out["cardId"] = base_card.get("cardId") or base_card["id"]
    out["id"] = out["cardId"]
    out["raw"] = None
    out["psa10"] = None
    out["grade_worthy"] = False
    return out


def collapse_to_unique_cards(cards):
    """Existing JSON may have already been variant-expanded from a prior run.
    Collapse back to a unique-card list keyed by cardId (or id when no cardId)
    so we can re-expand cleanly using fresh tcgplayer data.
    """
    seen = {}
    order = []
    for c in cards:
        key = c.get("cardId") or c["id"].split("__", 1)[0]
        if key in seen:
            continue
        # Strip variant fields; keep core card identity
        base = {
            "id": key,
            "n": c.get("n", ""),
            "name": c.get("name", ""),
            "rarity": c.get("rarity", ""),
            "img": c.get("img", ""),
            "large": c.get("large", ""),
            "types": c.get("types", []),
            "supertype": c.get("supertype", ""),
        }
        seen[key] = base
        order.append(key)
    return [seen[k] for k in order]


def enrich_file(path):
    with open(path) as f:
        data = json.load(f)
    set_id = data["id"]
    print(f"  fetching {set_id}...", flush=True)
    tcg_by_card = fetch_set_tcgplayer(set_id)
    if tcg_by_card is None:
        return False, "fetch error"

    base_cards = collapse_to_unique_cards(data.get("cards", []))
    new_cards = []
    multi_count = 0
    priced_slots = 0
    for bc in base_cards:
        variants = variants_for_card(tcg_by_card.get(bc["id"]))
        if not variants:
            new_cards.append(build_unpriced_slot(bc))
            continue
        multi = len(variants) > 1
        if multi:
            multi_count += 1
        for v in variants:
            new_cards.append(build_slot(bc, v, multi))
            priced_slots += 1

    # Sort: card number, then variant order (normal=0, holo=1, reverseHolo=2)
    variant_order = {"normal": 0, "holofoil": 1, "reverseHolo": 2}
    new_cards.sort(key=lambda c: (
        number_sort_key(c.get("n", "")),
        variant_order.get(c.get("variant"), -1),  # unpriced/single-variant first
        c["id"],
    ))

    data["cards"] = new_cards
    data["total"] = len(new_cards)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    return True, (
        f"{len(base_cards)} unique cards -> {len(new_cards)} slots "
        f"({multi_count} multi-variant, {priced_slots}/{len(new_cards)} priced)"
    )


def rebuild_manifest():
    """Rewrite _manifest.json with total_slots + total_value per set.

    Both fields are derived from the current binder JSONs on disk — no network
    calls, no API quota use. Safe to run any time; keeps the directory page
    (binders.html) in sync with the actual slot count and aggregate set value.

    total_value sums the raw price across every priceable slot (skips null
    prices, so unpriced cards just don't contribute).
    """
    manifest_path = BINDER_DIR / "_manifest.json"
    if not manifest_path.exists():
        print("  no _manifest.json — skipping", flush=True)
        return
    with open(manifest_path) as f:
        manifest = json.load(f)
    slot_counts = {}
    set_values = {}
    for p in BINDER_DIR.glob("*.json"):
        if p.name == "_manifest.json":
            continue
        try:
            with open(p) as f:
                d = json.load(f)
            cards = d.get("cards", [])
            slot_counts[d["id"]] = len(cards)
            set_values[d["id"]] = round(
                sum(float(c["raw"]) for c in cards if c.get("raw") is not None), 2
            )
        except Exception:
            continue
    for s in manifest.get("sets", []):
        s["total_slots"] = slot_counts.get(s["id"], s.get("total_cards", 0))
        s["total_value"] = set_values.get(s["id"], 0.0)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, separators=(",", ":"))
    print(f"  manifest rebuilt: {len(manifest.get('sets', []))} sets", flush=True)


def main():
    args = sys.argv[1:]
    manifest_only = "--manifest-only" in args
    only = [a for a in args if a != "--manifest-only"] or None

    if manifest_only:
        print("Rebuilding manifest only (no API fetch)...", flush=True)
        rebuild_manifest()
        return

    files = sorted(p for p in BINDER_DIR.glob("*.json") if p.name != "_manifest.json")
    if only:
        wanted = set(only)
        files = [p for p in files if p.stem in wanted]
        missing = wanted - {p.stem for p in files}
        for m in missing:
            print(f"  WARNING: no binder JSON for set '{m}'", flush=True)

    print(f"Enriching {len(files)} binder JSONs...", flush=True)
    ok = 0
    fail = []
    for i, p in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {p.name}", flush=True)
        success, msg = enrich_file(p)
        print(f"  -> {msg}", flush=True)
        if success:
            ok += 1
        else:
            fail.append((p.stem, msg))
        time.sleep(0.4)

    print(f"\nDONE: {ok}/{len(files)} enriched, {len(fail)} failed", flush=True)
    if fail:
        print("Failed sets:")
        for sid, msg in fail:
            print(f"  {sid}: {msg}")
    rebuild_manifest()


if __name__ == "__main__":
    main()
