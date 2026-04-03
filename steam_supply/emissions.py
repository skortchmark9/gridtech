"""
Emissions and venting analysis for ConEd steam system plants.

Computes:
  1. CO2 emission factors per station (lbs CO2 per Mlb steam)
  2. Cogen emission allocation under three methods
  3. Estimated steam venting (HRSG production vs actual sendout)
  4. System-wide blended emission factors by season

Data sources:
  - EPA CAMPD hourly emissions (2025) for facilities 2493, 2503, 2504, 54914
  - ConEd 2025 PSC filing sendout data (from plants.py)
"""

import csv
import json
import pandas as pd
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from plants import STATION_SENDOUT, compute_system_summary, SUMMER_HOURS, WINTER_HOURS

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMPD_FILE = os.path.join(BASE, "data", "emissions-hourly-2025-ny.csv")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Facility IDs
EAST_RIVER = 2493
FIFTY_NINTH = 2503
SEVENTY_FOURTH = 2504
BNY = 54914

# Steam enthalpy at ConEd delivery conditions (~165 psig, 358°F)
STEAM_ENTHALPY_BTU_LB = 1195

# HRSG heat balance parameters (for venting estimate)
STACK_LOSS_PCT = 0.12       # fraction of fuel energy lost out the stack after HRSG
HRSG_RECOVERY_PCT = 0.88    # fraction of exhaust heat captured as steam
NET_ENTHALPY_BTU_LB = 1000  # net enthalpy gain per lb (delivery minus feedwater)

# Natural gas emission factor
NG_CO2_LBS_PER_MMBTU = 117.0


def load_campd():
    print(f"Loading {CAMPD_FILE}...")
    df = pd.read_csv(CAMPD_FILE, low_memory=False, parse_dates=["Date"])
    df["month"] = df["Date"].dt.month
    df["is_summer"] = df["month"].isin([5, 6, 7, 8, 9, 10])
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# BOILER EMISSION FACTORS
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_boiler_station(df, facility_id, name):
    """Boiler-only stations: all fuel/emissions are attributable to steam."""
    fac = df[df["Facility ID"] == facility_id].copy()
    for col in ["Steam Load (1000 lb/hr)", "CO2 Mass (short tons)", "Heat Input (mmBtu)"]:
        fac[col] = pd.to_numeric(fac[col], errors="coerce")

    active = fac[fac["Steam Load (1000 lb/hr)"] > 0]
    summer = active[active["is_summer"]]
    winter = active[~active["is_summer"]]

    def stats(subset):
        steam = subset["Steam Load (1000 lb/hr)"].sum()
        co2 = subset["CO2 Mass (short tons)"].sum()
        heat = subset["Heat Input (mmBtu)"].sum()
        # Some stations (59th St) don't report CO2 via CEMS — estimate from heat input
        if co2 == 0 and heat > 0:
            co2 = heat * NG_CO2_LBS_PER_MMBTU / 2000  # short tons
            co2_source = "estimated"
        else:
            co2_source = "CEMS"
        co2_per_mlb = co2 / steam if steam > 0 else 0
        return {
            "steam_mlb": steam,
            "co2_tons": co2,
            "co2_source": co2_source,
            "heat_mmbtu": heat,
            "co2_per_mlb": co2_per_mlb,
            "co2_lbs_per_mlb": co2_per_mlb * 2000,
        }

    return {
        "name": name,
        "facility_id": facility_id,
        "type": "boiler",
        "annual": stats(active),
        "summer": stats(summer),
        "winter": stats(winter),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# COGEN EMISSION FACTORS + ALLOCATION
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_cogen_station(df, facility_id, name):
    """
    Cogen stations produce both electricity and steam. CAMPD reports
    electric output + fuel for the CT/CC units, but not the steam output
    (which goes to ConEd's district system). We use PSC sendout data for
    steam volumes and compute emission factors under three allocation methods.
    """
    fac = df[df["Facility ID"] == facility_id].copy()
    cogen_types = {"Combined cycle", "Combustion turbine"}
    is_ct = fac["Unit Type"].isin(cogen_types)

    ct_units = fac[is_ct].copy()
    boiler_units = fac[~is_ct].copy()

    for sub in [ct_units, boiler_units]:
        for col in ["Gross Load (MW)", "CO2 Mass (short tons)", "Heat Input (mmBtu)", "Steam Load (1000 lb/hr)"]:
            sub[col] = pd.to_numeric(sub[col], errors="coerce")

    # Get PSC sendout data
    if facility_id == EAST_RIVER:
        psc = next(s for s in STATION_SENDOUT if s["station_group"] == "East River 10 and 20")
    elif facility_id == BNY:
        psc = next(s for s in STATION_SENDOUT if s["station_group"] == "BNYCP")
    else:
        psc = None

    def ct_stats(subset, steam_sendout_mlb):
        mwh = subset["Gross Load (MW)"].sum()
        co2 = subset["CO2 Mass (short tons)"].sum()
        heat = subset["Heat Input (mmBtu)"].sum()
        hours = len(subset[subset["Gross Load (MW)"] > 0])
        elec_eff = (mwh * 3.412 / heat) if heat > 0 else 0

        # Electric-only emission rate (naive, ignoring steam)
        co2_per_mwh = co2 / mwh if mwh > 0 else 0
        co2_lbs_per_mwh = co2_per_mwh * 2000

        # ── Allocation methods ──
        electric_energy_mmbtu = mwh * 3.412
        steam_energy_mmbtu = steam_sendout_mlb * 1000 * STEAM_ENTHALPY_BTU_LB / 1e6
        total_useful = electric_energy_mmbtu + steam_energy_mmbtu
        steam_share = steam_energy_mmbtu / total_useful if total_useful > 0 else 0

        # Method 1: Energy allocation
        m1_co2_per_mlb = (co2 * steam_share / steam_sendout_mlb) if steam_sendout_mlb > 0 else 0

        # Method 2: Avoided burden (steam charged at boiler rate ~1,500 btu/lb)
        boiler_equiv_heat = steam_sendout_mlb * 1000 * 1500 / 1e6  # mmBtu
        boiler_equiv_co2 = boiler_equiv_heat * NG_CO2_LBS_PER_MMBTU / 2000
        m2_co2_per_mlb = boiler_equiv_co2 / steam_sendout_mlb if steam_sendout_mlb > 0 else 0

        # Method 3: Marginal (CTs run for electricity, steam is free byproduct)
        m3_co2_per_mlb = 0

        return {
            "mwh": mwh,
            "co2_tons": co2,
            "heat_mmbtu": heat,
            "operating_hours": hours,
            "elec_efficiency": elec_eff,
            "co2_per_mwh": co2_per_mwh,
            "co2_lbs_per_mwh": co2_lbs_per_mwh,
            "steam_sendout_mlb": steam_sendout_mlb,
            "allocation": {
                "energy":        {"co2_per_mlb": m1_co2_per_mlb, "co2_lbs_per_mlb": m1_co2_per_mlb * 2000},
                "avoided_burden": {"co2_per_mlb": m2_co2_per_mlb, "co2_lbs_per_mlb": m2_co2_per_mlb * 2000},
                "marginal":      {"co2_per_mlb": m3_co2_per_mlb, "co2_lbs_per_mlb": 0},
            },
        }

    # Boiler units at the same facility (ER units 60, 70)
    boiler_active = boiler_units[boiler_units["Steam Load (1000 lb/hr)"] > 0]
    boiler_steam = boiler_active["Steam Load (1000 lb/hr)"].sum()
    boiler_co2 = boiler_active["CO2 Mass (short tons)"].sum()
    boiler_heat = boiler_active["Heat Input (mmBtu)"].sum()

    return {
        "name": name,
        "facility_id": facility_id,
        "type": "cogen",
        "annual": ct_stats(ct_units, psc["annual_sendout_mlb"] if psc else 0),
        "summer": ct_stats(ct_units[ct_units["is_summer"]], psc["summer_sendout_mlb"] if psc else 0),
        "winter": ct_stats(ct_units[~ct_units["is_summer"]], psc["winter_sendout_mlb"] if psc else 0),
        "boilers": {
            "steam_mlb": boiler_steam,
            "co2_tons": boiler_co2,
            "heat_mmbtu": boiler_heat,
            "co2_per_mlb": boiler_co2 / boiler_steam if boiler_steam > 0 else 0,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# VENTING ESTIMATE (HRSG production vs sendout)
# ═══════════════════════════════════════════════════════════════════════════════

def estimate_venting(cogen_result):
    """
    Estimate how much steam the HRSGs produce vs what gets sent to customers.
    The difference is excess steam — vented or condensed.

    Uses a heat balance: fuel input → electric output + exhaust → HRSG → steam.
    Rough estimate — assumes ~12% stack losses and ~88% HRSG recovery.
    """
    results = {}
    for period in ["annual", "summer", "winter"]:
        ct = cogen_result[period]
        heat = ct["heat_mmbtu"]
        eff = ct["elec_efficiency"]
        sendout = ct["steam_sendout_mlb"]

        # Exhaust heat available to HRSG
        exhaust_heat = heat * (1 - eff - STACK_LOSS_PCT)
        recovered_heat = exhaust_heat * HRSG_RECOVERY_PCT

        # Estimated steam production
        estimated_steam_mlb = recovered_heat * 1e6 / NET_ENTHALPY_BTU_LB / 1e3

        excess_mlb = max(0, estimated_steam_mlb - sendout)

        hours = {"annual": SUMMER_HOURS + WINTER_HOURS,
                 "summer": SUMMER_HOURS,
                 "winter": WINTER_HOURS}[period]

        results[period] = {
            "estimated_production_mlb": estimated_steam_mlb,
            "sendout_mlb": sendout,
            "excess_mlb": excess_mlb,
            "excess_pct": excess_mlb / estimated_steam_mlb * 100 if estimated_steam_mlb > 0 else 0,
            "excess_avg_rate_mlbhr": excess_mlb / hours if hours > 0 else 0,
            "sendout_avg_rate_mlbhr": sendout / hours if hours > 0 else 0,
            "production_avg_rate_mlbhr": estimated_steam_mlb / hours if hours > 0 else 0,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM-WIDE BLENDED FACTORS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_system_emission_factors(boiler_results, cogen_results, allocation_method="energy"):
    """
    Compute blended system-wide emission factor for steam by season.
    Weights each station's emission factor by its sendout share.
    """
    factors = {}
    for period in ["annual", "summer", "winter"]:
        total_steam = 0
        total_co2 = 0

        for b in boiler_results:
            s = b[period]
            total_steam += s["steam_mlb"]
            total_co2 += s["co2_tons"]

        for c in cogen_results:
            ct = c[period]
            sendout = ct["steam_sendout_mlb"]
            co2 = ct["allocation"][allocation_method]["co2_per_mlb"] * sendout
            total_steam += sendout
            total_co2 += co2

            # Add facility boilers (ER 60/70) — proportioned by season
            # (boiler data not split by season in current structure, skip for now)

        factors[period] = {
            "total_steam_mlb": total_steam,
            "total_co2_tons": total_co2,
            "co2_per_mlb": total_co2 / total_steam if total_steam > 0 else 0,
            "co2_lbs_per_mlb": total_co2 / total_steam * 2000 if total_steam > 0 else 0,
        }

    return factors


def main():
    df = load_campd()
    system = compute_system_summary()

    print()
    print("=" * 78)
    print("CON EDISON STEAM SYSTEM — EMISSION FACTORS & VENTING (2025)")
    print("=" * 78)

    # ── Boiler stations ──
    print("\n" + "─" * 78)
    print("BOILER STATIONS — DIRECT EMISSION FACTORS")
    print("(All fuel burned → steam. Straightforward.)")
    print("─" * 78)

    boiler_results = []
    for fid, name in [
        (EAST_RIVER, "East River (boilers 60/70)"),
        (FIFTY_NINTH, "59th Street"),
        (SEVENTY_FOURTH, "74th Street"),
    ]:
        b = analyze_boiler_station(df, fid, name)
        boiler_results.append(b)
        a = b["annual"]
        note = f" ({a['co2_source']})" if a["co2_source"] == "estimated" else ""
        print(f"\n  {name}:")
        print(f"    Steam:          {a['steam_mlb']:>12,.0f} Mlb")
        print(f"    CO2:            {a['co2_tons']:>12,.0f} tons{note}")
        print(f"    Heat input:     {a['heat_mmbtu']:>12,.0f} mmBtu")
        print(f"    Emission factor: {a['co2_lbs_per_mlb']:>8.0f} lbs CO2 / Mlb steam")
        if b["summer"]["steam_mlb"] > 0:
            print(f"      Summer:        {b['summer']['co2_lbs_per_mlb']:>8.0f} lbs / Mlb")
        print(f"      Winter:        {b['winter']['co2_lbs_per_mlb']:>8.0f} lbs / Mlb")

    # ── Cogen stations ──
    print("\n" + "─" * 78)
    print("COGENERATION STATIONS — EMISSION FACTORS BY ALLOCATION METHOD")
    print("(CTs produce electricity + steam. How you split CO2 matters.)")
    print("─" * 78)

    cogen_results = []
    for fid, name in [
        (EAST_RIVER, "East River 10/20"),
        (BNY, "Brooklyn Navy Yard"),
    ]:
        c = analyze_cogen_station(df, fid, name)
        cogen_results.append(c)
        a = c["annual"]
        s = c["summer"]

        print(f"\n  {name}:")
        print(f"    Electric:       {a['mwh']:>12,.0f} MWh  ({a['co2_lbs_per_mwh']:,.0f} lbs CO2/MWh electric-only)")
        print(f"    Steam sendout:  {a['steam_sendout_mlb']:>12,} Mlb  (from PSC filing)")
        print(f"    Total CO2:      {a['co2_tons']:>12,.0f} tons")
        print(f"    Elec efficiency: {a['elec_efficiency']*100:.1f}%")
        print()
        print(f"    Steam emission factor by allocation method:")
        print(f"    {'Method':<22} {'Annual':>14} {'Summer':>14} {'Winter':>14}")
        print(f"    {'':22s} {'(lbs/Mlb)':>14} {'(lbs/Mlb)':>14} {'(lbs/Mlb)':>14}")
        print(f"    {'─'*22} {'─'*14} {'─'*14} {'─'*14}")
        for method in ["energy", "avoided_burden", "marginal"]:
            label = {"energy": "Energy allocation", "avoided_burden": "Avoided burden",
                     "marginal": "Marginal (free)"}[method]
            a_val = a["allocation"][method]["co2_lbs_per_mlb"]
            s_val = s["allocation"][method]["co2_lbs_per_mlb"]
            w_val = c["winter"]["allocation"][method]["co2_lbs_per_mlb"]
            print(f"    {label:<22} {a_val:>14.0f} {s_val:>14.0f} {w_val:>14.0f}")

    # ── Venting ──
    print("\n" + "─" * 78)
    print("COGEN STEAM VENTING ESTIMATE")
    print("(HRSG heat balance: estimated production vs actual sendout)")
    print("─" * 78)
    print(f"\n  Assumptions: {STACK_LOSS_PCT*100:.0f}% stack loss, "
          f"{HRSG_RECOVERY_PCT*100:.0f}% HRSG recovery, "
          f"{NET_ENTHALPY_BTU_LB} BTU/lb net enthalpy")

    for c in cogen_results:
        venting = estimate_venting(c)
        print(f"\n  {c['name']}:")
        print(f"    {'Period':<10} {'Produced':>12} {'Sent out':>12} {'Excess':>12} {'Excess%':>8} {'Rate':>10}")
        print(f"    {'':10s} {'(Mlb)':>12} {'(Mlb)':>12} {'(Mlb)':>12} {'':>8} {'(Mlb/hr)':>10}")
        print(f"    {'─'*10} {'─'*12} {'─'*12} {'─'*12} {'─'*8} {'─'*10}")
        for period in ["summer", "winter", "annual"]:
            v = venting[period]
            print(f"    {period:<10} {v['estimated_production_mlb']:>12,.0f} "
                  f"{v['sendout_mlb']:>12,} {v['excess_mlb']:>12,.0f} "
                  f"{v['excess_pct']:>7.0f}% {v['excess_avg_rate_mlbhr']:>10,.0f}")

    # Summarize venting
    er_venting = estimate_venting(cogen_results[0])
    bny_venting = estimate_venting(cogen_results[1])
    er_summer_excess = er_venting["summer"]["excess_mlb"]
    er_summer_rate = er_venting["summer"]["excess_avg_rate_mlbhr"]

    print(f"\n  Note: BNY excess may not be deliverable to ConEd's steam system —")
    print(f"  BNY operates under a fixed contract. ER 10/20 excess is the")
    print(f"  relevant number for Manhattan absorption cooling potential.")
    print(f"\n  ER 10/20 summer excess: {er_summer_excess:,.0f} Mlb ({er_summer_rate:,.0f} Mlb/hr avg)")
    print(f"  → This is steam produced by HRSGs that has no customer and is vented.")
    print(f"  → Using it for cooling would have zero marginal CO2.")

    # ── System-wide blended factors ──
    print("\n" + "─" * 78)
    print("SYSTEM-WIDE BLENDED EMISSION FACTORS")
    print("─" * 78)

    for method in ["energy", "avoided_burden", "marginal"]:
        factors = compute_system_emission_factors(boiler_results, cogen_results, method)
        label = {"energy": "Energy allocation", "avoided_burden": "Avoided burden",
                 "marginal": "Marginal (cogen steam free)"}[method]
        print(f"\n  {label}:")
        for period in ["annual", "summer", "winter"]:
            f = factors[period]
            print(f"    {period:<10} {f['co2_lbs_per_mlb']:>8.0f} lbs CO2 / Mlb  "
                  f"({f['total_steam_mlb']/1e6:.1f}B lbs, {f['total_co2_tons']:,.0f} t CO2)")

    # ── Summary ──
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)

    er_cogen_annual = cogen_results[0]["annual"]
    print(f"""
  Boiler emission factors (lbs CO2 per Mlb steam):
    74th Street:         {boiler_results[2]['annual']['co2_lbs_per_mlb']:.0f}
    59th Street:         {boiler_results[1]['annual']['co2_lbs_per_mlb']:.0f} (estimated from heat input)
    ER boilers (60/70):  {boiler_results[0]['annual']['co2_lbs_per_mlb']:.0f}

  Cogen emission factors — depends on allocation:
    ER 10/20 electric-only rate: {er_cogen_annual['co2_lbs_per_mwh']:,.0f} lbs CO2/MWh
      (comparable to peakers at ~1,383 lbs/MWh — ER runs for steam, not efficiency)
    ER 10/20 steam factor:
      Energy allocation:   {er_cogen_annual['allocation']['energy']['co2_lbs_per_mlb']:.0f} lbs CO2/Mlb
      Avoided burden:      {er_cogen_annual['allocation']['avoided_burden']['co2_lbs_per_mlb']:.0f} lbs CO2/Mlb
      Marginal (free):     0 lbs CO2/Mlb

  Cogen share of summer sendout: {system['cogen_pct_summer']:.0f}%

  Estimated summer venting (ER 10/20): ~{er_summer_rate:,.0f} Mlb/hr avg
    → Steam produced by HRSGs with no customer. Zero marginal CO2 if used.
    → ER runs at ~60% CF in summer; can't ramp up because no steam demand.
    → More absorption cooling demand would justify higher cogen dispatch,
      producing more electricity as byproduct (displacing peakers).
""")

    # ── Write outputs ──
    summary = {
        "boiler_emission_factors": {
            b["name"]: {
                "annual_co2_lbs_per_mlb": b["annual"]["co2_lbs_per_mlb"],
                "summer_co2_lbs_per_mlb": b["summer"]["co2_lbs_per_mlb"],
                "winter_co2_lbs_per_mlb": b["winter"]["co2_lbs_per_mlb"],
            } for b in boiler_results
        },
        "cogen_emission_factors": {
            c["name"]: {
                "electric_co2_lbs_per_mwh": c["annual"]["co2_lbs_per_mwh"],
                "steam_co2_lbs_per_mlb": {
                    method: c["annual"]["allocation"][method]["co2_lbs_per_mlb"]
                    for method in ["energy", "avoided_burden", "marginal"]
                },
            } for c in cogen_results
        },
        "venting": {
            c["name"]: {
                period: {
                    "excess_mlb": estimate_venting(c)[period]["excess_mlb"],
                    "excess_pct": estimate_venting(c)[period]["excess_pct"],
                    "excess_avg_rate_mlbhr": estimate_venting(c)[period]["excess_avg_rate_mlbhr"],
                } for period in ["summer", "winter", "annual"]
            } for c in cogen_results
        },
        "system_blended": {
            method: {
                period: compute_system_emission_factors(boiler_results, cogen_results, method)[period]["co2_lbs_per_mlb"]
                for period in ["annual", "summer", "winter"]
            } for method in ["energy", "avoided_burden", "marginal"]
        },
    }

    out_path = os.path.join(OUTPUT_DIR, "emission_factors_2025.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Written: {out_path}")


if __name__ == "__main__":
    main()
