from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT.parent / "data_global" / "merchant_data_full_with_zones_global.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare causal Gamma-Poisson repositioning across fleet sizes."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--fleet-sizes", type=int, nargs="+", default=[800, 900, 1000, 1100])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "fleet_comparison_latest")
    return parser.parse_args()


def run_case(input_path: Path, fleet_size: int, policy: str, output_dir: Path) -> dict[str, object]:
    case_name = "without_reposition" if policy == "none" else "with_reposition"
    case_dir = output_dir / f"fleet_{fleet_size}" / case_name
    subprocess.run([
        sys.executable,
        str(ROOT / "run_baseline.py"),
        "--input", str(input_path.resolve()),
        "--fleet-size", str(fleet_size),
        "--reposition-policy", policy,
        "--reposition-forecast-mode", "causal_gamma_poisson",
        "--output-dir", str(case_dir),
    ], check=True)
    metrics = pd.read_csv(case_dir / "metrics.csv").iloc[0].to_dict()
    metrics["fleet_size"] = fleet_size
    metrics["scenario"] = case_name
    return metrics


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for fleet_size in args.fleet_sizes:
        control = run_case(args.input, fleet_size, "none", output_dir)
        treatment = run_case(args.input, fleet_size, "gamma_poisson", output_dir)
        rows.extend([control, treatment])

    raw = pd.DataFrame(rows)
    raw.to_csv(output_dir / "fleet_metrics_all.csv", index=False, encoding="utf-8-sig")
    selected = raw[[
        "fleet_size", "scenario", "completion_rate",
        "on_time_delivery_rate_overall", "on_time_orders", "rejected_orders",
        "late_completed_orders", "total_lateness_minutes_completed",
        "service_route_distance_km", "reposition_distance_km", "total_distance_km",
        "total_weighted_objective", "reposition_moves", "runtime_seconds",
        "post_service_relocation_plans", "post_service_relocation_activated",
        "post_service_relocation_cancelled",
    ]].copy()
    selected.to_csv(output_dir / "fleet_comparison.csv", index=False, encoding="utf-8-sig")

    pivot = selected.pivot(index="fleet_size", columns="scenario")
    summary = pd.DataFrame({
        "fleet_size": args.fleet_sizes,
        "on_time_without": [pivot.loc[n, ("on_time_delivery_rate_overall", "without_reposition")] for n in args.fleet_sizes],
        "on_time_with": [pivot.loc[n, ("on_time_delivery_rate_overall", "with_reposition")] for n in args.fleet_sizes],
        "on_time_change_pp": [100.0 * (pivot.loc[n, ("on_time_delivery_rate_overall", "with_reposition")] - pivot.loc[n, ("on_time_delivery_rate_overall", "without_reposition")]) for n in args.fleet_sizes],
        "objective_without": [pivot.loc[n, ("total_weighted_objective", "without_reposition")] for n in args.fleet_sizes],
        "objective_with": [pivot.loc[n, ("total_weighted_objective", "with_reposition")] for n in args.fleet_sizes],
        "reposition_moves": [pivot.loc[n, ("reposition_moves", "with_reposition")] for n in args.fleet_sizes],
        "reposition_distance_km": [pivot.loc[n, ("reposition_distance_km", "with_reposition")] for n in args.fleet_sizes],
        "runtime_without_s": [pivot.loc[n, ("runtime_seconds", "without_reposition")] for n in args.fleet_sizes],
        "runtime_with_s": [pivot.loc[n, ("runtime_seconds", "with_reposition")] for n in args.fleet_sizes],
    })
    summary.to_csv(output_dir / "fleet_summary.csv", index=False, encoding="utf-8-sig")
    print(f"Fleet summary: {output_dir / 'fleet_summary.csv'}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
