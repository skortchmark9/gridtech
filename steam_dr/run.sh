#!/bin/bash
# Fetch data, classify buildings, and generate map.
# Usage: ./run.sh
# Requires: python3 with folium installed (pip install folium)

set -e
cd "$(dirname "$0")"

echo "=== Step 1: Fetch data ==="
python3 fetch_data.py

echo ""
echo "=== Step 2: Classify buildings ==="
python3 classify.py

echo ""
echo "=== Step 3: Generate map ==="
python3 make_map.py

echo ""
echo "Done. Open output/map.html to view."
