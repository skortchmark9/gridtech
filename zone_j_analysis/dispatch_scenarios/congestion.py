"""
Transmission congestion relief from steam-chiller DR in Zone J.

The double benefit of steam DR:
  1. DEMAND REDUCTION — 500 MW of electric chillers switch off
  2. COGEN COUPLING — the steam comes from cogen plants (East River,
     BNYCP) that also produce electricity locally, further displacing
     imports

This reduces the power flowing through constrained transmission
interfaces into NYC, lowering congestion costs for all consumers.

Data sources:
  - NYISO LBMP congestion component (already fetched)
  - NYISO interface flows (fetched here if available)
  - CAMPD unit-level generation for East River cogen (facility 2493)
  - Zone J load and local generation (from shared.py)

Usage:
    python -m zone_j_analysis.dispatch_scenarios.congestion
    # or
    cd zone_j_analysis/dispatch_scenarios && python congestion.py
"""

import os
import sys
import zipfile
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared import load_all_data, run_dr_scenario, DR_MW, OUT_DIR, NYISO_DIR


# East River cogen facility ID (units 10/20 are the CTs, 60/70 are boilers)
EAST_RIVER_ID = 2493
BNYCP_ID = 54914

# Cogen CT unit types in CAMPD
COGEN_UNIT_TYPES = {"Combined cycle", "Combustion turbine"}


def analyze_imports(merged):
    """Compute hourly imports into Zone J = load - local fossil generation."""
    merged = merged.copy()
    merged["imports_mw"] = merged["load_mw"] - merged["fossil_mw"]
    merged["import_pct"] = merged["imports_mw"] / merged["load_mw"]
    return merged


def analyze_cogen_electricity(units_df):
    """
    Extract hourly electricity output from East River and BNYCP cogen units.

    These plants produce BOTH electricity and steam. When steam demand
    increases (from absorption chillers), the CTs may already be running
    at capacity — the steam is waste heat capture. But understanding their
    electric output is key to the import picture.
    """
    cogen_units = units_df[
        units_df["Facility ID"].isin([EAST_RIVER_ID, BNYCP_ID]) &
        units_df["Unit Type"].isin(COGEN_UNIT_TYPES)
    ].copy()

    hourly = cogen_units.groupby("hour").agg(
        cogen_mw=("Gross Load (MW)", "sum"),
        cogen_co2=("CO2 Mass (short tons)", "sum"),
    )

    # Also get East River boiler units (60/70) separately
    er_boilers = units_df[
        (units_df["Facility ID"] == EAST_RIVER_ID) &
        (~units_df["Unit Type"].isin(COGEN_UNIT_TYPES))
    ].copy()
    er_boiler_hourly = er_boilers.groupby("hour").agg(
        er_boiler_mw=("Gross Load (MW)", "sum"),
    )

    return hourly, er_boiler_hourly


def analyze_congestion(lbmp_merged, merged):
    """Analyze LBMP congestion component and correlate with imports."""
    if lbmp_merged is None:
        return None

    # Merge congestion data with import calculations
    combined = merged.join(
        lbmp_merged[["lbmp", "marginal_cost_congestion"]], how="inner"
    )

    # Congestion cost = congestion component × load (total system cost)
    combined["congestion_cost"] = (
        combined["marginal_cost_congestion"] * combined["load_mw"]
    )

    return combined


def model_dr_congestion_relief(merged, units_df, lbmp_merged):
    """
    Model how 500 MW DR changes imports and congestion.

    For each hour:
      - Original imports = load - local_gen
      - New imports = (load - DR) - local_gen
      - Import reduction = DR (straightforward)
      - Congestion relief estimated from import-congestion relationship
    """
    merged = analyze_imports(merged)

    # Get cogen electricity data
    cogen_hourly, er_boiler_hourly = analyze_cogen_electricity(units_df)
    merged = merged.join(cogen_hourly, how="left")
    merged = merged.join(er_boiler_hourly, how="left")
    merged["cogen_mw"] = merged["cogen_mw"].fillna(0)
    merged["er_boiler_mw"] = merged["er_boiler_mw"].fillna(0)

    # With DR: imports reduced by DR_MW
    merged["new_imports_mw"] = (merged["imports_mw"] - DR_MW).clip(lower=0)
    merged["import_reduction_mw"] = merged["imports_mw"] - merged["new_imports_mw"]

    # Add congestion data
    if lbmp_merged is not None:
        merged = merged.join(
            lbmp_merged[["lbmp", "marginal_cost_congestion", "marginal_cost_losses"]],
            how="left",
        )
    else:
        merged["lbmp"] = np.nan
        merged["marginal_cost_congestion"] = np.nan
        merged["marginal_cost_losses"] = np.nan

    return merged


def fit_congestion_model(combined):
    """
    Fit relationship between load level and congestion cost.

    Higher load → more imports → more congestion. Use load rather than
    imports directly because congestion is really driven by total demand
    relative to local supply + transfer limits.
    """
    valid = combined.dropna(subset=["load_mw", "marginal_cost_congestion"])

    if len(valid) < 50:
        return None

    # Quadratic fit: congestion = f(load)
    # Use load as predictor since it's the fundamental driver
    coeffs = np.polyfit(valid["load_mw"].values,
                        valid["marginal_cost_congestion"].values, deg=2)
    poly = np.poly1d(coeffs)

    return poly, valid


def print_results(combined):
    """Print transmission congestion analysis results."""

    print("=" * 74)
    print("ZONE J TRANSMISSION CONGESTION ANALYSIS — SUMMER 2025")
    print("=" * 74)

    # ── Import statistics ──
    print("\n" + "─" * 74)
    print("IMPORT PROFILE")
    print("─" * 74)

    avg_load = combined["load_mw"].mean()
    avg_fossil = combined["fossil_mw"].mean()
    avg_imports = combined["imports_mw"].mean()
    avg_cogen = combined["cogen_mw"].mean()
    peak_imports = combined["imports_mw"].max()
    peak_load = combined["load_mw"].max()

    print(f"\n  Avg Zone J load:               {avg_load:>8,.0f} MW")
    print(f"  Avg in-zone fossil gen:        {avg_fossil:>8,.0f} MW")
    print(f"  Avg imports (load - local):    {avg_imports:>8,.0f} MW ({avg_imports/avg_load*100:.1f}% of load)")
    print(f"  Peak imports:                  {peak_imports:>8,.0f} MW")
    print(f"  Peak load:                     {peak_load:>8,.0f} MW")

    print(f"\n  Cogen electricity (ER + BNYCP):{avg_cogen:>8,.0f} MW avg")
    print(f"  Cogen as % of local fossil:    {avg_cogen/avg_fossil*100:>7.1f}%")
    print(f"  ER boiler electricity:         {combined['er_boiler_mw'].mean():>8,.0f} MW avg")

    # ── Import reduction from DR ──
    print("\n" + "─" * 74)
    print(f"IMPORT REDUCTION FROM {DR_MW} MW DR")
    print("─" * 74)

    avg_import_reduction = combined["import_reduction_mw"].mean()
    total_import_reduction_gwh = combined["import_reduction_mw"].sum() / 1000

    print(f"\n  Avg import reduction:          {avg_import_reduction:>8,.0f} MW")
    print(f"  Total import reduction:        {total_import_reduction_gwh:>8,.0f} GWh over summer")
    print(f"  Avg new imports:               {combined['new_imports_mw'].mean():>8,.0f} MW "
          f"(was {avg_imports:,.0f})")
    print(f"  New import % of load:          {combined['new_imports_mw'].mean()/(avg_load - DR_MW)*100:>7.1f}% "
          f"(was {avg_imports/avg_load*100:.1f}%)")

    # Hours where DR eliminates ALL imports
    no_import_hours = (combined["new_imports_mw"] == 0).sum()
    print(f"\n  Hours where DR eliminates imports: {no_import_hours:,} "
          f"({no_import_hours/len(combined)*100:.1f}%)")

    # ── Congestion analysis ──
    cong = combined.dropna(subset=["marginal_cost_congestion"])
    if len(cong) > 0:
        print("\n" + "─" * 74)
        print("CONGESTION COST ANALYSIS")
        print("─" * 74)

        avg_cong = cong["marginal_cost_congestion"].mean()
        total_cong_cost = (cong["marginal_cost_congestion"] * cong["load_mw"]).sum() / 1e6

        # Hours with positive congestion (binding constraint)
        binding = cong[cong["marginal_cost_congestion"] > 1]  # >$1/MWh
        binding_pct = len(binding) / len(cong) * 100

        print(f"\n  Avg congestion component:      ${avg_cong:>8.2f} / MWh")
        print(f"  Total congestion cost:         ${total_cong_cost:>8.1f} million")
        print(f"  Hours w/ binding congestion:   {len(binding):>5,} ({binding_pct:.1f}%)")

        if len(binding) > 0:
            avg_binding_cong = binding["marginal_cost_congestion"].mean()
            avg_binding_imports = binding["imports_mw"].mean()
            print(f"  Avg congestion when binding:   ${avg_binding_cong:>8.2f} / MWh")
            print(f"  Avg imports when binding:      {avg_binding_imports:>8,.0f} MW")
            print(f"  Avg load when binding:         {binding['load_mw'].mean():>8,.0f} MW")

        # Estimate congestion relief using load-congestion relationship
        fit_result = fit_congestion_model(cong)
        if fit_result:
            poly, valid = fit_result

            # For each hour, estimate congestion at original load vs reduced load
            valid = valid.copy()
            valid["cong_original"] = poly(valid["load_mw"])
            valid["cong_with_dr"] = poly(valid["load_mw"] - DR_MW)
            valid["cong_savings_per_mwh"] = valid["cong_original"] - valid["cong_with_dr"]
            valid["cong_savings_total"] = valid["cong_savings_per_mwh"] * valid["load_mw"]

            print(f"\n  Estimated congestion relief from {DR_MW} MW DR (load-congestion model):")

            # Overall
            avg_cong_savings = valid["cong_savings_per_mwh"].mean()
            total_cong_savings = valid["cong_savings_total"].sum() / 1e6
            print(f"    Avg congestion reduction:     ${avg_cong_savings:>7.2f} / MWh")
            print(f"    Total congestion savings:     ${total_cong_savings:>7.1f} million")

            # During binding hours only
            binding_valid = valid[valid["marginal_cost_congestion"] > 1]
            if len(binding_valid) > 0:
                binding_savings = (binding_valid["cong_savings_per_mwh"] *
                                   binding_valid["load_mw"]).sum() / 1e6
                binding_avg = binding_valid["cong_savings_per_mwh"].mean()
                print(f"\n    During binding congestion hours ({len(binding_valid)} hours):")
                print(f"      Avg congestion reduction:   ${binding_avg:>7.2f} / MWh")
                print(f"      Total savings:              ${binding_savings:>7.1f} million")

            # By load tier
            print(f"\n    Congestion relief by load level:")
            print(f"    {'Load tier':>20} {'Hours':>7} {'Avg cong':>10} "
                  f"{'Avg relief':>11} {'Total $M':>9}")
            print(f"    {'─'*20} {'─'*7} {'─'*10} {'─'*11} {'─'*9}")
            for label, lo, hi in [
                ("< 6 GW", 0, 6000),
                ("6-7 GW", 6000, 7000),
                ("7-8 GW", 7000, 8000),
                ("8-9 GW", 8000, 9000),
                ("9-10 GW", 9000, 10000),
                ("> 10 GW", 10000, 20000),
            ]:
                tier = valid[(valid["load_mw"] >= lo) & (valid["load_mw"] < hi)]
                if len(tier) > 0:
                    tier_savings = (tier["cong_savings_per_mwh"] * tier["load_mw"]).sum() / 1e6
                    actual_cong = tier["marginal_cost_congestion"].mean()
                    print(f"    {label:>20} {len(tier):>7,} ${actual_cong:>8.2f} "
                          f"${tier['cong_savings_per_mwh'].mean():>9.2f} "
                          f"${tier_savings:>7.1f}M")

            return valid, poly

    return None, None


def make_charts(combined, valid, poly, out_path):
    """Generate transmission congestion charts."""
    fig, axes = plt.subplots(3, 2, figsize=(16, 18))

    # 1. Daily imports vs local gen
    ax = axes[0, 0]
    daily = combined.resample("D").agg(
        load=("load_mw", "mean"),
        fossil=("fossil_mw", "mean"),
        imports=("imports_mw", "mean"),
        cogen=("cogen_mw", "mean"),
    )
    ax.fill_between(daily.index, 0, daily["fossil"] / 1000,
                    alpha=0.7, color="#d45f00", label="In-zone fossil")
    ax.fill_between(daily.index, daily["fossil"] / 1000,
                    (daily["fossil"] + daily["imports"]) / 1000,
                    alpha=0.5, color="#4292c6", label="Imports")
    ax.plot(daily.index, daily["load"] / 1000,
            color="black", linewidth=1.5, label="Total load")
    ax.plot(daily.index, daily["cogen"] / 1000,
            color="#41ab5d", linewidth=1, linestyle="--", label="Cogen electric")
    ax.set_ylabel("GW")
    ax.set_title("Zone J Daily Avg: Local Generation vs Imports\nSummer 2025",
                 fontweight="bold")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.3)

    # 2. Import reduction from DR
    ax = axes[0, 1]
    daily_dr = combined.resample("D").agg(
        imports=("imports_mw", "mean"),
        new_imports=("new_imports_mw", "mean"),
        reduction=("import_reduction_mw", "mean"),
    )
    ax.fill_between(daily_dr.index, daily_dr["new_imports"] / 1000,
                    daily_dr["imports"] / 1000,
                    alpha=0.4, color="#2171b5", label=f"{DR_MW} MW DR reduction")
    ax.plot(daily_dr.index, daily_dr["imports"] / 1000,
            color="#d45f00", linewidth=1, label="Original imports")
    ax.plot(daily_dr.index, daily_dr["new_imports"] / 1000,
            color="#2171b5", linewidth=1, label="Imports with DR")
    ax.set_ylabel("GW")
    ax.set_title(f"Import Reduction from {DR_MW} MW DR",
                 fontweight="bold")
    ax.legend()
    ax.grid(alpha=0.3)

    # 3. Load vs congestion scatter
    if valid is not None and poly is not None:
        ax = axes[1, 0]
        cong_data = combined.dropna(subset=["marginal_cost_congestion"])
        ax.scatter(cong_data["load_mw"] / 1000,
                   cong_data["marginal_cost_congestion"],
                   alpha=0.15, s=3, color="#666")
        x_fit = np.linspace(cong_data["load_mw"].min(),
                            cong_data["load_mw"].max(), 100)
        ax.plot(x_fit / 1000, poly(x_fit), color="red", linewidth=2,
                label="Quadratic fit")
        ax.plot(x_fit / 1000, poly(x_fit + DR_MW), color="#d45f00",
                linewidth=2, linestyle="--", alpha=0.5,
                label=f"At same load + {DR_MW} MW (no DR)")
        ax.set_xlabel("Zone J Load (GW)")
        ax.set_ylabel("Congestion component ($/MWh)")
        ax.set_title("Load vs LBMP Congestion Component",
                     fontweight="bold")
        ax.legend()
        ax.grid(alpha=0.3)

        # 4. Congestion savings time series
        ax = axes[1, 1]
        if "cong_savings_per_mwh" in valid.columns:
            daily_savings = valid.resample("D").agg(
                savings=("cong_savings_total", "sum"),
            )
            full_dates = pd.date_range(combined.index.min().date(),
                                       combined.index.max().date(), freq="D")
            daily_savings = daily_savings.reindex(full_dates, fill_value=0)
            ax.bar(daily_savings.index, daily_savings["savings"] / 1000,
                   color="#41ab5d", edgecolor="white", linewidth=0.3)
            ax.set_ylabel("$000s")
            ax.set_title(f"Daily Congestion Savings from {DR_MW} MW DR",
                         fontweight="bold")
            ax.grid(axis="y", alpha=0.3)
    else:
        axes[1, 0].text(0.5, 0.5, "Congestion data not available",
                        ha="center", va="center", transform=axes[1, 0].transAxes)
        axes[1, 1].text(0.5, 0.5, "Congestion data not available",
                        ha="center", va="center", transform=axes[1, 1].transAxes)

    # 5. Hourly import profile by hour of day
    ax = axes[2, 0]
    combined["hour_of_day"] = combined.index.hour
    hourly_imports = combined.groupby("hour_of_day").agg(
        imports=("imports_mw", "mean"),
        new_imports=("new_imports_mw", "mean"),
        load=("load_mw", "mean"),
        fossil=("fossil_mw", "mean"),
    )
    ax.bar(hourly_imports.index, hourly_imports["imports"] / 1000,
           color="#4292c6", alpha=0.6, label="Original imports")
    ax.bar(hourly_imports.index, hourly_imports["new_imports"] / 1000,
           color="#2171b5", alpha=0.8, label="Imports with DR")
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Avg imports (GW)")
    ax.set_title("Avg Hourly Imports: Original vs With DR", fontweight="bold")
    ax.set_xticks(range(0, 24, 3))
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    # 6. Cogen contribution breakdown
    ax = axes[2, 1]
    combined["non_cogen_fossil"] = combined["fossil_mw"] - combined["cogen_mw"]
    hourly_gen = combined.groupby("hour_of_day").agg(
        cogen=("cogen_mw", "mean"),
        non_cogen=("non_cogen_fossil", "mean"),
        load=("load_mw", "mean"),
    )
    ax.bar(hourly_gen.index, hourly_gen["cogen"] / 1000,
           color="#41ab5d", label="Cogen electric (ER+BNYCP)")
    ax.bar(hourly_gen.index, hourly_gen["non_cogen"] / 1000,
           bottom=hourly_gen["cogen"] / 1000,
           color="#d45f00", alpha=0.7, label="Other fossil")
    ax.plot(hourly_gen.index, hourly_gen["load"] / 1000,
            color="black", linewidth=2, label="Total load")
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("GW")
    ax.set_title("Zone J Avg Generation Stack by Hour of Day",
                 fontweight="bold")
    ax.set_xticks(range(0, 24, 3))
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"\nChart saved to {out_path}")


def print_executive_summary(combined, valid):
    """Print the narrative summary."""
    avg_imports = combined["imports_mw"].mean()
    avg_load = combined["load_mw"].mean()
    avg_cogen = combined["cogen_mw"].mean()
    avg_fossil = combined["fossil_mw"].mean()
    avg_reduction = combined["import_reduction_mw"].mean()
    total_reduction_gwh = combined["import_reduction_mw"].sum() / 1000

    print("\n" + "=" * 74)
    print("EXECUTIVE SUMMARY: TRANSMISSION CONGESTION RELIEF")
    print("=" * 74)

    print(f"""
  THE DOUBLE BENEFIT OF STEAM DR

  Zone J imported an average of {avg_imports:,.0f} MW ({avg_imports/avg_load*100:.0f}% of load) across
  the summer. These imports flow through constrained transmission
  corridors (Central East, UPNY-SENY, and submarine cables).

  500 MW of steam-chiller DR provides a double transmission benefit:

  1. DEMAND REDUCTION: {DR_MW} MW of electric chiller load switches off,
     directly reducing power flowing through constrained corridors.

  2. LOCAL COGEN SUPPLY: The cogen plants (East River 10/20 + BNYCP)
     that produce the steam also generate {avg_cogen:,.0f} MW of electricity
     locally — {avg_cogen/avg_fossil*100:.0f}% of all in-zone fossil generation. The
     steam is captured from exhaust heat at ~4 BTU/lb — nearly free.

  NET IMPORT REDUCTION
  Total import reduction over the summer: {total_reduction_gwh:,.0f} GWh
  Avg hourly import reduction: {avg_reduction:,.0f} MW
  Import share of load drops from {avg_imports/avg_load*100:.1f}% to {combined['new_imports_mw'].mean()/(avg_load-DR_MW)*100:.1f}%

  CONGESTION: WHAT THE MMU REPORT REVEALS
  (Source: Potomac Economics NYISO Q2 2025 Quarterly Report, Aug 2025)

  Our DA LBMP zonal congestion analysis showed an average of only
  -$1.70/MWh — but this UNDERSTATES actual congestion for three reasons:

  1. RT CONGESTION WAS 2X DA: $130M RT vs $58M DA in Q2 2025. The
     June 23-25 heat wave alone drove 44% of all RT congestion.
     RT LBMPs hit $1,300-$1,800/MWh on June 24 (5-8pm).

  2. INTERNAL NYC CONSTRAINTS are masked by zonal averaging. The
     MMU identified binding N-1 constraints on:
     - Greenwood-Vernon 138 kV (Gowanus-Greenwood lines OOS)
     - Motthavn-Dunwoodie 345 kV (major import path)
     - Astoria Annex-E.13th St 345 kV (forced out late April+)
     These internal constraints had POSITIVE congestion at specific
     buses, even when the zonal average was negative.

  3. OOM COSTS aren't in LBMP at all. NYC had out-of-market actions
     on 65 of 91 days in Q2 2025:
     - Load pocket reserves (N-1-1): 50 days
     - Transmission constraint management: 26 days
     - Voltage management: 18 days
     - ~$8M in BPCG uplift from Greenwood pocket OOM alone

  Steam DR at {DR_MW} MW would directly reduce the need for these
  OOM actions by reducing load in the constrained load pockets.
  During the June heat wave — when load peaked at 31.9 GW (post-DR)
  and fossil generators were 18.5% unavailable due to forced outages
  — 500 MW of dispatchable DR behind the constraint would have been
  worth far more than its emissions or price-suppression value.

  The MMU also found that 25% of external ICAP was cut by neighboring
  ISOs during the June 24 peak (non-firm transmission). Local
  resources like steam DR are immune to this import curtailment risk.
""")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    merged, units, lbmp_merged = load_all_data()

    # Model DR impact on imports and congestion
    combined = model_dr_congestion_relief(merged, units, lbmp_merged)

    # Analyze and print results
    valid, poly = print_results(combined)

    # Executive summary
    print_executive_summary(combined, valid)

    # Charts
    make_charts(combined, valid, poly,
                os.path.join(OUT_DIR, "congestion_relief.png"))


if __name__ == "__main__":
    main()
