#!/usr/bin/env python3
"""Generate static HTML site from sets data."""

import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "data"
SITE_DIR = Path(__file__).parent.parent / "site"
SITE_DIR.mkdir(exist_ok=True)

HTML_TEMPLATE = """<!DOCTYPE html>
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
</head>
<body>
    <div class="container">
        {content}
    </div>
</body>
</html>
"""

def generate_index(sets_data):
    """Generate main index page."""
    sets_html = []
    
    for set_data in sets_data:
        year = set_data["release_date"][:4] if set_data.get("release_date") else "Unknown"
        logo = set_data.get("set_logo") or set_data.get("set_symbol") or ""
        
        card_html = f"""
        <a href="{set_data['id']}.html" style="text-decoration: none; color: inherit;">
            <div class="set-card">
                <img src="{logo}" alt="{set_data['name']}" class="set-logo" onerror="this.style.display='none'">
                <div class="set-name">{set_data['name']}</div>
                <div class="set-meta">Released: {set_data.get('release_date', 'Unknown')}</div>
                <div class="set-meta">Series: {set_data.get('series', 'N/A')}</div>
                <div class="set-meta">Total Cards: {set_data.get('total_cards', 'N/A')}</div>
                <div class="set-meta" style="color: #4a9eff; margin-top: 8px;">
                    {len(set_data.get('top_cards', []))} Chase Cards
                </div>
            </div>
        </a>
        """
        sets_html.append(card_html)
    
    content = f"""
        <header>
            <h1>🃏 Pokemon Pack Guide</h1>
            <p class="subtitle">Complete set database with chase cards, pricing, and grading info</p>
        </header>
        <input type="text" class="search-bar" id="search" placeholder="Search sets..." onkeyup="filterSets()">
        <div class="sets-grid" id="sets-grid">
            {''.join(sets_html)}
        </div>
        <script>
            function filterSets() {{
                const query = document.getElementById('search').value.toLowerCase();
                const cards = document.querySelectorAll('.set-card');
                cards.forEach(card => {{
                    const text = card.textContent.toLowerCase();
                    card.parentElement.style.display = text.includes(query) ? 'block' : 'none';
                }});
            }}
        </script>
    """
    
    html = HTML_TEMPLATE.format(title="Pokemon Pack Guide", content=content)
    
    output = SITE_DIR / "index.html"
    with open(output, "w") as f:
        f.write(html)
    
    print(f"✅ Generated index.html")

def generate_set_page(set_data):
    """Generate individual set page."""
    cards_html = []
    
    for card in set_data.get("top_cards", []):
        grade_class = "grade-yes" if card.get("grade_worthy") else "grade-no"
        grade_text = "Worth Grading" if card.get("grade_worthy") else "Not Worth Grading"
        
        card_html = f"""
        <div class="card-item">
            <img src="{card.get('image', '')}" alt="{card.get('name')}" class="card-image" loading="lazy">
            <div class="card-name">{card.get('name')} #{card.get('number')}</div>
            <div class="price-row">
                <span class="price-label">Raw:</span>
                <span class="price-value">${card.get('raw_value', 0):.2f}</span>
            </div>
            <div class="price-row">
                <span class="price-label">PSA 10:</span>
                <span class="price-value">${card.get('psa10_value', 0):.2f}</span>
            </div>
            <div class="price-row">
                <span class="price-label">Rarity:</span>
                <span>{card.get('rarity', 'N/A')}</span>
            </div>
            <span class="grade-badge {grade_class}">{grade_text}</span>
        </div>
        """
        cards_html.append(card_html)
    
    content = f"""
        <a href="index.html" class="back-link">← Back to All Sets</a>
        <header>
            <h1>{set_data['name']}</h1>
            <p class="subtitle">Released: {set_data.get('release_date', 'Unknown')} • {set_data.get('series', 'N/A')}</p>
            <p class="subtitle">Total Cards: {set_data.get('total_cards', 'N/A')}</p>
        </header>
        <h2 style="margin-bottom: 20px; color: #4a9eff;">Top Chase Cards</h2>
        <div class="card-grid">
            {''.join(cards_html) if cards_html else '<p style="color: #888;">No pricing data available for this set.</p>'}
        </div>
    """
    
    html = HTML_TEMPLATE.format(title=f"{set_data['name']} - Pokemon Pack Guide", content=content)
    
    output = SITE_DIR / f"{set_data['id']}.html"
    with open(output, "w") as f:
        f.write(html)

def main():
    """Main execution."""
    sets_file = DATA_DIR / "sets.json"
    
    if not sets_file.exists():
        print("❌ sets.json not found. Run fetch-sets.py first.")
        return
    
    with open(sets_file) as f:
        sets_data = json.load(f)
    
    print(f"Generating site for {len(sets_data)} sets...")
    
    # Generate index
    generate_index(sets_data)
    
    # Generate set pages
    for idx, set_data in enumerate(sets_data, 1):
        print(f"  [{idx}/{len(sets_data)}] {set_data['name']}")
        generate_set_page(set_data)
    
    print(f"\n✅ Site generated at {SITE_DIR}")
    print(f"   Open {SITE_DIR}/index.html in your browser")

if __name__ == "__main__":
    main()
