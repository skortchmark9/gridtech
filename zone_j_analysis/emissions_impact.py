"""
Carbon intensity of Zone J electricity, summer 2025, and the impact of
500 MW steam-chiller demand response on grid emissions.

Approach
--------
1. AVERAGE EMISSIONS FACTOR
   - In-zone fossil: hourly CO2 and generation from EPA CAMPD
   - Imports: pro-rated NYCA fuel mix → estimate non-fossil and imported
     fossil contribution + their emissions

2. MARGINAL EMISSIONS IMPACT OF 500 MW DR
   - Each hour, rank Zone J generators by heat rate (dirtiest first)
   - Remove 500 MW of demand from the margin
   - Recompute total emissions and average intensity

3. ELECTRICITY PRICE IMPACT (bonus)
   - Fetch NYISO day-ahead LBMP for Zone J
   - Build load-price curve to estimate price reduction from 500 MW DR

Data sources:
  - EPA CAMPD hourly emissions (already downloaded)
  - NYISO zonal load PAL (already downloaded)
  - NYISO real-time fuel mix (already downloaded)
  - NYISO day-ahead LBMP (fetched here)
"""

import os
import sys
import zipfile
import glob as globmod
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
NYISO_DIR = os.path.join(DATA_DIR, "nyiso")
OUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# Zone J facility IDs (same as visualize.py)
ZONE_J_FACILITY_IDS = [
    2490, 2493, 2494, 2499, 2500, 2503, 2504, 7909, 7910, 7913,
    7914, 7915, 8053, 8906, 52168, 54114, 54914, 55375, 55699, 56196, 880100,
]

# Emission factors for non-fossil fuels (tons CO2 / MWh)
# Nuclear, hydro, wind, solar = 0
# "Other Renewables" could include some biomass, but for simplicity = 0
FUEL_EMISSION_FACTORS = {
    "Nuclear": 0.0,
    "Hydro": 0.0,
    "Wind": 0.0,
    "Other Renewables": 0.0,
    # For imported fossil (gas), we use NYCA-wide average from CAMPD
    # Natural Gas and Dual Fuel are covered by CAMPD unit-level data
}

DR_MW = 500  # MW of demand response


# ─── Data loading ──────────────────────────────────────────────────────────

def load_nyiso_zips(pattern):
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
    """Load 5-min zonal load, compute Zone J share of NYCA."""
    load_df = load_nyiso_zips(os.path.join(NYISO_DIR, "*pal_csv.zip"))
    nyca = load_df.groupby("Time Stamp")["Load"].sum().reset_index()
    nyca.columns = ["Time Stamp", "NYCA_Load"]
    zj = load_df[load_df["Name"] == "N.Y.C."].copy()
    zj = zj.merge(nyca, on="Time Stamp")
    zj["J_Share"] = zj["Load"] / zj["NYCA_Load"]
    zj["hour"] = zj["Time Stamp"].dt.floor("h")
    return zj


def load_fuel_mix():
    """Load NYISO 5-min fuel mix, aggregate to hourly."""
    fm = load_nyiso_zips(os.path.join(NYISO_DIR, "*rtfuelmix_csv.zip"))
    fm["hour"] = fm["Time Stamp"].dt.floor("h")
    hourly = fm.groupby(["hour", "Fuel Category"])["Gen MW"].mean().reset_index()
    return hourly


def load_campd_zone_j():
    """Load CAMPD, filter to Zone J summer 2025, parse numeric columns."""
    print("Loading CAMPD data...")
    df = pd.read_csv(
        os.path.join(DATA_DIR, "emissions-hourly-2025-ny.csv"),
        usecols=[
            "Facility ID", "Facility Name", "Unit ID", "Date", "Hour",
            "Gross Load (MW)", "CO2 Mass (short tons)", "Heat Input (mmBtu)",
            "Primary Fuel Type", "Unit Type",
        ],
        low_memory=False,
    )
    df["Date"] = pd.to_datetime(df["Date"])
    df = df[(df["Date"] >= "2025-06-01") & (df["Date"] <= "2025-08-31")]

    for col in ["Gross Load (MW)", "CO2 Mass (short tons)", "Heat Input (mmBtu)"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Filter to Zone J
    zj = df[df["Facility ID"].isin(ZONE_J_FACILITY_IDS)].copy()
    zj = zj[zj["Gross Load (MW)"] > 0]
    zj["hour"] = pd.to_datetime(zj["Date"]) + pd.to_timedelta(zj["Hour"], unit="h")

    # Also get all NY plants for NYCA-wide emission rates
    ny_all = df[df["Gross Load (MW)"] > 0].copy()
    ny_all["hour"] = pd.to_datetime(ny_all["Date"]) + pd.to_timedelta(ny_all["Hour"], unit="h")

    return zj, ny_all


def fetch_lbmp():
    """Download NYISO day-ahead LBMP for Zone J, Jun-Aug 2025."""
    lbmp_dir = os.path.join(NYISO_DIR, "lbmp")
    os.makedirs(lbmp_dir, exist_ok=True)

    frames = []
    for month in ["20250601", "20250701", "20250801"]:
        filename = f"{month}damlbmp_zone_csv.zip"
        dest = os.path.join(lbmp_dir, filename)
        if not os.path.exists(dest):
            url = f"http://mis.nyiso.com/public/csv/damlbmp/{filename}"
            print(f"  Downloading {filename}...")
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                f.write(resp.content)

        with zipfile.ZipFile(dest) as z:
            for name in z.namelist():
                if name.endswith(".csv"):
                    with z.open(name) as f:
                        frames.append(pd.read_csv(f))

    df = pd.concat(frames, ignore_index=True)
    df["Time Stamp"] = pd.to_datetime(df["Time Stamp"])
    # Filter to Zone J
    zj = df[df["Name"] == "N.Y.C."].copy()
    zj["hour"] = zj["Time Stamp"].dt.floor("h")
    return zj


# ─── Analysis ──────────────────────────────────────────────────────────────

def compute_average_emissions_factor(zj_campd, ny_all, zj_load, fuel_mix):
    """
    Compute the average carbon intensity of Zone J electricity.

    Two components:
    1. In-zone fossil: direct from CAMPD (CO2 / MWh for each plant)
    2. Imports + non-fossil: pro-rated from NYCA fuel mix
       - Non-fossil (nuclear, hydro, wind) = 0 CO2
       - Imported fossil: use NYCA-wide average fossil emission rate
    """
    # Hourly Zone J share
    j_share = zj_load.groupby("hour").agg(
        load_mw=("Load", "mean"),
        j_share=("J_Share", "mean"),
    )

    # In-zone fossil: hourly CO2 and generation
    zj_hourly = zj_campd.groupby("hour").agg(
        fossil_mw=("Gross Load (MW)", "sum"),
        fossil_co2=("CO2 Mass (short tons)", "sum"),
    )

    # NYCA-wide fossil emission rate (for imported fossil)
    ny_hourly = ny_all.groupby("hour").agg(
        ny_mw=("Gross Load (MW)", "sum"),
        ny_co2=("CO2 Mass (short tons)", "sum"),
    )
    ny_hourly["ny_co2_per_mwh"] = ny_hourly["ny_co2"] / ny_hourly["ny_mw"]

    # Fuel mix: hourly NYCA generation by fuel
    fuel_pivot = fuel_mix.pivot_table(
        index="hour", columns="Fuel Category", values="Gen MW",
        aggfunc="sum", fill_value=0,
    )
    fuel_pivot["total_gen"] = fuel_pivot.sum(axis=1)
    non_fossil_cols = [c for c in fuel_pivot.columns
                       if c in ("Nuclear", "Hydro", "Wind", "Other Renewables")]
    fuel_pivot["non_fossil_mw"] = fuel_pivot[non_fossil_cols].sum(axis=1)
    fossil_cols = [c for c in fuel_pivot.columns
                   if c not in non_fossil_cols + ["total_gen", "non_fossil_mw"]]
    fuel_pivot["system_fossil_mw"] = fuel_pivot[fossil_cols].sum(axis=1)

    # Merge everything on hour
    merged = j_share.join(zj_hourly, how="left").join(ny_hourly, how="left")
    merged = merged.join(fuel_pivot[["total_gen", "non_fossil_mw", "system_fossil_mw"]], how="left")
    merged = merged.dropna(subset=["load_mw", "total_gen"])
    merged["fossil_mw"] = merged["fossil_mw"].fillna(0)
    merged["fossil_co2"] = merged["fossil_co2"].fillna(0)

    # Zone J's share of system generation by type
    merged["j_non_fossil_mw"] = merged["non_fossil_mw"] * merged["j_share"]
    merged["j_imported_fossil_mw"] = (
        merged["system_fossil_mw"] * merged["j_share"] - merged["fossil_mw"]
    ).clip(lower=0)

    # CO2 from imported fossil (at NYCA average rate)
    merged["imported_fossil_co2"] = (
        merged["j_imported_fossil_mw"] * merged["ny_co2_per_mwh"]
    ).fillna(0)

    # Total Zone J CO2 = in-zone fossil + imported fossil
    merged["total_co2"] = merged["fossil_co2"] + merged["imported_fossil_co2"]

    # Fill ny_co2_per_mwh NaN with system-wide average for DR calculations
    ny_avg_rate = ny_hourly["ny_co2"].sum() / ny_hourly["ny_mw"].sum()
    merged["ny_co2_per_mwh"] = merged["ny_co2_per_mwh"].fillna(ny_avg_rate)

    # Average emissions factor
    total_co2 = merged["total_co2"].sum()
    total_load_mwh = merged["load_mw"].sum()  # each row = 1 hour, so MW = MWh
    avg_ef = total_co2 / total_load_mwh

    # Also compute by month
    merged["month"] = merged.index.month

    print("\n" + "=" * 70)
    print("ZONE J AVERAGE EMISSIONS FACTOR — SUMMER 2025")
    print("=" * 70)

    print(f"\n  Total Zone J load:              {total_load_mwh:>12,.0f} MWh")
    print(f"  In-zone fossil generation:      {merged['fossil_mw'].sum():>12,.0f} MWh")
    print(f"  In-zone fossil CO2:             {merged['fossil_co2'].sum():>12,.0f} short tons")
    print(f"  Imported fossil (est.):         {merged['j_imported_fossil_mw'].sum():>12,.0f} MWh")
    print(f"  Imported fossil CO2 (est.):     {merged['imported_fossil_co2'].sum():>12,.0f} short tons")
    print(f"  Non-fossil (pro-rated):         {merged['j_non_fossil_mw'].sum():>12,.0f} MWh")
    print(f"\n  Average emissions factor:       {avg_ef:.4f} tons CO2 / MWh")
    print(f"                                  {avg_ef * 2000:.1f} lbs CO2 / MWh")
    print(f"                                  {avg_ef * 1000:.1f} kg CO2 / MWh")

    for month_num, month_name in [(6, "June"), (7, "July"), (8, "August")]:
        m = merged[merged["month"] == month_num]
        if len(m) > 0:
            m_ef = m["total_co2"].sum() / m["load_mw"].sum()
            print(f"\n  {month_name}:  {m_ef:.4f} tons/MWh  "
                  f"({m['load_mw'].sum():,.0f} MWh load, "
                  f"{m['total_co2'].sum():,.0f} tons CO2)")

    return merged


def compute_dr_impact(zj_campd, merged_hourly):
    """
    Model the impact of 500 MW DR on emissions.

    Each hour, rank in-zone generators by heat rate (BTU/kWh). The dirtiest
    units are marginal — they would be displaced first by demand reduction.
    For imported generation, we assume DR displaces at the NYCA average rate.
    """
    # Build unit-level hourly data with heat rates
    units = zj_campd.copy()
    units = units[units["CO2 Mass (short tons)"].notna() & (units["CO2 Mass (short tons)"] > 0)]
    units["heat_rate"] = (
        units["Heat Input (mmBtu)"] * 1000 /  # mmBtu → kBtu
        units["Gross Load (MW)"]               # MW = MWh for 1 hour
    )  # kBtu / MWh = BTU / kWh
    units["co2_rate"] = units["CO2 Mass (short tons)"] / units["Gross Load (MW)"]
    units = units[units["co2_rate"].notna() & units["heat_rate"].notna()]

    # For each hour, compute what 500 MW of DR would displace
    hours = sorted(merged_hourly.index)
    results = []

    for hour in hours:
        row = merged_hourly.loc[hour]
        load = row["load_mw"]
        if load <= 0 or pd.isna(load):
            continue

        # How much DR to apply (can't reduce below 0)
        dr = min(DR_MW, load)

        # Get this hour's generators, sorted by heat rate (dirtiest first)
        hour_units = units[units["hour"] == hour].sort_values("heat_rate", ascending=False)

        # Displace from the margin
        remaining_dr = dr
        displaced_co2 = 0.0
        displaced_mw = 0.0

        # First displace in-zone marginal generators
        for _, unit in hour_units.iterrows():
            if remaining_dr <= 0:
                break
            displace = min(remaining_dr, unit["Gross Load (MW)"])
            displaced_co2 += unit["co2_rate"] * displace
            displaced_mw += displace
            remaining_dr -= displace

        # If DR exceeds in-zone fossil, remaining displaces imports
        # (at NYCA average rate)
        if remaining_dr > 0 and not pd.isna(row.get("ny_co2_per_mwh", np.nan)):
            displaced_co2 += remaining_dr * row["ny_co2_per_mwh"]
            displaced_mw += remaining_dr

        # New emissions factor (clamp at 0 — can't have negative emissions)
        new_co2 = max(0, row["total_co2"] - displaced_co2)
        new_load = load - dr
        new_ef = new_co2 / new_load if new_load > 0 else 0

        results.append({
            "hour": hour,
            "load_mw": load,
            "original_co2": row["total_co2"],
            "original_ef": row["total_co2"] / load,
            "displaced_co2": displaced_co2,
            "displaced_mw": displaced_mw,
            "new_co2": new_co2,
            "new_load": new_load,
            "new_ef": new_ef,
            "marginal_ef": displaced_co2 / displaced_mw if displaced_mw > 0 else 0,
        })

    dr_df = pd.DataFrame(results).set_index("hour")

    total_orig_co2 = dr_df["original_co2"].sum()
    total_new_co2 = dr_df["new_co2"].sum()
    total_displaced = dr_df["displaced_co2"].sum()
    total_orig_load = dr_df["load_mw"].sum()
    total_new_load = dr_df["new_load"].sum()

    orig_ef = total_orig_co2 / total_orig_load
    new_ef = total_new_co2 / total_new_load
    avg_marginal = dr_df["marginal_ef"].mean()

    print("\n" + "=" * 70)
    print(f"IMPACT OF {DR_MW} MW DEMAND RESPONSE ON ZONE J EMISSIONS")
    print("=" * 70)

    print(f"\n  Scenario: {DR_MW} MW load reduction every hour of summer 2025")
    print(f"  (Models steam chiller DR displacing the dirtiest marginal generators)")

    print(f"\n  Original total CO2:            {total_orig_co2:>12,.0f} short tons")
    print(f"  Displaced CO2:                 {total_displaced:>12,.0f} short tons")
    print(f"  New total CO2:                 {total_new_co2:>12,.0f} short tons")
    print(f"  CO2 reduction:                 {total_displaced / total_orig_co2 * 100:.2f}%")

    print(f"\n  Original avg emissions factor: {orig_ef:.4f} tons/MWh ({orig_ef * 2000:.1f} lbs/MWh)")
    print(f"  New avg emissions factor:      {new_ef:.4f} tons/MWh ({new_ef * 2000:.1f} lbs/MWh)")
    print(f"  Change:                        {(new_ef - orig_ef):.4f} tons/MWh ({(new_ef/orig_ef - 1)*100:+.2f}%)")
    print(f"\n  Avg marginal emission rate:    {avg_marginal:.4f} tons/MWh")
    print(f"  (Rate of displaced generators, weighted by hour)")

    # Peak hours analysis (2pm-6pm weekdays)
    dr_df["is_peak"] = (
        dr_df.index.hour.isin(range(14, 19)) &
        (dr_df.index.dayofweek < 5)
    )
    peak = dr_df[dr_df["is_peak"]]
    if len(peak) > 0:
        peak_orig_ef = peak["original_co2"].sum() / peak["load_mw"].sum()
        peak_new_ef = peak["new_co2"].sum() / peak["new_load"].sum()
        peak_displaced = peak["displaced_co2"].sum()
        print(f"\n  Peak hours (weekday 2-6pm):")
        print(f"    Original EF:  {peak_orig_ef:.4f} tons/MWh")
        print(f"    New EF:       {peak_new_ef:.4f} tons/MWh")
        print(f"    Displaced:    {peak_displaced:,.0f} tons CO2")
        print(f"    Avg marginal: {peak['marginal_ef'].mean():.4f} tons/MWh")

    return dr_df


def analyze_lbmp(lbmp_df, zj_load_hourly):
    """
    Analyze electricity price and estimate impact of 500 MW DR on price.

    Uses a simple supply-curve approach: fit a relationship between
    Zone J load and LBMP, then estimate price at (load - 500 MW).
    """
    # Hourly LBMP
    lbmp_hourly = lbmp_df.groupby("hour").agg(
        lbmp=("LBMP ($/MWHr)", "mean"),
        marginal_cost_losses=("Marginal Cost Losses ($/MWHr)", "mean"),
        marginal_cost_congestion=("Marginal Cost Congestion ($/MWHr)", "mean"),
    )

    # Merge with load
    load_hourly = zj_load_hourly.groupby("hour")["Load"].mean()
    merged = lbmp_hourly.join(load_hourly, how="inner")

    avg_lbmp = merged["lbmp"].mean()
    peak_mask = (merged.index.hour.isin(range(14, 19))) & (merged.index.dayofweek < 5)
    avg_peak_lbmp = merged.loc[peak_mask, "lbmp"].mean() if peak_mask.any() else avg_lbmp

    print("\n" + "=" * 70)
    print("ZONE J ELECTRICITY PRICE ANALYSIS — SUMMER 2025")
    print("=" * 70)

    print(f"\n  Average DA LBMP:               ${avg_lbmp:>8.2f} / MWh")
    print(f"  Avg peak LBMP (wkday 2-6pm):   ${avg_peak_lbmp:>8.2f} / MWh")
    print(f"  Max LBMP:                       ${merged['lbmp'].max():>8.2f} / MWh")
    print(f"  Min LBMP:                       ${merged['lbmp'].min():>8.2f} / MWh")
    print(f"  Avg congestion component:       ${merged['marginal_cost_congestion'].mean():>8.2f} / MWh")

    # Fit load-price relationship using polynomial
    # Sort by load for a supply curve view
    valid = merged.dropna(subset=["Load", "lbmp"])
    valid = valid[(valid["lbmp"] > 0) & (valid["lbmp"] < valid["lbmp"].quantile(0.99))]

    # Bin by load level for a cleaner curve
    valid["load_bin"] = pd.cut(valid["Load"], bins=20)
    binned = valid.groupby("load_bin", observed=True).agg(
        avg_load=("Load", "mean"),
        avg_lbmp=("lbmp", "mean"),
        count=("lbmp", "count"),
    ).dropna()

    # Linear regression: LBMP = a * Load + b
    if len(binned) >= 5:
        from numpy.polynomial import polynomial as P
        coeffs = np.polyfit(valid["Load"].values, valid["lbmp"].values, deg=2)
        poly = np.poly1d(coeffs)

        # Estimate price at current load vs load - 500 MW
        test_loads = np.array([6000, 7000, 8000, 9000, 10000])
        print(f"\n  Estimated price impact of {DR_MW} MW DR (quadratic fit):")
        print(f"  {'Load (MW)':>12} {'Price':>10} {'Price - DR':>12} {'Savings':>10} {'%':>8}")
        print(f"  {'─'*12} {'─'*10} {'─'*12} {'─'*10} {'─'*8}")
        for load in test_loads:
            p_orig = poly(load)
            p_new = poly(load - DR_MW)
            savings = p_orig - p_new
            pct = savings / p_orig * 100 if p_orig > 0 else 0
            print(f"  {load:>10,.0f}MW ${p_orig:>8.2f} ${p_new:>10.2f} ${savings:>8.2f} {pct:>6.1f}%")

        # Actual hour-by-hour estimate
        valid["est_price_current"] = poly(valid["Load"])
        valid["est_price_dr"] = poly(valid["Load"] - DR_MW)
        valid["price_savings"] = valid["est_price_current"] - valid["est_price_dr"]

        avg_savings = valid["price_savings"].mean()
        total_consumer_savings = (valid["price_savings"] * valid["Load"]).sum() / 1e6
        print(f"\n  Avg hourly price reduction:     ${avg_savings:.2f} / MWh")
        print(f"  Total consumer savings (est.):  ${total_consumer_savings:.1f} million")
        print(f"  (Based on price × load over all summer hours)")

    return merged


def make_charts(merged_hourly, dr_df, lbmp_merged, out_path):
    """Generate summary charts."""
    fig, axes = plt.subplots(3, 2, figsize=(16, 18))

    # 1. Hourly emissions factor time series
    ax = axes[0, 0]
    daily = merged_hourly.resample("D").agg(
        co2=("total_co2", "sum"),
        load=("load_mw", "sum"),
    )
    daily["ef"] = daily["co2"] / daily["load"]
    ax.plot(daily.index, daily["ef"] * 2000, color="#d45f00", linewidth=0.8)
    ax.axhline(y=daily["ef"].mean() * 2000, color="red", linestyle="--", alpha=0.7,
               label=f"Avg: {daily['ef'].mean() * 2000:.0f} lbs/MWh")
    ax.set_title("Zone J Daily Average Emissions Factor\nSummer 2025", fontweight="bold")
    ax.set_ylabel("lbs CO2 / MWh")
    ax.legend()
    ax.grid(alpha=0.3)

    # 2. Emissions factor by hour of day
    ax = axes[0, 1]
    merged_hourly["hour_of_day"] = merged_hourly.index.hour
    merged_hourly["ef"] = merged_hourly["total_co2"] / merged_hourly["load_mw"]
    hourly_avg = merged_hourly.groupby("hour_of_day")["ef"].mean() * 2000
    ax.bar(hourly_avg.index, hourly_avg.values, color="#fd8d3c", edgecolor="white")
    ax.set_title("Avg Emissions Factor by Hour of Day", fontweight="bold")
    ax.set_ylabel("lbs CO2 / MWh")
    ax.set_xlabel("Hour")
    ax.set_xticks(range(0, 24, 3))
    ax.grid(axis="y", alpha=0.3)

    # 3. DR impact — original vs new EF
    ax = axes[1, 0]
    dr_daily = dr_df.resample("D").agg(
        orig_co2=("original_co2", "sum"),
        new_co2=("new_co2", "sum"),
        orig_load=("load_mw", "sum"),
        new_load=("new_load", "sum"),
    )
    dr_daily["orig_ef"] = dr_daily["orig_co2"] / dr_daily["orig_load"] * 2000
    dr_daily["new_ef"] = dr_daily["new_co2"] / dr_daily["new_load"] * 2000
    ax.plot(dr_daily.index, dr_daily["orig_ef"], color="#d45f00", label="Original", linewidth=1)
    ax.plot(dr_daily.index, dr_daily["new_ef"], color="#2171b5", label=f"With {DR_MW}MW DR", linewidth=1)
    ax.fill_between(dr_daily.index, dr_daily["new_ef"], dr_daily["orig_ef"],
                     alpha=0.2, color="#2171b5")
    ax.set_title(f"Emissions Factor: Original vs With {DR_MW} MW DR", fontweight="bold")
    ax.set_ylabel("lbs CO2 / MWh")
    ax.legend()
    ax.grid(alpha=0.3)

    # 4. Marginal emission rate distribution
    ax = axes[1, 1]
    marginal_rates = dr_df["marginal_ef"] * 2000
    ax.hist(marginal_rates[marginal_rates > 0], bins=50, color="#d94701", edgecolor="white", alpha=0.8)
    ax.axvline(x=marginal_rates.mean(), color="red", linestyle="--",
               label=f"Mean: {marginal_rates.mean():.0f} lbs/MWh")
    ax.set_title("Distribution of Marginal Emission Rates\n(Displaced generators)", fontweight="bold")
    ax.set_xlabel("lbs CO2 / MWh")
    ax.set_ylabel("Hours")
    ax.legend()
    ax.grid(alpha=0.3)

    # 5. Load vs LBMP scatter
    if lbmp_merged is not None and len(lbmp_merged) > 0:
        ax = axes[2, 0]
        valid = lbmp_merged.dropna(subset=["Load", "lbmp"])
        valid = valid[valid["lbmp"] < valid["lbmp"].quantile(0.99)]
        ax.scatter(valid["Load"] / 1000, valid["lbmp"], alpha=0.1, s=3, color="#4292c6")

        # Fit line
        coeffs = np.polyfit(valid["Load"].values, valid["lbmp"].values, deg=2)
        poly = np.poly1d(coeffs)
        x_fit = np.linspace(valid["Load"].min(), valid["Load"].max(), 100)
        ax.plot(x_fit / 1000, poly(x_fit), color="red", linewidth=2, label="Quadratic fit")
        ax.plot(x_fit / 1000 - DR_MW / 1000, poly(x_fit), color="#2171b5",
                linewidth=2, linestyle="--", label=f"Shifted {DR_MW} MW")

        ax.set_title("Zone J Load vs Day-Ahead LBMP", fontweight="bold")
        ax.set_xlabel("Load (GW)")
        ax.set_ylabel("LBMP ($/MWh)")
        ax.legend()
        ax.grid(alpha=0.3)

        # 6. CO2 displaced by month
        ax = axes[2, 1]
        dr_df["month"] = dr_df.index.month
        monthly = dr_df.groupby("month").agg(
            displaced=("displaced_co2", "sum"),
            total_orig=("original_co2", "sum"),
        )
        monthly["pct"] = monthly["displaced"] / monthly["total_orig"] * 100
        months = ["June", "July", "August"]
        bars = ax.bar(months[:len(monthly)], monthly["displaced"] / 1000,
                      color="#2171b5", edgecolor="white")
        ax.set_title(f"CO2 Displaced by {DR_MW} MW DR, by Month", fontweight="bold")
        ax.set_ylabel("Thousand short tons CO2")
        for bar, (_, row) in zip(bars, monthly.iterrows()):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                    f"{row['pct']:.1f}%\nof total",
                    ha="center", fontsize=9, color="#333")
        ax.grid(axis="y", alpha=0.3)
    else:
        axes[2, 0].text(0.5, 0.5, "LBMP data not available", ha="center", va="center",
                        transform=axes[2, 0].transAxes)
        axes[2, 1].text(0.5, 0.5, "LBMP data not available", ha="center", va="center",
                        transform=axes[2, 1].transAxes)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\nChart saved to {out_path}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "emissions_impact.png")

    # Load data
    zj_load = load_zone_j_load()
    print(f"  Zone J load: {len(zj_load):,} records")

    fuel_mix = load_fuel_mix()
    print(f"  Fuel mix: {len(fuel_mix):,} records")

    zj_campd, ny_all = load_campd_zone_j()
    print(f"  CAMPD Zone J: {len(zj_campd):,} unit-hours, {zj_campd['Facility Name'].nunique()} plants")
    print(f"  CAMPD NY all: {len(ny_all):,} unit-hours")

    # Fetch LBMP
    print("\nFetching LBMP data...")
    try:
        lbmp = fetch_lbmp()
        print(f"  LBMP: {len(lbmp):,} records")
    except Exception as e:
        print(f"  LBMP fetch failed: {e}")
        lbmp = None

    # 1. Average emissions factor
    merged_hourly = compute_average_emissions_factor(zj_campd, ny_all, zj_load, fuel_mix)

    # 2. DR impact
    dr_df = compute_dr_impact(zj_campd, merged_hourly)

    # 3. LBMP analysis
    lbmp_merged = None
    if lbmp is not None:
        lbmp_merged = analyze_lbmp(lbmp, zj_load)

    # 4. Charts
    make_charts(merged_hourly, dr_df, lbmp_merged, out_path)

    # Summary
    total_displaced_co2 = dr_df["displaced_co2"].sum()
    total_orig_co2 = dr_df["original_co2"].sum()
    orig_ef = total_orig_co2 / dr_df["load_mw"].sum()
    new_ef = dr_df["new_co2"].sum() / dr_df["new_load"].sum()

    print("\n" + "=" * 70)
    print("EXECUTIVE SUMMARY")
    print("=" * 70)
    print(f"""
  Zone J (NYC) served {dr_df['load_mw'].sum() / 1e6:.1f} million MWh in summer 2025.
  The average grid emissions factor was {orig_ef:.4f} tons CO2/MWh
  ({orig_ef * 2000:.0f} lbs/MWh).

  If {DR_MW} MW of steam-chiller demand response had been deployed
  across all {len(dr_df)} hours of the summer:

    - {total_displaced_co2:,.0f} tons of CO2 would have been avoided
    - That's {total_displaced_co2 / total_orig_co2 * 100:.1f}% of Zone J's total grid emissions
    - The grid EF would have dropped from {orig_ef:.4f} to {new_ef:.4f} tons/MWh
      ({(new_ef/orig_ef - 1)*100:+.2f}% change)

  The marginal generators displaced by DR had an average emission rate
  of {dr_df['marginal_ef'].mean():.4f} tons/MWh — higher than the grid average,
  because DR displaces the dirtiest peakers first.
""")


if __name__ == "__main__":
    main()
