from __future__ import annotations

import html
from pathlib import Path


OUT = Path(__file__).resolve().parent / "outputs" / "today_three_version_comparison"
SVG = OUT / "assignment_routing_reposition_comparison.svg"

NAVY = "#0B2F6B"
NAVY_2 = "#16458A"
TEXT = "#13213C"
MUTED = "#64748B"
GRID = "#D8E2EE"
GREEN = "#16753A"
RED = "#D62828"
ORANGE = "#D97706"
WHITE = "#FFFFFF"
SOFT = "#F5F8FC"


def esc(value: object) -> str:
    return html.escape(str(value))


def txt(x: float, y: float, value: object, size: int = 20, anchor: str = "middle", color: str = TEXT, weight: int = 400) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
        f'fill="{color}" font-family="Arial, Helvetica, sans-serif" '
        f'font-size="{size}" font-weight="{weight}">{esc(value)}</text>'
    )


def main() -> None:
    rows = [
        ("Completion rate", "99.37%", "99.98%", "99.98%", "+0.62 pp", "0.00 pp", GREEN, MUTED),
        ("On-time delivery rate", "69.70%", "77.68%", "77.67%", "+7.98 pp", "−0.006 pp", GREEN, RED),
        ("Completed orders", "17,754", "17,864", "17,864", "+110", "0", GREEN, MUTED),
        ("Rejected orders", "113", "3", "3", "−110", "0", GREEN, MUTED),
        ("Late orders", "5,300", "3,985", "3,986", "−1,315", "+1", GREEN, RED),
        ("Total lateness (min)", "339,198.85", "117,724.68", "117,725.14", "−221,474.17", "+0.47", GREEN, RED),
        ("Total travel distance (km)", "41,512.39", "31,397.19", "31,462.17", "−10,115.20", "+64.97", GREEN, RED),
        ("Reposition distance (km)", "0.00", "0.00", "55.07", "0.00", "+55.07", MUTED, RED),
        ("Composite objective", "2,380,506.64", "1,021,520.59", "1,021,687.89", "−1,358,986.05", "+167.30", GREEN, RED),
        ("Runtime (sec)", "97.58", "181.15", "184.37", "+83.57", "+3.22", ORANGE, ORANGE),
    ]

    width, height = 1800, 1110
    left, top = 42, 154
    table_w = width - 84
    header_h, row_h = 74, 72
    col_w = [430, 238, 260, 274, 260, 254]
    x_edges = [left]
    for w in col_w:
        x_edges.append(x_edges[-1] + w)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="{WHITE}"/>',
        txt(width / 2, 61, "Assignment, Routing and Repositioning Performance Comparison", 38, "middle", NAVY, 700),
        txt(width / 2, 102, "17,867 orders · 800 riders · 20 km/h · Maximum 8 active orders per rider", 20, "middle", MUTED, 400),
        f'<rect x="{left}" y="{top}" width="{table_w}" height="{header_h + len(rows) * row_h}" rx="16" fill="{WHITE}" stroke="{GRID}" stroke-width="2"/>',
        f'<path d="M {left+16} {top} H {left+table_w-16} Q {left+table_w} {top} {left+table_w} {top+16} V {top+header_h} H {left} V {top+16} Q {left} {top} {left+16} {top} Z" fill="{NAVY}"/>',
    ]

    headers = ["Metric", "Before Improvement", "After Improvement", "With Repositioning", "Improvement Effect", "Reposition Effect"]
    for i, label in enumerate(headers):
        parts.append(txt((x_edges[i] + x_edges[i + 1]) / 2, top + 47, label, 18, "middle", WHITE, 700))

    for r, row in enumerate(rows):
        y = top + header_h + r * row_h
        if r % 2:
            parts.append(f'<rect x="{left+1}" y="{y}" width="{table_w-2}" height="{row_h}" fill="{SOFT}"/>')
        parts.append(f'<line x1="{left}" y1="{y}" x2="{left+table_w}" y2="{y}" stroke="{GRID}" stroke-width="1"/>')
        metric, before, after, reposition, improve_delta, repos_delta, improve_color, repos_color = row
        parts.append(txt(x_edges[0] + 28, y + 45, metric, 19, "start", TEXT, 500))
        parts.append(txt((x_edges[1] + x_edges[2]) / 2, y + 45, before, 19, "middle", TEXT, 400))
        parts.append(txt((x_edges[2] + x_edges[3]) / 2, y + 45, after, 19, "middle", NAVY_2, 700))
        parts.append(txt((x_edges[3] + x_edges[4]) / 2, y + 45, reposition, 19, "middle", TEXT, 400))
        parts.append(txt((x_edges[4] + x_edges[5]) / 2, y + 45, improve_delta, 19, "middle", improve_color, 700))
        parts.append(txt((x_edges[5] + x_edges[6]) / 2, y + 45, repos_delta, 19, "middle", repos_color, 700))

    for x in x_edges[1:-1]:
        parts.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{top+header_h+len(rows)*row_h}" stroke="{GRID}" stroke-width="1"/>')

    note_y = top + header_h + len(rows) * row_h + 50
    parts.extend([
        f'<circle cx="{left+18}" cy="{note_y-6}" r="8" fill="{GREEN}"/>',
        txt(left + 38, note_y, "Improvement effect compares After Improvement with Before Improvement.", 17, "start", MUTED),
        f'<circle cx="{left+755}" cy="{note_y-6}" r="8" fill="{RED}"/>',
        txt(left + 775, note_y, "Reposition effect compares With Repositioning with After Improvement.", 17, "start", MUTED),
        f'<rect x="{left}" y="{note_y+32}" width="{table_w}" height="72" rx="12" fill="{SOFT}"/>',
        txt(width / 2, note_y + 64, "Best current configuration: improved Assignment and Routing without repositioning", 23, "middle", NAVY, 700),
        txt(width / 2, note_y + 91, "Repositioning adds 64.97 km of travel and does not improve the on-time delivery rate.", 17, "middle", MUTED, 400),
        "</svg>",
    ])

    OUT.mkdir(parents=True, exist_ok=True)
    SVG.write_text("\n".join(parts), encoding="utf-8")
    print(SVG)


if __name__ == "__main__":
    main()
