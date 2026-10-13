from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ACTUAL = PACKAGE_DIR / "reproduced_outputs"
REFERENCE = PACKAGE_DIR / "reference_results"

EXACT_KEYS = [
    "valid_orders",
    "couriers",
    "assigned_orders",
    "rejected_orders",
    "completed_orders",
    "on_time_orders",
    "late_completed_orders",
    "high_risk_expansion_orders",
]

FLOAT_KEYS = [
    "completion_rate",
    "on_time_delivery_rate_overall",
    "total_lateness_minutes_completed",
    "total_distance_km",
    "total_weighted_objective",
]


def load_metrics(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare reproduced metrics with retained results.")
    parser.add_argument("--actual-root", type=Path, default=DEFAULT_ACTUAL)
    parser.add_argument("--absolute-tolerance", type=float, default=1e-6)
    args = parser.parse_args()

    failed = False
    for case_name in ("small_120", "small_100", "full_800"):
        expected = load_metrics(REFERENCE / case_name / "metrics.json")
        actual_path = args.actual_root / case_name / "metrics.json"
        if not actual_path.exists():
            print(f"FAIL {case_name}: missing {actual_path}")
            failed = True
            continue
        actual = load_metrics(actual_path)
        issues = []
        for key in EXACT_KEYS:
            if actual.get(key) != expected.get(key):
                issues.append(f"{key}: actual={actual.get(key)!r}, expected={expected.get(key)!r}")
        for key in FLOAT_KEYS:
            if not math.isclose(
                float(actual.get(key, math.nan)),
                float(expected.get(key, math.nan)),
                rel_tol=0.0,
                abs_tol=args.absolute_tolerance,
            ):
                issues.append(f"{key}: actual={actual.get(key)!r}, expected={expected.get(key)!r}")
        if issues:
            failed = True
            print(f"FAIL {case_name}")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"PASS {case_name}")

    if failed:
        raise SystemExit(1)
    print("All retained metrics were reproduced within tolerance. Runtime is intentionally excluded.")


if __name__ == "__main__":
    main()
