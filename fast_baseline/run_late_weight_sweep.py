from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT.parent
WEIGHTS = (100, 200, 300, 400, 500)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep late-order weights for Assignment + Routing V2")
    parser.add_argument(
        "--dataset",
        choices=["full_zones", "small", "large", "both"],
        default="full_zones",
        help="full_zones is the current default dataset; small/large are retained for historical comparisons",
    )
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs" / "late_weight_sweep")
    parser.add_argument("--consolidate-only", action="store_true")
    return parser.parse_args()


def dataset_args(name: str) -> list[str]:
    if name == "full_zones":
        return [
            "--input",
            str(DATA_ROOT / "merchant_data_full_with_zones.csv"),
            "--fleet-size",
            "800",
        ]
    if name == "large":
        return [
            "--input",
            str(DATA_ROOT / "10.17midday_data.csv"),
            "--fleet-size",
            "1300",
        ]
    return [
        "--input",
        str(DATA_ROOT / "2000.xlsx"),
        "--sheet-name",
        "sampled_data",
        "--courier-input",
        str(DATA_ROOT / "courier_pools" / "couriers_120.csv"),
        "--fleet-size",
        "120",
    ]


def result_row(dataset: str, weight: int, output_dir: Path) -> dict[str, object]:
    with (output_dir / "metrics.json").open(encoding="utf-8") as handle:
        metrics = json.load(handle)

    reference_objective_weight_100 = (
        float(metrics["total_distance_km"])
        + 1_000.0 * int(metrics["unserved_orders"])
        + 5.0 * float(metrics["total_lateness_minutes_completed"])
        + 100.0 * int(metrics["late_completed_orders"])
    )
    return {
        "dataset": dataset,
        "late_order_weight": weight,
        "valid_orders": metrics["valid_orders"],
        "couriers": metrics["couriers"],
        "completed_orders": metrics["completed_orders"],
        "rejected_orders": metrics["rejected_orders"],
        "unfinished_orders": metrics["unfinished_orders"],
        "completion_rate": metrics["completion_rate"],
        "on_time_orders": metrics["on_time_orders"],
        "on_time_rate_overall": metrics["on_time_delivery_rate_overall"],
        "late_completed_orders": metrics["late_completed_orders"],
        "total_overtime_minutes": metrics["total_lateness_minutes_completed"],
        "median_assignment_to_pickup_minutes": metrics["median_assignment_to_pickup_minutes"],
        "p90_assignment_to_pickup_minutes": metrics["p90_assignment_to_pickup_minutes"],
        "total_distance_km": metrics["total_distance_km"],
        "weighted_objective_at_run_weight": metrics["total_weighted_objective"],
        "reference_objective_weight_100": reference_objective_weight_100,
        "high_risk_expansion_orders": metrics["high_risk_expansion_orders"],
        "runtime_seconds": metrics["runtime_seconds"],
    }


def run_one(dataset: str, weight: int, output_root: Path) -> dict[str, object]:
    output_dir = output_root / dataset / f"late_weight_{weight}"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "run_baseline.py"),
            *dataset_args(dataset),
            "--late-order-weight",
            str(weight),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        check=True,
    )
    return result_row(dataset, weight, output_dir)


def main() -> None:
    args = parse_args()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    datasets = ("small", "large") if args.dataset == "both" else (args.dataset,)
    rows: list[dict[str, object]] = []
    for dataset in datasets:
        for weight in WEIGHTS:
            output_dir = output_root / dataset / f"late_weight_{weight}"
            if args.consolidate_only:
                rows.append(result_row(dataset, weight, output_dir))
            else:
                rows.append(run_one(dataset, weight, output_root))
            pd.DataFrame(rows).to_csv(
                output_root / "weight_sweep_results.csv",
                index=False,
                encoding="utf-8-sig",
            )
    print(f"Weight sweep table: {output_root / 'weight_sweep_results.csv'}")


if __name__ == "__main__":
    main()
