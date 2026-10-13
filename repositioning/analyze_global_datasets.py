from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


TIME_COLUMNS = [
    "platform_order_time",
    "order_push_time",
    "grab_time",
    "fetch_time",
    "arrive_time",
    "estimate_meal_prepare_time",
    "estimate_arrived_time",
]
COORDINATE_COLUMNS = [
    "sender_lng",
    "sender_lat",
    "recipient_lng",
    "recipient_lat",
    "grab_lng",
    "grab_lat",
]


def summarize(path: Path) -> tuple[pd.DataFrame, dict]:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    for column in TIME_COLUMNS:
        if column in frame:
            frame[column] = pd.to_datetime(
                frame[column], dayfirst=True, errors="coerce", format="mixed"
            )

    summary = {
        "path": str(path.resolve()),
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "duplicate_order_ids": int(frame["order_id"].duplicated().sum()),
        "unique_orders": int(frame["order_id"].nunique()),
        "unique_couriers": int(frame["courier_id"].nunique()),
        "unique_da_ids": int(frame["da_id"].nunique()),
        "unique_zone_ids": int(frame["zone_id"].nunique()),
        "missing_da_id": int(frame["da_id"].isna().sum()),
        "missing_zone_id": int(frame["zone_id"].isna().sum()),
        "release_start": str(frame["order_push_time"].min()),
        "release_end": str(frame["order_push_time"].max()),
        "deadline_end": str(frame["estimate_arrived_time"].max()),
        "zone_id_min": int(frame["zone_id"].min()),
        "zone_id_max": int(frame["zone_id"].max()),
        "hour_slot_values": sorted(
            int(value) for value in frame["hour_slot"].dropna().unique()
        ),
        "coordinate_ranges": {
            column: {
                "min": float(frame[column].min()),
                "max": float(frame[column].max()),
            }
            for column in COORDINATE_COLUMNS
        },
    }
    return frame, summary


def changed_columns(left: pd.DataFrame, right: pd.DataFrame) -> dict:
    common_columns = [column for column in left.columns if column in right.columns]
    merged = left[common_columns].merge(
        right[common_columns], on="order_id", how="inner", suffixes=("_left", "_right")
    )
    changes = {}
    for column in common_columns:
        if column == "order_id":
            continue
        left_values = merged[f"{column}_left"]
        right_values = merged[f"{column}_right"]
        equal = left_values.eq(right_values) | (left_values.isna() & right_values.isna())
        changed = int((~equal).sum())
        if changed:
            changes[column] = changed
    return {
        "common_orders": int(len(merged)),
        "left_only_orders": int((~left["order_id"].isin(right["order_id"])).sum()),
        "right_only_orders": int((~right["order_id"].isin(left["order_id"])).sum()),
        "changed_cells_by_column": changes,
    }


def zone_mapping(frame: pd.DataFrame) -> dict:
    da_to_zone = frame.groupby("da_id")["zone_id"].nunique()
    zone_to_da = frame.groupby("zone_id")["da_id"].nunique()
    return {
        "da_ids_mapping_to_multiple_zones": int((da_to_zone > 1).sum()),
        "max_zones_per_da_id": int(da_to_zone.max()),
        "zones_containing_multiple_da_ids": int((zone_to_da > 1).sum()),
        "max_da_ids_per_zone": int(zone_to_da.max()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--small", type=Path, required=True)
    parser.add_argument("--full", type=Path, required=True)
    parser.add_argument("--old-full", type=Path, required=True)
    args = parser.parse_args()

    small, small_summary = summarize(args.small)
    full, full_summary = summarize(args.full)
    old_full, old_full_summary = summarize(args.old_full)
    report = {
        "small": small_summary,
        "full": full_summary,
        "old_full": old_full_summary,
        "small_vs_new_full": changed_columns(small, full),
        "new_full_vs_old_full": changed_columns(full, old_full),
        "small_zone_mapping": zone_mapping(small),
        "full_zone_mapping": zone_mapping(full),
        "columns_identical_small_full": list(small.columns) == list(full.columns),
        "columns_identical_new_old_full": list(full.columns) == list(old_full.columns),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
