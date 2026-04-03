# Con Edison Steam System — Supply-Side Analysis

Plant-level capacity, sendout, and performance data for the Manhattan district
steam system. Quantifies summer spare capacity available for absorption cooling
expansion.

## Data Source

**Con Edison 2025 Steam Annual Capital Report** (Case 22-S-0659)
Filed February 27, 2026 with the NY Public Service Commission.
Joint Proposal Appendix 7, Section A.iii — Steam Plant Availability and
Performance Statistics.

Source PDF: `~/Downloads/2025 Steam Annual Filing - Final.pdf`

## Key Findings

- **Total system capacity:** ~9,995 Mlb/hr (ConEd-owned) + BNYCP contract
- **Annual sendout (2025):** 21.9 billion lbs
- **Summer sendout:** 7.0B lbs (32% of annual)
- **Winter sendout:** 14.9B lbs (68% of annual)
- **Average summer utilization:** ~16% of rated capacity
- **Estimated summer spare capacity:** ~7,000-8,000 Mlb/hr

### What's changed since 2007

- Ravenswood Steam: rated at 0, zero sendout — effectively retired
- Hudson Avenue: no longer appears in reporting — retired
- East River 10 & 20 (cogen): still the workhorse, 42% of total sendout
- BNYCP: 18% of sendout, runs summer and winter
- 59th Street Annex: 73.4% forced outage rate in summer — unreliable

## Usage

```bash
# Encode PSC filing data and compute spare capacity
python plants.py

# Emission factors, cogen allocation, and venting estimates
python emissions.py

# Run opportunity analysis (requires steam_dr/output/buildings_classified.csv)
python opportunity.py

# Generate interactive HTML dashboard
python visualize.py
open output/utilization.html
```

## Structure

```
steam_supply/
├── plants.py       # Plant-level data from 2025 PSC filing
├── emissions.py    # Emission factors, cogen allocation, venting estimates
├── opportunity.py  # Quantify cooling expansion opportunity
├── visualize.py    # Interactive HTML dashboard
├── data/           # Source reference (PSC filing is in ~/Downloads)
└── output/         # CSVs, JSON, and HTML
```
