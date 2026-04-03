"""
Shared data loading and marginal dispatch engine for all scenarios.

Loads data once, then each scenario calls run_dr_scenario() with a
boolean mask of which hours are active.
"""

import os
import zipfile
import glob as globmod
import pandas as pd
import numpy as np
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")
NYISO_DIR = os.path.join(DATA_DIR, "nyiso")
OUT_DIR = os.path.join(BASE_DIR, "dispatch_scenarios", "output")

ZONE_J_FACILITY_IDS = [
    2490, 2493, 2494, 2499, 2500, 2503, 2504, 7909, 7910, 7913,
    7914, 7915, 8053, 8906, 52168, 54114, 54914, 55375, 55699, 56196, 880100,
]

DR_MW = 500


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


def load_all_data():
    """Load and merge all data sources. Returns (merged_hourly, units, lbmp)."""
    print("Loading data...")

    # Zone J load
    load_df = load_nyiso_zips(os.path.join(NYISO_DIR, "*pal_csv.zip"))
    nyca = load_df.groupby("Time Stamp")["Load"].sum().reset_index()
    nyca.columns = ["Time Stamp", "NYCA_Load"]
    zj_load = load_df[load_df["Name"] == "N.Y.C."].copy()
    zj_load = zj_load.merge(nyca, on="Time Stamp")
    zj_load["J_Share"] = zj_load["Load"] / zj_load["NYCA_Load"]
    zj_load["hour"] = zj_load["Time Stamp"].dt.floor("h")
    print(f"  Zone J load: {len(zj_load):,} records")

    # Fuel mix
    fm = load_nyiso_zips(os.path.join(NYISO_DIR, "*rtfuelmix_csv.zip"))
    fm["hour"] = fm["Time Stamp"].dt.floor("h")
    fuel_mix = fm.groupby(["hour", "Fuel Category"])["Gen MW"].mean().reset_index()

    # CAMPD
    print("  Loading CAMPD data...")
    campd = pd.read_csv(
        os.path.join(DATA_DIR, "emissions-hourly-2025-ny.csv"),
        usecols=[
            "Facility ID", "Facility Name", "Unit ID", "Date", "Hour",
            "Gross Load (MW)", "CO2 Mass (short tons)", "Heat Input (mmBtu)",
            "Primary Fuel Type", "Unit Type",
        ],
        low_memory=False,
    )
    campd["Date"] = pd.to_datetime(campd["Date"])
    campd = campd[(campd["Date"] >= "2025-06-01") & (campd["Date"] <= "2025-08-31")]
    for col in ["Gross Load (MW)", "CO2 Mass (short tons)", "Heat Input (mmBtu)"]:
        campd[col] = pd.to_numeric(campd[col], errors="coerce")

    zj_campd = campd[campd["Facility ID"].isin(ZONE_J_FACILITY_IDS)].copy()
    zj_campd = zj_campd[zj_campd["Gross Load (MW)"] > 0]
    zj_campd["hour"] = pd.to_datetime(zj_campd["Date"]) + pd.to_timedelta(zj_campd["Hour"], unit="h")

    ny_all = campd[campd["Gross Load (MW)"] > 0].copy()
    ny_all["hour"] = pd.to_datetime(ny_all["Date"]) + pd.to_timedelta(ny_all["Hour"], unit="h")
    print(f"  CAMPD Zone J: {len(zj_campd):,} unit-hours, {zj_campd['Facility Name'].nunique()} plants")

    # ── Build merged hourly dataframe ──
    j_share = zj_load.groupby("hour").agg(
        load_mw=("Load", "mean"),
        j_share=("J_Share", "mean"),
    )
    zj_hourly = zj_campd.groupby("hour").agg(
        fossil_mw=("Gross Load (MW)", "sum"),
        fossil_co2=("CO2 Mass (short tons)", "sum"),
    )
    ny_hourly = ny_all.groupby("hour").agg(
        ny_mw=("Gross Load (MW)", "sum"),
        ny_co2=("CO2 Mass (short tons)", "sum"),
    )
    ny_hourly["ny_co2_per_mwh"] = ny_hourly["ny_co2"] / ny_hourly["ny_mw"]

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

    merged = j_share.join(zj_hourly, how="left").join(ny_hourly, how="left")
    merged = merged.join(fuel_pivot[["total_gen", "non_fossil_mw", "system_fossil_mw"]], how="left")
    merged = merged.dropna(subset=["load_mw", "total_gen"])
    merged["fossil_mw"] = merged["fossil_mw"].fillna(0)
    merged["fossil_co2"] = merged["fossil_co2"].fillna(0)

    merged["j_non_fossil_mw"] = merged["non_fossil_mw"] * merged["j_share"]
    merged["j_imported_fossil_mw"] = (
        merged["system_fossil_mw"] * merged["j_share"] - merged["fossil_mw"]
    ).clip(lower=0)
    merged["imported_fossil_co2"] = (
        merged["j_imported_fossil_mw"] * merged["ny_co2_per_mwh"]
    ).fillna(0)
    merged["total_co2"] = merged["fossil_co2"] + merged["imported_fossil_co2"]

    ny_avg_rate = ny_hourly["ny_co2"].sum() / ny_hourly["ny_mw"].sum()
    merged["ny_co2_per_mwh"] = merged["ny_co2_per_mwh"].fillna(ny_avg_rate)
    merged["month"] = merged.index.month

    # ── Build unit-level dispatch table ──
    units = zj_campd.copy()
    units = units[units["CO2 Mass (short tons)"].notna() & (units["CO2 Mass (short tons)"] > 0)]
    units["heat_rate"] = units["Heat Input (mmBtu)"] * 1000 / units["Gross Load (MW)"]
    units["co2_rate"] = units["CO2 Mass (short tons)"] / units["Gross Load (MW)"]
    units = units[units["co2_rate"].notna() & units["heat_rate"].notna()]

    # ── LBMP (DA and RT) ──
    da_lbmp = _load_lbmp("da")
    rt_lbmp = _load_lbmp("rt")
    load_hourly = zj_load.groupby("hour")["Load"].mean()

    lbmp_merged = None
    if da_lbmp is not None:
        da_hourly = da_lbmp.groupby("hour").agg(
            da_lbmp=("LBMP ($/MWHr)", "mean"),
            da_congestion=("Marginal Cost Congestion ($/MWHr)", "mean"),
            da_losses=("Marginal Cost Losses ($/MWHr)", "mean"),
        )
        lbmp_merged = da_hourly.join(load_hourly, how="inner")

    if rt_lbmp is not None:
        rt_hourly = rt_lbmp.groupby("hour").agg(
            rt_lbmp=("LBMP ($/MWHr)", "mean"),
            rt_congestion=("Marginal Cost Congestion ($/MWHr)", "mean"),
            rt_losses=("Marginal Cost Losses ($/MWHr)", "mean"),
        )
        if lbmp_merged is not None:
            lbmp_merged = lbmp_merged.join(rt_hourly, how="left")
        else:
            lbmp_merged = rt_hourly.join(load_hourly, how="inner")

    # Backwards compat: 'lbmp' column = DA if available, else RT
    if lbmp_merged is not None:
        if "da_lbmp" in lbmp_merged.columns:
            lbmp_merged["lbmp"] = lbmp_merged["da_lbmp"]
            lbmp_merged["marginal_cost_congestion"] = lbmp_merged["da_congestion"]
            lbmp_merged["marginal_cost_losses"] = lbmp_merged["da_losses"]

    print(f"  Merged hourly: {len(merged):,} hours")
    print("  Data loading complete.\n")

    return merged, units, lbmp_merged


def _load_lbmp(market="da"):
    """Load LBMP data. market='da' for day-ahead, 'rt' for real-time."""
    if market == "da":
        lbmp_dir = os.path.join(NYISO_DIR, "lbmp")
        url_path = "damlbmp"
        file_pattern = "damlbmp_zone_csv.zip"
    else:
        lbmp_dir = os.path.join(NYISO_DIR, "rt_lbmp")
        url_path = "realtime"
        file_pattern = "realtime_zone_csv.zip"

    os.makedirs(lbmp_dir, exist_ok=True)
    frames = []
    try:
        for month in ["20250601", "20250701", "20250801"]:
            filename = f"{month}{file_pattern}"
            dest = os.path.join(lbmp_dir, filename)
            if not os.path.exists(dest):
                url = f"http://mis.nyiso.com/public/csv/{url_path}/{filename}"
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
        zj = df[df["Name"] == "N.Y.C."].copy()
        zj["hour"] = zj["Time Stamp"].dt.floor("h")
        print(f"  {market.upper()} LBMP: {len(zj):,} records")
        return zj
    except Exception as e:
        print(f"  {market.upper()} LBMP fetch failed: {e}")
        return None


# ─── Dispatch engine ───────────────────────────────────────────────────────

def run_dr_scenario(merged_hourly, units, active_mask, dr_mw=DR_MW):
    """
    Run marginal dispatch for hours where active_mask is True.

    Parameters
    ----------
    merged_hourly : DataFrame
        Hourly Zone J data with total_co2, load_mw, ny_co2_per_mwh.
    units : DataFrame
        Unit-level CAMPD data with heat_rate, co2_rate.
    active_mask : Series[bool]
        Boolean series aligned with merged_hourly index. True = DR active.
    dr_mw : float
        MW of demand response to dispatch.

    Returns
    -------
    DataFrame with per-hour results (only active hours).
    """
    active_hours = merged_hourly.index[active_mask]
    results = []

    for hour in active_hours:
        row = merged_hourly.loc[hour]
        load = row["load_mw"]
        if load <= 0 or pd.isna(load):
            continue

        dr = min(dr_mw, load)
        hour_units = units[units["hour"] == hour].sort_values("heat_rate", ascending=False)

        remaining_dr = dr
        displaced_co2 = 0.0
        displaced_mw = 0.0

        for _, unit in hour_units.iterrows():
            if remaining_dr <= 0:
                break
            displace = min(remaining_dr, unit["Gross Load (MW)"])
            displaced_co2 += unit["co2_rate"] * displace
            displaced_mw += displace
            remaining_dr -= displace

        if remaining_dr > 0 and not pd.isna(row.get("ny_co2_per_mwh", np.nan)):
            displaced_co2 += remaining_dr * row["ny_co2_per_mwh"]
            displaced_mw += remaining_dr

        new_co2 = max(0, row["total_co2"] - displaced_co2)
        new_load = load - dr

        results.append({
            "hour": hour,
            "load_mw": load,
            "original_co2": row["total_co2"],
            "displaced_co2": displaced_co2,
            "displaced_mw": displaced_mw,
            "new_co2": new_co2,
            "new_load": new_load,
            "new_ef": new_co2 / new_load if new_load > 0 else 0,
            "marginal_ef": displaced_co2 / displaced_mw if displaced_mw > 0 else 0,
        })

    return pd.DataFrame(results).set_index("hour")


def estimate_price_impact(lbmp_merged, active_mask, dr_mw=DR_MW):
    """Estimate LBMP price reduction for active hours using quadratic fit.

    Uses RT LBMP if available, falls back to DA.
    """
    if lbmp_merged is None or len(lbmp_merged) == 0:
        return None

    # Use RT prices if available, otherwise DA
    price_col = "rt_lbmp" if "rt_lbmp" in lbmp_merged.columns else "lbmp"
    price_label = "RT" if price_col == "rt_lbmp" else "DA"

    valid = lbmp_merged.dropna(subset=["Load", price_col])
    valid = valid[(valid[price_col] > 0) & (valid[price_col] < valid[price_col].quantile(0.99))]

    if len(valid) < 20:
        return None

    coeffs = np.polyfit(valid["Load"].values, valid[price_col].values, deg=2)
    poly = np.poly1d(coeffs)

    # Apply only to active hours
    active = valid.loc[valid.index.isin(active_mask.index[active_mask])]
    if len(active) == 0:
        active = valid  # fallback: use all hours for estimate

    active = active.copy()
    active["price_original"] = poly(active["Load"])
    active["price_with_dr"] = poly(active["Load"] - dr_mw)
    active["savings_per_mwh"] = active["price_original"] - active["price_with_dr"]
    active["total_savings"] = active["savings_per_mwh"] * active["Load"]

    # Also compute direct RT savings (actual RT price × DR MW for active hours)
    # This is the simple "avoided energy cost" without supply curve modeling
    direct_savings = None
    if "rt_lbmp" in lbmp_merged.columns:
        active_rt = lbmp_merged.loc[
            lbmp_merged.index.isin(active_mask.index[active_mask])
        ].dropna(subset=["rt_lbmp"])
        if len(active_rt) > 0:
            # DR avoids purchasing dr_mw at the RT price
            direct_savings = (active_rt["rt_lbmp"] * dr_mw).sum() / 1e6

    peak_mask = (valid.index.hour.isin(range(14, 19))) & (valid.index.dayofweek < 5)

    return {
        "price_source": price_label,
        "avg_lbmp": valid[price_col].mean(),
        "avg_peak_lbmp": valid.loc[peak_mask, price_col].mean() if peak_mask.any() else 0,
        "max_lbmp": lbmp_merged[price_col].max() if price_col in lbmp_merged.columns else 0,
        "avg_savings_per_mwh": active["savings_per_mwh"].mean(),
        "total_consumer_savings_m": active["total_savings"].sum() / 1e6,
        "direct_avoided_cost_m": direct_savings,
        "active_hours": len(active),
        "poly": poly,
    }


def print_scenario_results(name, description, dr_df, merged_hourly, price_info=None):
    """Print standardized results for a scenario."""
    total_hours = len(merged_hourly)
    active_hours = len(dr_df)
    total_orig_co2 = merged_hourly["total_co2"].sum()
    total_orig_load = merged_hourly["load_mw"].sum()
    orig_ef = total_orig_co2 / total_orig_load

    displaced = dr_df["displaced_co2"].sum()
    new_total_co2 = total_orig_co2 - displaced
    new_ef = new_total_co2 / (total_orig_load - dr_df["displaced_mw"].sum())

    active_orig_co2 = dr_df["original_co2"].sum() if "original_co2" in dr_df else 0
    active_orig_load = dr_df["load_mw"].sum() if "load_mw" in dr_df else 0

    print("=" * 70)
    print(f"SCENARIO: {name}")
    print(f"  {description}")
    print("=" * 70)

    print(f"\n  Active hours:                  {active_hours:>6,} / {total_hours:,} ({active_hours/total_hours*100:.1f}%)")
    print(f"  DR capacity:                   {DR_MW:>6,} MW")

    print(f"\n  CO2 displaced:                 {displaced:>12,.0f} short tons")
    print(f"  % of summer total:             {displaced / total_orig_co2 * 100:>11.1f}%")

    print(f"\n  Grid EF (full summer):")
    print(f"    Original:                    {orig_ef:.4f} tons/MWh ({orig_ef * 2000:.0f} lbs/MWh)")
    print(f"    With DR:                     {new_ef:.4f} tons/MWh ({new_ef * 2000:.0f} lbs/MWh)")
    print(f"    Change:                      {(new_ef/orig_ef - 1)*100:+.2f}%")

    if len(dr_df) > 0:
        avg_marginal = dr_df["marginal_ef"].mean()
        print(f"\n  Avg marginal emission rate:    {avg_marginal:.4f} tons/MWh ({avg_marginal * 2000:.0f} lbs/MWh)")
        print(f"  (Rate of generators actually displaced by DR)")

    if price_info:
        src = price_info.get("price_source", "DA")
        print(f"\n  Electricity price impact ({src} LBMP):")
        print(f"    Avg {src} LBMP:                 ${price_info['avg_lbmp']:.2f} / MWh")
        print(f"    Peak {src} LBMP (wkday 2-6pm):  ${price_info['avg_peak_lbmp']:.2f} / MWh")
        print(f"    Max {src} LBMP:                  ${price_info['max_lbmp']:,.2f} / MWh")
        print(f"    Avg price reduction:         ${price_info['avg_savings_per_mwh']:.2f} / MWh")
        print(f"    Consumer savings (est.):     ${price_info['total_consumer_savings_m']:.1f} million")
        if price_info.get("direct_avoided_cost_m") is not None:
            print(f"    Direct avoided RT cost:      ${price_info['direct_avoided_cost_m']:.1f} million")
            print(f"    (= {DR_MW} MW × RT price for each active hour)")

    print()
    return {
        "name": name,
        "active_hours": active_hours,
        "displaced_co2": displaced,
        "pct_of_total": displaced / total_orig_co2 * 100,
        "orig_ef": orig_ef,
        "new_ef": new_ef,
        "ef_change_pct": (new_ef / orig_ef - 1) * 100,
        "avg_marginal_ef": dr_df["marginal_ef"].mean() if len(dr_df) > 0 else 0,
        "price_savings_m": price_info["total_consumer_savings_m"] if price_info else None,
        "rt_avoided_m": price_info.get("direct_avoided_cost_m") if price_info else None,
    }
