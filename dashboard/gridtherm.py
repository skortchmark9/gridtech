"""
GridTherm Service Dashboard — interactive product view.

Reads building classifications, steam supply data, and scenarios to render
a single-page HTML dashboard with:
  - Leaflet map of enrolled DR buildings (left)
  - Building roster with MW committed & status (right)
  - Steam system utilization gauge
  - Grid commitment & efficiency summary cards

Output: dashboard/output/gridtherm.html
"""

import csv
import json
import os
import random

random.seed(42)  # reproducible demo statuses

BASE_DIR = os.path.dirname(__file__)
ROOT = os.path.dirname(BASE_DIR)
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Load building data ──────────────────────────────────────────────────────
buildings = []
with open(os.path.join(ROOT, "steam_dr", "output", "dr_ready.csv")) as f:
    for row in csv.DictReader(f):
        lat = row["latitude"]
        lon = row["longitude"]
        if not lat or not lon:
            continue
        peak_kw = float(row["peak_month_cooling_kw"])
        avg_kw = float(row["avg_summer_cooling_kw"])
        peak_mw = round(peak_kw / 1000, 2)
        avg_mw = round(avg_kw / 1000, 2)

        # Simulate enrollment status for demo
        r = random.random()
        if r < 0.60:
            status = "ready"
        elif r < 0.93:
            status = "responding"
        else:
            status = "offline"

        buildings.append({
            "name": row["property_name"],
            "address": row["address"],
            "type": row["property_type"],
            "sqft": int(float(row["sqft"])),
            "peak_mw": peak_mw,
            "avg_mw": avg_mw,
            "lat": float(lat),
            "lon": float(lon),
            "status": status,
            "cooling_towers": int(float(row["num_cooling_towers"])),
            "steam_pct": float(row["steam_pct_of_total"]),
        })

# Sort by peak_mw descending for the roster
buildings.sort(key=lambda b: b["peak_mw"], reverse=True)

# ── Load steam supply summary ───────────────────────────────────────────────
with open(os.path.join(ROOT, "steam_supply", "output", "system_summary_2025.json")) as f:
    steam = json.load(f)

# ── Load scenario data ──────────────────────────────────────────────────────
scenarios = []
with open(os.path.join(ROOT, "steam_supply", "output", "scenarios.csv")) as f:
    for row in csv.DictReader(f):
        scenarios.append(row)

# Pick scenario 3b (realistic) for dashboard metrics
realistic = next(s for s in scenarios if "3b" in s["name"])

# ── Aggregate stats ─────────────────────────────────────────────────────────
total_buildings = len(buildings)
total_mw = round(sum(b["peak_mw"] for b in buildings), 1)
responding_count = sum(1 for b in buildings if b["status"] == "responding")
ready_count = sum(1 for b in buildings if b["status"] == "ready")
offline_count = sum(1 for b in buildings if b["status"] == "offline")
responding_mw = round(sum(b["peak_mw"] for b in buildings if b["status"] == "responding"), 1)

utilization_pct = steam["summer_utilization_pct"]
spare_capacity = steam["summer_spare_capacity_mlbhr"]
total_capacity = steam["total_rated_capacity_mlbhr"]

# Current DR load on steam system (sum of responding buildings)
dr_steam_demand_mlbhr = round(
    sum(b["peak_mw"] for b in buildings if b["status"] == "responding") * 1000  # kW
    * 3.412  # kBtu/kW
    / 0.7    # absorption COP
    / 1000   # Mlb (approx 1000 BTU/lb)
, 1)

current_utilization = round(utilization_pct + (dr_steam_demand_mlbhr / total_capacity * 100), 1)

buildings_json = json.dumps(buildings)

# ── Efficiency metrics ──────────────────────────────────────────────────────
# Load emission factors
with open(os.path.join(ROOT, "steam_supply", "output", "emission_factors_2025.json")) as f:
    emissions = json.load(f)

blended_summer_marginal = emissions["system_blended"]["marginal"]["summer"]  # lbs CO2/Mlb
blended_summer_energy = emissions["system_blended"]["energy"]["summer"]

# Grid marginal emission rate (gas peakers) ~0.4 tons CO2/MWh = 800 lbs/MWh
grid_marginal_lbs_per_mwh = 800
# Steam cooling emission rate: steam CO2/Mlb * Mlb/ton-cooling / COP-adjusted kW
# Simplified: compare lbs CO2 per MWh-equivalent of cooling
# Electric chiller: 1 MWh electricity → 5.0 MWh cooling (COP 5) → 800/5 = 160 lbs CO2/MWh-cooling
# Absorption: 1 MWh-cooling needs ~4.88 Mlb steam (at COP 0.7) → 4.88 * 71 = 346 lbs CO2/MWh-cooling (marginal)
# But marginal steam is essentially zero-carbon (using spare capacity from cogen)
electric_cooling_co2 = round(grid_marginal_lbs_per_mwh / 5.0, 1)  # lbs CO2/MWh-cooling
steam_cooling_co2_marginal = round(blended_summer_marginal * 4.88, 1)  # marginal method
co2_avoided_pct = round((1 - steam_cooling_co2_marginal / electric_cooling_co2) * 100, 1) if electric_cooling_co2 > 0 else 0

# ── Generate HTML ────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GridTherm — Demand Response Dashboard</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root {{
    --bg: #f4f6f8;
    --panel: #ffffff;
    --panel-alt: #f0f2f5;
    --border: #e0e4e8;
    --text: #1a2b3c;
    --text-dim: #6b7a8d;
    --accent: #0277bd;
    --green: #2e7d32;
    --amber: #e65100;
    --red: #c62828;
    --cyan: #00838f;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    height: 100vh;
    overflow: hidden;
  }}

  /* ── Header ── */
  .header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 24px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    height: 56px;
  }}
  .header .brand {{
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .header .brand svg {{ width: 28px; height: 28px; }}
  .header .brand h1 {{
    font-size: 18px;
    font-weight: 600;
    letter-spacing: 0.5px;
  }}
  .header .brand span {{
    color: var(--accent);
    font-weight: 300;
  }}
  .header .status-bar {{
    display: flex;
    gap: 24px;
    font-size: 13px;
    color: var(--text-dim);
  }}
  .header .status-bar .live {{
    color: var(--green);
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .header .status-bar .live::before {{
    content: '';
    width: 8px; height: 8px;
    background: var(--green);
    border-radius: 50%;
    animation: pulse 2s infinite;
  }}
  @keyframes pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.4; }}
  }}

  /* ── Main layout ── */
  .main {{
    display: grid;
    grid-template-columns: 1fr 420px;
    height: calc(100vh - 56px);
  }}

  /* ── Map panel ── */
  .map-panel {{
    position: relative;
  }}
  #map {{ height: 100%; width: 100%; }}
  .map-overlay {{
    position: absolute;
    top: 16px;
    left: 16px;
    z-index: 1000;
    background: rgba(255, 255, 255, 0.92);
    backdrop-filter: blur(8px);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 18px;
    min-width: 200px;
  }}
  .map-overlay h3 {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: var(--text-dim);
    margin-bottom: 10px;
  }}
  .map-legend {{
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}
  .map-legend .item {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
  }}
  .map-legend .dot {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
  }}

  /* ── Right panel ── */
  .right-panel {{
    background: var(--panel);
    border-left: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }}

  /* ── Metrics strip ── */
  .metrics-strip {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1px;
    background: var(--border);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }}
  .metric-card {{
    background: var(--panel);
    padding: 14px 16px;
    text-align: center;
  }}
  .metric-card .label {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--text-dim);
    margin-bottom: 4px;
  }}
  .metric-card .value {{
    font-size: 24px;
    font-weight: 700;
    color: var(--accent);
    line-height: 1.1;
  }}
  .metric-card .unit {{
    font-size: 11px;
    color: var(--text-dim);
    font-weight: 400;
  }}

  /* ── Utilization & grid section ── */
  .info-section {{
    padding: 16px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }}
  .info-section h3 {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: var(--text-dim);
    margin-bottom: 12px;
  }}

  /* Utilization bar */
  .util-bar-container {{
    margin-bottom: 12px;
  }}
  .util-bar-header {{
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    margin-bottom: 6px;
  }}
  .util-bar {{
    height: 20px;
    background: var(--bg);
    border-radius: 4px;
    overflow: hidden;
    position: relative;
  }}
  .util-bar .segment {{
    height: 100%;
    float: left;
    transition: width 0.6s ease;
  }}
  .util-bar .base {{ background: var(--cyan); opacity: 0.6; }}
  .util-bar .dr {{ background: var(--accent); }}
  .util-bar .spare {{ background: var(--panel-alt); }}
  .util-labels {{
    display: flex;
    justify-content: space-between;
    font-size: 10px;
    color: var(--text-dim);
    margin-top: 4px;
  }}

  /* Grid stats */
  .grid-stats {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }}
  .grid-stat {{
    background: var(--panel-alt);
    border-radius: 6px;
    padding: 10px 12px;
  }}
  .grid-stat .stat-label {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--text-dim);
    margin-bottom: 4px;
  }}
  .grid-stat .stat-value {{
    font-size: 16px;
    font-weight: 600;
  }}
  .grid-stat .stat-detail {{
    font-size: 10px;
    color: var(--text-dim);
    margin-top: 2px;
  }}
  .stat-green {{ color: var(--green); }}
  .stat-cyan {{ color: var(--cyan); }}
  .stat-amber {{ color: var(--amber); }}

  /* ── Building roster ── */
  .roster-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }}
  .roster-header h3 {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: var(--text-dim);
  }}
  .roster-header .filter-pills {{
    display: flex;
    gap: 4px;
  }}
  .filter-pill {{
    font-size: 10px;
    padding: 3px 8px;
    border-radius: 10px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-dim);
    cursor: pointer;
    transition: all 0.2s;
  }}
  .filter-pill:hover, .filter-pill.active {{
    background: var(--accent);
    color: #ffffff;
    border-color: var(--accent);
  }}

  .roster {{
    flex: 1;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }}
  .roster::-webkit-scrollbar {{ width: 6px; }}
  .roster::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}

  .building-row {{
    display: grid;
    grid-template-columns: 1fr 70px 80px;
    align-items: center;
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background 0.15s;
  }}
  .building-row:hover {{
    background: var(--panel-alt);
  }}
  .building-row .bldg-name {{
    font-size: 12px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .building-row .bldg-addr {{
    font-size: 10px;
    color: var(--text-dim);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-top: 1px;
  }}
  .building-row .bldg-mw {{
    font-size: 13px;
    font-weight: 600;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }}
  .building-row .bldg-status {{
    text-align: right;
  }}
  .status-badge {{
    display: inline-block;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 2px 8px;
    border-radius: 8px;
  }}
  .status-responding {{
    background: rgba(46,125,50,0.1);
    color: var(--green);
  }}
  .status-ready {{
    background: rgba(2,119,189,0.1);
    color: var(--accent);
  }}
  .status-offline {{
    background: rgba(198,40,40,0.1);
    color: var(--red);
  }}

  /* Leaflet popup override */
  .leaflet-popup-content-wrapper {{
    background: var(--panel) !important;
    color: var(--text) !important;
    border-radius: 8px !important;
    border: 1px solid var(--border) !important;
    box-shadow: 0 4px 20px rgba(0,0,0,0.12) !important;
  }}
  .leaflet-popup-tip {{
    background: var(--panel) !important;
    border: 1px solid var(--border) !important;
  }}
  .leaflet-popup-content {{
    font-family: inherit !important;
    font-size: 12px !important;
    line-height: 1.5 !important;
    margin: 10px 14px !important;
  }}
  .leaflet-popup-content b {{ color: var(--accent); }}
  .popup-status {{ font-weight: 600; text-transform: uppercase; font-size: 10px; }}
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div class="brand">
    <svg viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="28" height="28" rx="6" fill="#0277bd" fill-opacity="0.15"/>
      <path d="M7 21V11l7-5 7 5v10" stroke="#0277bd" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M14 6v3" stroke="#0277bd" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M10 17h8M10 20h8" stroke="#0277bd" stroke-width="1" stroke-linecap="round" opacity="0.6"/>
      <circle cx="14" cy="13.5" r="2" stroke="#0277bd" stroke-width="1.2"/>
    </svg>
    <h1>Grid<span>Therm</span></h1>
  </div>
  <div class="status-bar">
    <div class="live">System Active</div>
    <div>Manhattan Steam District &middot; Zone J</div>
    <div>Summer 2025</div>
  </div>
</div>

<!-- Main -->
<div class="main">
  <!-- Map -->
  <div class="map-panel">
    <div id="map"></div>
    <div class="map-overlay">
      <h3>Enrolled Buildings</h3>
      <div class="map-legend">
        <div class="item"><div class="dot" style="background:var(--green)"></div>Responding &mdash; {responding_count}</div>
        <div class="item"><div class="dot" style="background:var(--accent)"></div>Ready &mdash; {ready_count}</div>
        <div class="item"><div class="dot" style="background:var(--red)"></div>Offline &mdash; {offline_count}</div>
      </div>
    </div>
  </div>

  <!-- Right Panel -->
  <div class="right-panel">
    <!-- Metric cards -->
    <div class="metrics-strip">
      <div class="metric-card">
        <div class="label">Enrolled</div>
        <div class="value">{total_buildings}</div>
        <div class="unit">buildings</div>
      </div>
      <div class="metric-card">
        <div class="label">Committed</div>
        <div class="value">{total_mw}<span class="unit"> MW</span></div>
      </div>
      <div class="metric-card">
        <div class="label">Responding</div>
        <div class="value" style="color:var(--green)">{responding_mw}<span class="unit"> MW</span></div>
      </div>
    </div>

    <!-- Steam utilization -->
    <div class="info-section">
      <h3>Steam System Utilization</h3>
      <div class="util-bar-container">
        <div class="util-bar-header">
          <span>Base load: {utilization_pct}%</span>
          <span style="color:var(--accent)">+ DR: {round(dr_steam_demand_mlbhr / total_capacity * 100, 1)}%</span>
          <span style="color:var(--text-dim)">Total: {current_utilization}%</span>
        </div>
        <div class="util-bar">
          <div class="segment base" style="width:{utilization_pct}%"></div>
          <div class="segment dr" style="width:{round(dr_steam_demand_mlbhr / total_capacity * 100, 1)}%"></div>
        </div>
        <div class="util-labels">
          <span>0 Mlb/hr</span>
          <span>{int(steam["summer_avg_rate_mlbhr"])} base + {int(dr_steam_demand_mlbhr)} DR</span>
          <span>{total_capacity:,} Mlb/hr</span>
        </div>
      </div>
    </div>

    <!-- Grid commitments & efficiency -->
    <div class="info-section">
      <h3>Grid Commitments & Efficiency</h3>
      <div class="grid-stats">
        <div class="grid-stat">
          <div class="stat-label">Zone J Peak Relief</div>
          <div class="stat-value stat-green">{round(float(realistic['pct_zone_j']),1)}%</div>
          <div class="stat-detail">of 10.88 GW peak demand</div>
        </div>
        <div class="grid-stat">
          <div class="stat-label">CO&#8322; Reduction</div>
          <div class="stat-value stat-green">{co2_avoided_pct}%</div>
          <div class="stat-detail">vs electric cooling (marginal)</div>
        </div>
        <div class="grid-stat">
          <div class="stat-label">Spare Capacity Used</div>
          <div class="stat-value stat-cyan">{round(dr_steam_demand_mlbhr / spare_capacity * 100, 1)}%</div>
          <div class="stat-detail">{int(dr_steam_demand_mlbhr)} / {int(spare_capacity)} Mlb/hr</div>
        </div>
        <div class="grid-stat">
          <div class="stat-label">Cogen Share</div>
          <div class="stat-value stat-amber">{steam['cogen_pct_summer']}%</div>
          <div class="stat-detail">of summer steam supply</div>
        </div>
      </div>
    </div>

    <!-- Building roster -->
    <div class="roster-header">
      <h3>Building Roster</h3>
      <div class="filter-pills">
        <button class="filter-pill active" onclick="filterRoster('all')">All</button>
        <button class="filter-pill" onclick="filterRoster('responding')">Responding</button>
        <button class="filter-pill" onclick="filterRoster('ready')">Ready</button>
        <button class="filter-pill" onclick="filterRoster('offline')">Offline</button>
      </div>
    </div>
    <div class="roster" id="roster"></div>
  </div>
</div>

<script>
const buildings = {buildings_json};

// ── Map ────────────────────────────────────────────────────────────────────
const map = L.map('map', {{
  zoomControl: false,
  attributionControl: false,
}}).setView([40.765, -73.975], 13);

L.control.zoom({{ position: 'bottomright' }}).addTo(map);

L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  maxZoom: 19,
  subdomains: 'abcd',
}}).addTo(map);

const statusColors = {{
  responding: '#2e7d32',
  ready: '#0277bd',
  offline: '#c62828',
}};

const markers = [];
buildings.forEach((b, i) => {{
  const radius = Math.max(4, Math.min(14, Math.sqrt(b.peak_mw) * 6));
  const marker = L.circleMarker([b.lat, b.lon], {{
    radius: radius,
    color: statusColors[b.status],
    fillColor: statusColors[b.status],
    fillOpacity: 0.55,
    weight: 1.5,
  }}).addTo(map);

  const statusClass = b.status === 'responding' ? 'color:#2e7d32' :
                      b.status === 'ready' ? 'color:#0277bd' : 'color:#c62828';

  marker.bindPopup(`
    <div>
      <b>${{b.name}}</b><br>
      ${{b.address}}<br>
      <span style="color:#6b7a8d">${{b.type}} &middot; ${{(b.sqft/1000).toFixed(0)}}k sqft</span><br>
      <br>
      Peak: <b>${{b.peak_mw}} MW</b> &middot; Avg: ${{b.avg_mw}} MW<br>
      <span class="popup-status" style="${{statusClass}}">${{b.status}}</span>
    </div>
  `);

  marker._buildingIndex = i;
  markers.push(marker);
}});

// ── Roster ─────────────────────────────────────────────────────────────────
function renderRoster(filter) {{
  const roster = document.getElementById('roster');
  const filtered = filter === 'all' ? buildings : buildings.filter(b => b.status === filter);
  roster.innerHTML = filtered.map((b, i) => `
    <div class="building-row" data-index="${{buildings.indexOf(b)}}" onclick="focusBuilding(${{buildings.indexOf(b)}})">
      <div>
        <div class="bldg-name">${{b.name}}</div>
        <div class="bldg-addr">${{b.address}}</div>
      </div>
      <div class="bldg-mw">${{b.peak_mw}}</div>
      <div class="bldg-status">
        <span class="status-badge status-${{b.status}}">${{b.status}}</span>
      </div>
    </div>
  `).join('');
}}

function filterRoster(status) {{
  document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
  event.target.classList.add('active');
  renderRoster(status);
}}

function focusBuilding(index) {{
  const b = buildings[index];
  map.flyTo([b.lat, b.lon], 16, {{ duration: 0.6 }});
  markers[index].openPopup();
}}

renderRoster('all');
</script>
</body>
</html>
"""

out_path = os.path.join(OUTPUT_DIR, "gridtherm.html")
with open(out_path, "w") as f:
    f.write(html)

print(f"Dashboard written to {out_path}")
print(f"  {total_buildings} buildings | {total_mw} MW committed")
print(f"  Status: {responding_count} responding, {ready_count} ready, {offline_count} offline")
print(f"  Steam utilization: {utilization_pct}% base + {round(dr_steam_demand_mlbhr / total_capacity * 100, 1)}% DR = {current_utilization}%")
