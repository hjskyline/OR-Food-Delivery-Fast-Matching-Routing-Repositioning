from __future__ import annotations

import argparse
import csv
import html
import math
from pathlib import Path


NAVY, ORANGE, GREEN, RED = "#123B73", "#E68632", "#218739", "#C83E3E"
GRAY, GRID, TEXT, WHITE = "#64748B", "#D9E2EC", "#14213D", "#FFFFFF"


def esc(value: object) -> str:
    return html.escape(str(value))


def line(x1: float, y1: float, x2: float, y2: float, color: str = GRID, width: float = 1) -> str:
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{width}"/>'


def text(x: float, y: float, value: object, size: int = 18, anchor: str = "middle", color: str = TEXT, weight: int = 400) -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" fill="{color}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" font-weight="{weight}">{esc(value)}</text>'


def polyline(points: list[tuple[float, float]], color: str) -> str:
    joined = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polyline points="{joined}" fill="none" stroke="{color}" stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/>'


def panel(parts: list[str], x: float, y: float, w: float, h: float, title_value: str) -> None:
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{WHITE}" stroke="{GRID}" stroke-width="2"/>')
    parts.append(text(x + 28, y + 42, title_value, 24, "start", NAVY, 700))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.input.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = sorted(csv.DictReader(handle), key=lambda row: int(row["fleet_size"]))

    fleet = [int(row["fleet_size"]) for row in rows]
    ot0 = [100 * float(row["on_time_without"]) for row in rows]
    ot1 = [100 * float(row["on_time_with"]) for row in rows]
    delta = [float(row["on_time_change_pp"]) for row in rows]
    obj0 = [float(row["objective_without"]) for row in rows]
    obj1 = [float(row["objective_with"]) for row in rows]
    run0 = [float(row["runtime_without_s"]) for row in rows]
    run1 = [float(row["runtime_with_s"]) for row in rows]
    moves = [float(row["reposition_moves"]) for row in rows]
    dist = [float(row["reposition_distance_km"]) for row in rows]

    width, height = 1800, 1200
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', f'<rect width="100%" height="100%" fill="{WHITE}"/>']
    parts.append(text(width / 2, 60, "Fleet Size Sensitivity: Causal Gamma–Poisson Repositioning", 38, "middle", NAVY, 700))
    parts.append(text(width / 2, 94, "17,867 orders · 20 km/h · Maximum 8 active orders per rider", 19, "middle", GRAY))

    panels = [(55, 125), (925, 125), (55, 650), (925, 650)]
    pw, ph = 820, 475
    for location, title_value in zip(panels, ["On-time Delivery Rate", "Composite Objective (Lower Is Better)", "Simulation Runtime", "Repositioning Activity"]):
        panel(parts, *location, pw, ph, title_value)

    x, y = panels[0]
    left, right, top, bottom = x + 90, x + pw - 35, y + 75, y + ph - 65
    ymin, ymax = 74.0, 101.0
    xs = [left + i * (right - left) / 3 for i in range(4)]
    sy = lambda v: bottom - (v - ymin) / (ymax - ymin) * (bottom - top)
    for tick in [75, 80, 85, 90, 95, 100]:
        yy = sy(tick); parts.extend([line(left, yy, right, yy), text(left - 15, yy + 6, f"{tick}%", 16, "end", GRAY)])
    parts.extend([polyline(list(zip(xs, map(sy, ot0))), NAVY), polyline(list(zip(xs, map(sy, ot1))), ORANGE)])
    for xi, v0, v1, d, n in zip(xs, ot0, ot1, delta, fleet):
        parts.extend([f'<circle cx="{xi:.1f}" cy="{sy(v0):.1f}" r="7" fill="{NAVY}"/>', f'<rect x="{xi-7:.1f}" y="{sy(v1)-7:.1f}" width="14" height="14" fill="{ORANGE}"/>', text(xi, bottom + 30, n, 17), text(xi, sy(v0) - 16, f"{v0:.2f}%", 16, "middle", NAVY, 700)])
        color = RED if d < -1e-9 else GREEN if d > 1e-9 else GRAY
        parts.append(text(xi, sy(v1) + 28, f"Δ {d:+.3f} pp", 15, "middle", color))
    parts.extend([line(left, bottom, right, bottom, TEXT, 2), text((left + right) / 2, y + ph - 18, "Number of riders", 17, "middle", GRAY)])
    parts.extend([f'<rect x="{x+440}" y="{y+27}" width="18" height="6" fill="{NAVY}"/>', text(x+465, y+36, "Without repositioning", 14, "start", GRAY), f'<rect x="{x+630}" y="{y+27}" width="18" height="6" fill="{ORANGE}"/>', text(x+655, y+36, "With repositioning", 14, "start", GRAY)])

    x, y = panels[1]; left, right, top, bottom = x + 110, x + pw - 35, y + 75, y + ph - 65
    logs = [math.log10(v) for v in obj0 + obj1]; lo, hi = math.floor(min(logs) * 10) / 10, math.ceil(max(logs) * 10) / 10
    sy2 = lambda v: bottom - (math.log10(v) - lo) / (hi - lo) * (bottom - top)
    for tick in [40000, 100000, 250000, 500000, 1000000]:
        if lo <= math.log10(tick) <= hi:
            yy = sy2(tick); parts.extend([line(left, yy, right, yy), text(left - 15, yy + 6, f"{tick:,.0f}", 15, "end", GRAY)])
    xs2 = [left + i * (right-left)/3 for i in range(4)]
    parts.extend([polyline(list(zip(xs2, map(sy2, obj0))), NAVY), polyline(list(zip(xs2, map(sy2, obj1))), ORANGE)])
    for xi, a, b, n in zip(xs2, obj0, obj1, fleet):
        parts.extend([f'<circle cx="{xi:.1f}" cy="{sy2(a):.1f}" r="7" fill="{NAVY}"/>', f'<rect x="{xi-7:.1f}" y="{sy2(b)-7:.1f}" width="14" height="14" fill="{ORANGE}"/>', text(xi, bottom + 30, n, 17)])
    parts.extend([line(left, bottom, right, bottom, TEXT, 2), text((left+right)/2, y+ph-18, "Number of riders", 17, "middle", GRAY)])

    x, y = panels[2]; left, right, top, bottom = x + 90, x + pw - 35, y + 75, y + ph - 65
    maxrun = max(run0 + run1) * 1.16; group_x = [left + (i + .5) * (right-left)/4 for i in range(4)]; barw = 46
    for tick in range(0, int(maxrun) + 1, 50):
        yy = bottom - tick/maxrun*(bottom-top); parts.extend([line(left, yy, right, yy), text(left-15, yy+6, tick, 15, "end", GRAY)])
    for xi, a, b, n in zip(group_x, run0, run1, fleet):
        for off, val, color in [(-barw/2, a, NAVY), (barw/2, b, ORANGE)]:
            bh = val/maxrun*(bottom-top); parts.extend([f'<rect x="{xi+off-barw/2:.1f}" y="{bottom-bh:.1f}" width="{barw}" height="{bh:.1f}" fill="{color}"/>', text(xi+off, bottom-bh-9, f"{val:.1f}s", 14, "middle", color, 700)])
        parts.append(text(xi, bottom+30, n, 17))
    parts.extend([line(left,bottom,right,bottom,TEXT,2), text((left+right)/2,y+ph-18,"Number of riders",17,"middle",GRAY), text(left-55,(top+bottom)/2,"Runtime (seconds)",16,"middle",GRAY)])

    x, y = panels[3]; left, right, top, bottom = x + 90, x + pw - 75, y + 75, y + ph - 65
    maxm = max(moves) * 1.25 if max(moves) else 1; maxd = max(dist) * 1.25 if max(dist) else 1; group_x = [left + (i+.5)*(right-left)/4 for i in range(4)]
    for tick in range(0, int(maxm)+1, 50):
        yy=bottom-tick/maxm*(bottom-top); parts.extend([line(left,yy,right,yy), text(left-15,yy+6,tick,15,"end",GRAY)])
    distance_points=[]
    for xi, m, d, n in zip(group_x,moves,dist,fleet):
        bh=m/maxm*(bottom-top); parts.extend([f'<rect x="{xi-31:.1f}" y="{bottom-bh:.1f}" width="62" height="{bh:.1f}" fill="{ORANGE}"/>', text(xi,bottom-bh-9,f"{m:.0f}",15,"middle",ORANGE,700), text(xi,bottom+30,n,17)]); distance_points.append((xi,bottom-d/maxd*(bottom-top)))
    parts.append(polyline(distance_points,GREEN))
    for (xi,yy),d in zip(distance_points,dist):
        parts.extend([f'<circle cx="{xi:.1f}" cy="{yy:.1f}" r="7" fill="{GREEN}"/>', text(xi,yy-14,f"{d:.1f} km",14,"middle",GREEN,700)])
    parts.extend([line(left,bottom,right,bottom,TEXT,2), text((left+right)/2,y+ph-18,"Number of riders",17,"middle",GRAY), text(left-55,(top+bottom)/2,"Reposition moves",16,"middle",GRAY), text(right+52,(top+bottom)/2,"Distance (km)",16,"middle",GREEN)])

    parts.append(text(width/2, 1180, "Result: causal repositioning did not improve the on-time delivery rate at any tested fleet size.", 20, "middle", RED, 700))
    parts.append("</svg>")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    main()
