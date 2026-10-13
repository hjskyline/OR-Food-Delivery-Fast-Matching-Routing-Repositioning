from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


CODE_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = CODE_DIR.parent
DATA_DIR = PACKAGE_DIR / "data_global"

CASES = {
    "small_120": {
        "input": DATA_DIR / "merchant_data_2200_with_zones_global.csv",
        "fleet_size": 120,
    },
    "small_100": {
        "input": DATA_DIR / "merchant_data_2200_with_zones_global.csv",
        "fleet_size": 100,
    },
    "full_800": {
        "input": DATA_DIR / "merchant_data_full_with_zones_global.csv",
        "fleet_size": 800,
    },
}


def build_command(case_name: str, output_root: Path) -> list[str]:
    case = CASES[case_name]
    return [
        sys.executable,
        str(CODE_DIR / "run_baseline.py"),
        "--input", str(case["input"]),
        "--output-dir", str(output_root / case_name),
        "--fleet-size", str(case["fleet_size"]),
        "--speed-kmh", "20",
        "--max-active-orders", "8",
        "--candidate-riders", "8",
        "--insertion-position-limit", "3",
        "--route-fit-candidate-riders", "4",
        "--lowest-load-candidate-riders", "2",
        "--earliest-pickup-candidate-riders", "2",
        "--route-fit-prefilter-riders", "256",
        "--route-fit-prefilter-nearest-riders", "128",
        "--route-fit-prefilter-earliest-pickup-riders", "96",
        "--route-fit-prefilter-lowest-load-riders", "32",
        "--high-risk-candidate-riders", "12",
        "--high-risk-insertion-position-limit", "4",
        "--route-optimization-min-active-orders", "3",
        "--route-optimization-max-passes", "2",
        "--route-optimization-position-limit", "4",
        "--distance-weight", "1",
        "--unserved-order-penalty", "1000",
        "--lateness-minute-weight", "5",
        "--late-order-weight", "100",
        "--rider-start-mode", "simulation_start",
        "--fleet-selection", "most_active",
        "--fleet-random-seed", "42",
        "--dispatch-processing-minutes", "1",
        "--pickup-service-minutes", "1",
        "--delivery-service-minutes", "2",
        "--ready-time-buffer-minutes", "0",
        "--distance-metric", "rectilinear",
        "--reposition-policy", "none",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reproduce the three retained assignment-and-routing experiments."
    )
    parser.add_argument(
        "--case",
        choices=["all", *CASES],
        default="all",
        help="Run all retained cases or one named case.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PACKAGE_DIR / "reproduced_outputs",
    )
    args = parser.parse_args()

    selected = list(CASES) if args.case == "all" else [args.case]
    args.output_root.mkdir(parents=True, exist_ok=True)
    for case_name in selected:
        print(f"\n=== Running {case_name} ===", flush=True)
        subprocess.run(build_command(case_name, args.output_root), cwd=CODE_DIR, check=True)

    print("\nAll requested experiments completed.")
    print(f"Results: {args.output_root.resolve()}")


if __name__ == "__main__":
    main()
