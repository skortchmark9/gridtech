"""
Fetch all required datasets from NYC Open Data.

Datasets:
  1. LL84 Energy Benchmarking (annual) — buildings >25k sqft with energy data
  2. LL84 Monthly Electricity — monthly electric consumption by building
  3. DOHMH Cooling Tower Registry — buildings with registered cooling towers
"""

import json
import subprocess
import sys
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)


def fetch(url, output_file, description):
    path = os.path.join(DATA_DIR, output_file)
    if os.path.exists(path):
        data = json.load(open(path))
        print(f"  {description}: {len(data)} records (cached)")
        return
    print(f"  Fetching {description}...")
    subprocess.run(["curl", "-s", url, "-o", path], check=True)
    data = json.load(open(path))
    print(f"  {description}: {len(data)} records")


def fetch_chunked(base_url, output_file, description, chunk_size=50000):
    """Download large datasets in parallel chunks."""
    path = os.path.join(DATA_DIR, output_file)
    if os.path.exists(path):
        data = json.load(open(path))
        print(f"  {description}: {len(data)} records (cached)")
        return

    print(f"  Fetching {description} in chunks...")

    # First get total count
    count_url = base_url.split("?")[0] + "?" + "&".join(
        p for p in base_url.split("?")[1].split("&")
        if "$select" not in p and "$limit" not in p and "$offset" not in p
    ) + "&$select=count(*)"
    count_file = os.path.join(DATA_DIR, "_count.json")
    subprocess.run(["curl", "-s", count_url, "-o", count_file], check=True)
    total = int(json.load(open(count_file))[0]["count"])
    os.remove(count_file)

    n_chunks = (total // chunk_size) + 1
    chunk_files = []

    # Download chunks in parallel
    procs = []
    for i in range(n_chunks):
        offset = i * chunk_size
        chunk_path = os.path.join(DATA_DIR, f"_chunk_{i}.json")
        chunk_files.append(chunk_path)
        url = f"{base_url}&$limit={chunk_size}&$offset={offset}"
        proc = subprocess.Popen(["curl", "-s", url, "-o", chunk_path])
        procs.append(proc)

    for proc in procs:
        proc.wait()

    # Combine
    all_rows = []
    for cf in chunk_files:
        all_rows.extend(json.load(open(cf)))
        os.remove(cf)

    json.dump(all_rows, open(path, "w"))
    print(f"  {description}: {len(all_rows)} records")


print("Fetching NYC Open Data...")

# 1. LL84 annual data — steam buildings with energy + electricity fields
fetch(
    "https://data.cityofnewyork.us/resource/5zyy-y8am.json?"
    "$where=district_steam_use_kbtu%20!=%20%27Not%20Available%27"
    "%20AND%20district_steam_use_kbtu%20%3E%20%270%27&"
    "$select=property_id,property_name,address_1,city,borough,"
    "primary_property_type_self,property_gfa_self_reported,"
    "district_steam_use_kbtu,district_chilled_water_use,"
    "site_energy_use_kbtu,electricity_use_grid_purchase,"
    "electricity_use_grid_purchase_1,natural_gas_use_kbtu,"
    "nyc_borough_block_and_lot,nyc_building_identification,"
    "latitude,longitude,report_year,site_eui_kbtu_ft&"
    "$order=district_steam_use_kbtu%20DESC&$limit=5000",
    "ll84_annual.json",
    "LL84 annual steam buildings",
)

# 2. LL84 monthly electricity data (2024)
fetch_chunked(
    "https://data.cityofnewyork.us/resource/fvp3-gcb2.json?"
    "$where=calendar_year=%272024%27",
    "ll84_monthly_2024.json",
    "LL84 monthly electricity (2024)",
)

# 3. Cooling tower registry
fetch(
    "https://data.cityofnewyork.us/resource/y4fw-iqfr.json?"
    "$select=bin,bbl,address,borough,activeequipment,latitude,longitude"
    "&$limit=50000",
    "cooling_towers.json",
    "DOHMH cooling tower registry",
)

print("\nDone. Data saved to data/")
