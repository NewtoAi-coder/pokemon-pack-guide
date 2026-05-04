#!/usr/bin/env python3
"""Regenerate per-set HTML pages at the deployed root.

Why this exists: scripts/generate-site.py writes to the legacy site/
folder; the live deploy reads root (commit 00583ee moved files for
GitHub Pages). When sets.json is updated by enrichment runs, the root
per-set pages stay stale until something rebuilds them.

This script targets ROOT specifically, only writes the sets you ask
about (default: every set whose top_cards contains any pricing_pending
entry — i.e. sets touched by the rarity-tier fallback), and renders
pricing_pending cards without misleading "$0.00" rows. Real priced
cards render exactly the same as the existing per-set pages.

Usage:
  scripts/regenerate_set_pages.py                  # auto-detect affected sets
  scripts/regenerate_set_pages.py me3 me2pt5 sv8   # specific sets only
  scripts/regenerate_set_pages.py --all            # rebuild every set page
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETS_FILE = ROOT / "data" / "sets.json"

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #0a0a0a;
            color: #fff;
            padding: 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        header {{
            text-align: center;
            padding: 40px 0;
            border-bottom: 2px solid #333;
            margin-bottom: 40px;
        }}
        h1 {{ font-size: 2.5rem; margin-bottom: 10px; }}
        .subtitle {{ color: #888; font-size: 1.1rem; }}
        .search-bar {{
            width: 100%;
            max-width: 600px;
            margin: 0 auto 40px;
            padding: 15px 20px;
            font-size: 1rem;
            background: #1a1a1a;
            border: 2px solid #333;
            border-radius: 8px;
            color: #fff;
        }}
        .sets-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 60px;
        }}
        .set-card {{
            background: #1a1a1a;
            border: 2px solid #333;
            border-radius: 12px;
            padding: 20px;
            transition: all 0.3s;
            cursor: pointer;
        }}
        .set-card:hover {{
            border-color: #4a9eff;
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(74, 158, 255, 0.3);
        }}
        .set-logo {{
            width: 100%;
            height: 120px;
            object-fit: contain;
            margin-bottom: 15px;
        }}
        .set-name {{ font-size: 1.3rem; font-weight: 600; margin-bottom: 8px; }}
        .set-meta {{ color: #888; font-size: 0.9rem; margin-bottom: 4px; }}
        .card-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 24px;
            margin-top: 40px;
        }}
        .card-item {{
            background: #1a1a1a;
            border: 2px solid #333;
            border-radius: 12px;
            padding: 16px;
            transition: all 0.3s;
        }}
        .card-item:hover {{
            border-color: #4a9eff;
            transform: scale(1.02);
        }}
        .card-image {{
            width: 100%;
            border-radius: 8px;
            margin-bottom: 12px;
        }}
        .card-name {{ font-size: 1.1rem; font-weight: 600; margin-bottom: 8px; }}
        .price-row {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 6px;
            font-size: 0.95rem;
        }}
        .price-label {{ color: #888; }}
        .price-value {{ font-weight: 600; color: #4a9eff; }}
        .grade-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 0.85rem;
            font-weight: 600;
            margin-top: 8px;
        }}
        .grade-yes {{ background: #28a745; color: #fff; }}
        .grade-no {{ background: #666; color: #ccc; }}
        .pricing-pending-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 500;
            margin-top: 8px;
            background: #2a2a2a;
            color: #aaa;
            border: 1px solid #444;
        }}
        .back-link {{
            display: inline-block;
            margin: 20px 0;
            padding: 10px 20px;
            background: #333;
            color: #fff;
            text-decoration: none;
            border-radius: 6px;
            transition: background 0.3s;
        }}
        .back-link:hover {{ background: #444; }}
    </style>
    <script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{{"token":"12a7741b0e664f26a9670c00d353d038"}}'></script>
</head>
<body>
    <div class="container">

        <a href="index.html" class="back-link">← Back to All Sets</a>
        <a href="binder.html?set={set_id}" class="back-link" style="background:#4a9eff; margin-left: 8px;">📖 Master Set Binder</a>
        <header>
            <h1>{set_name}</h1>
            <p class="subtitle">Released: {release_date} • {series}</p>
            <p class="subtitle">Total Cards: {total_cards}</p>
        </header>
        <h2 style="margin-bottom: 20px; color: #4a9eff;">Top Chase Cards</h2>
        <div class="card-grid">
            {cards_html}
        </div>

    </div>
</body>
</html>
"""


def html_escape(s):
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_card(card):
    """Render a single chase card. Pricing-pending entries get a clean
    layout without misleading $0.00 rows; real priced cards render
    exactly as the existing per-set pages do."""
    name = html_escape(card.get("name", ""))
    number = html_escape(card.get("number", ""))
    rarity = html_escape(card.get("rarity", "N/A"))
    image = html_escape(card.get("image", ""))
    is_pending = bool(card.get("pricing_pending"))

    if is_pending:
        return f"""
        <div class="card-item">
            <img src="{image}" alt="{name}" class="card-image" loading="lazy">
            <div class="card-name">{name} #{number}</div>
            <div class="price-row">
                <span class="price-label">Rarity:</span>
                <span>{rarity}</span>
            </div>
            <span class="pricing-pending-badge">Pricing pending</span>
        </div>
        """

    raw_value = float(card.get("raw_value") or 0)
    psa10_value = float(card.get("psa10_value") or 0)
    grade_class = "grade-yes" if card.get("grade_worthy") else "grade-no"
    grade_text = "Worth Grading" if card.get("grade_worthy") else "Not Worth Grading"
    return f"""
        <div class="card-item">
            <img src="{image}" alt="{name}" class="card-image" loading="lazy">
            <div class="card-name">{name} #{number}</div>
            <div class="price-row">
                <span class="price-label">Raw:</span>
                <span class="price-value">${raw_value:.2f}</span>
            </div>
            <div class="price-row">
                <span class="price-label">PSA 10:</span>
                <span class="price-value">${psa10_value:.2f}</span>
            </div>
            <div class="price-row">
                <span class="price-label">Rarity:</span>
                <span>{rarity}</span>
            </div>
            <span class="grade-badge {grade_class}">{grade_text}</span>
        </div>
        """


def render_set_page(set_data):
    cards = set_data.get("top_cards", [])
    if not cards:
        cards_html = '<p style="color: #888;">No pricing data available for this set.</p>'
    else:
        cards_html = "".join(render_card(c) for c in cards)
    return PAGE_TEMPLATE.format(
        title=f"{html_escape(set_data['name'])} - Pokemon Pack Guide",
        set_id=html_escape(set_data["id"]),
        set_name=html_escape(set_data["name"]),
        release_date=html_escape(set_data.get("release_date", "Unknown")),
        series=html_escape(set_data.get("series", "N/A")),
        total_cards=html_escape(set_data.get("total_cards", "N/A")),
        cards_html=cards_html,
    )


def has_pricing_pending(set_data):
    return any(c.get("pricing_pending") for c in set_data.get("top_cards", []))


def main():
    args = sys.argv[1:]
    do_all = "--all" in args
    only = [a for a in args if not a.startswith("--")] or None

    with open(SETS_FILE) as f:
        sets_data = json.load(f)

    if only:
        wanted = set(only)
        targets = [s for s in sets_data if s["id"] in wanted]
        missing = wanted - {s["id"] for s in targets}
        for m in missing:
            print(f"  WARNING: set '{m}' not in sets.json", flush=True)
    elif do_all:
        targets = sets_data
    else:
        # Default: every set with at least one pricing_pending entry,
        # i.e. sets touched by the rarity-tier fallback.
        targets = [s for s in sets_data if has_pricing_pending(s)]

    if not targets:
        print("No target sets to regenerate.", flush=True)
        return

    print(f"Regenerating {len(targets)} per-set page(s) at root...", flush=True)
    for s in targets:
        out = ROOT / f"{s['id']}.html"
        html = render_set_page(s)
        with open(out, "w") as f:
            f.write(html)
        n_cards = len(s.get("top_cards", []))
        n_pending = sum(1 for c in s.get("top_cards", []) if c.get("pricing_pending"))
        print(
            f"  {s['id']:<10} {s['name'][:30]:<30}  {n_cards:>3} chase cards "
            f"({n_pending} pricing-pending)",
            flush=True,
        )


if __name__ == "__main__":
    main()
