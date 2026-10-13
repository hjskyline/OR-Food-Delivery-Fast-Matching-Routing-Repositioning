from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT.parent / "data_global" / "merchant_data_2200_with_zones_global.csv"


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Run the same assignment/routing instance with and without Gamma-Poisson repositioning."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--fleet-size", type=int, default=120)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "comparison_latest")
    args, passthrough = parser.parse_known_args()
    return args, passthrough


def run_case(args: argparse.Namespace, passthrough: list[str], policy: str, name: str) -> dict[str, object]:
    case_dir = args.output_dir.resolve() / name
    command = [
        sys.executable,
        str(ROOT / "run_baseline.py"),
        "--input",
        str(args.input.resolve()),
        "--fleet-size",
        str(args.fleet_size),
        "--output-dir",
        str(case_dir),
        "--reposition-policy",
        policy,
        *passthrough,
    ]
    subprocess.run(command, check=True)
    return pd.read_csv(case_dir / "metrics.csv").iloc[0].to_dict()


def main() -> None:
    args, passthrough = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    control = run_case(args, passthrough, "none", "without_reposition")
    treatment = run_case(args, passthrough, "gamma_poisson", "with_gamma_poisson")

    definitions = [
        ("Completion rate", "completion_rate", "higher"),
        ("On-time delivery rate", "on_time_delivery_rate_overall", "higher"),
        ("Rejected orders", "rejected_orders", "lower"),
        ("Late completed orders", "late_completed_orders", "lower"),
        ("Total lateness (min)", "total_lateness_minutes_completed", "lower"),
        ("Service-route distance (km)", "service_route_distance_km", "lower"),
        ("Reposition distance (km)", "reposition_distance_km", "lower"),
        ("Total distance (km)", "total_distance_km", "lower"),
        ("Weighted system objective", "total_weighted_objective", "lower"),
        ("Runtime (s)", "runtime_seconds", "lower"),
        ("Reposition moves", "reposition_moves", "information"),
    ]
    rows: list[dict[str, object]] = []
    for label, key, direction in definitions:
        before = float(control[key])
        after = float(treatment[key])
        change = after - before
        relative = change / before if abs(before) > 1e-12 else float("nan")
        if direction == "information" or abs(change) <= 1e-12:
            evaluation = "Information" if direction == "information" else "No change"
        else:
            improved = change > 0 if direction == "higher" else change < 0
            evaluation = "Improved" if improved else "Worsened"
        rows.append({
            "metric": label,
            "without_reposition": before,
            "with_gamma_poisson": after,
            "absolute_change": change,
            "relative_change": relative,
            "evaluation": evaluation,
        })
    comparison = pd.DataFrame(rows)
    comparison.to_csv(args.output_dir.resolve() / "comparison.csv", index=False, encoding="utf-8-sig")
    print(f"Comparison output: {args.output_dir.resolve() / 'comparison.csv'}")
    print(comparison.to_string(index=False))


if __name__ == "__main__":
    main()
