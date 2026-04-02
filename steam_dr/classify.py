"""
Classify NYC steam buildings by chiller type and estimate DR potential.

Uses three evidence sources:
  1. Steam intensity vs heating-only baseline → steam cooling evidence
  2. Summer vs winter electricity (monthly data) → electric cooling evidence
  3. Cooling tower registrations → physical chiller plant evidence

Classifications:
  BOTH          — Steam + electric cooling. DR ready: can shift load between them.
  STEAM_ONLY    — Steam cooling, minimal electric cooling component.
  ELECTRIC_ONLY — Electric cooling, steam for heating only.
  UNCLEAR       — Insufficient data to classify.

Evidence thresholds:
  Steam cooling:   steam intensity > 1.5x the 25th-percentile for building type
                   (25th percentile ≈ heating-only buildings)
  Electric cooling: summer electricity > 15% above winter baseline
                    AND cooling intensity > 1 kBtu/sqft
"""

import json
import csv
import os
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def safe_float(val, default=0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def percentile(lst, pct):
    s = sorted(lst)
    idx = int(len(s) * pct / 100)
    return s[min(idx, len(s) - 1)]


# ── Load data ──

with open(os.path.join(DATA_DIR, "ll84_annual.json")) as f:
    annual_raw = json.load(f)

with open(os.path.join(DATA_DIR, "ll84_monthly_2024.json")) as f:
    monthly_raw = json.load(f)

with open(os.path.join(DATA_DIR, "cooling_towers.json")) as f:
    ct_raw = json.load(f)

print(f"Loaded: {len(annual_raw)} annual, {len(monthly_raw)} monthly, {len(ct_raw)} cooling towers")

# ── Build lookups ──

# Cooling towers by BIN and BBL
ct_by_bin = {}
ct_by_bbl = {}
for ct in ct_raw:
    equip = int(ct.get("activeequipment", 0) or 0)
    if ct.get("bin"):
        ct_by_bin[ct["bin"]] = equip
    if ct.get("bbl"):
        ct_by_bbl[ct["bbl"]] = equip

# Property ID → BBL mapping
pid_to_bbl = {}
for r in annual_raw:
    pid = r.get("property_id", "")
    bbl = r.get("nyc_borough_block_and_lot", "")
    if pid and bbl:
        pid_to_bbl[pid] = bbl

# ── Parse monthly electricity into summer/winter profiles ──

MONTH_ORDER = {
    "24-Jan": 1, "24-Feb": 2, "24-Mar": 3, "24-Apr": 4,
    "24-May": 5, "24-Jun": 6, "24-Jul": 7, "24-Aug": 8,
    "24-Sep": 9, "24-Oct": 10, "24-Nov": 11, "24-Dec": 12,
}
WINTER = {1, 2, 12}
SUMMER = {6, 7, 8, 9}

prop_monthly = defaultdict(dict)
for r in monthly_raw:
    pid = r.get("property_id", "")
    month_num = MONTH_ORDER.get(r.get("month", ""))
    elec = safe_float(r.get("electricity_use_grid_kbtu_"))
    if pid and month_num and elec > 0:
        prop_monthly[pid][month_num] = elec

# Compute cooling metrics per BBL
bbl_cooling = {}
for pid, months_data in prop_monthly.items():
    bbl = pid_to_bbl.get(pid)
    if not bbl:
        continue

    winter_vals = [months_data[m] for m in WINTER if m in months_data]
    summer_vals = [months_data[m] for m in SUMMER if m in months_data]
    if len(winter_vals) < 2 or len(summer_vals) < 3:
        continue

    monthly_baseload = sum(winter_vals) / len(winter_vals)
    peak_summer = max(summer_vals)
    summer_total = sum(summer_vals)
    summer_baseline = monthly_baseload * len(summer_vals)
    cooling_kbtu = max(0, summer_total - summer_baseline)

    # Shoulder months
    shoulder_vals = [months_data[m] for m in [4, 5, 10, 11] if m in months_data]
    shoulder_cooling = (
        max(0, sum(shoulder_vals) - monthly_baseload * len(shoulder_vals))
        if shoulder_vals else 0
    )
    total_cooling_kbtu = cooling_kbtu + shoulder_cooling

    annual_elec = sum(months_data.values())
    cooling_pct = (total_cooling_kbtu / annual_elec * 100) if annual_elec > 0 else 0

    # Peak month cooling kW (22 weekdays x 10 peak hours per month)
    peak_month_cooling_kbtu = max(0, peak_summer - monthly_baseload)
    peak_month_kw = (peak_month_cooling_kbtu * 0.293071) / (22 * 10)

    # Average summer cooling kW
    avg_summer_kw = (cooling_kbtu * 0.293071) / (4 * 22 * 10)

    bbl_cooling[bbl] = {
        "monthly_baseload_kbtu": monthly_baseload,
        "peak_summer_kbtu": peak_summer,
        "total_cooling_kbtu": total_cooling_kbtu,
        "cooling_pct": cooling_pct,
        "peak_month_kw": peak_month_kw,
        "avg_summer_kw": avg_summer_kw,
        "summer_increase_pct": (
            (peak_summer - monthly_baseload) / monthly_baseload * 100
            if monthly_baseload > 0 else 0
        ),
    }

print(f"Monthly cooling profiles computed: {len(bbl_cooling)}")

# ── Deduplicate annual data to most recent year per BBL ──

latest = {}
for b in annual_raw:
    bbl = b.get("nyc_borough_block_and_lot", "")
    year = int(b.get("report_year", 0))
    if bbl not in latest or year > latest[bbl]["report_year"]:
        latest[bbl] = {**b, "report_year": year}

# ── Compute heating-only baselines by building type ──
# 25th percentile steam intensity ≈ buildings using steam for heating only

type_steam = defaultdict(list)
for b in latest.values():
    sqft = safe_float(b.get("property_gfa_self_reported"))
    steam = safe_float(b.get("district_steam_use_kbtu"))
    ptype = b.get("primary_property_type_self", "Other")
    if sqft > 0 and steam > 0:
        type_steam[ptype].append(steam / sqft)

heating_baselines = {}
for ptype, vals in type_steam.items():
    heating_baselines[ptype] = percentile(vals, 25 if len(vals) >= 5 else 50)

print("\nHeating-only baselines (25th pctl kBtu/sqft):")
for ptype in sorted(heating_baselines, key=lambda t: -len(type_steam[t])):
    if len(type_steam[ptype]) >= 5:
        print(f"  {ptype:<40} {heating_baselines[ptype]:>6.1f}  (n={len(type_steam[ptype])})")

# ── Classify each building ──

results = []
for bbl, b in latest.items():
    steam = safe_float(b.get("district_steam_use_kbtu"))
    site_energy = safe_float(b.get("site_energy_use_kbtu"))
    sqft = safe_float(b.get("property_gfa_self_reported"))
    elec_kwh = safe_float(b.get("electricity_use_grid_purchase_1"))

    if steam <= 0 or sqft < 50000:
        continue

    steam_intensity = steam / sqft
    if steam_intensity > 5000:  # data quality filter
        continue

    bin_id = b.get("nyc_building_identification", "")
    ptype = b.get("primary_property_type_self", "Other")
    num_ct = ct_by_bin.get(bin_id, ct_by_bbl.get(bbl, 0))
    steam_pct = (steam / site_energy * 100) if site_energy > 0 else 0

    # ── Steam cooling evidence ──
    heating_baseline = heating_baselines.get(ptype, 25)
    steam_ratio = steam_intensity / heating_baseline if heating_baseline > 0 else 1
    has_steam_cooling = steam_ratio > 1.5

    # ── Electric cooling evidence ──
    cooling = bbl_cooling.get(bbl)
    has_monthly = cooling is not None

    if has_monthly:
        summer_increase_pct = cooling["summer_increase_pct"]
        cooling_intensity = cooling["total_cooling_kbtu"] / sqft
        peak_kw = cooling["peak_month_kw"]
        avg_kw = cooling["avg_summer_kw"]
        cooling_pct = cooling["cooling_pct"]
        has_electric_cooling = summer_increase_pct > 15 and cooling_intensity > 1
    else:
        summer_increase_pct = cooling_intensity = peak_kw = avg_kw = cooling_pct = 0
        has_electric_cooling = False

    # ── Classify ──
    if has_steam_cooling and has_electric_cooling:
        classification = "BOTH"
    elif has_steam_cooling:
        classification = "STEAM_ONLY"
    elif has_electric_cooling:
        classification = "ELECTRIC_ONLY"
    else:
        classification = "UNCLEAR"

    results.append({
        "property_name": b.get("property_name", ""),
        "address": b.get("address_1", ""),
        "borough": b.get("borough", ""),
        "property_type": ptype,
        "sqft": int(sqft),
        "classification": classification,
        "has_steam_cooling": has_steam_cooling,
        "has_electric_cooling": has_electric_cooling,
        "has_monthly_data": has_monthly,
        "steam_intensity": round(steam_intensity, 1),
        "heating_baseline": round(heating_baseline, 1),
        "steam_ratio_vs_baseline": round(steam_ratio, 2),
        "steam_pct_of_total": round(steam_pct, 1),
        "summer_elec_increase_pct": round(summer_increase_pct, 1),
        "cooling_intensity_kbtu_sqft": round(cooling_intensity, 1),
        "cooling_pct_of_elec": round(cooling_pct, 1),
        "peak_month_cooling_kw": int(peak_kw),
        "avg_summer_cooling_kw": int(avg_kw),
        "num_cooling_towers": num_ct,
        "district_steam_kbtu": int(steam),
        "elec_kwh": int(elec_kwh) if elec_kwh else 0,
        "bbl": bbl,
        "bin": bin_id,
        "latitude": b.get("latitude", ""),
        "longitude": b.get("longitude", ""),
    })

results.sort(key=lambda x: (
    0 if x["classification"] == "BOTH" else
    1 if x["classification"] == "STEAM_ONLY" else
    2 if x["classification"] == "ELECTRIC_ONLY" else 3,
    -x["peak_month_cooling_kw"],
    -x["steam_intensity"],
))

# ── Summary ──

print("\n" + "=" * 70)
print("CLASSIFICATION SUMMARY")
print("=" * 70)

LABELS = {
    "BOTH": "Both steam + electric cooling (DR ready)",
    "STEAM_ONLY": "Steam cooling only",
    "ELECTRIC_ONLY": "Electric cooling only (steam for heating)",
    "UNCLEAR": "Unclear / insufficient data",
}

for cls in ["BOTH", "STEAM_ONLY", "ELECTRIC_ONLY", "UNCLEAR"]:
    subset = [r for r in results if r["classification"] == cls]
    peak_mw = sum(r["peak_month_cooling_kw"] for r in subset) / 1000
    avg_mw = sum(r["avg_summer_cooling_kw"] for r in subset) / 1000
    sqft_m = sum(r["sqft"] for r in subset) / 1e6
    print(f"\n  {LABELS[cls]}")
    print(f"    Buildings:  {len(subset):>6}        Total sqft: {sqft_m:>8.0f}M")
    print(f"    Peak MW:    {peak_mw:>6.0f}        Avg summer MW: {avg_mw:>5.0f}")

# ── Write outputs ──

all_path = os.path.join(OUTPUT_DIR, "buildings_classified.csv")
with open(all_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

both = [r for r in results if r["classification"] == "BOTH"]
dr_path = os.path.join(OUTPUT_DIR, "dr_ready.csv")
with open(dr_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=both[0].keys())
    writer.writeheader()
    writer.writerows(both)

print(f"\nOutput: {all_path} ({len(results)} buildings)")
print(f"Output: {dr_path} ({len(both)} DR-ready buildings)")
