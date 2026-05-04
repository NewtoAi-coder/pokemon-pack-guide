#!/usr/bin/env python3
"""Inject the analytics tag into every root HTML page.

Idempotent — files that already include the snippet are skipped, so this
is safe to re-run any time. Targets ROOT only (the deployed directory,
served via GitHub Pages); the legacy site/ folder is untouched.

Currently using Cloudflare Web Analytics (free, no cookies, no consent
banner needed). Sign up at cloudflare.com/web-analytics and register
this site to get a token. Replace CF_TOKEN_PLACEHOLDER below with your
real token, then re-run this script — the marker check will skip files
that already have the snippet, so it's safe.

If you change providers, update both ANALYTICS_SNIPPET and
ANALYTICS_MARKER here AND the embedded snippet in
scripts/regenerate_set_pages.py (the per-set page template).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Cloudflare Web Analytics snippet. Token comes from
# cloudflare.com/web-analytics → your site → "JS snippet" tab.
ANALYTICS_SNIPPET = (
    '<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
    'data-cf-beacon=\'{"token":"CF_TOKEN_PLACEHOLDER"}\'></script>'
)
# Stable substring used to detect prior installation (re-run safety).
ANALYTICS_MARKER = "cloudflareinsights.com/beacon"


def inject(path):
    with open(path) as f:
        html = f.read()
    if ANALYTICS_MARKER in html:
        return "skip"
    new_html, n = re.subn(
        r"</head>",
        f"    {ANALYTICS_SNIPPET}\n</head>",
        html,
        count=1,
    )
    if n == 0:
        return "no_head"
    with open(path, "w") as f:
        f.write(new_html)
    return "added"


def main():
    files = sorted(p for p in ROOT.glob("*.html"))
    counts = {"added": 0, "skip": 0, "no_head": 0}
    no_head_files = []
    for p in files:
        result = inject(p)
        counts[result] += 1
        if result == "no_head":
            no_head_files.append(p.name)

    print(f"Files scanned:    {len(files)}")
    print(f"Tag added:        {counts['added']}")
    print(f"Already had tag:  {counts['skip']}")
    print(f"No </head> found: {counts['no_head']}")
    for name in no_head_files:
        print(f"  - {name}")
    if counts["added"] == 0 and counts["skip"] > 0:
        print("\nNothing to do — every page is already instrumented.")
    elif counts["added"] > 0:
        print(
            "\nNOTE: Replace CF_TOKEN_PLACEHOLDER with your real Cloudflare\n"
            "      token (from cloudflare.com/web-analytics) and re-run.\n"
            "      Or sed -i '' 's/CF_TOKEN_PLACEHOLDER/<your-token>/g' *.html"
        )


if __name__ == "__main__":
    main()
