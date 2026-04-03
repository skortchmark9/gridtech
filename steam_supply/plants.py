"""
Con Edison steam system plant-level data — 2025 actuals.

Source: Case 22-S-0659, 2025 Steam Annual Capital Report
        Joint Proposal Appendix 7, Section A.iii
        Filed February 27, 2026 with NY PSC.

Data extracted from:
  Exhibit 1 — Forced Outage Rate (plant availability + unit ratings)
  Exhibit 2 — Station Performance (heat rates + sendout by season)
"""

import csv
import json
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════════
# UNIT-LEVEL DATA (Exhibit 1)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Steam ratings are from Exhibit 1 footnotes.
# FOR = Forced Outage Rate = Forced Outage Hours / (Forced Outage Hours + Service Hours) x 100
# Summer FOR: May 1 - October 31
# Winter FOR: January 1 - April 30 and November 1 - December 31

LARGE_BOILERS = [
    {
        "unit": "East River 1/10",
        "station": "East River",
        "type": "cogen_ct_hrsg",
        "steam_rating_mlbhr": 1600,
        "summer_for_pct": 1.9,
        "winter_for_pct": 0.6,
        "annual_for_pct": 1.3,
        "notes": "GE 7FA.04 combustion turbine + HRSG with duct burners",
    },
    {
        "unit": "East River 2/20",
        "station": "East River",
        "type": "cogen_ct_hrsg",
        "steam_rating_mlbhr": 1600,
        "summer_for_pct": 1.9,
        "winter_for_pct": 0.6,
        "annual_for_pct": 1.3,
        "notes": "GE 7FA.04 combustion turbine + HRSG with duct burners",
    },
    {
        "unit": "East River 6/60",
        "station": "East River",
        "type": "boiler_steam_only",
        "steam_rating_mlbhr": 830,
        "summer_for_pct": 1.9,
        "winter_for_pct": 0.6,
        "annual_for_pct": 1.3,
        "notes": "Natural circulation boiler, extraction mode cogen capable. Zero summer sendout in 2025.",
    },
    {
        "unit": "East River 7/70",
        "station": "East River",
        "type": "boiler_steam_only",
        "steam_rating_mlbhr": 1200,
        "summer_for_pct": 1.9,
        "winter_for_pct": 0.6,
        "annual_for_pct": 1.3,
        "notes": "Runs electric-only in summer, steam-only boiler in winter. Converted to steam sendout 1995.",
    },
    {
        "unit": "59th Street Annex Boiler A",
        "station": "59th Street",
        "type": "boiler_hp",
        "steam_rating_mlbhr": 500,
        "summer_for_pct": 73.4,
        "winter_for_pct": 16.6,
        "annual_for_pct": 34.7,
        "notes": "High forced outage rate, especially in summer.",
    },
    {
        "unit": "59th Street Annex Boiler B",
        "station": "59th Street",
        "type": "boiler_hp",
        "steam_rating_mlbhr": 500,
        "summer_for_pct": 73.4,
        "winter_for_pct": 16.6,
        "annual_for_pct": 34.7,
        "notes": "High forced outage rate, especially in summer.",
    },
    {
        "unit": "74th Street HP Boiler 1",
        "station": "74th Street",
        "type": "boiler_hp",
        "steam_rating_mlbhr": 433,
        "summer_for_pct": 0.0,
        "winter_for_pct": 0.1,
        "annual_for_pct": 0.1,
        "notes": "Very reliable. Three HP boilers at 433 Mlb/hr each.",
    },
    {
        "unit": "74th Street HP Boiler 2",
        "station": "74th Street",
        "type": "boiler_hp",
        "steam_rating_mlbhr": 433,
        "summer_for_pct": 0.0,
        "winter_for_pct": 0.1,
        "annual_for_pct": 0.1,
        "notes": "Very reliable.",
    },
    {
        "unit": "74th Street HP Boiler 3",
        "station": "74th Street",
        "type": "boiler_hp",
        "steam_rating_mlbhr": 433,
        "summer_for_pct": 0.0,
        "winter_for_pct": 0.1,
        "annual_for_pct": 0.1,
        "notes": "Very reliable.",
    },
]

PACKAGE_BOILERS = [
    {
        "unit": "East River South Package",
        "station": "East River",
        "type": "package_boiler",
        "steam_rating_mlbhr": 650,
        "summer_for_pct": 2.8,
        "winter_for_pct": 0.0,
        "annual_for_pct": 0.7,
        "notes": "5 package boilers, 130 Mlb/hr each.",
    },
    {
        "unit": "Ravenswood Steam",
        "station": "Ravenswood",
        "type": "package_boiler",
        "steam_rating_mlbhr": 0,
        "summer_for_pct": 0.0,
        "winter_for_pct": 0.0,
        "annual_for_pct": 0.0,
        "notes": "Rated at 0. Effectively retired — zero sendout all year.",
    },
    {
        "unit": "59th Street Package",
        "station": "59th Street",
        "type": "package_boiler",
        "steam_rating_mlbhr": 381,
        "summer_for_pct": 0.0,
        "winter_for_pct": 0.0,
        "annual_for_pct": 0.0,
        "notes": "3 package boilers.",
    },
    {
        "unit": "60th Street Package",
        "station": "60th Street",
        "type": "package_boiler",
        "steam_rating_mlbhr": 726,
        "summer_for_pct": 0.0,
        "winter_for_pct": 1.1,
        "annual_for_pct": 0.9,
        "notes": "6 package boilers, burn natural gas or distillate oil.",
    },
    {
        "unit": "74th Street Package",
        "station": "74th Street",
        "type": "package_boiler",
        "steam_rating_mlbhr": 708,
        "summer_for_pct": 4.0,
        "winter_for_pct": 0.3,
        "annual_for_pct": 1.1,
        "notes": "6 package boilers.",
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
# STATION-LEVEL SENDOUT AND HEAT RATE (Exhibit 2)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Sendout in Mlb (thousand pounds).
# Heat Rate = High Heating Value of Fuel Burned (btu) / Net Steam Sendout (lb)
# Summer: May 1 - October 31
# Winter: January 1 - April 30 and November 1 - December 31
# BNYCP heat rate reported as 0 because ConEd doesn't burn fuel there (contract purchase).

STATION_SENDOUT = [
    {
        "station_group": "East River 60 Extraction Station",
        "station": "East River",
        "summer_sendout_mlb": 0,
        "winter_sendout_mlb": 968_114,
        "annual_sendout_mlb": 968_114,
        "summer_heat_rate_btu_lb": 0,
        "winter_heat_rate_btu_lb": 1185,
        "annual_heat_rate_btu_lb": 1185,
        "notes": "Winter-only operation. Extraction steam turbine.",
    },
    {
        "station_group": "East River 10 and 20",
        "station": "East River",
        "summer_sendout_mlb": 4_485_774,
        "winter_sendout_mlb": 4_753_649,
        "annual_sendout_mlb": 9_239_423,
        "summer_heat_rate_btu_lb": 4,
        "winter_heat_rate_btu_lb": 31,
        "annual_heat_rate_btu_lb": 20,
        "notes": "Primary cogen. 4 btu/lb summer = steam is nearly free byproduct of electric generation.",
    },
    {
        "station_group": "East River Boiler 70 (Steam Only)",
        "station": "East River",
        "summer_sendout_mlb": 0,
        "winter_sendout_mlb": 394_022,
        "annual_sendout_mlb": 394_022,
        "summer_heat_rate_btu_lb": 0,
        "winter_heat_rate_btu_lb": 1640,
        "annual_heat_rate_btu_lb": 1640,
        "notes": "Winter-only steam boiler mode. Electric-only in summer.",
    },
    {
        "station_group": "East River Boiler 60 (Steam Only)",
        "station": "East River",
        "summer_sendout_mlb": 0,
        "winter_sendout_mlb": 0,
        "annual_sendout_mlb": 0,
        "summer_heat_rate_btu_lb": 0,
        "winter_heat_rate_btu_lb": 0,
        "annual_heat_rate_btu_lb": 0,
        "notes": "Zero sendout all year. May be offline/reserve.",
    },
    {
        "station_group": "East River South Steam Package",
        "station": "East River",
        "summer_sendout_mlb": 170_685,
        "winter_sendout_mlb": 643_517,
        "annual_sendout_mlb": 814_202,
        "summer_heat_rate_btu_lb": 1523,
        "winter_heat_rate_btu_lb": 1452,
        "annual_heat_rate_btu_lb": 1463,
        "notes": "5 package boilers at 130 Mlb/hr each.",
    },
    {
        "station_group": "59th Street Annex",
        "station": "59th Street",
        "summer_sendout_mlb": 155_684,
        "winter_sendout_mlb": 1_514_005,
        "annual_sendout_mlb": 1_669_689,
        "summer_heat_rate_btu_lb": 1555,
        "winter_heat_rate_btu_lb": 1514,
        "annual_heat_rate_btu_lb": 1518,
        "notes": "2 HP annex boilers at 500 Mlb/hr each. 73% summer FOR.",
    },
    {
        "station_group": "59th Street Package",
        "station": "59th Street",
        "summer_sendout_mlb": 86_384,
        "winter_sendout_mlb": 265_737,
        "annual_sendout_mlb": 352_121,
        "summer_heat_rate_btu_lb": 1363,
        "winter_heat_rate_btu_lb": 1447,
        "annual_heat_rate_btu_lb": 1426,
        "notes": "3 package boilers.",
    },
    {
        "station_group": "Ravenswood Steam",
        "station": "Ravenswood",
        "summer_sendout_mlb": 0,
        "winter_sendout_mlb": 0,
        "annual_sendout_mlb": 0,
        "summer_heat_rate_btu_lb": 0,
        "winter_heat_rate_btu_lb": 0,
        "annual_heat_rate_btu_lb": 0,
        "notes": "Retired. Zero sendout, zero rating.",
    },
    {
        "station_group": "74th Street High Pressure",
        "station": "74th Street",
        "summer_sendout_mlb": 340_819,
        "winter_sendout_mlb": 2_726_992,
        "annual_sendout_mlb": 3_067_811,
        "summer_heat_rate_btu_lb": 1551,
        "winter_heat_rate_btu_lb": 1512,
        "annual_heat_rate_btu_lb": 1516,
        "notes": "3 HP boilers at 433 Mlb/hr each. Very reliable (0.1% FOR).",
    },
    {
        "station_group": "74th Street Package",
        "station": "74th Street",
        "summer_sendout_mlb": 126_068,
        "winter_sendout_mlb": 504_195,
        "annual_sendout_mlb": 630_263,
        "summer_heat_rate_btu_lb": 1810,
        "winter_heat_rate_btu_lb": 1658,
        "annual_heat_rate_btu_lb": 1654,
        "notes": "6 package boilers.",
    },
    {
        "station_group": "60th Street Package",
        "station": "60th Street",
        "summer_sendout_mlb": 195_086,
        "winter_sendout_mlb": 612_977,
        "annual_sendout_mlb": 808_063,
        "summer_heat_rate_btu_lb": 1392,
        "winter_heat_rate_btu_lb": 1425,
        "annual_heat_rate_btu_lb": 1417,
        "notes": "6 package boilers, natural gas or distillate oil.",
    },
    {
        "station_group": "BNYCP",
        "station": "Brooklyn Navy Yard",
        "summer_sendout_mlb": 1_407_801,
        "winter_sendout_mlb": 2_554_012,
        "annual_sendout_mlb": 3_961_813,
        "summer_heat_rate_btu_lb": 0,
        "winter_heat_rate_btu_lb": 0,
        "annual_heat_rate_btu_lb": 0,
        "notes": "Third-party cogen (Axium Infrastructure). Heat rate 0 = ConEd purchases steam, doesn't burn fuel.",
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

# EPA CAMPD facility IDs for cross-referencing with electric generation data
EPA_FACILITY_IDS = {
    "East River": 2493,
    "59th Street": 2503,
    "74th Street": 2504,
    "Brooklyn Navy Yard": 54914,
}

# Summer = May 1 - Oct 31 (184 days), Winter = Jan 1 - Apr 30 + Nov 1 - Dec 31 (181 days)
SUMMER_DAYS = 184
WINTER_DAYS = 181
SUMMER_HOURS = SUMMER_DAYS * 24
WINTER_HOURS = WINTER_DAYS * 24


def compute_system_summary():
    """Compute aggregate system statistics from the plant data."""
    all_units = LARGE_BOILERS + PACKAGE_BOILERS

    total_rating = sum(u["steam_rating_mlbhr"] for u in all_units)
    coned_rating = total_rating  # all units are ConEd-owned

    summer_total = sum(s["summer_sendout_mlb"] for s in STATION_SENDOUT)
    winter_total = sum(s["winter_sendout_mlb"] for s in STATION_SENDOUT)
    annual_total = sum(s["annual_sendout_mlb"] for s in STATION_SENDOUT)

    # Average sendout rates (Mlb/hr)
    summer_avg_rate = summer_total / SUMMER_HOURS
    winter_avg_rate = winter_total / WINTER_HOURS

    # Spare capacity = rated capacity - average utilization
    summer_spare = total_rating - summer_avg_rate
    winter_spare = total_rating - winter_avg_rate

    # Cogen vs boiler sendout
    cogen_groups = {"East River 10 and 20", "BNYCP"}
    cogen_annual = sum(
        s["annual_sendout_mlb"] for s in STATION_SENDOUT
        if s["station_group"] in cogen_groups
    )
    cogen_summer = sum(
        s["summer_sendout_mlb"] for s in STATION_SENDOUT
        if s["station_group"] in cogen_groups
    )

    return {
        "total_rated_capacity_mlbhr": total_rating,
        "summer_sendout_mlb": summer_total,
        "winter_sendout_mlb": winter_total,
        "annual_sendout_mlb": annual_total,
        "summer_avg_rate_mlbhr": round(summer_avg_rate, 0),
        "winter_avg_rate_mlbhr": round(winter_avg_rate, 0),
        "summer_spare_capacity_mlbhr": round(summer_spare, 0),
        "winter_spare_capacity_mlbhr": round(winter_spare, 0),
        "summer_utilization_pct": round(summer_avg_rate / total_rating * 100, 1),
        "winter_utilization_pct": round(winter_avg_rate / total_rating * 100, 1),
        "cogen_pct_annual": round(cogen_annual / annual_total * 100, 1),
        "cogen_pct_summer": round(cogen_summer / summer_total * 100, 1),
    }


def print_summary():
    """Print a formatted summary of the steam system."""
    summary = compute_system_summary()

    print("=" * 78)
    print("CON EDISON STEAM SYSTEM — 2025 PLANT DATA")
    print("Source: Case 22-S-0659, 2025 Steam Annual Capital Report (Feb 2026)")
    print("=" * 78)

    # Station sendout table
    print("\n  STATION SENDOUT (2025)")
    print(f"  {'Station Group':<36} {'Summer':>10} {'Winter':>10} {'Annual':>10} {'S/W':>6} {'HeatRate':>9}")
    print(f"  {'':36s} {'(Mlb)':>10} {'(Mlb)':>10} {'(Mlb)':>10} {'ratio':>6} {'(btu/lb)':>9}")
    print(f"  {'─'*36} {'─'*10} {'─'*10} {'─'*10} {'─'*6} {'─'*9}")

    for s in STATION_SENDOUT:
        if s["annual_sendout_mlb"] == 0 and s["summer_sendout_mlb"] == 0:
            ratio_str = "—"
        elif s["winter_sendout_mlb"] == 0:
            ratio_str = "∞"
        else:
            ratio_str = f"{s['summer_sendout_mlb'] / s['winter_sendout_mlb']:.2f}"

        hr = s["annual_heat_rate_btu_lb"]
        hr_str = f"{hr:,}" if hr > 0 else "n/a"

        print(f"  {s['station_group']:<36} "
              f"{s['summer_sendout_mlb']:>10,} "
              f"{s['winter_sendout_mlb']:>10,} "
              f"{s['annual_sendout_mlb']:>10,} "
              f"{ratio_str:>6} "
              f"{hr_str:>9}")

    total_summer = summary["summer_sendout_mlb"]
    total_winter = summary["winter_sendout_mlb"]
    total_annual = summary["annual_sendout_mlb"]
    print(f"  {'─'*36} {'─'*10} {'─'*10} {'─'*10}")
    print(f"  {'TOTAL':<36} {total_summer:>10,} {total_winter:>10,} {total_annual:>10,} "
          f"{total_summer/total_winter:.2f}")

    # Unit ratings table
    print(f"\n  UNIT RATINGS AND AVAILABILITY")
    print(f"  {'Unit':<32} {'Rating':>8} {'SumFOR':>7} {'WinFOR':>7} {'Type':<20}")
    print(f"  {'':32s} {'(Mlb/hr)':>8} {'(%)':>7} {'(%)':>7}")
    print(f"  {'─'*32} {'─'*8} {'─'*7} {'─'*7} {'─'*20}")

    for u in LARGE_BOILERS + PACKAGE_BOILERS:
        if u["steam_rating_mlbhr"] == 0:
            continue
        print(f"  {u['unit']:<32} {u['steam_rating_mlbhr']:>8,} "
              f"{u['summer_for_pct']:>6.1f}% {u['winter_for_pct']:>6.1f}% "
              f"{u['type']:<20}")

    total_rating = summary["total_rated_capacity_mlbhr"]
    print(f"  {'─'*32} {'─'*8}")
    print(f"  {'TOTAL (excl. retired)':<32} {total_rating:>8,}")

    # System summary
    print(f"\n  SYSTEM SUMMARY")
    print(f"    Total rated capacity:        {total_rating:>8,} Mlb/hr")
    print(f"    Annual sendout:              {total_annual/1e6:>8.1f} billion lbs")
    print(f"    Summer sendout:              {total_summer/1e6:>8.1f} billion lbs  ({total_summer/total_annual*100:.0f}%)")
    print(f"    Winter sendout:              {total_winter/1e6:>8.1f} billion lbs  ({total_winter/total_annual*100:.0f}%)")
    print(f"    Summer avg utilization:      {summary['summer_utilization_pct']:>7.1f}%  ({summary['summer_avg_rate_mlbhr']:,.0f} Mlb/hr avg)")
    print(f"    Winter avg utilization:      {summary['winter_utilization_pct']:>7.1f}%  ({summary['winter_avg_rate_mlbhr']:,.0f} Mlb/hr avg)")
    print(f"    Summer spare capacity:       {summary['summer_spare_capacity_mlbhr']:>8,.0f} Mlb/hr")
    print(f"    Cogen share (annual):        {summary['cogen_pct_annual']:>7.1f}%")
    print(f"    Cogen share (summer):        {summary['cogen_pct_summer']:>7.1f}%")

    # The cogen economics point
    print(f"\n  COGEN ECONOMICS")
    er10_summer = next(s for s in STATION_SENDOUT if s["station_group"] == "East River 10 and 20")
    print(f"    East River 10 & 20 summer heat rate: {er10_summer['summer_heat_rate_btu_lb']} btu/lb")
    print(f"    → Steam is essentially FREE in summer (byproduct of electricity generation)")
    print(f"    → Boiler-only stations: 1,363–1,810 btu/lb (pure fuel cost)")
    print(f"    East River 10 & 20 share of summer sendout: "
          f"{er10_summer['summer_sendout_mlb']/total_summer*100:.0f}%")

    return summary


def write_csvs():
    """Write plant data to CSV files for downstream analysis."""
    # Station sendout
    path = os.path.join(OUTPUT_DIR, "station_sendout_2025.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STATION_SENDOUT[0].keys())
        writer.writeheader()
        writer.writerows(STATION_SENDOUT)
    print(f"\n  Written: {path}")

    # Unit ratings
    all_units = LARGE_BOILERS + PACKAGE_BOILERS
    path = os.path.join(OUTPUT_DIR, "unit_ratings_2025.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_units[0].keys())
        writer.writeheader()
        writer.writerows(all_units)
    print(f"  Written: {path}")

    # System summary
    summary = compute_system_summary()
    path = os.path.join(OUTPUT_DIR, "system_summary_2025.json")
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Written: {path}")


if __name__ == "__main__":
    summary = print_summary()
    write_csvs()
