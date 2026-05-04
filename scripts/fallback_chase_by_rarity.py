#!/usr/bin/env python3
"""Rarity-based chase-card augmentation for top_cards in sets.json.

Why this exists: brand-new sets (Mega Evolution era) often have card
entries on pokemontcg.io but no tcgplayer market price yet, so they
end up with empty or sparse top_cards arrays — and the home page shows
misleadingly low chase counts even though the set obviously contains
many alt arts, Mega ex hits, secret rares.

For every set, this script fetches all cards whose rarity matches a
chase tier (Special Illustration Rare, Hyper Rare, Mega Hyper Rare,
Ultra Rare, Illustration Rare, Secret Rare, Mega Rare, Double Rare).
If priced_count is BELOW SPARSE_PRICED_THRESHOLD, it merges rarity
candidates INTO existing top_cards (priced entries first by raw_value
desc; rarity additions follow by tier priority, deduped by card
number). Sets that already have a healthy priced leaderboard from
refresh_top_cards.py are untouched — their tail entries would otherwise
get misleading "pricing_pending" tags despite having real prices below
the top-N cutoff.

Each rarity-fallback entry carries `pricing_pending: true` so downstream
consumers can distinguish them from real priced chase cards.

The script then surgically patches /index.html (deployed root, NOT
legacy site/) for every tile whose chase count actually changed.

Usage:
  scripts/fallback_chase_by_rarity.py                # merge across all sets
  scripts/fallback_chase_by_rarity.py me3 me2pt5     # specific sets only
  scripts/fallback_chase_by_rarity.py --no-index     # just data, skip HTML patch
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETS_FILE = ROOT / "data" / "sets.json"
INDEX_FILE = ROOT / "index.html"

# Rarity tiers the user designated as chase-worthy. Match is case-insensitive.
# Order = priority for sorting (most prestigious first).
RARITY_TIERS = [
    "Mega Hyper Rare",
    "Special Illustration Rare",
    "Hyper Rare",
    "Mega Rare",
    "Illustration Rare",
    "Secret Rare",
    "Ultra Rare",
    "Double Rare",   # modern ex/V tier — meaningful cards even without prices
]

# Trigger threshold: only run the rarity merge when a set has fewer than
# this many priced top_cards. Sets that already got a healthy 30+ priced
# leaderboard from refresh_top_cards.py are skipped so we don't tag their
# real-priced tail with misleading "pricing_pending" labels.
SPARSE_PRICED_THRESHOLD = 30
RARITY_PRIORITY = {r.lower(): i for i, r in enumerate(RARITY_TIERS)}
RARITY_LOWERCASE = set(RARITY_PRIORITY)


def fetch_chase_by_rarity(set_id):
    """Fetch all cards in the set whose rarity matches any chase tier."""
    out = []
    page = 1
    while True:
        q = urllib.parse.urlencode({
            "q": f"set.id:{set_id}",
            "pageSize": 250,
            "page": page,
            "select": "id,name,number,rarity,images",
        })
        url = f"https://api.pokemontcg.io/v2/cards?{q}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "pokemon-pack-guide/1.0 (rarity fallback)",
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
            rarity = (c.get("rarity") or "").strip()
            if not rarity:
                continue
            if rarity.lower() not in RARITY_LOWERCASE:
                continue
            out.append({
                "name": c.get("name"),
                "number": c.get("number"),
                "rarity": rarity,
                "image": c.get("images", {}).get("large"),
                "raw_value": 0,
                "psa10_value": 0,
                "grade_worthy": False,
                "pricing_pending": True,
            })
        total = data.get("totalCount", len(out))
        if page * 250 >= total or not cards:
            return out
        page += 1
        time.sleep(0.3)


def sort_by_rarity_then_number(cards):
    def number_key(n):
        if not n:
            return (3, 0, "")
        if n.isdigit():
            return (0, int(n), "")
        m = re.search(r"\d+", n)
        if m:
            return (1, int(m.group()), n)
        return (2, 0, n)

    cards.sort(key=lambda c: (
        RARITY_PRIORITY.get((c.get("rarity") or "").lower(), 99),
        number_key(c.get("number") or ""),
    ))
    return cards


def patch_index_html(updates):
    """Sync the 'N Chase Cards' count in root /index.html to match
    `updates`. Only patches the tiles passed in (i.e. tiles whose count
    actually changed this run). Re-runs are no-ops once everything's in
    sync because callers only pass in changed sets.
    """
    if not INDEX_FILE.exists():
        print(f"  WARNING: {INDEX_FILE} not found; skipping HTML patch", flush=True)
        return 0
    with open(INDEX_FILE) as f:
        html = f.read()

    patched = 0
    skipped_unchanged = 0
    for sid, count in updates.items():
        # Find the <a href="<sid>.html" ...>...</a> tile (DOTALL across newlines)
        tile_re = re.compile(
            rf'(<a\s+href="{re.escape(sid)}\.html"[^>]*>.*?</a>)',
            re.DOTALL,
        )
        m = tile_re.search(html)
        if not m:
            continue
        tile = m.group(1)
        current = re.search(
            r'<div\s+class="set-meta"[^>]*color:\s*#4a9eff[^>]*>\s*(\d+)\s+Chase\s+Cards\s*</div>',
            tile,
        )
        if current and int(current.group(1)) == count:
            skipped_unchanged += 1
            continue
        new_tile, n = re.subn(
            r'(<div\s+class="set-meta"[^>]*color:\s*#4a9eff[^>]*>\s*)\d+(\s+Chase\s+Cards\s*</div>)',
            rf'\g<1>{count}\g<2>',
            tile,
            count=1,
        )
        if n == 0:
            continue
        html = html[:m.start(1)] + new_tile + html[m.end(1):]
        patched += 1

    if patched > 0:
        with open(INDEX_FILE, "w") as f:
            f.write(html)
    print(f"  {patched} tile(s) updated, {skipped_unchanged} already in sync", flush=True)
    return patched


def is_priced(card):
    """A card counts as 'priced' if it has a real raw_value AND isn't a
    pricing_pending placeholder from a prior fallback run."""
    return (card.get("raw_value") or 0) > 0 and not card.get("pricing_pending")


def merge_top_cards(current, rarity_cards):
    """Merge priced top_cards with rarity-tier additions, deduped by `number`.

    Returns (merged_list, priced_count, additions_count). Priced entries lead
    (sorted by raw_value desc), then rarity additions (sorted by tier priority,
    then number).

    Skips the merge entirely when the set already has SPARSE_PRICED_THRESHOLD+
    priced cards — that's a refreshed leaderboard with real chase data, and
    appending pricing_pending entries below the top would mislead users.
    """
    priced = [c for c in current if is_priced(c)]
    priced_n = len(priced)
    rarity_n = len(rarity_cards)
    if priced_n >= SPARSE_PRICED_THRESHOLD:
        return None
    if rarity_n <= priced_n:
        return None
    priced_numbers = {str(c.get("number")) for c in priced if c.get("number") is not None}
    additions = [c for c in rarity_cards if str(c.get("number")) not in priced_numbers]
    sort_by_rarity_then_number(additions)
    priced_sorted = sorted(priced, key=lambda c: -(c.get("raw_value") or 0))
    return priced_sorted + additions, priced_n, len(additions)


def main():
    args = sys.argv[1:]
    skip_index = "--no-index" in args
    only = [a for a in args if not a.startswith("--")] or None

    if not SETS_FILE.exists():
        print(f"ERROR: {SETS_FILE} not found", flush=True)
        sys.exit(1)

    with open(SETS_FILE) as f:
        sets_data = json.load(f)

    targets = []
    for s in sets_data:
        if only and s["id"] not in only:
            continue
        targets.append(s)

    print(f"Auditing {len(targets)} sets for rarity-tier augmentation...", flush=True)
    print()

    updates = {}    # set_id -> new chase count
    changes = []    # list of (set_id, name, old_count, new_count) for reporting
    skipped = 0
    fetch_errors = []

    for i, s in enumerate(targets, 1):
        sid = s["id"]
        rarity_cards = fetch_chase_by_rarity(sid)
        if rarity_cards is None:
            fetch_errors.append(sid)
            print(f"[{i}/{len(targets)}] {sid:<10} fetch error", flush=True)
            time.sleep(0.4)
            continue

        current = s.get("top_cards", [])
        merged_result = merge_top_cards(current, rarity_cards)
        if merged_result is None:
            skipped += 1
            time.sleep(0.4)
            continue

        merged, priced_n, additions_n = merged_result
        old_count = len(current)
        new_count = len(merged)
        s["top_cards"] = merged
        updates[sid] = new_count
        changes.append((sid, s["name"], old_count, new_count, priced_n, additions_n))
        print(
            f"[{i}/{len(targets)}] {sid:<10} {s['name'][:28]:<28}  "
            f"{old_count:>3} -> {new_count:>3}  ({priced_n} priced + {additions_n} rarity)",
            flush=True,
        )
        time.sleep(0.4)

    print()
    print(f"Summary: {len(changes)} merged, {skipped} skipped (already rich enough), "
          f"{len(fetch_errors)} fetch errors", flush=True)
    if fetch_errors:
        print(f"Fetch errors: {', '.join(fetch_errors)}", flush=True)

    if not changes:
        print("Nothing to write.", flush=True)
        return

    with open(SETS_FILE, "w") as f:
        json.dump(sets_data, f, indent=2)
    print(f"Wrote {SETS_FILE}", flush=True)

    if skip_index:
        print("Skipped index.html patch (--no-index)", flush=True)
        return

    print("\nPatching /index.html chase counts for changed tiles...", flush=True)
    patch_index_html(updates)


if __name__ == "__main__":
    main()
