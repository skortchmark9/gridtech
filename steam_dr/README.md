# NYC Steam Chiller DR Potential

Identifies large NYC buildings that can do summertime demand response by switching
between steam and electric chillers.

## Data Sources

All from [NYC Open Data](https://data.cityofnewyork.us):

- **LL84 Energy Benchmarking** — annual energy data for buildings >25k sqft
  (dataset `5zyy-y8am`)
- **LL84 Monthly Electricity** — monthly electric consumption
  (dataset `fvp3-gcb2`)
- **DOHMH Cooling Tower Registry** — registered cooling towers by building
  (dataset `y4fw-iqfr`)

## Classification Method

Buildings are classified into four categories based on observable evidence:

| Class | Meaning | Evidence |
|-------|---------|----------|
| **BOTH** | Steam + electric cooling (DR ready) | Steam intensity >1.5x heating baseline AND summer electricity >15% above winter |
| **STEAM_ONLY** | Steam cooling, minimal electric | High steam intensity, no summer electric bump |
| **ELECTRIC_ONLY** | Electric cooling, steam for heating | Summer electric bump, but steam near heating-only levels |
| **UNCLEAR** | Insufficient data | Can't confidently classify |

**Steam cooling evidence:** Steam intensity (kBtu/sqft) compared to the 25th percentile
for the same building type. The 25th percentile approximates heating-only buildings.
Buildings >1.5x this baseline are likely using steam for cooling too.

**Electric cooling evidence:** Monthly electricity data from 2024. Winter months
(Dec/Jan/Feb) establish a non-cooling baseline. Summer months (Jun-Sep) above
this baseline = electric cooling load. Threshold: >15% increase AND >1 kBtu/sqft.

## Usage

```bash
pip install folium
./run.sh
open output/map.html
```

## Output

- `output/buildings_classified.csv` — all steam buildings with classification
- `output/dr_ready.csv` — buildings with both steam + electric cooling
- `output/map.html` — interactive map

## Structure

```
steam_dr/
├── fetch_data.py    # Download datasets from NYC Open Data
├── classify.py      # Classify buildings + compute DR potential
├── make_map.py      # Generate interactive map
├── run.sh           # Run full pipeline
├── data/            # Raw downloaded data (gitignored)
└── output/          # CSVs and map
```
