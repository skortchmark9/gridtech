"""
Visualize what generation served NYISO Zone J (NYC) in summer 2025.

Combines three data sources:
  1. EPA CAMPD hourly emissions — unit-level fossil generation in NYC
  2. NYISO zonal load (PAL) — total Zone J demand
  3. NYISO system fuel mix — NYCA generation by fuel category

The approach: Zone J load gives us total demand. CAMPD gives us local fossil gen.
System fuel mix pro-rated by Zone J's share of NYCA load estimates the fuel
breakdown of imports + local generation combined.

Usage:
    python visualize.py          # default output: zone_j_summer_2025.png
    python visualize.py out.png  # custom output path
"""

import sys
import os
import zipfile
import glob as globmod
import pandas as pd
import matplotlib.pyplot as plt

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# NYC (Zone J) power plants — EPA CAMPD ORIS facility codes
# Plants physically in the five boroughs, cross-referenced with NYISO Gold Book
ZONE_J_FACILITY_IDS = [
    2490,    # Arthur Kill (Staten Island)
    2493,    # East River (Manhattan)
    2494,    # Gowanus Generating Station (Brooklyn)
    2499,    # Narrows Generating Station (Brooklyn)
    2500,    # Ravenswood Generating Station (Queens)
    2503,    # 59th Street (Manhattan)
    2504,    # 74th Street (Manhattan)
    7909,    # Vernon Boulevard (Queens)
    7910,    # 23rd and 3rd (Manhattan)
    7913,    # Hell Gate (Bronx)
    7914,    # Harlem River Yard (Bronx)
    7915,    # North 1st (Brooklyn)
    8053,    # Pouch Terminal (Staten Island)
    8906,    # Astoria Generating Station (Queens)
    52168,   # Riverbay Corp / Co-Op City (Bronx)
    54114,   # KIAC Cogeneration — JFK Airport (Queens)
    54914,   # Brooklyn Navy Yard Cogeneration (Brooklyn)
    55375,   # Astoria Energy (Queens)
    55699,   # Bayswater Peaking Facility (Queens)
    56196,   # Poletti 500 MW CC (Queens)
    880100,  # Ravenswood Steam Plant (Queens)
]

FUEL_COLORS = {
    "Nuclear": "#b467c4",
    "Hydro": "#2171b5",
    "Wind": "#41ab5d",
    "Other Renewables": "#78c679",
    "Natural Gas": "#fd8d3c",
    "Dual Fuel": "#d94701",
    "Other Fossil Fuels": "#666666",
}

FUEL_ORDER = [
    "Nuclear", "Hydro", "Wind", "Other Renewables",
    "Natural Gas", "Dual Fuel", "Other Fossil Fuels",
]


def load_nyiso_zips(pattern):
    """Load all CSVs from monthly NYISO zip archives matching a glob pattern."""
    frames = []
    for zpath in sorted(globmod.glob(pattern)):
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():
                if name.endswith(".csv"):
                    with z.open(name) as f:
                        frames.append(pd.read_csv(f))
    df = pd.concat(frames, ignore_index=True)
    df["Time Stamp"] = pd.to_datetime(df["Time Stamp"])
    return df


def load_zone_j_load():
    """Load NYISO zonal load, return Zone J records with NYCA share computed."""
    load_df = load_nyiso_zips(os.path.join(DATA_DIR, "nyiso", "*pal_csv.zip"))
    nyca_load = load_df.groupby("Time Stamp")["Load"].sum().reset_index()
    nyca_load.columns = ["Time Stamp", "NYCA_Load"]

    zone_j = load_df[load_df["Name"] == "N.Y.C."].copy()
    zone_j = zone_j.merge(nyca_load, on="Time Stamp")
    zone_j["J_Share"] = zone_j["Load"] / zone_j["NYCA_Load"]
    zone_j["week"] = zone_j["Time Stamp"].dt.isocalendar().week.astype(int)
    return zone_j


def load_fuel_mix(zone_j_load):
    """Load NYISO fuel mix, pro-rate to Zone J share, aggregate weekly."""
    fuel_df = load_nyiso_zips(os.path.join(DATA_DIR, "nyiso", "*rtfuelmix_csv.zip"))
    fuel_df["hour"] = fuel_df["Time Stamp"].dt.floor("h")

    fuel_hourly = (
        fuel_df.groupby(["hour", "Fuel Category"])["Gen MW"]
        .mean()
        .reset_index()
    )

    j_share_hourly = (
        zone_j_load[["Time Stamp", "J_Share"]]
        .rename(columns={"Time Stamp": "hour"})
    )
    j_share_hourly["hour"] = j_share_hourly["hour"].dt.floor("h")
    j_share_hourly = j_share_hourly.groupby("hour")["J_Share"].mean().reset_index()

    merged = fuel_hourly.merge(j_share_hourly, on="hour", how="inner")
    merged["j_gen_mw"] = merged["Gen MW"] * merged["J_Share"]
    merged["week"] = merged["hour"].dt.isocalendar().week.astype(int)

    weekly = merged.groupby(["week", "Fuel Category"])["j_gen_mw"].sum().reset_index()
    weekly["GWh"] = weekly["j_gen_mw"] / 1000
    return weekly


def load_campd_fossil():
    """Load EPA CAMPD emissions, filter to Zone J summer 2025."""
    campd = pd.read_csv(
        os.path.join(DATA_DIR, "emissions-hourly-2025-ny.csv"),
        usecols=["Facility ID", "Facility Name", "Date", "Hour",
                 "Gross Load (MW)", "Primary Fuel Type"],
        low_memory=False,
    )
    campd["Date"] = pd.to_datetime(campd["Date"])
    campd = campd[(campd["Date"] >= "2025-06-01") & (campd["Date"] <= "2025-08-31")]
    campd["Gross Load (MW)"] = pd.to_numeric(campd["Gross Load (MW)"], errors="coerce")

    nyc = campd[campd["Facility ID"].isin(ZONE_J_FACILITY_IDS)].copy()
    nyc = nyc[nyc["Gross Load (MW)"] > 0]
    nyc["week"] = nyc["Date"].dt.isocalendar().week.astype(int)
    return nyc


def make_charts(zone_j_load, weekly_fuel, nyc_fossil, out_path):
    weeks = sorted(zone_j_load["week"].unique())
    week_labels = (
        zone_j_load.groupby("week")["Time Stamp"]
        .min().dt.strftime("Week of\n%b %d")
    )

    # Weekly aggregates
    weekly_load = zone_j_load.groupby("week").agg(
        load_gwh=("Load", lambda x: x.sum() / 12 / 1000),
    )
    weekly_fossil_total = nyc_fossil.groupby("week")["Gross Load (MW)"].sum() / 1000
    weekly_peak = zone_j_load.groupby("week")["Load"].max() / 1000
    weekly_avg = zone_j_load.groupby("week")["Load"].mean() / 1000
    fossil_hourly = nyc_fossil.groupby(["week", "Date", "Hour"])["Gross Load (MW)"].sum().reset_index()
    fossil_weekly_peak = fossil_hourly.groupby("week")["Gross Load (MW)"].max() / 1000

    x = range(len(weeks))
    load_vals = [weekly_load.loc[w, "load_gwh"] if w in weekly_load.index else 0 for w in weeks]
    fossil_vals = [weekly_fossil_total.get(w, 0) for w in weeks]
    import_vals = [l - f for l, f in zip(load_vals, fossil_vals)]

    fig, axes = plt.subplots(4, 1, figsize=(14, 20))

    # ── Chart 1: Load breakdown — local fossil vs imports ──
    ax = axes[0]
    ax.bar(x, fossil_vals, width=0.7, label="In-zone fossil generation", color="#d45f00")
    ax.bar(x, import_vals, width=0.7, bottom=fossil_vals,
           label="Imports + non-fossil", color="#4292c6")
    ax.set_title("Zone J (NYC) — Weekly Load: Local Fossil Gen vs Imports\nSummer 2025",
                  fontsize=13, fontweight="bold")
    ax.set_ylabel("Energy (GWh)")
    ax.set_xticks(x)
    ax.set_xticklabels([week_labels.get(w, str(w)) for w in weeks], fontsize=8)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    for i, (l, f) in enumerate(zip(load_vals, fossil_vals)):
        if l > 0:
            ax.text(i, l + 5, f"{f/l:.0%}\nlocal", ha="center", fontsize=7, color="#666")

    # ── Chart 2: Estimated fuel mix serving Zone J ──
    pivot_fuel = weekly_fuel.pivot_table(
        index="week", columns="Fuel Category", values="GWh",
        aggfunc="sum", fill_value=0,
    )
    fuel_cols = [f for f in FUEL_ORDER if f in pivot_fuel.columns]
    pivot_fuel = pivot_fuel[fuel_cols]
    pf = pivot_fuel.loc[weeks]
    pf.index = range(len(weeks))
    pf.plot(
        kind="bar", stacked=True, ax=axes[1],
        color=[FUEL_COLORS.get(c, "#999") for c in pf.columns],
        edgecolor="white", linewidth=0.3, width=0.85,
    )
    axes[1].set_title(
        "Estimated Fuel Mix Serving Zone J (NYCA mix pro-rated by load share)\nSummer 2025",
        fontsize=13, fontweight="bold")
    axes[1].set_ylabel("Energy (GWh)")
    axes[1].set_xticks(range(len(weeks)))
    axes[1].set_xticklabels([week_labels.get(w, str(w)) for w in weeks], fontsize=8)
    axes[1].legend(title="Fuel", bbox_to_anchor=(1.01, 1.0), loc="upper left", fontsize=8)
    axes[1].grid(axis="y", alpha=0.3)

    # ── Chart 3: In-zone fossil by plant ──
    weekly_plant = nyc_fossil.groupby(["week", "Facility Name"])["Gross Load (MW)"].sum().reset_index()
    weekly_plant["GWh"] = weekly_plant["Gross Load (MW)"] / 1000
    pivot_plant = weekly_plant.pivot_table(
        index="week", columns="Facility Name", values="GWh",
        aggfunc="sum", fill_value=0,
    )
    pivot_plant = pivot_plant[pivot_plant.sum().sort_values(ascending=False).index]
    plant_weeks = sorted([w for w in weeks if w in pivot_plant.index])
    pp = pivot_plant.loc[plant_weeks]
    pp.index = range(len(pp))
    cmap = plt.colormaps["tab20"]
    pp.plot(
        kind="bar", stacked=True, ax=axes[2],
        color=[cmap(i) for i in range(len(pp.columns))],
        edgecolor="white", linewidth=0.3, width=0.85,
    )
    axes[2].set_title("Zone J In-City Fossil Generation by Plant\nSummer 2025",
                       fontsize=13, fontweight="bold")
    axes[2].set_ylabel("Energy (GWh)")
    axes[2].set_xticks(range(len(plant_weeks)))
    axes[2].set_xticklabels([week_labels.get(w, str(w)) for w in plant_weeks], fontsize=8)
    axes[2].legend(title="Plant", bbox_to_anchor=(1.01, 1.0), loc="upper left", fontsize=7)
    axes[2].grid(axis="y", alpha=0.3)

    # ── Chart 4: Peak & average demand in GW ──
    ax = axes[3]
    peak_vals = [weekly_peak.get(w, 0) for w in weeks]
    avg_vals = [weekly_avg.get(w, 0) for w in weeks]
    fossil_peak_vals = [fossil_weekly_peak.get(w, 0) for w in weeks]

    ax.bar(x, peak_vals, width=0.7, color="#c44e52", alpha=0.85, label="Zone J peak load")
    ax.bar(x, fossil_peak_vals, width=0.7, color="#d45f00", alpha=0.85,
           label="In-zone fossil peak gen")
    ax.plot(x, avg_vals, color="#4292c6", linewidth=2, marker="o", markersize=4,
            label="Zone J avg load", zorder=5)
    ax.set_title("Zone J (NYC) — Weekly Peak & Average Demand (GW)\nSummer 2025",
                  fontsize=13, fontweight="bold")
    ax.set_ylabel("Power (GW)")
    ax.set_xticks(x)
    ax.set_xticklabels([week_labels.get(w, str(w)) for w in weeks], fontsize=8)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    for i, p in enumerate(peak_vals):
        if p > 0:
            ax.text(i, p + 0.1, f"{p:.1f}", ha="center", fontsize=8,
                    color="#333", fontweight="bold")

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Chart saved to {out_path}")


def print_summary(zone_j_load, weekly_fuel, nyc_fossil):
    fossil_hourly = nyc_fossil.groupby(["week", "Date", "Hour"])["Gross Load (MW)"].sum().reset_index()
    total_load = zone_j_load["Load"].sum() / 12 / 1000  # 5-min → MWh → GWh
    total_fossil = nyc_fossil["Gross Load (MW)"].sum() / 1000
    peak_gw = zone_j_load["Load"].max() / 1000
    peak_time = zone_j_load.loc[zone_j_load["Load"].idxmax(), "Time Stamp"]
    fossil_peak_gw = fossil_hourly["Gross Load (MW)"].max() / 1000

    print(f"\n{'=' * 55}")
    print(f"Zone J (NYC) Summer 2025 Summary")
    print(f"{'=' * 55}")
    print(f"Peak demand:                 {peak_gw:.2f} GW  ({peak_time})")
    print(f"Peak in-zone fossil gen:     {fossil_peak_gw:.2f} GW")
    print(f"Total load:                  {total_load:,.0f} GWh")
    print(f"In-zone fossil generation:   {total_fossil:,.0f} GWh ({total_fossil/total_load:.0%})")
    print(f"Imports + non-fossil:        {total_load - total_fossil:,.0f} GWh ({(total_load-total_fossil)/total_load:.0%})")
    print(f"Avg Zone J share of NYCA:    {zone_j_load['J_Share'].mean():.1%}")

    print(f"\nEstimated fuel mix (NYCA pro-rated):")
    fuel_totals = weekly_fuel.groupby("Fuel Category")["GWh"].sum().sort_values(ascending=False)
    for fuel, gwh in fuel_totals.items():
        print(f"  {fuel:<25} {gwh:>8.1f} GWh  ({gwh/fuel_totals.sum():.1%})")

    print(f"\nIn-zone fossil plants:")
    plant_totals = (
        nyc_fossil.groupby("Facility Name")["Gross Load (MW)"]
        .agg(["sum", "count", "max"])
    )
    plant_totals.columns = ["Total MWh", "Operating Hours", "Peak MW"]
    plant_totals["Total GWh"] = plant_totals["Total MWh"] / 1000
    plant_totals = plant_totals.sort_values("Total MWh", ascending=False)
    for name, row in plant_totals.iterrows():
        print(f"  {name:<40} {row['Total GWh']:>7.1f} GWh  (peak {row['Peak MW']:>5.0f} MW)")


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "zone_j_summer_2025.png"

    print("Loading data...")
    zone_j_load = load_zone_j_load()
    print(f"  Zone J load: {len(zone_j_load):,} records, avg {zone_j_load['J_Share'].mean():.1%} of NYCA")

    weekly_fuel = load_fuel_mix(zone_j_load)
    print(f"  Fuel mix: {len(weekly_fuel):,} weekly fuel-category records")

    nyc_fossil = load_campd_fossil()
    print(f"  CAMPD fossil: {len(nyc_fossil):,} operating-hour records, "
          f"{nyc_fossil['Facility Name'].nunique()} plants")

    make_charts(zone_j_load, weekly_fuel, nyc_fossil, out_path)
    print_summary(zone_j_load, weekly_fuel, nyc_fossil)


if __name__ == "__main__":
    main()
