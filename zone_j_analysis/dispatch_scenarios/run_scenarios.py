"""
Run all DR dispatch scenarios and produce comparison output.

Scenarios:
  1. All hours      — 500 MW every hour of summer (upper bound)
  2. Peak hours     — weekday 12pm-8pm only
  3. Top 100 hours  — the 100 highest-load hours
  4. High-load days — hours when Zone J load > 8 GW
  5. NYISO DR proxy — hours when load > 90th percentile (simulates
                      NYISO calling DLRP/CSRP events)

Usage:
    python -m zone_j_analysis.dispatch_scenarios.run_scenarios
    # or
    cd zone_j_analysis/dispatch_scenarios && python run_scenarios.py
"""

import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared import (
    load_all_data, run_dr_scenario, estimate_price_impact,
    print_scenario_results, DR_MW, OUT_DIR,
)


def define_scenarios(merged):
    """Return dict of {name: (description, boolean_mask)}."""
    load = merged["load_mw"]
    hour_of_day = merged.index.hour
    day_of_week = merged.index.dayofweek
    is_weekday = day_of_week < 5

    p90_load = load.quantile(0.90)
    p75_load = load.quantile(0.75)

    # Top N hours by load
    top_100_threshold = load.nlargest(100).min()
    top_200_threshold = load.nlargest(200).min()

    scenarios = {
        "all_hours": (
            f"500 MW DR active every hour ({len(merged):,} hours)",
            pd.Series(True, index=merged.index),
        ),
        "peak_hours": (
            f"Weekday 12pm-8pm ({is_weekday & hour_of_day.isin(range(12, 20)).reindex(merged.index, fill_value=False).sum() if False else 'business peak hours'})",
            pd.Series(
                is_weekday & pd.Series(hour_of_day, index=merged.index).isin(range(12, 20)),
                index=merged.index,
            ),
        ),
        "top_100_hours": (
            f"100 highest-load hours (load >= {top_100_threshold:,.0f} MW)",
            load >= top_100_threshold,
        ),
        "top_200_hours": (
            f"200 highest-load hours (load >= {top_200_threshold:,.0f} MW)",
            load >= top_200_threshold,
        ),
        "high_load_8gw": (
            "Hours when Zone J load exceeds 8,000 MW",
            load >= 8000,
        ),
        "nyiso_dr_proxy": (
            f"Load > 90th percentile ({p90_load:,.0f} MW) — simulates NYISO DR events",
            load >= p90_load,
        ),
    }

    # Fix peak_hours mask
    scenarios["peak_hours"] = (
        "Weekday 12pm-8pm (business peak hours)",
        pd.Series(
            (day_of_week < 5) & np.isin(hour_of_day, range(12, 20)),
            index=merged.index,
        ),
    )

    return scenarios


def make_comparison_chart(all_results, out_path):
    """Bar chart comparing all scenarios."""
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    names = [r["name"] for r in all_results]
    short_names = [n.replace("_", "\n") for n in names]

    # 1. CO2 displaced (thousand tons)
    ax = axes[0, 0]
    vals = [r["displaced_co2"] / 1000 for r in all_results]
    bars = ax.barh(short_names, vals, color="#2171b5", edgecolor="white")
    ax.set_xlabel("Thousand short tons CO2 displaced")
    ax.set_title("CO2 Displaced by Scenario", fontweight="bold")
    for bar, v in zip(bars, vals):
        ax.text(bar.get_width() + 2, bar.get_y() + bar.get_height() / 2,
                f"{v:.0f}k", va="center", fontsize=9)
    ax.grid(axis="x", alpha=0.3)

    # 2. Active hours
    ax = axes[0, 1]
    vals = [r["active_hours"] for r in all_results]
    bars = ax.barh(short_names, vals, color="#fd8d3c", edgecolor="white")
    ax.set_xlabel("Active hours")
    ax.set_title("DR Active Hours by Scenario", fontweight="bold")
    for bar, v in zip(bars, vals):
        ax.text(bar.get_width() + 5, bar.get_y() + bar.get_height() / 2,
                f"{v:,}", va="center", fontsize=9)
    ax.grid(axis="x", alpha=0.3)

    # 3. CO2 displaced per active hour (efficiency)
    ax = axes[1, 0]
    vals = [r["displaced_co2"] / r["active_hours"] if r["active_hours"] > 0 else 0
            for r in all_results]
    bars = ax.barh(short_names, vals, color="#41ab5d", edgecolor="white")
    ax.set_xlabel("Tons CO2 displaced per active hour")
    ax.set_title("Efficiency: CO2 per Active Hour", fontweight="bold")
    for bar, v in zip(bars, vals):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{v:.0f}", va="center", fontsize=9)
    ax.grid(axis="x", alpha=0.3)

    # 4. Grid EF change
    ax = axes[1, 1]
    vals = [r["ef_change_pct"] for r in all_results]
    colors = ["#2171b5" if v < 0 else "#d45f00" for v in vals]
    bars = ax.barh(short_names, vals, color=colors, edgecolor="white")
    ax.set_xlabel("% change in grid emissions factor")
    ax.set_title("Grid Emissions Factor Change", fontweight="bold")
    for bar, v in zip(bars, vals):
        x = bar.get_width() - 0.3 if v < 0 else bar.get_width() + 0.1
        ax.text(x, bar.get_y() + bar.get_height() / 2,
                f"{v:+.2f}%", va="center", fontsize=9, ha="right" if v < 0 else "left")
    ax.grid(axis="x", alpha=0.3)

    plt.suptitle(f"Zone J Steam-Chiller DR Dispatch Scenarios — {DR_MW} MW, Summer 2025",
                 fontsize=14, fontweight="bold", y=1.01)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Comparison chart saved to {out_path}")


def make_scenario_detail_charts(scenario_results_dict, merged, out_path):
    """Time-series chart showing when each scenario is active and its impact."""
    scenarios_to_plot = ["all_hours", "peak_hours", "top_200_hours",
                         "high_load_8gw", "nyiso_dr_proxy"]
    scenarios_to_plot = [s for s in scenarios_to_plot if s in scenario_results_dict]

    fig, axes = plt.subplots(len(scenarios_to_plot) + 1, 1,
                             figsize=(16, 3.5 * (len(scenarios_to_plot) + 1)),
                             sharex=True)

    # Top panel: Zone J load
    ax = axes[0]
    daily_load = merged.resample("D")["load_mw"].agg(["mean", "max"])
    ax.fill_between(daily_load.index, 0, daily_load["max"] / 1000,
                    alpha=0.3, color="#4292c6", label="Daily peak")
    ax.plot(daily_load.index, daily_load["mean"] / 1000,
            color="#2171b5", linewidth=1.5, label="Daily avg")
    ax.set_ylabel("Load (GW)")
    ax.set_title("Zone J Load — Summer 2025", fontweight="bold")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)

    # Subsequent panels: displaced CO2 by scenario
    colors = ["#2171b5", "#fd8d3c", "#41ab5d", "#d94701", "#b467c4"]
    for i, scenario_name in enumerate(scenarios_to_plot):
        ax = axes[i + 1]
        dr_df = scenario_results_dict[scenario_name]["dr_df"]
        if len(dr_df) == 0:
            continue

        daily = dr_df.resample("D").agg(
            displaced=("displaced_co2", "sum"),
            hours=("displaced_co2", "count"),
        )
        # Reindex to full date range
        full_dates = pd.date_range(merged.index.min().date(), merged.index.max().date(), freq="D")
        daily = daily.reindex(full_dates, fill_value=0)

        color = colors[i % len(colors)]
        ax.bar(daily.index, daily["displaced"] / 1000, width=0.8,
               color=color, edgecolor="white", linewidth=0.3, alpha=0.85)
        ax.set_ylabel("kTons CO2\ndisplaced")

        result = scenario_results_dict[scenario_name]["summary"]
        ax.set_title(
            f"{scenario_name.replace('_', ' ').title()} — "
            f"{result['displaced_co2']:,.0f} tons total, "
            f"{result['active_hours']:,} hours active",
            fontweight="bold", fontsize=10,
        )
        ax.grid(axis="y", alpha=0.3)

    axes[-1].set_xlabel("Date")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Detail chart saved to {out_path}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    merged, units, lbmp_merged = load_all_data()

    scenarios = define_scenarios(merged)
    all_results = []
    scenario_details = {}

    for name, (description, mask) in scenarios.items():
        active_count = mask.sum()
        if active_count == 0:
            print(f"Skipping {name}: no active hours")
            continue

        dr_df = run_dr_scenario(merged, units, mask)
        price = estimate_price_impact(lbmp_merged, mask)
        summary = print_scenario_results(name, description, dr_df, merged, price)
        all_results.append(summary)
        scenario_details[name] = {"dr_df": dr_df, "summary": summary}

    # Comparison table
    print("\n" + "=" * 90)
    print("SCENARIO COMPARISON SUMMARY")
    print("=" * 90)
    print(f"\n  {'Scenario':<20} {'Hours':>7} {'CO2 Disp':>12} {'% Total':>8} "
          f"{'EF Chg':>8} {'Marg EF':>10} {'Price $M':>9}")
    print(f"  {'─'*20} {'─'*7} {'─'*12} {'─'*8} {'─'*8} {'─'*10} {'─'*9}")

    for r in all_results:
        price_str = f"${r['price_savings_m']:.0f}M" if r["price_savings_m"] else "n/a"
        print(f"  {r['name']:<20} {r['active_hours']:>7,} "
              f"{r['displaced_co2']:>12,.0f} {r['pct_of_total']:>7.1f}% "
              f"{r['ef_change_pct']:>+7.2f}% "
              f"{r['avg_marginal_ef']:>9.4f} "
              f"{price_str:>9}")

    # Save CSV
    results_df = pd.DataFrame(all_results)
    csv_path = os.path.join(OUT_DIR, "scenario_comparison.csv")
    results_df.to_csv(csv_path, index=False)
    print(f"\nResults saved to {csv_path}")

    # Charts
    make_comparison_chart(all_results, os.path.join(OUT_DIR, "scenario_comparison.png"))
    make_scenario_detail_charts(scenario_details, merged, os.path.join(OUT_DIR, "scenario_details.png"))


if __name__ == "__main__":
    main()
