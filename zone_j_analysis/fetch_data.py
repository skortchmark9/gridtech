"""
Download generation and load data for NYISO Zone J (NYC), summer 2025.

Data sources:
  1. EPA CAMPD bulk emissions — hourly unit-level fossil generation for NY state
  2. NYISO zonal load (PAL) — 5-min actual load by zone
  3. NYISO real-time fuel mix — 5-min system-wide generation by fuel category

Requires EPA_API_KEY in .env (register at https://www.epa.gov/power-sector/cam-api-portal).
NYISO data is freely available without authentication.

Usage:
    python fetch_data.py
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
EPA_API_KEY = os.environ.get("EPA_API_KEY", "DEMO_KEY")


def download_file(url, dest, description=""):
    """Download a file with progress, skip if already cached."""
    if os.path.exists(dest):
        size_mb = os.path.getsize(dest) / (1024 * 1024)
        print(f"  Cached: {dest} ({size_mb:.1f}MB)")
        return

    print(f"  Downloading {description or url}...")
    resp = requests.get(url, timeout=600, stream=True)
    resp.raise_for_status()

    downloaded = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
            downloaded += len(chunk)
            if downloaded % (50 * 1024 * 1024) < 65536:
                print(f"    {downloaded // (1024 * 1024)}MB...")

    size_mb = os.path.getsize(dest) / (1024 * 1024)
    print(f"    Done: {size_mb:.1f}MB")


def fetch_campd():
    """Download EPA CAMPD hourly emissions bulk file for NY 2025."""
    print("\n[1/3] EPA CAMPD — NY hourly emissions 2025")
    url = (
        f"https://api.epa.gov/easey/bulk-files/"
        f"emissions/hourly/state/emissions-hourly-2025-ny.csv"
        f"?api_key={EPA_API_KEY}"
    )
    download_file(url, os.path.join(DATA_DIR, "emissions-hourly-2025-ny.csv"),
                  "emissions-hourly-2025-ny.csv (~412MB)")


def fetch_nyiso_load():
    """Download NYISO real-time actual load (PAL) monthly zips for Jun-Aug 2025."""
    print("\n[2/3] NYISO — Zonal load (PAL), Jun-Aug 2025")
    for month in ["20250601", "20250701", "20250801"]:
        filename = f"{month}pal_csv.zip"
        url = f"http://mis.nyiso.com/public/csv/pal/{filename}"
        download_file(url, os.path.join(DATA_DIR, "nyiso", filename), filename)


def fetch_nyiso_fuel_mix():
    """Download NYISO real-time fuel mix monthly zips for Jun-Aug 2025."""
    print("\n[3/3] NYISO — System fuel mix, Jun-Aug 2025")
    for month in ["20250601", "20250701", "20250801"]:
        filename = f"{month}rtfuelmix_csv.zip"
        url = f"http://mis.nyiso.com/public/csv/rtfuelmix/{filename}"
        download_file(url, os.path.join(DATA_DIR, "nyiso", filename), filename)


def main():
    os.makedirs(os.path.join(DATA_DIR, "nyiso"), exist_ok=True)

    print("Fetching data for NYISO Zone J analysis, Summer 2025")
    print("=" * 55)

    fetch_campd()
    fetch_nyiso_load()
    fetch_nyiso_fuel_mix()

    print("\n" + "=" * 55)
    print("All data downloaded. Run visualize.py to generate charts.")


if __name__ == "__main__":
    main()
