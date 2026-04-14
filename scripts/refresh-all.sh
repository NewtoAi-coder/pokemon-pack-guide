#!/bin/bash
# Complete refresh pipeline: fetch TCG data, enrich with eBay, regenerate site

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/../venv/bin"

echo "==================================="
echo "Pokemon Pack Guide - Full Refresh"
echo "==================================="
echo ""

echo "Step 1/3: Fetching Pokemon TCG API data..."
"$VENV/python3" "$SCRIPT_DIR/fetch-sets-v2.py"

echo ""
echo "Step 2/3: Enriching with eBay sold listings..."
"$VENV/python3" "$SCRIPT_DIR/enrich-ebay.py"

echo ""
echo "Step 3/3: Regenerating HTML site..."
"$VENV/python3" "$SCRIPT_DIR/generate-site.py"

echo ""
echo "✅ Complete! Site refreshed at $(date)"
