# Zone J (NYC) Generation Analysis — Summer 2025

Which generators ran to serve NYISO Zone J (New York City) in summer 2025?

Combines three public data sources:
1. **EPA CAMPD** — hourly unit-level fossil generation for NYC plants
2. **NYISO zonal load (PAL)** — 5-min actual demand by zone
3. **NYISO fuel mix** — 5-min system-wide generation by fuel category

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Register for a free EPA API key at https://www.epa.gov/power-sector/cam-api-portal and add it to a `.env` file in the project root:

```
EPA_API_KEY=your_key_here
```

## Usage

```bash
# 1. Download data (~415MB total, cached after first run)
python fetch_data.py

# 2. Generate charts
python visualize.py                  # default: zone_j_summer_2025.png
python visualize.py custom_name.png  # custom output
```

## Key findings

- Zone J peak demand: **10.88 GW** (June 25, 2025)
- In-zone fossil generation covered **49%** of summer load (7,480 of 15,301 GWh)
- The other **51%** came from imports and non-fossil sources
- Estimated fuel mix serving Zone J (pro-rated from NYCA): ~60% gas, ~19% nuclear, ~16% hydro, ~5% renewables
- 18 active fossil plants in NYC, dominated by Astoria Energy, Astoria Generating Station, Ravenswood, and Poletti

## Caveats

- Fuel mix pro-rating assumes Zone J consumes the same mix as the rest of NYCA. In reality NYC is disproportionately served by gas and imports.
- EPA CAMPD covers fossil plants only — solar, wind, battery storage, and behind-the-meter generation are not included.
- "Dual Fuel" in NYISO data means plants that can burn gas or oil; they almost always run on gas.
