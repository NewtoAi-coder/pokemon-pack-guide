import requests, base64, os

with open(os.path.expanduser('~/.openclaw/workspace/.env.ebay')) as f:
    creds = {}
    for line in f:
        if '=' in line and not line.startswith('#'):
            k, v = line.strip().split('=', 1)
            creds[k.strip()] = v.strip().strip('"\'')

auth = base64.b64encode(f'{creds["EBAY_APP_ID"]}:{creds["EBAY_CERT_ID"]}'.encode()).decode()
r = requests.post('https://api.ebay.com/identity/v1/oauth2/token',
    headers={'Content-Type': 'application/x-www-form-urlencoded', 'Authorization': f'Basic {auth}'},
    data={'grant_type': 'client_credentials', 'scope': 'https://api.ebay.com/oauth/api_scope'}, timeout=15)
token = r.json()['access_token']

queries = [
    'pokemon Ascended Heroes booster box 36 sealed',
    'pokemon Surging Sparks booster box 36 sealed',
    'pokemon Obsidian Flames booster box sealed',
    'pokemon Temporal Forces booster box sealed',
]

for query in queries:
    r2 = requests.get('https://api.ebay.com/buy/browse/v1/item_summary/search',
        headers={'Authorization': f'Bearer {token}', 'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'},
        params={
            'q': query,
            'filter': 'buyingOptions:{FIXED_PRICE},price:[80..300],priceCurrency:USD',
            'sort': 'price',
            'limit': 10,
        }, timeout=20)

    items = r2.json().get('itemSummaries', [])
    for item in items:
        ttl = item.get('title', '')
        tl = ttl.lower()
        if 'korean' in tl or 'chinese' in tl or 'japanese' in tl or 'japan' in tl:
            continue
        if 'booster' not in tl and 'box' not in tl:
            continue

        price = float(item.get('price', {}).get('value', 0))
        seller = item.get('seller', {})
        fb_pct = seller.get('feedbackPercentage', '0')
        fb_score = seller.get('feedbackScore', 0)
        url = item.get('itemWebUrl', '')
        shipping = item.get('shippingOptions', [{}])
        ship_cost = float(shipping[0].get('shippingCost', {}).get('value', 0)) if shipping else 0
        top_rated = seller.get('topRatedSeller', False)

        if fb_score >= 100 and float(fb_pct) >= 97:
            total = price + ship_cost
            badge = 'TOP RATED' if top_rated else 'TRUSTED'
            print(f'{badge} | ${total:.2f} | {fb_score} fb ({fb_pct}%)')
            print(f'  {ttl[:90]}')
            print(f'  {url}')
            print()
