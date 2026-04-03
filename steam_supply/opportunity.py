"""
Steam absorption cooling opportunity analysis for Manhattan.

Connects supply-side data (ConEd steam system spare capacity from plants.py)
with demand-side data (building classifications from steam_dr/) to quantify
how much electric cooling load could shift to steam absorption cooling.

Requires: steam_dr/output/buildings_classified.csv (run steam_dr/run.sh first)
"""

import csv
import os
import sys

# Import plant data from sibling module
sys.path.insert(0, os.path.dirname(__file__))
from plants import compute_system_summary, STATION_SENDOUT

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLASSIFIED_PATH = os.path.join(BASE, "steam_dr", "output", "buildings_classified.csv")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# ── Constants ──

# From 2025 PSC filing (plants.py computes these from actual data)
SYSTEM = compute_system_summary()
SUMMER_SPARE_MLBHR = SYSTEM["summer_spare_capacity_mlbhr"]  # from actual 2025 sendout

# From ConEd filings and Zone J analysis
EXISTING_ABSORPTION_TONS = 625_000      # existing absorption cooling (ConEd FAQ / 2007 Resource Plan)
EXISTING_ABSORPTION_MW = 375            # existing peak electric offset (ConEd estimate)
ZONE_J_SUMMER_PEAK_MW = 10_880          # summer 2025 peak (from zone_j_analysis)

# Absorption chiller parameters
LBS_STEAM_PER_TON_COOLING = 10          # double-effect at 125 psig
ELECTRIC_CHILLER_COP = 5.0             # typical electric centrifugal chiller

# Grid impact parameters
MARGINAL_CO2_TONS_PER_MWH = 0.4        # gas peaker marginal emissions
PEAKER_SIZE_MW = 200                    # typical Zone J peaker
HOURS_PER_SUMMER_PEAK_DAY = 10
PEAK_SUMMER_DAYS = 22 * 4              # ~88 weekdays in Jun-Sep


def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def mw_electric_to_tons_cooling(mw_electric):
    """MW of electric chiller input → tons of cooling output."""
    return mw_electric * 1000 / 3.517 * ELECTRIC_CHILLER_COP


def tons_cooling_to_steam_mlbhr(tons):
    """Tons of cooling → Mlb/hr (thousand lbs/hr) of steam for absorption chillers."""
    return tons * LBS_STEAM_PER_TON_COOLING / 1e3


def load_buildings():
    """Load classified buildings from steam_dr output."""
    if not os.path.exists(CLASSIFIED_PATH):
        print(f"ERROR: {CLASSIFIED_PATH} not found.")
        print("Run steam_dr/run.sh first to generate building classifications.")
        sys.exit(1)

    with open(CLASSIFIED_PATH) as f:
        return list(csv.DictReader(f))


def building_stats(bldgs):
    """Aggregate stats for a list of buildings."""
    return {
        "count": len(bldgs),
        "sqft_m": sum(safe_int(b["sqft"]) for b in bldgs) / 1e6,
        "peak_cooling_mw": sum(safe_int(b["peak_month_cooling_kw"]) for b in bldgs) / 1000,
        "avg_cooling_mw": sum(safe_int(b["avg_summer_cooling_kw"]) for b in bldgs) / 1000,
    }


def evaluate_scenario(name, description, mw_shifted, participation=""):
    """Evaluate a scenario and return results dict."""
    tons_cooling = mw_electric_to_tons_cooling(mw_shifted)
    steam_mlbhr = tons_cooling_to_steam_mlbhr(tons_cooling)
    pct_zone_j = mw_shifted / ZONE_J_SUMMER_PEAK_MW * 100
    peakers = mw_shifted / PEAKER_SIZE_MW
    summer_peak_hours = PEAK_SUMMER_DAYS * HOURS_PER_SUMMER_PEAK_DAY
    co2_tons = mw_shifted * summer_peak_hours * MARGINAL_CO2_TONS_PER_MWH

    fits_spare = steam_mlbhr <= SUMMER_SPARE_MLBHR

    return {
        "name": name,
        "description": description,
        "participation": participation,
        "mw_shifted": mw_shifted,
        "tons_cooling": tons_cooling,
        "steam_mlbhr": steam_mlbhr,
        "pct_spare_used": steam_mlbhr / SUMMER_SPARE_MLBHR * 100,
        "fits_spare": fits_spare,
        "pct_zone_j": pct_zone_j,
        "peakers": peakers,
        "co2_tons": co2_tons,
    }


def print_scenario(s):
    """Print formatted scenario results."""
    print()
    print(f"  {'─' * 74}")
    print(f"  SCENARIO: {s['name']}")
    print(f"  {s['description']}")
    if s["participation"]:
        print(f"  ({s['participation']})")
    print(f"  {'─' * 74}")
    print()
    print(f"    Peak electric demand avoided:     {s['mw_shifted']:>8.0f} MW")
    print(f"    Cooling tons shifted to steam:     {s['tons_cooling']:>8,.0f} tons")
    print(f"    Steam required:                   {s['steam_mlbhr']:>8,.0f} Mlb/hr")
    spare_status = "FITS" if s["fits_spare"] else "EXCEEDS spare capacity"
    print(f"    vs spare capacity ({SUMMER_SPARE_MLBHR:,.0f} Mlb/hr): {spare_status}")
    print(f"    Spare capacity utilization:       {s['pct_spare_used']:>7.0f}%")
    print()
    print(f"    % of Zone J summer peak:          {s['pct_zone_j']:>7.1f}%")
    print(f"    Equivalent peaker plants avoided:  {s['peakers']:>6.1f}  (at {PEAKER_SIZE_MW} MW each)")
    print()
    print(f"    Seasonal CO2 reduction:           {s['co2_tons']:>8,.0f} tons CO2")


def main():
    buildings = load_buildings()
    print(f"Loaded {len(buildings)} classified buildings from steam_dr/output/")

    both = [b for b in buildings if b["classification"] == "BOTH"]
    electric_only = [b for b in buildings if b["classification"] == "ELECTRIC_ONLY"]
    steam_only = [b for b in buildings if b["classification"] == "STEAM_ONLY"]
    unclear = [b for b in buildings if b["classification"] == "UNCLEAR"]

    both_stats = building_stats(both)
    eo_stats = building_stats(electric_only)

    # ── Supply side summary ──

    print()
    print("=" * 78)
    print("SUPPLY SIDE — Con Edison Steam System (2025 PSC Filing)")
    print("=" * 78)
    print()
    print(f"  Rated capacity (ConEd-owned):   {SYSTEM['total_rated_capacity_mlbhr']:>8,} Mlb/hr")
    print(f"  Summer avg utilization:         {SYSTEM['summer_utilization_pct']:>7.1f}%  ({SYSTEM['summer_avg_rate_mlbhr']:,.0f} Mlb/hr)")
    print(f"  Summer spare capacity:          {SUMMER_SPARE_MLBHR:>8,.0f} Mlb/hr")
    print(f"  Cogen share of summer sendout:  {SYSTEM['cogen_pct_summer']:>7.1f}%")

    # ── Demand side summary ──

    print()
    print("=" * 78)
    print("DEMAND SIDE — Building Electric Cooling Load")
    print("=" * 78)
    print()

    for label, bldgs in [("BOTH", both), ("ELECTRIC_ONLY", electric_only),
                          ("STEAM_ONLY", steam_only), ("UNCLEAR", unclear)]:
        s = building_stats(bldgs)
        print(f"  {label:<20}  {s['count']:>4} bldgs  {s['sqft_m']:>7.1f}M sqft  "
              f"Peak cooling: {s['peak_cooling_mw']:>6.1f} MW  "
              f"Avg summer: {s['avg_cooling_mw']:>6.1f} MW")

    print()
    print(f"  Total shiftable electric cooling: {both_stats['peak_cooling_mw'] + eo_stats['peak_cooling_mw']:.0f} MW")

    # ── Scenarios ──

    print()
    print("=" * 78)
    print("SCENARIO ANALYSIS")
    print("=" * 78)

    scenarios = []

    # Scenario 1: BOTH buildings fully shift
    s1 = evaluate_scenario(
        "1 — BOTH buildings fully shift to steam cooling",
        "All buildings with both steam and electric cooling shift 100% of\n"
        "  electric cooling to new/expanded absorption chillers.",
        both_stats["peak_cooling_mw"],
        f"{len(both)} buildings, {both_stats['sqft_m']:.0f}M sqft",
    )
    scenarios.append(s1)
    print_scenario(s1)

    # Scenario 2: 50% of BOTH at 50%
    s2 = evaluate_scenario(
        "2 — 50% of BOTH buildings shift 50% of cooling",
        "Half of dual-system buildings participate, each shifting half.\n"
        "  Realistic near-term target.",
        both_stats["peak_cooling_mw"] * 0.5 * 0.5,
        f"~{len(both)//2} buildings participating",
    )
    scenarios.append(s2)
    print_scenario(s2)

    # Scenario 3: Full buildout
    s3 = evaluate_scenario(
        "3 — All BOTH + ELECTRIC_ONLY shift to steam cooling",
        "Maximum opportunity: all steam customers add/expand absorption\n"
        "  chillers. ELECTRIC_ONLY buildings already have steam pipes.",
        both_stats["peak_cooling_mw"] + eo_stats["peak_cooling_mw"],
        f"{len(both) + len(electric_only)} buildings, "
        f"{both_stats['sqft_m'] + eo_stats['sqft_m']:.0f}M sqft",
    )
    scenarios.append(s3)
    print_scenario(s3)

    # Scenario 3b: Realistic expansion
    s3b_mw = (both_stats["peak_cooling_mw"] * 0.50 * 0.75 +
              eo_stats["peak_cooling_mw"] * 0.25 * 0.50)
    s3b = evaluate_scenario(
        "3b — Realistic expansion",
        "50% of BOTH at 75% shift; 25% of ELECTRIC_ONLY install\n"
        "  absorption chillers covering 50% of cooling.",
        s3b_mw,
        f"~{len(both)//2 + len(electric_only)//4} buildings participating",
    )
    scenarios.append(s3b)
    print_scenario(s3b)

    # ── Comparison table ──

    print()
    print()
    print("=" * 78)
    print("COMPARISON TABLE")
    print("=" * 78)
    print()
    print(f"  {'Scenario':<42} {'MW':>6} {'Steam':>9} {'Spare%':>7} {'%ZoneJ':>7} {'CO2(kt)':>8}")
    print(f"  {'':42s} {'':>6} {'(Mlb/hr)':>9} {'used':>7} {'peak':>7} {'avoided':>8}")
    print(f"  {'─' * 42} {'─'*6} {'─'*9} {'─'*7} {'─'*7} {'─'*8}")

    for s in scenarios:
        print(f"  {s['name'][:42]:<42} {s['mw_shifted']:>6.0f} {s['steam_mlbhr']:>9,.0f} "
              f"{s['pct_spare_used']:>6.0f}% {s['pct_zone_j']:>6.1f}% {s['co2_tons']/1000:>7.0f}")

    print()
    print(f"  Context:")
    print(f"    Existing absorption cooling offsets:  ~{EXISTING_ABSORPTION_MW} MW")
    print(f"    Zone J summer peak:                   {ZONE_J_SUMMER_PEAK_MW/1000:.1f} GW")
    print(f"    Summer spare steam (2025 actual):     {SUMMER_SPARE_MLBHR:,.0f} Mlb/hr")
    print(f"    Cogen summer heat rate:               4 btu/lb (steam is free byproduct)")

    # ── Top buildings ──

    print()
    print("=" * 78)
    print("TOP 15 BUILDINGS — BOTH (low-hanging fruit)")
    print("=" * 78)
    print()
    print(f"  {'Name':<38} {'Type':<14} {'SqFt':>10} {'PeakMW':>7} {'AvgMW':>6}")
    print(f"  {'─'*38} {'─'*14} {'─'*10} {'─'*7} {'─'*6}")

    both_sorted = sorted(both, key=lambda b: -safe_int(b["peak_month_cooling_kw"]))
    for b in both_sorted[:15]:
        print(f"  {b['property_name'][:37]:<38} {b['property_type'][:13]:<14} "
              f"{safe_int(b['sqft']):>10,} "
              f"{safe_int(b['peak_month_cooling_kw'])/1000:>7.1f} "
              f"{safe_int(b['avg_summer_cooling_kw'])/1000:>6.1f}")

    print()
    print("=" * 78)
    print("TOP 15 BUILDINGS — ELECTRIC_ONLY (expansion targets)")
    print("=" * 78)
    print()
    print(f"  {'Name':<38} {'Type':<14} {'SqFt':>10} {'PeakMW':>7} {'AvgMW':>6}")
    print(f"  {'─'*38} {'─'*14} {'─'*10} {'─'*7} {'─'*6}")

    eo_sorted = sorted(electric_only, key=lambda b: -safe_int(b["peak_month_cooling_kw"]))
    for b in eo_sorted[:15]:
        print(f"  {b['property_name'][:37]:<38} {b['property_type'][:13]:<14} "
              f"{safe_int(b['sqft']):>10,} "
              f"{safe_int(b['peak_month_cooling_kw'])/1000:>7.1f} "
              f"{safe_int(b['avg_summer_cooling_kw'])/1000:>6.1f}")

    # ── Key takeaways ──

    print()
    print()
    print("=" * 78)
    print("KEY TAKEAWAYS")
    print("=" * 78)
    print()
    print(f"  1. ConEd's steam system runs at {SYSTEM['summer_utilization_pct']:.0f}% utilization in summer (2025 actual)")
    print(f"     with {SUMMER_SPARE_MLBHR:,.0f} Mlb/hr of spare capacity sitting idle.")
    print()
    print(f"  2. East River cogen produces steam at 4 btu/lb in summer — effectively")
    print(f"     free, since it's a byproduct of electricity generation.")
    print()
    print(f"  3. The realistic scenario (3b) shifts {s3b['mw_shifted']:.0f} MW using "
          f"{s3b['pct_spare_used']:.0f}% of spare")
    print(f"     capacity. Combined with existing {EXISTING_ABSORPTION_MW} MW offset, total = "
          f"~{EXISTING_ABSORPTION_MW + s3b['mw_shifted']:.0f} MW")
    print(f"     ({(EXISTING_ABSORPTION_MW + s3b['mw_shifted'])/ZONE_J_SUMMER_PEAK_MW*100:.1f}% of Zone J peak).")
    print()
    print(f"  4. Full buildout ({s3['mw_shifted']:.0f} MW) uses {s3['pct_spare_used']:.0f}% of spare — "
          f"{'supply-limited' if not s3['fits_spare'] else 'fits within spare'}.")
    print(f"     The opportunity is {'steam-supply-limited' if not s3['fits_spare'] else 'demand-limited'}, "
          f"not {'demand' if not s3['fits_spare'] else 'supply'}-limited.")

    # ── Write output ──

    out_path = os.path.join(OUTPUT_DIR, "scenarios.csv")
    with open(out_path, "w", newline="") as f:
        keys = ["name", "mw_shifted", "steam_mlbhr", "pct_spare_used",
                "fits_spare", "pct_zone_j", "peakers", "co2_tons", "tons_cooling"]
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(scenarios)
    print(f"\n  Written: {out_path}")


if __name__ == "__main__":
    main()
