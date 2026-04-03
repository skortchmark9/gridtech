"""
Generate an interactive HTML dashboard showing ConEd steam plant utilization.

Uses 2025 sendout and capacity data from plants.py.
Output: output/utilization.html
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from plants import STATION_SENDOUT, LARGE_BOILERS, PACKAGE_BOILERS, compute_system_summary, SUMMER_HOURS, WINTER_HOURS

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Build per-station capacity by summing unit ratings
station_capacity = {}
for u in LARGE_BOILERS + PACKAGE_BOILERS:
    st = u["station"]
    station_capacity[st] = station_capacity.get(st, 0) + u["steam_rating_mlbhr"]

# Map station_group → station for capacity lookup
GROUP_TO_STATION = {s["station_group"]: s["station"] for s in STATION_SENDOUT}

# Aggregate sendout to station level (some stations have multiple groups)
station_sendout = {}
for s in STATION_SENDOUT:
    st = s["station"]
    if st not in station_sendout:
        station_sendout[st] = {
            "station": st,
            "summer_sendout_mlb": 0,
            "winter_sendout_mlb": 0,
            "annual_sendout_mlb": 0,
        }
    station_sendout[st]["summer_sendout_mlb"] += s["summer_sendout_mlb"]
    station_sendout[st]["winter_sendout_mlb"] += s["winter_sendout_mlb"]
    station_sendout[st]["annual_sendout_mlb"] += s["annual_sendout_mlb"]

# Compute utilization rates
stations_data = []
for st, send in station_sendout.items():
    cap = station_capacity.get(st, 0)
    if cap == 0 and send["annual_sendout_mlb"] == 0:
        continue  # skip fully retired with no sendout

    summer_avg = send["summer_sendout_mlb"] / SUMMER_HOURS if SUMMER_HOURS > 0 else 0
    winter_avg = send["winter_sendout_mlb"] / WINTER_HOURS if WINTER_HOURS > 0 else 0
    annual_hours = SUMMER_HOURS + WINTER_HOURS
    annual_avg = send["annual_sendout_mlb"] / annual_hours if annual_hours > 0 else 0

    stations_data.append({
        "station": st,
        "capacity_mlbhr": cap,
        "summer_sendout_mlb": send["summer_sendout_mlb"],
        "winter_sendout_mlb": send["winter_sendout_mlb"],
        "annual_sendout_mlb": send["annual_sendout_mlb"],
        "summer_avg_mlbhr": round(summer_avg, 1),
        "winter_avg_mlbhr": round(winter_avg, 1),
        "annual_avg_mlbhr": round(annual_avg, 1),
        "summer_util_pct": round(summer_avg / cap * 100, 1) if cap > 0 else 0,
        "winter_util_pct": round(winter_avg / cap * 100, 1) if cap > 0 else 0,
        "annual_util_pct": round(annual_avg / cap * 100, 1) if cap > 0 else 0,
    })

# Also build the station_group-level detail for the detailed view
groups_data = []
for s in STATION_SENDOUT:
    if s["annual_sendout_mlb"] == 0 and s["summer_sendout_mlb"] == 0:
        continue
    summer_avg = s["summer_sendout_mlb"] / SUMMER_HOURS
    winter_avg = s["winter_sendout_mlb"] / WINTER_HOURS
    annual_avg = s["annual_sendout_mlb"] / (SUMMER_HOURS + WINTER_HOURS)
    groups_data.append({
        "group": s["station_group"],
        "station": s["station"],
        "summer_sendout_mlb": s["summer_sendout_mlb"],
        "winter_sendout_mlb": s["winter_sendout_mlb"],
        "annual_sendout_mlb": s["annual_sendout_mlb"],
        "summer_avg_mlbhr": round(summer_avg, 1),
        "winter_avg_mlbhr": round(winter_avg, 1),
        "annual_avg_mlbhr": round(annual_avg, 1),
        "summer_heat_rate": s["summer_heat_rate_btu_lb"],
        "winter_heat_rate": s["winter_heat_rate_btu_lb"],
        "annual_heat_rate": s["annual_heat_rate_btu_lb"],
        "notes": s["notes"],
    })

# Sort by annual sendout descending
stations_data.sort(key=lambda x: -x["annual_sendout_mlb"])
groups_data.sort(key=lambda x: -x["annual_sendout_mlb"])

summary = compute_system_summary()

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Con Edison Steam System — 2025 Plant Utilization</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0a0e17;
    color: #c8cdd5;
    padding: 24px;
    max-width: 1200px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 22px;
    font-weight: 600;
    color: #e8ecf1;
    margin-bottom: 4px;
  }}
  .subtitle {{
    font-size: 13px;
    color: #6b7280;
    margin-bottom: 28px;
  }}
  .subtitle a {{ color: #7b93b0; text-decoration: none; }}
  .subtitle a:hover {{ text-decoration: underline; }}

  /* KPI row */
  .kpi-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin-bottom: 28px;
  }}
  .kpi {{
    background: #141824;
    border: 1px solid #1e2536;
    border-radius: 8px;
    padding: 16px;
  }}
  .kpi-label {{ font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; }}
  .kpi-value {{ font-size: 26px; font-weight: 700; color: #e8ecf1; margin-top: 4px; }}
  .kpi-unit {{ font-size: 13px; color: #6b7280; font-weight: 400; }}
  .kpi-sub {{ font-size: 12px; color: #4b5563; margin-top: 2px; }}

  /* Section */
  .section {{
    background: #141824;
    border: 1px solid #1e2536;
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 20px;
  }}
  .section h2 {{
    font-size: 15px;
    font-weight: 600;
    color: #e8ecf1;
    margin-bottom: 16px;
  }}

  /* Bar chart */
  .chart-container {{ position: relative; }}
  .bar-row {{
    display: grid;
    grid-template-columns: 160px 1fr 80px;
    align-items: center;
    gap: 12px;
    margin-bottom: 10px;
  }}
  .bar-label {{
    font-size: 13px;
    color: #c8cdd5;
    text-align: right;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .bar-track {{
    height: 32px;
    background: #1a1f2e;
    border-radius: 4px;
    position: relative;
    overflow: hidden;
  }}
  .bar-fill {{
    height: 100%;
    border-radius: 4px;
    position: absolute;
    top: 0;
    left: 0;
    transition: width 0.6s ease;
  }}
  .bar-fill.summer {{ background: #f59e0b; opacity: 0.85; z-index: 2; }}
  .bar-fill.winter {{ background: #3b82f6; opacity: 0.6; z-index: 1; }}
  .bar-fill.capacity {{
    background: none;
    border-right: 2px dashed #4b5563;
    z-index: 3;
  }}
  .bar-value {{
    font-size: 13px;
    color: #9ca3af;
    font-variant-numeric: tabular-nums;
  }}

  /* Dual bar (summer + winter side by side) */
  .dual-bar {{
    display: flex;
    gap: 2px;
    height: 100%;
    align-items: flex-end;
  }}
  .dual-bar-segment {{
    border-radius: 3px;
    min-width: 2px;
  }}

  /* Legend */
  .legend {{
    display: flex;
    gap: 20px;
    margin-bottom: 14px;
    font-size: 12px;
    color: #9ca3af;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .legend-dot {{
    width: 12px;
    height: 12px;
    border-radius: 3px;
  }}

  /* Table */
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  th {{
    text-align: left;
    font-weight: 600;
    color: #9ca3af;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 8px 10px;
    border-bottom: 1px solid #1e2536;
  }}
  th.right, td.right {{ text-align: right; }}
  td {{
    padding: 8px 10px;
    border-bottom: 1px solid #1a1f2e;
    color: #c8cdd5;
  }}
  tr:hover td {{ background: #1a1f2e; }}

  /* Utilization meter */
  .util-meter {{
    width: 60px;
    height: 8px;
    background: #1a1f2e;
    border-radius: 4px;
    display: inline-block;
    vertical-align: middle;
    margin-right: 6px;
    overflow: hidden;
  }}
  .util-meter-fill {{
    height: 100%;
    border-radius: 4px;
  }}

  /* Heat rate color coding */
  .hr-cogen {{ color: #34d399; font-weight: 600; }}
  .hr-boiler {{ color: #f59e0b; }}
  .hr-na {{ color: #4b5563; }}

  .note {{ font-size: 12px; color: #4b5563; margin-top: 12px; line-height: 1.5; }}
</style>
</head>
<body>

<h1>Con Edison Steam System — 2025 Plant Utilization</h1>
<div class="subtitle">
  Source: Case 22-S-0659, 2025 Steam Annual Capital Report (filed Feb 27, 2026)
  &middot; Joint Proposal Appendix 7, Section A.iii
</div>

<div class="kpi-row">
  <div class="kpi">
    <div class="kpi-label">Rated Capacity</div>
    <div class="kpi-value">{summary['total_rated_capacity_mlbhr']:,} <span class="kpi-unit">Mlb/hr</span></div>
    <div class="kpi-sub">ConEd-owned (excl. retired)</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Annual Sendout</div>
    <div class="kpi-value">{summary['annual_sendout_mlb']/1e6:.1f} <span class="kpi-unit">B lbs</span></div>
    <div class="kpi-sub">{summary['summer_sendout_mlb']/1e6:.1f}B summer / {summary['winter_sendout_mlb']/1e6:.1f}B winter</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Summer Utilization</div>
    <div class="kpi-value">{summary['summer_utilization_pct']:.0f}<span class="kpi-unit">%</span></div>
    <div class="kpi-sub">{summary['summer_avg_rate_mlbhr']:,.0f} Mlb/hr avg of {summary['total_rated_capacity_mlbhr']:,}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Summer Spare Capacity</div>
    <div class="kpi-value">{summary['summer_spare_capacity_mlbhr']:,} <span class="kpi-unit">Mlb/hr</span></div>
    <div class="kpi-sub">{summary['summer_spare_capacity_mlbhr']/summary['total_rated_capacity_mlbhr']*100:.0f}% of rated capacity idle</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Cogen Share (Summer)</div>
    <div class="kpi-value">{summary['cogen_pct_summer']:.0f}<span class="kpi-unit">%</span></div>
    <div class="kpi-sub">ER 10/20 + BNYCP</div>
  </div>
</div>

<!-- Utilization bar chart -->
<div class="section">
  <h2>Average Sendout Rate vs Rated Capacity — By Station</h2>
  <div class="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#f59e0b"></div> Summer avg (Mlb/hr)</div>
    <div class="legend-item"><div class="legend-dot" style="background:#3b82f6"></div> Winter avg (Mlb/hr)</div>
    <div class="legend-item"><div class="legend-dot" style="background:none;border:1px dashed #4b5563"></div> Rated capacity</div>
  </div>
  <div class="chart-container" id="util-chart"></div>
  <div class="note">
    Sendout rates are averages over the season (Summer: May–Oct, Winter: Jan–Apr + Nov–Dec).
    Peak sendout rates are significantly higher than averages, especially in winter.
  </div>
</div>

<!-- Sendout breakdown -->
<div class="section">
  <h2>Annual Sendout by Station Group — Summer vs Winter</h2>
  <div class="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#f59e0b"></div> Summer (May–Oct)</div>
    <div class="legend-item"><div class="legend-dot" style="background:#3b82f6"></div> Winter (Jan–Apr, Nov–Dec)</div>
  </div>
  <div class="chart-container" id="sendout-chart"></div>
</div>

<!-- Detail table -->
<div class="section">
  <h2>Station Group Detail</h2>
  <table>
    <thead>
      <tr>
        <th>Station Group</th>
        <th class="right">Summer<br>Sendout (Mlb)</th>
        <th class="right">Winter<br>Sendout (Mlb)</th>
        <th class="right">Annual<br>Sendout (Mlb)</th>
        <th class="right">Summer<br>Avg (Mlb/hr)</th>
        <th class="right">Heat Rate<br>(btu/lb)</th>
        <th>Notes</th>
      </tr>
    </thead>
    <tbody id="detail-table"></tbody>
    <tfoot id="detail-footer"></tfoot>
  </table>
</div>

<!-- Utilization table -->
<div class="section">
  <h2>Station Utilization Rates</h2>
  <table>
    <thead>
      <tr>
        <th>Station</th>
        <th class="right">Capacity<br>(Mlb/hr)</th>
        <th class="right">Summer<br>Utilization</th>
        <th class="right">Winter<br>Utilization</th>
        <th class="right">Annual<br>Utilization</th>
      </tr>
    </thead>
    <tbody id="util-table"></tbody>
  </table>
  <div class="note">
    East River cogen runs at low apparent utilization because capacity includes boiler units (6/60, 7/70)
    that don't produce steam in summer. The cogen CTs (units 10, 20) run near baseload.
    59th St shows low utilization partly due to 73.4% forced outage rate in summer.
  </div>
</div>

<script>
const stations = {json.dumps(stations_data)};
const groups = {json.dumps(groups_data)};

// Find max values for scaling
const maxCapacity = Math.max(...stations.map(s => s.capacity_mlbhr));
const maxWinterAvg = Math.max(...stations.map(s => s.winter_avg_mlbhr));
const scaleMax = Math.max(maxCapacity, maxWinterAvg) * 1.05;

// Utilization bar chart
const utilChart = document.getElementById('util-chart');
stations.forEach(s => {{
  if (s.capacity_mlbhr === 0 && s.annual_sendout_mlb === 0) return;
  const capPct = (s.capacity_mlbhr / scaleMax * 100).toFixed(1);
  const sumPct = (s.summer_avg_mlbhr / scaleMax * 100).toFixed(1);
  const winPct = (s.winter_avg_mlbhr / scaleMax * 100).toFixed(1);

  const row = document.createElement('div');
  row.className = 'bar-row';
  row.innerHTML = `
    <div class="bar-label">${{s.station}}</div>
    <div class="bar-track">
      <div class="bar-fill winter" style="width:${{winPct}}%"></div>
      <div class="bar-fill summer" style="width:${{sumPct}}%"></div>
      ${{s.capacity_mlbhr > 0 ? `<div class="bar-fill capacity" style="width:${{capPct}}%"></div>` : ''}}
    </div>
    <div class="bar-value">${{s.capacity_mlbhr.toLocaleString()}}</div>
  `;
  utilChart.appendChild(row);
}});

// Sendout bar chart
const sendoutChart = document.getElementById('sendout-chart');
const maxGroupSendout = Math.max(...groups.map(g => g.summer_sendout_mlb + g.winter_sendout_mlb));
groups.forEach(g => {{
  const total = g.summer_sendout_mlb + g.winter_sendout_mlb;
  const totalPct = (total / maxGroupSendout * 100).toFixed(1);
  const sumShare = total > 0 ? (g.summer_sendout_mlb / total * 100).toFixed(1) : 0;

  const row = document.createElement('div');
  row.className = 'bar-row';
  row.innerHTML = `
    <div class="bar-label" title="${{g.group}}">${{g.group.length > 22 ? g.group.slice(0,22) + '...' : g.group}}</div>
    <div class="bar-track">
      <div style="display:flex;height:100%;width:${{totalPct}}%">
        <div style="width:${{sumShare}}%;background:#f59e0b;border-radius:4px 0 0 4px;opacity:0.85"></div>
        <div style="flex:1;background:#3b82f6;border-radius:0 4px 4px 0;opacity:0.6"></div>
      </div>
    </div>
    <div class="bar-value">${{(total/1e6).toFixed(1)}}B</div>
  `;
  sendoutChart.appendChild(row);
}});

// Detail table
const tbody = document.getElementById('detail-table');
const tfoot = document.getElementById('detail-footer');
let totSummer = 0, totWinter = 0, totAnnual = 0;

groups.forEach(g => {{
  totSummer += g.summer_sendout_mlb;
  totWinter += g.winter_sendout_mlb;
  totAnnual += g.annual_sendout_mlb;

  let hrClass, hrText;
  if (g.annual_heat_rate === 0) {{
    hrClass = 'hr-na';
    hrText = g.group === 'BNYCP' ? 'contract' : 'n/a';
  }} else if (g.annual_heat_rate < 100) {{
    hrClass = 'hr-cogen';
    hrText = g.annual_heat_rate;
  }} else {{
    hrClass = 'hr-boiler';
    hrText = g.annual_heat_rate.toLocaleString();
  }}

  const row = document.createElement('tr');
  row.innerHTML = `
    <td>${{g.group}}</td>
    <td class="right">${{g.summer_sendout_mlb.toLocaleString()}}</td>
    <td class="right">${{g.winter_sendout_mlb.toLocaleString()}}</td>
    <td class="right">${{g.annual_sendout_mlb.toLocaleString()}}</td>
    <td class="right">${{g.summer_avg_mlbhr.toLocaleString()}}</td>
    <td class="right ${{hrClass}}">${{hrText}}</td>
    <td style="font-size:11px;color:#6b7280;max-width:250px">${{g.notes}}</td>
  `;
  tbody.appendChild(row);
}});

const footRow = document.createElement('tr');
footRow.innerHTML = `
  <td style="font-weight:600;color:#e8ecf1">TOTAL</td>
  <td class="right" style="font-weight:600;color:#e8ecf1">${{totSummer.toLocaleString()}}</td>
  <td class="right" style="font-weight:600;color:#e8ecf1">${{totWinter.toLocaleString()}}</td>
  <td class="right" style="font-weight:600;color:#e8ecf1">${{totAnnual.toLocaleString()}}</td>
  <td class="right" style="font-weight:600;color:#e8ecf1">${{Math.round(totSummer / {SUMMER_HOURS}).toLocaleString()}}</td>
  <td></td><td></td>
`;
tfoot.appendChild(footRow);

// Utilization table
const utilTbody = document.getElementById('util-table');
stations.forEach(s => {{
  if (s.capacity_mlbhr === 0 && s.annual_sendout_mlb === 0) return;

  function meterHtml(pct, color) {{
    const clampPct = Math.min(pct, 100);
    return `<span class="util-meter"><span class="util-meter-fill" style="width:${{clampPct}}%;background:${{color}}"></span></span>${{pct.toFixed(1)}}%`;
  }}

  const row = document.createElement('tr');
  row.innerHTML = `
    <td>${{s.station}}</td>
    <td class="right">${{s.capacity_mlbhr.toLocaleString()}}</td>
    <td class="right">${{s.capacity_mlbhr > 0 ? meterHtml(s.summer_util_pct, '#f59e0b') : '—'}}</td>
    <td class="right">${{s.capacity_mlbhr > 0 ? meterHtml(s.winter_util_pct, '#3b82f6') : '—'}}</td>
    <td class="right">${{s.capacity_mlbhr > 0 ? meterHtml(s.annual_util_pct, '#8b5cf6') : '—'}}</td>
  `;
  utilTbody.appendChild(row);
}});
</script>

</body>
</html>"""

out_path = os.path.join(OUTPUT_DIR, "utilization.html")
with open(out_path, "w") as f:
    f.write(html)
print(f"Written: {out_path}")
print(f"Open with: open {out_path}")
