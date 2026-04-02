"""
Generate interactive map of classified buildings.
"""

import csv
import os
import folium
from folium.plugins import HeatMap

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# Load classified buildings
buildings = []
with open(os.path.join(OUTPUT_DIR, "buildings_classified.csv")) as f:
    for r in csv.DictReader(f):
        try:
            r["lat"] = float(r["latitude"])
            r["lng"] = float(r["longitude"])
            r["sqft_n"] = int(r["sqft"])
            r["peak_kw"] = int(r["peak_month_cooling_kw"])
            r["avg_kw"] = int(r["avg_summer_cooling_kw"])
            buildings.append(r)
        except (ValueError, TypeError):
            pass

print(f"Mapping {len(buildings)} buildings")

m = folium.Map(
    location=[40.754, -73.984],
    zoom_start=13,
    tiles="CartoDB dark_matter",
)

COLORS = {
    "BOTH": "#ff3333",
    "STEAM_ONLY": "#ff9900",
    "ELECTRIC_ONLY": "#4488ff",
    "UNCLEAR": "#666666",
}

LABELS = {
    "BOTH": "Both Steam + Electric Cooling (DR Ready)",
    "STEAM_ONLY": "Steam Cooling Only",
    "ELECTRIC_ONLY": "Electric Cooling Only (steam for heating)",
    "UNCLEAR": "Unclear / Insufficient Data",
}


def get_radius(r):
    kw = r["peak_kw"]
    if kw > 5000:
        return 14
    if kw > 2000:
        return 10
    if kw > 500:
        return 7
    if kw > 100:
        return 5
    return 3


def fmt(n):
    return f"{n:,}"


# Add building markers
for b in buildings:
    cls = b["classification"]
    color = COLORS[cls]

    if cls == "UNCLEAR" and b["peak_kw"] == 0:
        continue

    popup_html = f"""
    <div style="font-family: Arial, sans-serif; font-size: 12px; min-width: 300px;">
        <h3 style="margin: 0 0 8px 0; color: #333;">{b['property_name'][:50]}</h3>
        <div style="
            display: inline-block;
            padding: 3px 10px;
            border-radius: 4px;
            background: {color};
            color: white;
            font-weight: bold;
            font-size: 11px;
            margin-bottom: 8px;
        ">{LABELS[cls]}</div>
        <table style="border-collapse: collapse; width: 100%; margin-top: 8px;">
            <tr><td style="padding: 2px 8px 2px 0; color: #666;">Address</td>
                <td style="padding: 2px 0;"><b>{b['address']}</b></td></tr>
            <tr><td style="padding: 2px 8px 2px 0; color: #666;">Type</td>
                <td style="padding: 2px 0;">{b['property_type']}</td></tr>
            <tr><td style="padding: 2px 8px 2px 0; color: #666;">Size</td>
                <td style="padding: 2px 0;">{fmt(b['sqft_n'])} sqft</td></tr>
            <tr><td colspan="2" style="padding: 8px 0 4px 0; font-weight: bold; color: #333;
                border-top: 1px solid #eee;">Steam Evidence</td></tr>
            <tr><td style="padding: 2px 8px 2px 0; color: #666;">Steam vs heating baseline</td>
                <td style="padding: 2px 0;"><b>{b['steam_ratio_vs_baseline']}x</b></td></tr>
            <tr><td style="padding: 2px 8px 2px 0; color: #666;">Steam % of total energy</td>
                <td style="padding: 2px 0;">{b['steam_pct_of_total']}%</td></tr>
            <tr><td style="padding: 2px 8px 2px 0; color: #666;">Cooling towers</td>
                <td style="padding: 2px 0;">{b['num_cooling_towers']}</td></tr>
            <tr><td colspan="2" style="padding: 8px 0 4px 0; font-weight: bold; color: #333;
                border-top: 1px solid #eee;">Electric Cooling Evidence</td></tr>
            <tr><td style="padding: 2px 8px 2px 0; color: #666;">Summer elec increase</td>
                <td style="padding: 2px 0;"><b>{b['summer_elec_increase_pct']}%</b> above winter</td></tr>
            <tr><td style="padding: 2px 8px 2px 0; color: #666;">Cooling % of electricity</td>
                <td style="padding: 2px 0;">{b['cooling_pct_of_elec']}%</td></tr>
            <tr style="background: #f0f7ff;">
                <td style="padding: 4px 8px 4px 0; color: #666;">Peak month cooling</td>
                <td style="padding: 4px 0;"><b>{fmt(b['peak_kw'])} kW</b></td></tr>
            <tr style="background: #f0f7ff;">
                <td style="padding: 4px 8px 4px 0; color: #666;">Avg summer cooling</td>
                <td style="padding: 4px 0;"><b>{fmt(b['avg_kw'])} kW</b></td></tr>
        </table>
    </div>
    """

    tooltip = f"{b['property_name'][:30]} — {LABELS[cls].split('(')[0].strip()}"
    if b["peak_kw"] > 0:
        tooltip += f" — {fmt(b['peak_kw'])} kW"

    folium.CircleMarker(
        location=[b["lat"], b["lng"]],
        radius=get_radius(b),
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.7,
        weight=1,
        popup=folium.Popup(popup_html, max_width=380),
        tooltip=tooltip,
    ).add_to(m)

# Heatmap of DR-ready buildings
heat_data = []
for b in buildings:
    if b["classification"] == "BOTH" and b["peak_kw"] > 0:
        weight = min(b["peak_kw"] / 1000, 20)
        heat_data.append([b["lat"], b["lng"], weight])

HeatMap(
    heat_data,
    name="DR-Ready Heatmap",
    radius=25,
    blur=20,
    max_zoom=15,
    gradient={
        0.2: "#0000ff",
        0.4: "#00ffff",
        0.6: "#00ff00",
        0.8: "#ffff00",
        1.0: "#ff0000",
    },
).add_to(m)

# Legend with DR totals per class
class_stats = {}
for cls in ["BOTH", "STEAM_ONLY", "ELECTRIC_ONLY", "UNCLEAR"]:
    subset = [b for b in buildings if b["classification"] == cls]
    class_stats[cls] = {
        "count": len(subset),
        "peak_mw": sum(b["peak_kw"] for b in subset) / 1000,
        "avg_mw": sum(b["avg_kw"] for b in subset) / 1000,
    }

s = class_stats
legend_html = f"""
<div style="
    position: fixed;
    bottom: 30px;
    left: 30px;
    z-index: 1000;
    background: rgba(0,0,0,0.88);
    padding: 16px 20px;
    border-radius: 8px;
    font-family: Arial, sans-serif;
    font-size: 12px;
    color: white;
    line-height: 1.6;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
">
    <div style="font-size: 14px; font-weight: bold; margin-bottom: 4px;">
        Chiller Classification
    </div>
    <div style="font-size: 11px; color: #aaa; margin-bottom: 10px;">
        Based on steam intensity + monthly electric data
    </div>
    <table style="border-collapse: collapse; width: 100%; font-size: 12px;">
        <tr style="color: #999; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px;">
            <td style="padding: 0 0 6px 0;"></td>
            <td style="padding: 0 0 6px 8px; text-align: right;">Bldgs</td>
            <td style="padding: 0 0 6px 8px; text-align: right;">Peak MW</td>
            <td style="padding: 0 0 6px 8px; text-align: right;">Avg MW</td>
        </tr>
        <tr>
            <td style="padding: 3px 0;"><span style="color: #ff3333;">&#11044;</span> <b>Both</b> (DR ready)</td>
            <td style="padding: 3px 0 3px 8px; text-align: right;">{s['BOTH']['count']}</td>
            <td style="padding: 3px 0 3px 8px; text-align: right; color: #ff3333;"><b>{s['BOTH']['peak_mw']:.0f}</b></td>
            <td style="padding: 3px 0 3px 8px; text-align: right;">{s['BOTH']['avg_mw']:.0f}</td>
        </tr>
        <tr>
            <td style="padding: 3px 0;"><span style="color: #ff9900;">&#11044;</span> <b>Steam only</b></td>
            <td style="padding: 3px 0 3px 8px; text-align: right;">{s['STEAM_ONLY']['count']}</td>
            <td style="padding: 3px 0 3px 8px; text-align: right;">{s['STEAM_ONLY']['peak_mw']:.0f}</td>
            <td style="padding: 3px 0 3px 8px; text-align: right;">{s['STEAM_ONLY']['avg_mw']:.0f}</td>
        </tr>
        <tr>
            <td style="padding: 3px 0;"><span style="color: #4488ff;">&#11044;</span> <b>Electric only</b></td>
            <td style="padding: 3px 0 3px 8px; text-align: right;">{s['ELECTRIC_ONLY']['count']}</td>
            <td style="padding: 3px 0 3px 8px; text-align: right;">{s['ELECTRIC_ONLY']['peak_mw']:.0f}</td>
            <td style="padding: 3px 0 3px 8px; text-align: right;">{s['ELECTRIC_ONLY']['avg_mw']:.0f}</td>
        </tr>
        <tr style="color: #777;">
            <td style="padding: 3px 0;"><span style="color: #666;">&#11044;</span> Unclear</td>
            <td style="padding: 3px 0 3px 8px; text-align: right;">{s['UNCLEAR']['count']}</td>
            <td style="padding: 3px 0 3px 8px; text-align: right;">{s['UNCLEAR']['peak_mw']:.0f}</td>
            <td style="padding: 3px 0 3px 8px; text-align: right;">{s['UNCLEAR']['avg_mw']:.0f}</td>
        </tr>
    </table>
    <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid #444;">
        <div style="font-size: 11px; color: #aaa;">Peak MW = peak month cooling load</div>
        <div style="font-size: 11px; color: #aaa;">Avg MW = average summer cooling load</div>
        <div style="font-size: 11px; color: #aaa;">Circle size = peak cooling kW</div>
        <div style="font-size: 11px; color: #aaa;">Click buildings for details</div>
    </div>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

# Title
both_peak = s["BOTH"]["peak_mw"]
both_avg = s["BOTH"]["avg_mw"]
both_n = s["BOTH"]["count"]
title_html = f"""
<div style="
    position: fixed;
    top: 15px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 1000;
    background: rgba(0,0,0,0.88);
    padding: 12px 24px;
    border-radius: 8px;
    font-family: Arial, sans-serif;
    color: white;
    text-align: center;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
">
    <div style="font-size: 18px; font-weight: bold;">
        NYC Steam Chiller DR Potential
    </div>
    <div style="font-size: 12px; color: #aaa; margin-top: 4px;">
        {both_n} buildings with both steam + electric cooling &bull;
        {both_peak:.0f} MW peak &bull; {both_avg:.0f} MW avg summer
    </div>
</div>
"""
m.get_root().html.add_child(folium.Element(title_html))

folium.LayerControl().add_to(m)

map_path = os.path.join(OUTPUT_DIR, "map.html")
m.save(map_path)
print(f"Map saved to {map_path}")
