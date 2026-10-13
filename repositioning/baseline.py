from __future__ import annotations

import heapq
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
try:
    from typing import Literal, Tuple
except ImportError:  # Python 3.7 compatibility for the local Anaconda environment
    from typing import Tuple
    from typing_extensions import Literal

import numpy as np
import pandas as pd


EARTH_RADIUS_KM = 6371.0088
NS_PER_MINUTE = 60_000_000_000
NAT_INT = np.iinfo(np.int64).min
PICKUP = 0
DELIVERY = 1
MOVEMENT_NONE = 0
MOVEMENT_SERVICE = 1
MOVEMENT_REPOSITION = 2
Stop = Tuple[int, int]  # (order_index, PICKUP/DELIVERY)


@dataclass(frozen=True)
class SimulationConfig:
    # Data columns
    release_column: str = "order_push_time"
    deadline_column: str = "estimate_arrived_time"
    ready_column: str = "estimate_meal_prepare_time"

    # Assignment / routing rules
    order_priority: Literal["earliest_deadline", "fifo"] = "earliest_deadline"
    max_active_orders: int = 8
    candidate_riders: int = 8
    insertion_position_limit: int = 3
    # Rider shortlist composition. The first component replaces the old
    # "nearest to merchant" rule with the exact minimum distance increase from
    # inserting both the new pickup and delivery into the remaining route.
    route_fit_candidate_riders: int = 4
    lowest_load_candidate_riders: int = 2
    earliest_pickup_candidate_riders: int = 2
    # Route-fit is calculated exactly inside a wider, cheap prefilter. Set this to
    # zero to traverse every eligible rider (accurate but substantially slower).
    route_fit_prefilter_riders: int = 256
    route_fit_prefilter_nearest_riders: int = 128
    route_fit_prefilter_earliest_pickup_riders: int = 96
    route_fit_prefilter_lowest_load_riders: int = 32
    enable_on_time_protection: bool = True
    enable_high_risk_expansion: bool = True
    high_risk_candidate_riders: int = 12
    high_risk_insertion_position_limit: int = 4

    # Selective intra-rider route repair. This revisits an already-built remaining
    # route only when it currently predicts lateness, keeping the normal greedy
    # assignment path fast.
    enable_route_optimization: bool = True
    route_optimization_min_active_orders: int = 3
    route_optimization_max_passes: int = 2
    route_optimization_position_limit: int = 4

    # Weighted system objective:
    # distance_weight * distance_km
    # + unserved_order_penalty * unserved_orders
    # + lateness_minute_weight * total_lateness_minutes
    # + late_order_weight * late_orders
    distance_weight: float = 1.0
    unserved_order_penalty: float = 1_000.0
    lateness_minute_weight: float = 5.0
    late_order_weight: float = 100.0
    enable_active_rejection: bool = True

    # Rider availability assumptions
    # "reconstructed" is the default: a rider is assumed available shortly before
    # their first observed grab, which avoids both extremes of putting everybody
    # online at simulation start and waiting until the exact first observed grab.
    rider_start_mode: Literal["reconstructed", "first_grab", "simulation_start"] = "simulation_start"
    shift_start_buffer_minutes: float = 35.0
    respect_observed_shift_end: bool = False
    fleet_size: int | None = 800
    fleet_selection: Literal["most_active", "random"] = "most_active"
    fleet_random_seed: int = 42

    # Small operational/service-time allowances. These keep the replay from
    # treating assignment, pickup handoff, and customer handoff as instantaneous.
    dispatch_processing_minutes: float = 1.0
    pickup_service_minutes: float = 1.0
    delivery_service_minutes: float = 2.0
    ready_time_buffer_minutes: float = 0.0

    # Coordinates / travel model
    coordinate_scale: float = 1_000_000.0
    longitude_offset: float = 62.0
    distance_metric: Literal["rectilinear", "haversine"] = "rectilinear"
    speed_kmh: float | None = None
    min_travel_minutes: float = 1.0

    # Speed calibration filters
    calibration_min_distance_km: float = 0.05
    calibration_max_distance_km: float = 20.0
    calibration_min_duration_minutes: float = 1.0
    calibration_max_duration_minutes: float = 60.0

    # Periodic repositioning. "none" is the exact no-reposition control.
    # gamma_poisson ports the causal prediction core from the supplied
    # idle-relocation reference while preserving this version's greedy
    # assignment, route-fit shortlist, and routing optimization unchanged.
    reposition_policy: Literal[
        "none", "demand_gap_greedy", "gamma_poisson"
    ] = "none"
    reposition_forecast_mode: Literal[
        "causal_gamma_poisson", "perfect_horizon_benchmark"
    ] = "causal_gamma_poisson"
    reposition_interval_minutes: float = 5.0
    reposition_forecast_history_minutes: float = 30.0
    reposition_forecast_horizon_minutes: float = 15.0
    reposition_warmup_minutes: float = 30.0
    reposition_max_distance_km: float = 2.5
    reposition_max_travel_minutes: float = 6.0
    reposition_max_idle_fraction: float = 0.05
    reposition_min_idle_reserve_per_zone: int = 2
    reposition_cooldown_minutes: float = 15.0
    reposition_include_soon_free_supply: bool = True
    reposition_post_service_enabled: bool = True
    reposition_zone_method: Literal["da_id", "zone_id"] = "zone_id"
    reposition_use_objective_gate: bool = True
    reposition_urgent_deadline_minutes: float = 15.0
    reposition_near_deadline_minutes: float = 30.0
    reposition_urgent_demand_weight: float = 3.0
    reposition_near_demand_weight: float = 2.0
    reposition_soon_free_full_weight_minutes: float = 5.0
    reposition_soon_free_medium_weight_minutes: float = 10.0
    reposition_soon_free_medium_weight: float = 0.6
    reposition_soon_free_far_weight: float = 0.3

    # Causal Gamma-Poisson policy parameters.
    reposition_poisson_history_window_minutes: float = 20.0
    reposition_poisson_prior_exposure_minutes: float = 15.0
    reposition_poisson_zone_share_smoothing: float = 10.0
    reposition_hotspot_history_window_minutes: float = 60.0
    reposition_hotspot_decay_minutes: float = 30.0
    reposition_late_risk_prior_mean: float = 0.05
    reposition_late_risk_prior_strength: float = 20.0
    reposition_minimum_demand_gap_orders: float = 0.5
    reposition_min_distance_km: float = 0.1
    reposition_min_service_time_minutes: float = 1.0
    reposition_travel_time_penalty: float = 0.05
    reposition_min_expected_net_on_time_gain: float = 0.05
    reposition_objective_improvement_margin: float = 10.0


@dataclass
class DataBundle:
    orders: pd.DataFrame
    couriers: pd.DataFrame
    invalid_orders: pd.DataFrame
    speed_kmh: float
    input_rows: int
    historical_on_time_rate: float
    courier_source: str = "derived_from_orders"


@dataclass
class RouteProjection:
    feasible: bool
    route: list[Stop]
    remaining_distance_km: float
    late_count: int
    total_lateness_min: float
    pickup_arrival_ns: dict[int, int]
    pickup_ns: dict[int, int]
    delivery_ns: dict[int, int]
    release_ns: int
    release_lat: float
    release_lng: float


@dataclass
class InsertionChoice:
    courier_index: int
    route: list[Stop]
    score: float
    incremental_distance_km: float
    incremental_lateness_min: float
    incremental_late_orders: int
    projection: RouteProjection
    baseline_projection: RouteProjection


class DenseIndexSet:
    """O(1) add/remove with a contiguous NumPy view."""

    def __init__(self, capacity: int) -> None:
        self._values = np.empty(capacity, dtype=np.int64)
        self._positions = np.full(capacity, -1, dtype=np.int64)
        self.size = 0

    def add(self, value: int) -> None:
        if self._positions[value] >= 0:
            return
        self._values[self.size] = value
        self._positions[value] = self.size
        self.size += 1

    def remove(self, value: int) -> None:
        position = int(self._positions[value])
        if position < 0:
            return
        last_position = self.size - 1
        last_value = int(self._values[last_position])
        self._values[position] = last_value
        self._positions[last_value] = position
        self._positions[value] = -1
        self.size -= 1

    def view(self) -> np.ndarray:
        return self._values[: self.size]


def haversine_rows(
    lat1: np.ndarray,
    lon1: np.ndarray,
    lat2: np.ndarray,
    lon2: np.ndarray,
) -> np.ndarray:
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = phi2 - phi1
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    return EARTH_RADIUS_KM * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(np.maximum(0.0, 1.0 - a)))


def rectilinear_rows(
    lat1: np.ndarray,
    lon1: np.ndarray,
    lat2: np.ndarray,
    lon2: np.ndarray,
) -> np.ndarray:
    """Approximate grid-road distance as north-south km plus east-west km."""
    mean_latitude = np.radians((lat1 + lat2) / 2.0)
    north_south_km = EARTH_RADIUS_KM * np.radians(np.abs(lat2 - lat1))
    east_west_km = EARTH_RADIUS_KM * np.cos(mean_latitude) * np.radians(np.abs(lon2 - lon1))
    return north_south_km + east_west_km


def distance_rows(
    lat1: np.ndarray,
    lon1: np.ndarray,
    lat2: np.ndarray,
    lon2: np.ndarray,
    metric: Literal["rectilinear", "haversine"],
) -> np.ndarray:
    if metric == "rectilinear":
        return rectilinear_rows(lat1, lon1, lat2, lon2)
    return haversine_rows(lat1, lon1, lat2, lon2)


def distance_pair(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    metric: Literal["rectilinear", "haversine"],
) -> float:
    """Fast scalar distance used inside the insertion search."""
    if metric == "rectilinear":
        mean_latitude = math.radians((lat1 + lat2) / 2.0)
        north_south_km = EARTH_RADIUS_KM * math.radians(abs(lat2 - lat1))
        east_west_km = EARTH_RADIUS_KM * math.cos(mean_latitude) * math.radians(abs(lon2 - lon1))
        return north_south_km + east_west_km

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return EARTH_RADIUS_KM * 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def _normalize_coordinate_series(
    values: pd.Series,
    *,
    is_longitude: bool,
    config: SimulationConfig,
) -> pd.Series:
    """Accept both legacy microdegree coordinates and already scaled degrees."""
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric[np.isfinite(numeric)]
    if not finite.empty and float(finite.abs().median()) > 1_000.0:
        numeric = numeric / config.coordinate_scale
    if is_longitude:
        numeric = numeric - config.longitude_offset
    return numeric


def _normalize_coordinates(df: pd.DataFrame, config: SimulationConfig) -> pd.DataFrame:
    result = df.copy()
    for name in ("sender_lng", "recipient_lng", "grab_lng"):
        result[f"_{name}"] = _normalize_coordinate_series(
            result[name], is_longitude=True, config=config
        )
    for name in ("sender_lat", "recipient_lat", "grab_lat"):
        result[f"_{name}"] = _normalize_coordinate_series(
            result[name], is_longitude=False, config=config
        )
    return result


def _calibrate_speed_kmh(df: pd.DataFrame, config: SimulationConfig) -> float:
    distance_km = distance_rows(
        df["_sender_lat"].to_numpy(float),
        df["_sender_lng"].to_numpy(float),
        df["_recipient_lat"].to_numpy(float),
        df["_recipient_lng"].to_numpy(float),
        config.distance_metric,
    )
    duration_minutes = (df["arrive_time"] - df["fetch_time"]).dt.total_seconds().to_numpy() / 60.0
    valid = (
        np.isfinite(distance_km)
        & np.isfinite(duration_minutes)
        & (distance_km >= config.calibration_min_distance_km)
        & (distance_km <= config.calibration_max_distance_km)
        & (duration_minutes >= config.calibration_min_duration_minutes)
        & (duration_minutes <= config.calibration_max_duration_minutes)
    )
    if not valid.any():
        raise ValueError("No valid rows are available for travel-speed calibration.")
    effective_speed = distance_km[valid] / duration_minutes[valid] * 60.0
    return float(np.median(effective_speed))


def _read_independent_orders(path: Path, sheet_name: str | None) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, encoding="utf-8-sig")
    if suffix in {".xlsx", ".xlsm"}:
        return pd.read_excel(path, sheet_name=sheet_name or 0, engine="openpyxl")
    raise ValueError(f"Unsupported order input format: {suffix}. Use CSV or XLSX.")


def _load_with_external_couriers(
    order_path: Path,
    courier_path: Path,
    config: SimulationConfig,
    sheet_name: str | None,
) -> DataBundle:
    """Load demand and supply independently without requiring historical courier IDs."""
    df = _read_independent_orders(order_path, sheet_name)
    df.columns = [str(column).lstrip("\ufeff") for column in df.columns]
    input_rows = len(df)

    core_time_columns = {
        config.release_column,
        config.deadline_column,
        config.ready_column,
    }
    optional_time_columns = {
        "platform_order_time",
        "dispatch_time",
        "grab_time",
        "fetch_time",
        "arrive_time",
    }
    missing_core = sorted(core_time_columns - set(df.columns))
    if "order_id" not in df.columns:
        missing_core.append("order_id")
    if missing_core:
        raise ValueError(f"Independent order input is missing required columns: {missing_core}")

    for column in core_time_columns | (optional_time_columns & set(df.columns)):
        df[column] = pd.to_datetime(df[column], dayfirst=True, errors="coerce", format="mixed")

    coordinate_names = ("sender_lng", "sender_lat", "recipient_lng", "recipient_lat")
    for name in coordinate_names:
        normalized_name = f"{name}_normalized"
        if normalized_name in df.columns:
            df[f"_{name}"] = pd.to_numeric(df[normalized_name], errors="coerce")
        elif name in df.columns:
            df[f"_{name}"] = _normalize_coordinate_series(
                df[name], is_longitude=name.endswith("lng"), config=config
            )
        else:
            raise ValueError(
                f"Independent order input needs either {name!r} or {normalized_name!r}"
            )

    df["_source_row"] = np.arange(len(df), dtype=np.int64)
    required_non_null = [
        "order_id",
        config.release_column,
        config.deadline_column,
        config.ready_column,
        "_sender_lng",
        "_sender_lat",
        "_recipient_lng",
        "_recipient_lat",
    ]
    valid = df[required_non_null].notna().all(axis=1)
    if "platform_order_time" in df.columns:
        valid &= df["platform_order_time"].isna() | df["platform_order_time"].le(df[config.release_column])

    invalid_orders = df.loc[~valid].copy()
    invalid_orders["invalid_reason"] = "missing required order field or invalid release chronology"
    clean = df.loc[valid].sort_values([config.release_column, "order_id"], kind="stable")

    duplicate_mask = clean.duplicated("order_id", keep="first")
    if duplicate_mask.any():
        duplicates = clean.loc[duplicate_mask].copy()
        duplicates["invalid_reason"] = "duplicate order_id"
        invalid_orders = pd.concat([invalid_orders, duplicates], ignore_index=True)
        clean = clean.loc[~duplicate_mask]

    clean = clean.reset_index(drop=True)
    if clean.empty:
        raise ValueError("No valid orders remain after independent order cleaning.")

    if config.speed_kmh is not None:
        speed_kmh = float(config.speed_kmh)
    elif {"fetch_time", "arrive_time"}.issubset(clean.columns):
        speed_kmh = _calibrate_speed_kmh(clean, config)
    else:
        raise ValueError("Speed calibration requires fetch_time and arrive_time.")
    if not np.isfinite(speed_kmh) or speed_kmh <= 0:
        raise ValueError("speed_kmh must be a positive finite number.")

    courier_path = courier_path.resolve()
    courier_df = pd.read_csv(courier_path, encoding="utf-8-sig")
    courier_df.columns = [str(column).lstrip("\ufeff") for column in courier_df.columns]
    required_courier_columns = {"courier_id", "start_lng", "start_lat"}
    missing_courier_columns = sorted(required_courier_columns - set(courier_df.columns))
    if missing_courier_columns:
        raise ValueError(f"Courier input is missing required columns: {missing_courier_columns}")
    if courier_df["courier_id"].duplicated().any():
        raise ValueError("Courier input contains duplicate courier_id values.")

    couriers = courier_df.copy()
    couriers["start_lng"] = pd.to_numeric(couriers["start_lng"], errors="coerce")
    couriers["start_lat"] = pd.to_numeric(couriers["start_lat"], errors="coerce")
    if couriers[["courier_id", "start_lng", "start_lat"]].isna().any(axis=1).any():
        raise ValueError("Courier input contains missing courier IDs or start coordinates.")

    simulation_start = clean[config.release_column].min()
    simulation_end = clean[config.deadline_column].max()
    if "start_time" in couriers.columns:
        couriers["start_time"] = pd.to_datetime(couriers["start_time"], errors="coerce", format="mixed")
    else:
        couriers["start_time"] = simulation_start
    if "shift_end" in couriers.columns:
        couriers["shift_end"] = pd.to_datetime(couriers["shift_end"], errors="coerce", format="mixed")
    else:
        couriers["shift_end"] = simulation_end + pd.Timedelta(days=1)
    couriers["start_time"] = couriers["start_time"].fillna(simulation_start)
    couriers["shift_end"] = couriers["shift_end"].fillna(simulation_end + pd.Timedelta(days=1))
    if "historical_orders" not in couriers.columns:
        couriers["historical_orders"] = 0

    if config.fleet_size is not None:
        if config.fleet_size < 1:
            raise ValueError("fleet_size must be >= 1 or None")
        if config.fleet_size > len(couriers):
            raise ValueError(
                f"Requested fleet_size={config.fleet_size}, but courier input contains only {len(couriers)} riders."
            )
        if len(couriers) > config.fleet_size:
            if config.fleet_selection == "most_active":
                couriers = couriers.sort_values(
                    ["historical_orders", "courier_id"],
                    ascending=[False, True],
                    kind="stable",
                ).head(config.fleet_size)
            else:
                couriers = couriers.sample(n=config.fleet_size, random_state=config.fleet_random_seed)

    if config.rider_start_mode == "simulation_start":
        couriers["start_time"] = simulation_start
    elif config.rider_start_mode == "reconstructed":
        buffer = pd.to_timedelta(config.shift_start_buffer_minutes, unit="m")
        couriers["start_time"] = (couriers["start_time"] - buffer).clip(lower=simulation_start)
    couriers = couriers.sort_values(["start_time", "courier_id"], kind="stable").reset_index(drop=True)

    if "arrive_time" in clean.columns and clean["arrive_time"].notna().any():
        historical_on_time_rate = float(
            clean.loc[clean["arrive_time"].notna(), "arrive_time"]
            .le(clean.loc[clean["arrive_time"].notna(), config.deadline_column])
            .mean()
        )
    else:
        historical_on_time_rate = 0.0

    return DataBundle(
        orders=clean,
        couriers=couriers,
        invalid_orders=invalid_orders,
        speed_kmh=speed_kmh,
        input_rows=input_rows,
        historical_on_time_rate=historical_on_time_rate,
        courier_source="external_file",
    )


def load_and_prepare(
    csv_path: str | Path,
    config: SimulationConfig,
    courier_path: str | Path | None = None,
    sheet_name: str | None = None,
) -> DataBundle:
    path = Path(csv_path)
    if courier_path is not None:
        return _load_with_external_couriers(
            order_path=path.resolve(),
            courier_path=Path(courier_path),
            config=config,
            sheet_name=sheet_name,
        )

    # Backward-compatible legacy path. Keeping this branch unchanged preserves the
    # existing 22,408-order / 1,300-rider baseline exactly.
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [str(column).lstrip("\ufeff") for column in df.columns]
    input_rows = len(df)

    time_columns = {
        config.release_column,
        config.deadline_column,
        config.ready_column,
        "platform_order_time",
        "order_push_time",
        "grab_time",
        "fetch_time",
        "arrive_time",
    }
    coordinate_columns = {
        "sender_lng",
        "sender_lat",
        "recipient_lng",
        "recipient_lat",
        "grab_lng",
        "grab_lat",
    }
    required_columns = {
        "order_id",
        "waybill_id",
        "courier_id",
        "is_courier_grabbed",
        *time_columns,
        *coordinate_columns,
    }
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    for column in time_columns:
        df[column] = pd.to_datetime(df[column], dayfirst=True, errors="coerce", format="mixed")
    df = _normalize_coordinates(df, config)
    df["_source_row"] = np.arange(len(df), dtype=np.int64)

    required_non_null = [
        "order_id",
        "waybill_id",
        "courier_id",
        config.release_column,
        config.deadline_column,
        config.ready_column,
        "grab_time",
        "fetch_time",
        "arrive_time",
        "_sender_lng",
        "_sender_lat",
        "_recipient_lng",
        "_recipient_lat",
        "_grab_lng",
        "_grab_lat",
    ]
    valid = df["is_courier_grabbed"].eq(1) & df[required_non_null].notna().all(axis=1)
    valid &= df["platform_order_time"].le(df["order_push_time"])
    valid &= df["order_push_time"].le(df["grab_time"])
    valid &= df["grab_time"].le(df["fetch_time"])
    valid &= df["fetch_time"].le(df["arrive_time"])

    invalid_orders = df.loc[~valid].copy()
    invalid_orders["invalid_reason"] = "missing field, not grabbed, or invalid operational chronology"
    clean = df.loc[valid].sort_values([config.release_column, "order_id"], kind="stable")

    duplicate_mask = clean.duplicated("order_id", keep="first")
    if duplicate_mask.any():
        duplicates = clean.loc[duplicate_mask].copy()
        duplicates["invalid_reason"] = "duplicate order_id"
        invalid_orders = pd.concat([invalid_orders, duplicates], ignore_index=True)
        clean = clean.loc[~duplicate_mask]

    clean = clean.reset_index(drop=True)
    if clean.empty:
        raise ValueError("No valid orders remain after cleaning.")

    speed_kmh = float(config.speed_kmh) if config.speed_kmh is not None else _calibrate_speed_kmh(clean, config)
    if not np.isfinite(speed_kmh) or speed_kmh <= 0:
        raise ValueError("speed_kmh must be a positive finite number.")

    first_rows = clean.sort_values(["grab_time", "order_id"], kind="stable").groupby("courier_id", sort=False).first()
    shift_ends = clean.groupby("courier_id", sort=False)["arrive_time"].max()
    historical_orders = clean.groupby("courier_id", sort=False).size()
    simulation_start = clean[config.release_column].min()
    couriers = pd.DataFrame(
        {
            "courier_id": first_rows.index,
            "start_time": first_rows["grab_time"].to_numpy(),
            "shift_end": shift_ends.reindex(first_rows.index).to_numpy(),
            "start_lng": first_rows["_grab_lng"].to_numpy(float),
            "start_lat": first_rows["_grab_lat"].to_numpy(float),
            "historical_orders": historical_orders.reindex(first_rows.index).to_numpy(int),
        }
    )

    if config.fleet_size is not None:
        if config.fleet_size < 1:
            raise ValueError("fleet_size must be >= 1 or None")
        if config.fleet_size > len(couriers):
            raise ValueError(
                f"Requested fleet_size={config.fleet_size}, but only {len(couriers)} couriers are available."
            )
        if config.fleet_selection == "most_active":
            couriers = couriers.sort_values(
                ["historical_orders", "start_time", "courier_id"],
                ascending=[False, True, True],
                kind="stable",
            ).head(config.fleet_size)
        else:
            couriers = couriers.sample(n=config.fleet_size, random_state=config.fleet_random_seed)

    if config.rider_start_mode == "simulation_start":
        couriers["start_time"] = simulation_start
    elif config.rider_start_mode == "reconstructed":
        buffer = pd.to_timedelta(config.shift_start_buffer_minutes, unit="m")
        couriers["start_time"] = (couriers["start_time"] - buffer).clip(lower=simulation_start)
    couriers = couriers.sort_values(["start_time", "courier_id"], kind="stable").reset_index(drop=True)

    historical_on_time_rate = float(clean["arrive_time"].le(clean[config.deadline_column]).mean())
    return DataBundle(
        orders=clean,
        couriers=couriers,
        invalid_orders=invalid_orders,
        speed_kmh=speed_kmh,
        input_rows=input_rows,
        historical_on_time_rate=historical_on_time_rate,
    )


class GreedyAssignmentRoutingSimulator:
    """
    Event-driven Assignment + Routing simulator.

    Key rule in this version:
    - A courier may hold up to `max_active_orders` unfinished orders.
    - A new order is inserted into the courier's remaining route.
    - If the courier is already travelling to the next stop, that next stop is frozen;
      insertion is allowed only after it.
    - Existing stop order is preserved; only the new pickup and delivery are inserted.
    - Candidate choices minimize the weighted system-objective increment:
        distance_weight * incremental distance
        + lateness_minute_weight * incremental lateness minutes
        + late_order_weight * incremental late orders.
    - If the best feasible insertion costs more than unserved_order_penalty, the order
      is actively rejected. Physical feasibility constraints remain hard constraints.
    """

    def __init__(self, config: SimulationConfig, speed_kmh: float) -> None:
        if config.max_active_orders < 1:
            raise ValueError("max_active_orders must be >= 1")
        if config.candidate_riders < 1:
            raise ValueError("candidate_riders must be >= 1")
        if config.insertion_position_limit < 2:
            raise ValueError("insertion_position_limit must be >= 2")
        if min(
            config.route_fit_candidate_riders,
            config.lowest_load_candidate_riders,
            config.earliest_pickup_candidate_riders,
        ) < 0:
            raise ValueError("hybrid candidate component counts must be >= 0")
        if config.route_fit_prefilter_riders < 0:
            raise ValueError("route_fit_prefilter_riders must be >= 0")
        if min(
            config.route_fit_prefilter_nearest_riders,
            config.route_fit_prefilter_earliest_pickup_riders,
            config.route_fit_prefilter_lowest_load_riders,
        ) < 0:
            raise ValueError("route-fit prefilter component counts must be >= 0")
        if (
            0 < config.route_fit_prefilter_riders
            < config.route_fit_candidate_riders
        ):
            raise ValueError(
                "route_fit_prefilter_riders must be zero or >= route_fit_candidate_riders"
            )
        if config.high_risk_candidate_riders < config.candidate_riders:
            raise ValueError("high_risk_candidate_riders must be >= candidate_riders")
        if config.high_risk_insertion_position_limit < config.insertion_position_limit:
            raise ValueError(
                "high_risk_insertion_position_limit must be >= insertion_position_limit"
            )
        if config.route_optimization_min_active_orders < 2:
            raise ValueError("route_optimization_min_active_orders must be >= 2")
        if config.route_optimization_max_passes < 1:
            raise ValueError("route_optimization_max_passes must be >= 1")
        if config.route_optimization_position_limit < 2:
            raise ValueError("route_optimization_position_limit must be >= 2")
        if config.distance_weight < 0:
            raise ValueError("distance_weight must be >= 0")
        if config.unserved_order_penalty < 0:
            raise ValueError("unserved_order_penalty must be >= 0")
        if config.lateness_minute_weight < 0:
            raise ValueError("lateness_minute_weight must be >= 0")
        if config.late_order_weight < 0:
            raise ValueError("late_order_weight must be >= 0")
        if config.reposition_interval_minutes <= 0:
            raise ValueError("reposition_interval_minutes must be > 0")
        if config.reposition_forecast_history_minutes <= 0:
            raise ValueError("reposition_forecast_history_minutes must be > 0")
        if config.reposition_forecast_horizon_minutes <= 0:
            raise ValueError("reposition_forecast_horizon_minutes must be > 0")
        if config.reposition_max_distance_km < 0:
            raise ValueError("reposition_max_distance_km must be >= 0")
        if not 0 <= config.reposition_max_idle_fraction <= 1:
            raise ValueError("reposition_max_idle_fraction must be between 0 and 1")
        if config.reposition_min_idle_reserve_per_zone < 0:
            raise ValueError("reposition_min_idle_reserve_per_zone must be >= 0")
        if config.reposition_urgent_deadline_minutes <= 0:
            raise ValueError("reposition_urgent_deadline_minutes must be > 0")
        if config.reposition_near_deadline_minutes < config.reposition_urgent_deadline_minutes:
            raise ValueError("reposition_near_deadline_minutes must be >= urgent deadline")
        if config.reposition_urgent_demand_weight < config.reposition_near_demand_weight:
            raise ValueError("urgent demand weight must be >= near-deadline demand weight")
        if config.reposition_near_demand_weight < 1:
            raise ValueError("reposition demand weights must be >= 1")
        if not (
            0 < config.reposition_soon_free_full_weight_minutes
            <= config.reposition_soon_free_medium_weight_minutes
        ):
            raise ValueError("soon-free time thresholds must be positive and ordered")
        if not 0 <= config.reposition_soon_free_far_weight <= 1:
            raise ValueError("reposition_soon_free_far_weight must be between 0 and 1")
        if not 0 <= config.reposition_soon_free_medium_weight <= 1:
            raise ValueError("reposition_soon_free_medium_weight must be between 0 and 1")
        poisson_positive = {
            "reposition_poisson_history_window_minutes": (
                config.reposition_poisson_history_window_minutes
            ),
            "reposition_poisson_prior_exposure_minutes": (
                config.reposition_poisson_prior_exposure_minutes
            ),
            "reposition_poisson_zone_share_smoothing": (
                config.reposition_poisson_zone_share_smoothing
            ),
            "reposition_hotspot_history_window_minutes": (
                config.reposition_hotspot_history_window_minutes
            ),
            "reposition_hotspot_decay_minutes": (
                config.reposition_hotspot_decay_minutes
            ),
            "reposition_late_risk_prior_strength": (
                config.reposition_late_risk_prior_strength
            ),
            "reposition_min_service_time_minutes": (
                config.reposition_min_service_time_minutes
            ),
            "reposition_max_travel_minutes": config.reposition_max_travel_minutes,
        }
        if any(value <= 0 for value in poisson_positive.values()):
            raise ValueError(
                "Gamma-Poisson history, prior, smoothing, decay, risk strength, "
                "and service-time parameters must be > 0"
            )
        if not 0 <= config.reposition_late_risk_prior_mean <= 1:
            raise ValueError("reposition_late_risk_prior_mean must be between 0 and 1")
        if config.reposition_minimum_demand_gap_orders < 0:
            raise ValueError("reposition_minimum_demand_gap_orders must be >= 0")
        if not 0 <= config.reposition_min_distance_km <= config.reposition_max_distance_km:
            raise ValueError("reposition minimum distance must be between 0 and maximum")
        if config.reposition_travel_time_penalty < 0:
            raise ValueError("reposition_travel_time_penalty must be >= 0")
        if config.reposition_min_expected_net_on_time_gain < 0:
            raise ValueError("reposition_min_expected_net_on_time_gain must be >= 0")
        if config.reposition_objective_improvement_margin < 0:
            raise ValueError("reposition_objective_improvement_margin must be >= 0")
        self.config = config
        self.speed_kmh = speed_kmh
        self.reposition_events = pd.DataFrame()

    def _travel_minutes(self, distance_km: float | np.ndarray) -> float | np.ndarray:
        return np.maximum(self.config.min_travel_minutes, np.asarray(distance_km) / self.speed_kmh * 60.0)

    def run(self, bundle: DataBundle) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float | int | str | bool]]:
        started_at = time.perf_counter()
        orders = bundle.orders.reset_index(drop=True)
        couriers = bundle.couriers.reset_index(drop=True)
        order_count = len(orders)
        courier_count = len(couriers)

        release_ns = orders[self.config.release_column].to_numpy(dtype="datetime64[ns]").astype(np.int64)
        deadline_ns = orders[self.config.deadline_column].to_numpy(dtype="datetime64[ns]").astype(np.int64)
        ready_ns = orders[self.config.ready_column].to_numpy(dtype="datetime64[ns]").astype(np.int64)
        sender_lat = orders["_sender_lat"].to_numpy(float)
        sender_lng = orders["_sender_lng"].to_numpy(float)
        recipient_lat = orders["_recipient_lat"].to_numpy(float)
        recipient_lng = orders["_recipient_lng"].to_numpy(float)
        reposition_noise_orders_reassigned = 0
        reposition_demand_valid_mask = np.zeros(order_count, dtype=bool)
        if self.config.reposition_policy != "none":
            zone_column = self.config.reposition_zone_method
            if zone_column not in orders.columns:
                raise ValueError(
                    "demand_gap_greedy repositioning with "
                    f"zone_method={zone_column!r} requires column {zone_column!r}"
                )
            zone_series = orders[zone_column]
            if zone_series.isna().any():
                raise ValueError(
                    f"Repositioning requires non-missing {zone_column} for every valid order"
                )
            if zone_column == "zone_id":
                numeric_zone = pd.to_numeric(zone_series, errors="coerce")
                if numeric_zone.isna().any():
                    raise ValueError("zone_id must be numeric when used for repositioning")
                noise_mask = numeric_zone.eq(-1).to_numpy()
            else:
                noise_mask = np.zeros(order_count, dtype=bool)

            valid_zone_codes, zone_values = pd.factorize(
                zone_series.loc[~noise_mask], sort=True
            )
            if len(zone_values) == 0:
                raise ValueError("Repositioning needs at least one non-noise zone")
            order_zone = np.full(order_count, -1, dtype=np.int64)
            order_zone[~noise_mask] = valid_zone_codes.astype(np.int64)
            zone_labels = [str(value) for value in zone_values.tolist()]
            zone_count = len(zone_labels)
            zone_lat = np.array(
                [float(np.median(sender_lat[order_zone == zone])) for zone in range(zone_count)]
            )
            zone_lng = np.array(
                [float(np.median(sender_lng[order_zone == zone])) for zone in range(zone_count)]
            )
            # DBSCAN label -1 is noise, not a relocation destination. Associate
            # each noise order with its nearest valid merchant-zone centroid so
            # its demand is retained without creating a fake target zone.
            noise_indices = np.flatnonzero(noise_mask)
            for order_index in noise_indices:
                distances_to_zones = distance_rows(
                    np.full(zone_count, sender_lat[order_index], dtype=float),
                    np.full(zone_count, sender_lng[order_index], dtype=float),
                    zone_lat,
                    zone_lng,
                    self.config.distance_metric,
                )
                order_zone[order_index] = int(np.argmin(distances_to_zones))
            reposition_noise_orders_reassigned = int(len(noise_indices))
            reposition_demand_valid_mask = ~noise_mask
        else:
            order_zone = np.zeros(order_count, dtype=np.int64)
            zone_labels = []
            zone_count = 0
            zone_lat = np.empty(0, dtype=float)
            zone_lng = np.empty(0, dtype=float)

        direct_service_distance_km = distance_rows(
            sender_lat,
            sender_lng,
            recipient_lat,
            recipient_lng,
            self.config.distance_metric,
        )
        direct_service_minutes = (
            np.asarray(self._travel_minutes(direct_service_distance_km), dtype=float)
            + self.config.pickup_service_minutes
            + self.config.delivery_service_minutes
        )

        courier_ids = couriers["courier_id"].to_numpy()
        courier_lat = couriers["start_lat"].to_numpy(float).copy()
        courier_lng = couriers["start_lng"].to_numpy(float).copy()
        courier_start_ns = pd.to_datetime(couriers["start_time"]).to_numpy(dtype="datetime64[ns]").astype(np.int64)
        courier_end_ns = pd.to_datetime(couriers["shift_end"]).to_numpy(dtype="datetime64[ns]").astype(np.int64)

        # Per-order realised simulation outputs.
        assigned = np.zeros(order_count, dtype=bool)
        rejected = np.zeros(order_count, dtype=bool)
        delivered = np.zeros(order_count, dtype=bool)
        picked = np.zeros(order_count, dtype=bool)
        simulated_courier = np.full(order_count, None, dtype=object)
        assignment_ns = np.full(order_count, NAT_INT, dtype=np.int64)
        restaurant_arrival_ns = np.full(order_count, NAT_INT, dtype=np.int64)
        pickup_ns = np.full(order_count, NAT_INT, dtype=np.int64)
        delivery_ns = np.full(order_count, NAT_INT, dtype=np.int64)
        pickup_leg_km = np.full(order_count, np.nan)
        delivery_leg_km = np.full(order_count, np.nan)
        pickup_leg_min = np.full(order_count, np.nan)
        delivery_leg_min = np.full(order_count, np.nan)
        restaurant_wait_min = np.full(order_count, np.nan)
        on_time = np.zeros(order_count, dtype=bool)
        rejection_ns = np.full(order_count, NAT_INT, dtype=np.int64)
        decision_weighted_score = np.full(order_count, np.nan)
        best_assignment_score_at_decision = np.full(order_count, np.nan)
        decision_incremental_distance_km = np.full(order_count, np.nan)
        decision_incremental_lateness_min = np.full(order_count, np.nan)
        decision_incremental_late_orders = np.full(order_count, np.nan)

        # Release forecast captured at the moment each order is assigned.
        rider_release_at_assignment_ns = np.full(order_count, NAT_INT, dtype=np.int64)
        rider_release_at_assignment_lat = np.full(order_count, np.nan)
        rider_release_at_assignment_lng = np.full(order_count, np.nan)
        active_orders_at_assignment = np.zeros(order_count, dtype=np.int64)

        # Courier dynamic state.
        started = np.zeros(courier_count, dtype=bool)
        routes: list[list[Stop]] = [[] for _ in range(courier_count)]
        active_orders: list[set[int]] = [set() for _ in range(courier_count)]
        active_count = np.zeros(courier_count, dtype=np.int64)
        carried_count = np.zeros(courier_count, dtype=np.int64)
        max_active_observed = np.zeros(courier_count, dtype=np.int64)
        moving = np.zeros(courier_count, dtype=bool)
        movement_mode = np.full(courier_count, MOVEMENT_NONE, dtype=np.int8)
        next_event_ns = np.full(courier_count, NAT_INT, dtype=np.int64)
        next_arrival_ns = np.full(courier_count, NAT_INT, dtype=np.int64)
        next_service_start_ns = np.full(courier_count, NAT_INT, dtype=np.int64)
        needs_dispatch_delay = np.zeros(courier_count, dtype=bool)
        current_leg_distance_km = np.zeros(courier_count, dtype=float)
        current_leg_minutes = np.zeros(courier_count, dtype=float)
        route_version = np.zeros(courier_count, dtype=np.int64)
        # Position used for the geographic shortlist: current position if stationary,
        # committed next stop if currently travelling.
        shortlist_lat = courier_lat.copy()
        shortlist_lng = courier_lng.copy()
        # Cached end-of-route state used by the fast candidate pre-score. It is updated
        # only when a route changes, avoiding a full projection of all riders per order.
        route_release_ns = courier_start_ns.copy()
        route_release_lat = courier_lat.copy()
        route_release_lng = courier_lng.copy()
        courier_order_count = np.zeros(courier_count, dtype=np.int64)
        courier_service_distance_km = np.zeros(courier_count, dtype=float)
        courier_reposition_distance_km = np.zeros(courier_count, dtype=float)
        courier_reposition_minutes = np.zeros(courier_count, dtype=float)
        courier_reposition_count = np.zeros(courier_count, dtype=np.int64)
        courier_orders_assigned_during_reposition = np.zeros(courier_count, dtype=np.int64)
        last_reposition_end_ns = np.full(courier_count, NAT_INT, dtype=np.int64)
        active_reposition_event_index = np.full(courier_count, -1, dtype=np.int64)
        courier_busy_minutes = np.zeros(courier_count, dtype=float)
        courier_busy_start_ns = np.full(courier_count, NAT_INT, dtype=np.int64)

        pending: list[tuple[int, int, int]] = []
        route_events: list[tuple[int, int, int]] = []  # (completion_time, version, courier_index)
        reposition_event_rows: list[dict[str, object]] = []
        reposition_tick_count = 0
        reposition_candidate_count = 0
        reposition_objective_gate_rejection_count = 0
        reposition_on_time_gate_rejection_count = 0
        post_service_plan_count = 0
        post_service_activated_count = 0
        post_service_cancelled_count = 0
        pending_post_service: list[dict[str, object] | None] = [
            None for _ in range(courier_count)
        ]
        high_risk_expansion_count = 0
        route_optimization_attempt_count = 0
        route_optimization_improved_route_count = 0
        route_optimization_accepted_move_count = 0
        route_optimization_candidate_count = 0
        route_fit_rider_evaluation_count = 0
        route_optimization_distance_reduction_km = 0.0
        route_optimization_lateness_reduction_min = 0.0
        route_optimization_late_orders_reduced = 0
        route_optimization_objective_reduction = 0.0
        route_optimization_runtime_seconds = 0.0
        order_ptr = 0
        courier_ptr = 0
        current_time = int(release_ns[0] if courier_count == 0 else min(release_ns[0], courier_start_ns[0]))
        reposition_interval_ns = int(round(self.config.reposition_interval_minutes * NS_PER_MINUTE))
        next_reposition_ns = int(
            release_ns[0] + round(self.config.reposition_warmup_minutes * NS_PER_MINUTE)
        )

        def stop_location(stop: Stop) -> tuple[float, float]:
            order_index, kind = stop
            if kind == PICKUP:
                return float(sender_lat[order_index]), float(sender_lng[order_index])
            return float(recipient_lat[order_index]), float(recipient_lng[order_index])

        def nearest_zone(lat: float, lng: float) -> int:
            distances = distance_rows(
                np.full(zone_count, lat, dtype=float),
                np.full(zone_count, lng, dtype=float),
                zone_lat,
                zone_lng,
                self.config.distance_metric,
            )
            return int(np.argmin(distances))

        def project_route(courier_index: int, route: list[Stop], at_time: int) -> RouteProjection:
            """Project the remaining route from the courier's current committed state."""
            pickup_arrivals: dict[int, int] = {}
            pickup_times: dict[int, int] = {}
            delivery_times: dict[int, int] = {}
            total_distance = 0.0

            temp_carried = int(carried_count[courier_index])
            temp_picked = {o for o in active_orders[courier_index] if picked[o] and not delivered[o]}

            if moving[courier_index]:
                if movement_mode[courier_index] == MOVEMENT_REPOSITION:
                    # A reposition leg is committed, but no service stop has started. Any
                    # assigned route begins from the reposition target after arrival.
                    temp_time = int(next_event_ns[courier_index])
                    temp_lat = float(shortlist_lat[courier_index])
                    temp_lng = float(shortlist_lng[courier_index])
                    total_distance += float(current_leg_distance_km[courier_index])
                    remaining = route
                else:
                    if not route:
                        return RouteProjection(False, route, 0.0, 0, 0.0, {}, {}, {}, at_time, courier_lat[courier_index], courier_lng[courier_index])

                    # The current service leg and first stop are committed and cannot change.
                    first = route[0]
                    first_order, first_kind = first
                    temp_time = int(next_event_ns[courier_index])
                    temp_lat, temp_lng = stop_location(first)
                    total_distance += float(current_leg_distance_km[courier_index])

                    if first_kind == PICKUP:
                        pickup_arrivals[first_order] = int(next_arrival_ns[courier_index])
                        pickup_times[first_order] = temp_time
                        temp_picked.add(first_order)
                        temp_carried += 1
                        if temp_carried > self.config.max_active_orders:
                            return RouteProjection(False, route, total_distance, 0, 0.0, {}, {}, {}, temp_time, temp_lat, temp_lng)
                    else:
                        if first_order not in temp_picked:
                            return RouteProjection(False, route, total_distance, 0, 0.0, {}, {}, {}, temp_time, temp_lat, temp_lng)
                        delivery_times[first_order] = temp_time
                        temp_picked.remove(first_order)
                        temp_carried -= 1
                        if temp_carried < 0:
                            return RouteProjection(False, route, total_distance, 0, 0.0, {}, {}, {}, temp_time, temp_lat, temp_lng)

                    remaining = route[1:]
            else:
                temp_time = int(at_time)
                # An idle rider needs a small processing / response allowance before
                # beginning the first leg of a newly assigned route.
                if active_count[courier_index] == 0 and route:
                    temp_time += int(round(self.config.dispatch_processing_minutes * NS_PER_MINUTE))
                temp_lat = float(courier_lat[courier_index])
                temp_lng = float(courier_lng[courier_index])
                remaining = route

            ready_buffer_ns = int(round(self.config.ready_time_buffer_minutes * NS_PER_MINUTE))
            pickup_service_ns = int(round(self.config.pickup_service_minutes * NS_PER_MINUTE))
            delivery_service_ns = int(round(self.config.delivery_service_minutes * NS_PER_MINUTE))

            for stop in remaining:
                order_index, kind = stop
                target_lat, target_lng = stop_location(stop)
                leg_km = distance_pair(temp_lat, temp_lng, target_lat, target_lng, self.config.distance_metric)
                leg_min = float(self._travel_minutes(leg_km))
                arrival = temp_time + int(round(leg_min * NS_PER_MINUTE))
                total_distance += leg_km

                if kind == PICKUP:
                    service_start = max(arrival, int(ready_ns[order_index]) + ready_buffer_ns)
                    completion = service_start + pickup_service_ns
                    pickup_arrivals[order_index] = arrival
                    pickup_times[order_index] = completion
                    temp_picked.add(order_index)
                    temp_carried += 1
                    if temp_carried > self.config.max_active_orders:
                        return RouteProjection(False, route, total_distance, 0, 0.0, {}, {}, {}, completion, target_lat, target_lng)
                else:
                    if order_index not in temp_picked:
                        return RouteProjection(False, route, total_distance, 0, 0.0, {}, {}, {}, arrival, target_lat, target_lng)
                    completion = arrival + delivery_service_ns
                    delivery_times[order_index] = completion
                    temp_picked.remove(order_index)
                    temp_carried -= 1
                    if temp_carried < 0:
                        return RouteProjection(False, route, total_distance, 0, 0.0, {}, {}, {}, completion, target_lat, target_lng)

                temp_time = completion
                temp_lat, temp_lng = target_lat, target_lng

            # All active orders must still have a delivery either already completed in the
            # committed first stop or somewhere in the projected suffix.
            relevant_orders = set(active_orders[courier_index])
            for stop in route:
                relevant_orders.add(stop[0])

            late_count = 0
            total_lateness = 0.0
            for order_index in relevant_orders:
                if delivered[order_index]:
                    continue
                dtime = delivery_times.get(order_index)
                if dtime is None:
                    # It is possible that the first committed stop is a pickup; delivery must
                    # still be present in the suffix. Missing delivery means an invalid route.
                    return RouteProjection(False, route, total_distance, 0, 0.0, {}, {}, {}, temp_time, temp_lat, temp_lng)
                lateness = max(0.0, (dtime - int(deadline_ns[order_index])) / NS_PER_MINUTE)
                if lateness > 0:
                    late_count += 1
                    total_lateness += lateness

            return RouteProjection(
                True,
                route,
                total_distance,
                late_count,
                total_lateness,
                pickup_arrivals,
                pickup_times,
                delivery_times,
                int(temp_time),
                float(temp_lat),
                float(temp_lng),
            )

        def route_projection_objective(projection: RouteProjection) -> float:
            return float(
                self.config.distance_weight * projection.remaining_distance_km
                + self.config.lateness_minute_weight * projection.total_lateness_min
                + self.config.late_order_weight * projection.late_count
            )

        def optimize_courier_route(courier_index: int, at_time: int) -> bool:
            """Repair one late remaining route with precedence-safe relocate moves."""
            nonlocal route_optimization_attempt_count
            nonlocal route_optimization_improved_route_count
            nonlocal route_optimization_accepted_move_count
            nonlocal route_optimization_candidate_count
            nonlocal route_optimization_distance_reduction_km
            nonlocal route_optimization_lateness_reduction_min
            nonlocal route_optimization_late_orders_reduced
            nonlocal route_optimization_objective_reduction
            nonlocal route_optimization_runtime_seconds

            if (
                not self.config.enable_route_optimization
                or active_count[courier_index]
                < self.config.route_optimization_min_active_orders
                or not routes[courier_index]
            ):
                return False

            initial_projection = project_route(
                courier_index, routes[courier_index], at_time
            )
            if not initial_projection.feasible or initial_projection.late_count == 0:
                return False

            optimization_started_at = time.perf_counter()
            route_optimization_attempt_count += 1
            current_projection = initial_projection
            current_objective = route_projection_objective(current_projection)
            improved = False

            # A service stop already being travelled to is immutable. Reposition travel
            # commits only the origin of the service route, not its first service stop.
            fixed_prefix = (
                1
                if moving[courier_index]
                and movement_mode[courier_index] == MOVEMENT_SERVICE
                else 0
            )

            def local_added_distance(
                route: list[Stop], position: int, target: Stop
            ) -> float:
                target_lat, target_lng = stop_location(target)
                if position == 0:
                    if (
                        moving[courier_index]
                        and movement_mode[courier_index] == MOVEMENT_REPOSITION
                    ):
                        previous_lat = float(shortlist_lat[courier_index])
                        previous_lng = float(shortlist_lng[courier_index])
                    else:
                        previous_lat = float(courier_lat[courier_index])
                        previous_lng = float(courier_lng[courier_index])
                else:
                    previous_lat, previous_lng = stop_location(route[position - 1])

                added = distance_pair(
                    previous_lat,
                    previous_lng,
                    target_lat,
                    target_lng,
                    self.config.distance_metric,
                )
                if position < len(route):
                    next_lat, next_lng = stop_location(route[position])
                    added += distance_pair(
                        target_lat,
                        target_lng,
                        next_lat,
                        next_lng,
                        self.config.distance_metric,
                    )
                    added -= distance_pair(
                        previous_lat,
                        previous_lng,
                        next_lat,
                        next_lng,
                        self.config.distance_metric,
                    )
                return float(added)

            def promising_positions(
                route: list[Stop], start: int, target: Stop
            ) -> list[int]:
                positions = list(range(start, len(route) + 1))
                limit = self.config.route_optimization_position_limit
                if len(positions) <= limit:
                    return positions

                distance_order = sorted(
                    positions,
                    key=lambda position: local_added_distance(route, position, target),
                )
                target_deadline = int(deadline_ns[target[0]])
                deadline_position = positions[-1]
                for position in positions:
                    if position >= len(route):
                        break
                    if int(deadline_ns[route[position][0]]) >= target_deadline:
                        deadline_position = position
                        break

                chosen = [distance_order[0], positions[0], deadline_position]
                if limit >= 4:
                    chosen.append(positions[-1])
                for position in distance_order:
                    chosen.append(position)
                    if len(dict.fromkeys(chosen)) >= limit:
                        break
                return sorted(list(dict.fromkeys(chosen))[:limit])

            def relocation_candidates(route: list[Stop], order_index: int):
                indexed_stops = [
                    (position, stop)
                    for position, stop in enumerate(route)
                    if stop[0] == order_index
                ]
                delivery_positions = [
                    position
                    for position, stop in indexed_stops
                    if stop[1] == DELIVERY
                ]
                if not delivery_positions or delivery_positions[0] < fixed_prefix:
                    return

                pickup_positions = [
                    position
                    for position, stop in indexed_stops
                    if stop[1] == PICKUP
                ]
                pickup_is_movable = bool(
                    pickup_positions and pickup_positions[0] >= fixed_prefix
                )

                if pickup_is_movable:
                    reduced = [stop for stop in route if stop[0] != order_index]
                    pickup_stop = (order_index, PICKUP)
                    delivery_stop = (order_index, DELIVERY)
                    for pickup_position in promising_positions(
                        reduced, fixed_prefix, pickup_stop
                    ):
                        with_pickup = list(reduced)
                        with_pickup.insert(pickup_position, pickup_stop)
                        for delivery_position in promising_positions(
                            with_pickup, pickup_position + 1, delivery_stop
                        ):
                            candidate = list(with_pickup)
                            candidate.insert(delivery_position, delivery_stop)
                            yield candidate
                else:
                    # The order is already carried, or its pickup is the frozen first
                    # stop. Only its delivery may move, always after any retained pickup.
                    reduced = [
                        stop
                        for position, stop in enumerate(route)
                        if position != delivery_positions[0]
                    ]
                    retained_pickup = next(
                        (
                            position
                            for position, stop in enumerate(reduced)
                            if stop == (order_index, PICKUP)
                        ),
                        -1,
                    )
                    minimum_position = max(fixed_prefix, retained_pickup + 1)
                    delivery_stop = (order_index, DELIVERY)
                    for delivery_position in promising_positions(
                        reduced, minimum_position, delivery_stop
                    ):
                        candidate = list(reduced)
                        candidate.insert(delivery_position, delivery_stop)
                        yield candidate

            for _ in range(self.config.route_optimization_max_passes):
                best_route: list[Stop] | None = None
                best_projection: RouteProjection | None = None
                best_objective = current_objective
                current_route_key = tuple(current_projection.route)
                late_orders = {
                    order_index
                    for order_index, delivery_time in current_projection.delivery_ns.items()
                    if delivery_time > int(deadline_ns[order_index])
                }
                route_orders = list(dict.fromkeys(stop[0] for stop in current_projection.route))
                route_orders.sort(
                    key=lambda order_index: (
                        order_index not in late_orders,
                        int(deadline_ns[order_index]),
                    )
                )
                seen_routes: set[tuple[Stop, ...]] = set()

                for order_index in route_orders:
                    for candidate_route in relocation_candidates(
                        current_projection.route, order_index
                    ):
                        candidate_key = tuple(candidate_route)
                        if candidate_key == current_route_key or candidate_key in seen_routes:
                            continue
                        seen_routes.add(candidate_key)
                        route_optimization_candidate_count += 1
                        candidate_projection = project_route(
                            courier_index, candidate_route, at_time
                        )
                        if not candidate_projection.feasible:
                            continue
                        if (
                            self.config.respect_observed_shift_end
                            and candidate_projection.release_ns
                            > int(courier_end_ns[courier_index])
                        ):
                            continue
                        # Never trade away an on-time order. Among routes with no more
                        # late orders, use the same weighted objective as assignment.
                        if candidate_projection.late_count > current_projection.late_count:
                            continue
                        candidate_objective = route_projection_objective(
                            candidate_projection
                        )
                        if candidate_objective < best_objective - 1e-9:
                            best_route = candidate_route
                            best_projection = candidate_projection
                            best_objective = candidate_objective

                if best_route is None or best_projection is None:
                    break
                routes[courier_index] = best_route
                current_projection = best_projection
                current_objective = best_objective
                route_optimization_accepted_move_count += 1
                improved = True

            if improved:
                routes[courier_index] = current_projection.route
                route_release_ns[courier_index] = current_projection.release_ns
                route_release_lat[courier_index] = current_projection.release_lat
                route_release_lng[courier_index] = current_projection.release_lng
                route_optimization_improved_route_count += 1
                route_optimization_distance_reduction_km += max(
                    0.0,
                    initial_projection.remaining_distance_km
                    - current_projection.remaining_distance_km,
                )
                route_optimization_lateness_reduction_min += max(
                    0.0,
                    initial_projection.total_lateness_min
                    - current_projection.total_lateness_min,
                )
                route_optimization_late_orders_reduced += max(
                    0, initial_projection.late_count - current_projection.late_count
                )
                route_optimization_objective_reduction += max(
                    0.0,
                    route_projection_objective(initial_projection)
                    - route_projection_objective(current_projection),
                )

            route_optimization_runtime_seconds += (
                time.perf_counter() - optimization_started_at
            )
            return improved

        def generate_insertions(
            courier_index: int,
            order_index: int,
            position_limit: int,
        ) -> list[list[Stop]]:
            base = routes[courier_index]
            if not base:
                return [[(order_index, PICKUP), (order_index, DELIVERY)]]

            # If already travelling, the next stop is frozen. Otherwise insertion may happen
            # before the next planned stop because no next leg has started yet.
            min_pickup_pos = (
                1
                if moving[courier_index] and movement_mode[courier_index] == MOVEMENT_SERVICE
                else 0
            )
            def added_distance_for_position(
                route: list[Stop],
                position: int,
                target_lat: float,
                target_lng: float,
            ) -> float:
                if position == 0:
                    if moving[courier_index] and movement_mode[courier_index] == MOVEMENT_REPOSITION:
                        previous_lat = float(shortlist_lat[courier_index])
                        previous_lng = float(shortlist_lng[courier_index])
                    else:
                        previous_lat = float(courier_lat[courier_index])
                        previous_lng = float(courier_lng[courier_index])
                else:
                    previous_lat, previous_lng = stop_location(route[position - 1])

                added = distance_pair(
                    previous_lat,
                    previous_lng,
                    target_lat,
                    target_lng,
                    self.config.distance_metric,
                )
                if position < len(route):
                    next_lat, next_lng = stop_location(route[position])
                    added += distance_pair(
                        target_lat,
                        target_lng,
                        next_lat,
                        next_lng,
                        self.config.distance_metric,
                    )
                    added -= distance_pair(
                        previous_lat,
                        previous_lng,
                        next_lat,
                        next_lng,
                        self.config.distance_metric,
                    )
                return added

            def bounded_positions(
                route: list[Stop],
                positions: range,
                target_lat: float,
                target_lng: float,
                deadline_position: int,
            ) -> list[int]:
                candidates = list(positions)
                if len(candidates) <= position_limit:
                    return candidates
                scored = sorted(
                    candidates,
                    key=lambda position: added_distance_for_position(
                        route,
                        position,
                        target_lat,
                        target_lng,
                    ),
                )
                # Keep the local-distance best, earliest legal, and deadline-aligned
                # positions. The fourth high-risk slot, when enabled, protects the tail.
                chosen = [scored[0]]
                if candidates[0] not in chosen:
                    chosen.append(candidates[0])
                if deadline_position in candidates and deadline_position not in chosen:
                    chosen.append(deadline_position)
                if position_limit >= 4 and candidates[-1] not in chosen:
                    chosen.append(candidates[-1])
                for position in scored:
                    if position not in chosen:
                        chosen.append(position)
                    if len(chosen) >= position_limit:
                        break
                return sorted(chosen[:position_limit])

            def deadline_aligned_position(route: list[Stop], positions: range) -> int:
                candidates = list(positions)
                new_deadline = int(deadline_ns[order_index])
                for position in candidates:
                    if position >= len(route):
                        return position
                    next_order = route[position][0]
                    if int(deadline_ns[next_order]) >= new_deadline:
                        return position
                return candidates[-1]

            pickup_range = range(min_pickup_pos, len(base) + 1)
            pickup_positions = bounded_positions(
                base,
                pickup_range,
                float(sender_lat[order_index]),
                float(sender_lng[order_index]),
                deadline_aligned_position(base, pickup_range),
            )
            proposals: list[list[Stop]] = []
            for pickup_pos in pickup_positions:
                with_pickup = list(base)
                with_pickup.insert(pickup_pos, (order_index, PICKUP))
                delivery_range = range(pickup_pos + 1, len(with_pickup) + 1)
                delivery_positions = bounded_positions(
                    with_pickup,
                    delivery_range,
                    float(recipient_lat[order_index]),
                    float(recipient_lng[order_index]),
                    deadline_aligned_position(with_pickup, delivery_range),
                )
                for delivery_pos in delivery_positions:
                    candidate = list(with_pickup)
                    candidate.insert(delivery_pos, (order_index, DELIVERY))
                    proposals.append(candidate)
            return proposals

        def currently_eligible_indices(at_time: int) -> np.ndarray:
            mask = started & (active_count < self.config.max_active_orders)
            if self.config.respect_observed_shift_end:
                mask &= courier_end_ns >= at_time
            return np.flatnonzero(mask)

        def minimum_pair_insertion_distance_increase(
            courier_index: int,
            order_index: int,
        ) -> float:
            """Return the exact distance increase over every legal insertion gap.

            This distance-only value is used for the rider shortlist. The later
            insertion search still projects times and minimizes the full weighted
            system objective. Delivery gap costs use suffix minima, reducing the
            calculation from O(route length squared) to O(route length).
            """
            base = routes[courier_index]
            pickup_lat = float(sender_lat[order_index])
            pickup_lng = float(sender_lng[order_index])
            delivery_lat = float(recipient_lat[order_index])
            delivery_lng = float(recipient_lng[order_index])

            if (
                moving[courier_index]
                and movement_mode[courier_index] == MOVEMENT_REPOSITION
            ):
                origin_lat = float(shortlist_lat[courier_index])
                origin_lng = float(shortlist_lng[courier_index])
            else:
                origin_lat = float(courier_lat[courier_index])
                origin_lng = float(courier_lng[courier_index])

            if not base:
                return distance_pair(
                    origin_lat,
                    origin_lng,
                    pickup_lat,
                    pickup_lng,
                    self.config.distance_metric,
                ) + distance_pair(
                    pickup_lat,
                    pickup_lng,
                    delivery_lat,
                    delivery_lng,
                    self.config.distance_metric,
                )

            route_locations = [stop_location(stop) for stop in base]
            route_length = len(base)
            min_pickup_pos = (
                1
                if moving[courier_index]
                and movement_mode[courier_index] == MOVEMENT_SERVICE
                else 0
            )

            def gap_increase(target_lat: float, target_lng: float, gap: int) -> float:
                if gap == 0:
                    previous_lat, previous_lng = origin_lat, origin_lng
                else:
                    previous_lat, previous_lng = route_locations[gap - 1]
                increase = distance_pair(
                    previous_lat,
                    previous_lng,
                    target_lat,
                    target_lng,
                    self.config.distance_metric,
                )
                if gap < route_length:
                    next_lat, next_lng = route_locations[gap]
                    increase += distance_pair(
                        target_lat,
                        target_lng,
                        next_lat,
                        next_lng,
                        self.config.distance_metric,
                    )
                    increase -= distance_pair(
                        previous_lat,
                        previous_lng,
                        next_lat,
                        next_lng,
                        self.config.distance_metric,
                    )
                return increase

            delivery_gap_increases = [
                gap_increase(delivery_lat, delivery_lng, gap)
                for gap in range(route_length + 1)
            ]
            delivery_suffix_min = list(delivery_gap_increases)
            for gap in range(route_length - 1, -1, -1):
                delivery_suffix_min[gap] = min(
                    delivery_suffix_min[gap], delivery_suffix_min[gap + 1]
                )

            best_increase = math.inf
            pickup_to_delivery = distance_pair(
                pickup_lat,
                pickup_lng,
                delivery_lat,
                delivery_lng,
                self.config.distance_metric,
            )
            for pickup_gap in range(min_pickup_pos, route_length + 1):
                # Delivery immediately follows pickup in the same original gap.
                if pickup_gap == 0:
                    previous_lat, previous_lng = origin_lat, origin_lng
                else:
                    previous_lat, previous_lng = route_locations[pickup_gap - 1]
                adjacent_increase = distance_pair(
                    previous_lat,
                    previous_lng,
                    pickup_lat,
                    pickup_lng,
                    self.config.distance_metric,
                ) + pickup_to_delivery
                if pickup_gap < route_length:
                    next_lat, next_lng = route_locations[pickup_gap]
                    adjacent_increase += distance_pair(
                        delivery_lat,
                        delivery_lng,
                        next_lat,
                        next_lng,
                        self.config.distance_metric,
                    )
                    adjacent_increase -= distance_pair(
                        previous_lat,
                        previous_lng,
                        next_lat,
                        next_lng,
                        self.config.distance_metric,
                    )
                best_increase = min(best_increase, adjacent_increase)

                # At least one existing stop lies between pickup and delivery.
                if pickup_gap < route_length:
                    separated_increase = (
                        gap_increase(pickup_lat, pickup_lng, pickup_gap)
                        + delivery_suffix_min[pickup_gap + 1]
                    )
                    best_increase = min(best_increase, separated_increase)

            return float(best_increase)

        def candidate_shortlist(
            order_index: int,
            at_time: int,
            shortlist_size: int,
        ) -> np.ndarray:
            nonlocal route_fit_rider_evaluation_count
            eligible = currently_eligible_indices(at_time)
            if eligible.size == 0:
                return eligible

            # With max_active_orders=1 every eligible rider is idle/stationary, so the exact
            # one-order rule is simply the nearest rider; no larger shortlist is needed.
            shortlist_size = 1 if self.config.max_active_orders == 1 else shortlist_size
            if eligible.size <= shortlist_size:
                return eligible

            distances = distance_rows(
                shortlist_lat[eligible],
                shortlist_lng[eligible],
                np.full(eligible.size, sender_lat[order_index], dtype=float),
                np.full(eligible.size, sender_lng[order_index], dtype=float),
                self.config.distance_metric,
            )
            available_ns = np.maximum(route_release_ns[eligible], at_time)
            tail_to_merchant_km = distance_rows(
                route_release_lat[eligible],
                route_release_lng[eligible],
                np.full(eligible.size, sender_lat[order_index], dtype=float),
                np.full(eligible.size, sender_lng[order_index], dtype=float),
                self.config.distance_metric,
            )
            tail_travel_ns = np.rint(
                self._travel_minutes(tail_to_merchant_km) * NS_PER_MINUTE
            ).astype(np.int64)
            estimated_arrival_ns = available_ns + tail_travel_ns
            estimated_pickup_ns = np.maximum(
                estimated_arrival_ns,
                int(ready_ns[order_index])
                + int(round(self.config.ready_time_buffer_minutes * NS_PER_MINUTE)),
            ) + int(round(self.config.pickup_service_minutes * NS_PER_MINUTE))

            chosen_positions: list[int] = []

            def add_best(values: np.ndarray, count: int) -> None:
                if count <= 0:
                    return
                for position in np.argsort(values, kind="stable")[:count]:
                    value = int(position)
                    if value not in chosen_positions:
                        chosen_positions.append(value)

            load_order = np.lexsort((estimated_pickup_ns, active_count[eligible]))

            # Wide cheap prefilter, followed by exact route-distance traversal.
            # This inserts BOTH pickup and delivery and therefore identifies riders
            # whose remaining route is genuinely on the way.
            prefilter_positions: list[int] = []

            def add_prefilter(values: np.ndarray, count: int) -> None:
                if count <= 0:
                    return
                for position in np.argsort(values, kind="stable")[:count]:
                    value = int(position)
                    if value not in prefilter_positions:
                        prefilter_positions.append(value)

            prefilter_limit = self.config.route_fit_prefilter_riders
            if prefilter_limit == 0 or eligible.size <= prefilter_limit:
                prefilter_positions = list(range(eligible.size))
            else:
                add_prefilter(
                    distances, self.config.route_fit_prefilter_nearest_riders
                )
                add_prefilter(
                    estimated_pickup_ns,
                    self.config.route_fit_prefilter_earliest_pickup_riders,
                )
                for position in load_order[
                    : self.config.route_fit_prefilter_lowest_load_riders
                ]:
                    value = int(position)
                    if value not in prefilter_positions:
                        prefilter_positions.append(value)
                # Fill duplicate-created vacancies without exceeding the wide pool.
                for ranking in (
                    np.argsort(estimated_pickup_ns, kind="stable"),
                    np.argsort(distances, kind="stable"),
                ):
                    for position in ranking:
                        value = int(position)
                        if value not in prefilter_positions:
                            prefilter_positions.append(value)
                        if len(prefilter_positions) >= prefilter_limit:
                            break
                    if len(prefilter_positions) >= prefilter_limit:
                        break
                prefilter_positions = prefilter_positions[:prefilter_limit]

            route_fit_rider_evaluation_count += len(prefilter_positions)
            route_fit_ranked = sorted(
                prefilter_positions,
                key=lambda position: (
                    minimum_pair_insertion_distance_increase(
                        int(eligible[position]), order_index
                    ),
                    int(estimated_pickup_ns[position]),
                    float(distances[position]),
                    int(position),
                ),
            )
            for position in route_fit_ranked[: self.config.route_fit_candidate_riders]:
                value = int(position)
                if value not in chosen_positions:
                    chosen_positions.append(value)

            # The other two original shortlist rules remain unchanged.
            for position in load_order[: self.config.lowest_load_candidate_riders]:
                value = int(position)
                if value not in chosen_positions:
                    chosen_positions.append(value)
            add_best(estimated_pickup_ns, self.config.earliest_pickup_candidate_riders)

            # High-risk expansion adds riders with the earliest complete pickup estimate;
            # route-fit ranking and proximity fill vacancies from deduplication.
            add_best(estimated_pickup_ns, shortlist_size)
            for position in route_fit_ranked:
                value = int(position)
                if value not in chosen_positions:
                    chosen_positions.append(value)
                if len(chosen_positions) >= shortlist_size:
                    break
            add_best(distances, shortlist_size)
            return eligible[chosen_positions[:shortlist_size]]

        def search_insertion(
            order_index: int,
            at_time: int,
            rider_limit: int,
            position_limit: int,
        ) -> InsertionChoice | None:
            best_any: InsertionChoice | None = None
            best_protected: InsertionChoice | None = None
            for courier_index_raw in candidate_shortlist(order_index, at_time, rider_limit):
                courier_index = int(courier_index_raw)
                baseline = project_route(courier_index, routes[courier_index], at_time)
                if not baseline.feasible:
                    continue

                for candidate_route in generate_insertions(
                    courier_index,
                    order_index,
                    position_limit,
                ):
                    projection = project_route(courier_index, candidate_route, at_time)
                    if not projection.feasible:
                        continue

                    if self.config.respect_observed_shift_end and projection.release_ns > int(courier_end_ns[courier_index]):
                        continue

                    incremental_late = projection.late_count - baseline.late_count
                    incremental_lateness = projection.total_lateness_min - baseline.total_lateness_min
                    added_distance = projection.remaining_distance_km - baseline.remaining_distance_km
                    score = (
                        self.config.distance_weight * added_distance
                        + self.config.lateness_minute_weight * incremental_lateness
                        + self.config.late_order_weight * incremental_late
                    )

                    choice = InsertionChoice(
                            courier_index=courier_index,
                            route=candidate_route,
                            score=float(score),
                            incremental_distance_km=float(added_distance),
                            incremental_lateness_min=float(incremental_lateness),
                            incremental_late_orders=int(incremental_late),
                            projection=projection,
                            baseline_projection=baseline,
                        )
                    if best_any is None or score < best_any.score - 1e-9:
                        best_any = choice
                    if incremental_late <= 0 and (
                        best_protected is None or score < best_protected.score - 1e-9
                    ):
                        best_protected = choice
            if self.config.enable_on_time_protection and best_protected is not None:
                return best_protected
            return best_any

        def best_insertion(order_index: int, at_time: int) -> InsertionChoice | None:
            nonlocal high_risk_expansion_count
            choice = search_insertion(
                order_index,
                at_time,
                self.config.candidate_riders,
                self.config.insertion_position_limit,
            )
            projected_delivery = (
                choice.projection.delivery_ns.get(order_index) if choice is not None else None
            )
            high_risk = (
                choice is None
                or projected_delivery is None
                or projected_delivery > int(deadline_ns[order_index])
            )
            if self.config.enable_high_risk_expansion and high_risk:
                high_risk_expansion_count += 1
                expanded = search_insertion(
                    order_index,
                    at_time,
                    self.config.high_risk_candidate_riders,
                    self.config.high_risk_insertion_position_limit,
                )
                if expanded is not None:
                    return expanded
            return choice

        def schedule_next_stop(courier_index: int, at_time: int) -> None:
            if moving[courier_index] or not routes[courier_index]:
                return

            stop = routes[courier_index][0]
            order_index, kind = stop
            target_lat, target_lng = stop_location(stop)
            leg_km = distance_pair(
                float(courier_lat[courier_index]),
                float(courier_lng[courier_index]),
                target_lat,
                target_lng,
                self.config.distance_metric,
            )
            leg_min = float(self._travel_minutes(leg_km))
            departure = int(at_time)
            if needs_dispatch_delay[courier_index]:
                departure += int(round(self.config.dispatch_processing_minutes * NS_PER_MINUTE))
                needs_dispatch_delay[courier_index] = False
            arrival = int(departure + round(leg_min * NS_PER_MINUTE))
            if kind == PICKUP:
                service_start = max(
                    arrival,
                    int(ready_ns[order_index]) + int(round(self.config.ready_time_buffer_minutes * NS_PER_MINUTE)),
                )
                completion = service_start + int(round(self.config.pickup_service_minutes * NS_PER_MINUTE))
            else:
                service_start = arrival
                completion = arrival + int(round(self.config.delivery_service_minutes * NS_PER_MINUTE))

            moving[courier_index] = True
            movement_mode[courier_index] = MOVEMENT_SERVICE
            shortlist_lat[courier_index] = target_lat
            shortlist_lng[courier_index] = target_lng
            next_arrival_ns[courier_index] = arrival
            next_service_start_ns[courier_index] = service_start
            next_event_ns[courier_index] = completion
            current_leg_distance_km[courier_index] = leg_km
            current_leg_minutes[courier_index] = leg_min
            route_version[courier_index] += 1
            heapq.heappush(
                route_events,
                (completion, int(route_version[courier_index]), courier_index),
            )

        def apply_assignment(order_index: int, choice: InsertionChoice, at_time: int) -> None:
            nonlocal post_service_cancelled_count
            courier_index = choice.courier_index
            if pending_post_service[courier_index] is not None:
                pending_post_service[courier_index] = None
                post_service_cancelled_count += 1
            routes[courier_index] = choice.route
            route_release_ns[courier_index] = choice.projection.release_ns
            route_release_lat[courier_index] = choice.projection.release_lat
            route_release_lng[courier_index] = choice.projection.release_lng
            was_idle = active_count[courier_index] == 0
            active_orders[courier_index].add(order_index)
            active_count[courier_index] += 1
            if was_idle:
                courier_busy_start_ns[courier_index] = at_time
                needs_dispatch_delay[courier_index] = True
            max_active_observed[courier_index] = max(
                max_active_observed[courier_index],
                int(active_count[courier_index]),
            )

            assigned[order_index] = True
            simulated_courier[order_index] = courier_ids[courier_index]
            assignment_ns[order_index] = at_time
            rider_release_at_assignment_ns[order_index] = choice.projection.release_ns
            rider_release_at_assignment_lat[order_index] = choice.projection.release_lat
            rider_release_at_assignment_lng[order_index] = choice.projection.release_lng
            active_orders_at_assignment[order_index] = int(active_count[courier_index])
            courier_order_count[courier_index] += 1
            if moving[courier_index] and movement_mode[courier_index] == MOVEMENT_REPOSITION:
                courier_orders_assigned_during_reposition[courier_index] += 1
                event_index = int(active_reposition_event_index[courier_index])
                if event_index >= 0:
                    reposition_event_rows[event_index]["orders_assigned_during_reposition"] = int(
                        reposition_event_rows[event_index]["orders_assigned_during_reposition"]
                    ) + 1
            decision_weighted_score[order_index] = choice.score
            best_assignment_score_at_decision[order_index] = choice.score
            decision_incremental_distance_km[order_index] = choice.incremental_distance_km
            decision_incremental_lateness_min[order_index] = choice.incremental_lateness_min
            decision_incremental_late_orders[order_index] = choice.incremental_late_orders

            # Do not start a new leg here. All same-time pending orders are considered first;
            # stationary riders start their next leg after the assignment batch.

        def reject_order(order_index: int, at_time: int, best_score: float) -> None:
            rejected[order_index] = True
            rejection_ns[order_index] = at_time
            decision_weighted_score[order_index] = self.config.unserved_order_penalty
            best_assignment_score_at_decision[order_index] = best_score
            decision_incremental_distance_km[order_index] = np.nan
            decision_incremental_lateness_min[order_index] = np.nan
            decision_incremental_late_orders[order_index] = np.nan

        def gamma_poisson_snapshot(at_time: int) -> dict[str, np.ndarray] | None:
            """Build a causal zone forecast using only information known at_time."""
            elapsed_minutes = max(
                0.0, (at_time - int(release_ns.min())) / NS_PER_MINUTE
            )
            if elapsed_minutes <= 1e-9:
                return None

            observed_order_mask = (
                reposition_demand_valid_mask & (release_ns <= at_time)
            )
            if not observed_order_mask.any():
                return None
            cumulative_counts = np.bincount(
                order_zone[observed_order_mask], minlength=zone_count
            ).astype(float)
            perfect_benchmark = (
                self.config.reposition_forecast_mode
                == "perfect_horizon_benchmark"
            )
            horizon_end = int(
                at_time
                + round(
                    self.config.reposition_forecast_horizon_minutes
                    * NS_PER_MINUTE
                )
            )
            future_mask = (
                reposition_demand_valid_mask
                & (release_ns > at_time)
                & (release_ns <= horizon_end)
            )
            geometry_mask = (
                observed_order_mask | future_mask
                if perfect_benchmark
                else observed_order_mask
            )
            geometry_counts = np.bincount(
                order_zone[geometry_mask], minlength=zone_count
            ).astype(float)
            observed_zones = np.flatnonzero(geometry_counts > 0)
            if observed_zones.size == 0:
                return None

            causal_center_lat = np.full(zone_count, np.nan)
            causal_center_lng = np.full(zone_count, np.nan)
            target_lat = np.full(zone_count, np.nan)
            target_lng = np.full(zone_count, np.nan)
            hotspot_start = int(
                at_time
                - round(
                    self.config.reposition_hotspot_history_window_minutes
                    * NS_PER_MINUTE
                )
            )
            decay_minutes = self.config.reposition_hotspot_decay_minutes
            for zone in observed_zones:
                zone_mask = geometry_mask & (order_zone == int(zone))
                causal_center_lat[zone] = float(np.median(sender_lat[zone_mask]))
                causal_center_lng[zone] = float(np.median(sender_lng[zone_mask]))
                if perfect_benchmark:
                    recent_zone_mask = future_mask & (order_zone == int(zone))
                else:
                    recent_zone_mask = zone_mask & (release_ns >= hotspot_start)
                if recent_zone_mask.any():
                    if perfect_benchmark:
                        weights = np.ones(int(recent_zone_mask.sum()), dtype=float)
                    else:
                        ages = np.maximum(
                            0.0,
                            (at_time - release_ns[recent_zone_mask]) / NS_PER_MINUTE,
                        )
                        weights = np.exp(-ages / decay_minutes)
                    target_lat[zone] = float(
                        np.average(sender_lat[recent_zone_mask], weights=weights)
                    )
                    target_lng[zone] = float(
                        np.average(sender_lng[recent_zone_mask], weights=weights)
                    )
                else:
                    target_lat[zone] = float(np.mean(sender_lat[zone_mask]))
                    target_lng[zone] = float(np.mean(sender_lng[zone_mask]))

            history = self.config.reposition_poisson_history_window_minutes
            exposure = min(history, elapsed_minutes)
            history_start = int(at_time - round(exposure * NS_PER_MINUTE))
            recent_mask = (
                reposition_demand_valid_mask
                & (release_ns > history_start)
                & (release_ns <= at_time)
            )
            recent_counts = np.bincount(
                order_zone[recent_mask], minlength=zone_count
            ).astype(float)
            recent_total = float(recent_counts.sum())
            if recent_total <= 0:
                return None

            smoothing = self.config.reposition_poisson_zone_share_smoothing
            if perfect_benchmark:
                recent_counts = np.bincount(
                    order_zone[future_mask], minlength=zone_count
                ).astype(float)
                predicted_demand = recent_counts.copy()
            else:
                global_rate = recent_total / max(exposure, 1e-9)
                prior_exposure = self.config.reposition_poisson_prior_exposure_minutes
                zone_share = np.zeros(zone_count, dtype=float)
                zone_share[observed_zones] = (
                    cumulative_counts[observed_zones]
                    + smoothing / len(observed_zones)
                ) / (float(cumulative_counts.sum()) + smoothing)
                prior_rate = global_rate * zone_share
                posterior_rate = (
                    recent_counts + prior_exposure * prior_rate
                ) / (exposure + prior_exposure)
                predicted_demand = (
                    self.config.reposition_forecast_horizon_minutes * posterior_rate
                )

            observed_service = np.maximum(
                self.config.reposition_min_service_time_minutes,
                direct_service_minutes[observed_order_mask],
            )
            global_service_mean = float(np.mean(observed_service))
            service_capacity = np.zeros(zone_count, dtype=float)
            for zone in observed_zones:
                values = np.maximum(
                    self.config.reposition_min_service_time_minutes,
                    direct_service_minutes[
                        observed_order_mask & (order_zone == int(zone))
                    ],
                )
                zone_mean = (
                    float(values.sum()) + smoothing * global_service_mean
                ) / (len(values) + smoothing)
                service_capacity[zone] = min(
                    float(self.config.max_active_orders),
                    self.config.reposition_forecast_horizon_minutes
                    / max(self.config.reposition_min_service_time_minutes, zone_mean),
                )

            completed_mask = (
                reposition_demand_valid_mask
                & delivered
                & (delivery_ns != NAT_INT)
                & (delivery_ns <= at_time)
            )
            late_probability = np.full(
                zone_count, self.config.reposition_late_risk_prior_mean
            )
            mean_lateness = np.zeros(zone_count, dtype=float)
            strength = self.config.reposition_late_risk_prior_strength
            if completed_mask.any():
                completed_lateness = np.maximum(
                    0.0,
                    (delivery_ns[completed_mask] - deadline_ns[completed_mask])
                    / NS_PER_MINUTE,
                )
                completed_zones = order_zone[completed_mask]
                completed_counts = np.bincount(
                    completed_zones, minlength=zone_count
                ).astype(float)
                late_counts = np.bincount(
                    completed_zones,
                    weights=(completed_lateness > 1e-9).astype(float),
                    minlength=zone_count,
                )
                lateness_sums = np.bincount(
                    completed_zones,
                    weights=completed_lateness,
                    minlength=zone_count,
                )
                global_late_probability = (
                    float(late_counts.sum())
                    + strength * self.config.reposition_late_risk_prior_mean
                ) / (float(completed_counts.sum()) + strength)
                global_mean_lateness = float(lateness_sums.sum()) / max(
                    1.0, float(completed_counts.sum())
                )
                late_probability[observed_zones] = (
                    late_counts[observed_zones]
                    + strength * global_late_probability
                ) / (completed_counts[observed_zones] + strength)
                mean_lateness[observed_zones] = (
                    lateness_sums[observed_zones]
                    + strength * global_mean_lateness
                ) / (completed_counts[observed_zones] + strength)

            return {
                "observed_zones": observed_zones,
                "center_lat": causal_center_lat,
                "center_lng": causal_center_lng,
                "target_lat": target_lat,
                "target_lng": target_lng,
                "recent_counts": recent_counts,
                "cumulative_counts": cumulative_counts,
                "predicted_demand": predicted_demand,
                "service_capacity": service_capacity,
                "late_probability": late_probability,
                "mean_lateness": mean_lateness,
            }

        def nearest_snapshot_zone(
            lat: float,
            lng: float,
            snapshot: dict[str, np.ndarray],
        ) -> int:
            observed_zones = snapshot["observed_zones"].astype(np.int64)
            distances = distance_rows(
                np.full(len(observed_zones), lat, dtype=float),
                np.full(len(observed_zones), lng, dtype=float),
                snapshot["center_lat"][observed_zones],
                snapshot["center_lng"][observed_zones],
                self.config.distance_metric,
            )
            return int(observed_zones[int(np.argmin(distances))])

        def schedule_reposition(
            courier_index: int,
            target_zone: int,
            at_time: int,
            predicted_raw_demand: float,
            predicted_weighted_demand: float,
            idle_supply_before: float,
            soon_free_supply: float,
            target_gap_before: float,
            urgency_multiplier: float,
            capture_probability: float,
            avoided_pickup_distance_km: float,
            estimated_lateness_reduction_min: float,
            estimated_late_orders_avoided: float,
            estimated_objective_delta: float,
            *,
            target_lat_override: float | None = None,
            target_lng_override: float | None = None,
            prediction_model: str = "scaled_recent_count",
            diagnostics: dict[str, float | int | str] | None = None,
        ) -> None:
            origin_lat = float(courier_lat[courier_index])
            origin_lng = float(courier_lng[courier_index])
            target_lat = (
                float(zone_lat[target_zone])
                if target_lat_override is None
                else float(target_lat_override)
            )
            target_lng = (
                float(zone_lng[target_zone])
                if target_lng_override is None
                else float(target_lng_override)
            )
            leg_km = distance_pair(
                origin_lat,
                origin_lng,
                target_lat,
                target_lng,
                self.config.distance_metric,
            )
            leg_min = float(self._travel_minutes(leg_km))
            arrival = int(at_time + round(leg_min * NS_PER_MINUTE))

            moving[courier_index] = True
            movement_mode[courier_index] = MOVEMENT_REPOSITION
            shortlist_lat[courier_index] = target_lat
            shortlist_lng[courier_index] = target_lng
            next_arrival_ns[courier_index] = arrival
            next_service_start_ns[courier_index] = arrival
            next_event_ns[courier_index] = arrival
            current_leg_distance_km[courier_index] = leg_km
            current_leg_minutes[courier_index] = leg_min
            route_version[courier_index] += 1

            event_index = len(reposition_event_rows)
            active_reposition_event_index[courier_index] = event_index
            reposition_event_rows.append(
                {
                    "event_id": event_index + 1,
                    "courier_id": courier_ids[courier_index],
                    "decision_time": pd.to_datetime(at_time),
                    "origin_lng": origin_lng,
                    "origin_lat": origin_lat,
                    "source_zone": zone_labels[nearest_zone(origin_lat, origin_lng)],
                    "target_zone": zone_labels[target_zone],
                    "prediction_model": prediction_model,
                    "target_lng": target_lng,
                    "target_lat": target_lat,
                    "distance_km": leg_km,
                    "travel_minutes": leg_min,
                    "planned_arrival_time": pd.to_datetime(arrival),
                    "actual_arrival_time": pd.NaT,
                    "predicted_target_demand": predicted_weighted_demand,
                    "predicted_target_raw_demand": predicted_raw_demand,
                    "predicted_target_urgency_weighted_demand": predicted_weighted_demand,
                    "target_idle_supply_before": idle_supply_before,
                    "target_soon_free_supply": soon_free_supply,
                    "target_gap_before": target_gap_before,
                    "target_urgency_multiplier": urgency_multiplier,
                    "estimated_capture_probability": capture_probability,
                    "estimated_avoided_pickup_distance_km": avoided_pickup_distance_km,
                    "estimated_lateness_reduction_minutes": estimated_lateness_reduction_min,
                    "estimated_late_orders_avoided": estimated_late_orders_avoided,
                    "estimated_reposition_objective_delta": estimated_objective_delta,
                    "orders_assigned_during_reposition": 0,
                    "completed": False,
                }
            )
            if diagnostics:
                reposition_event_rows[-1].update(diagnostics)
            heapq.heappush(
                route_events,
                (arrival, int(route_version[courier_index]), courier_index),
            )

        def attempt_gamma_poisson_reposition(
            at_time: int,
            idle_indices: np.ndarray,
        ) -> set[int]:
            """Greedy joint relocation using causal Gamma-Poisson forecasts."""
            nonlocal reposition_candidate_count
            nonlocal reposition_objective_gate_rejection_count
            nonlocal reposition_on_time_gate_rejection_count
            nonlocal post_service_plan_count
            snapshot = gamma_poisson_snapshot(at_time)
            if snapshot is None:
                return set()

            observed_zones = snapshot["observed_zones"].astype(np.int64)
            demand = snapshot["predicted_demand"]
            service_capacity = snapshot["service_capacity"]
            late_probability = snapshot["late_probability"]
            mean_lateness = snapshot["mean_lateness"]
            horizon = self.config.reposition_forecast_horizon_minutes

            supply = np.zeros(zone_count, dtype=float)
            idle_supply_count = np.zeros(zone_count, dtype=np.int64)
            courier_zone = np.full(courier_count, -1, dtype=np.int64)
            for courier_index_raw in idle_indices:
                courier_index = int(courier_index_raw)
                if (
                    moving[courier_index]
                    and movement_mode[courier_index] == MOVEMENT_REPOSITION
                ):
                    lat = float(shortlist_lat[courier_index])
                    lng = float(shortlist_lng[courier_index])
                    remaining_minutes = max(
                        0.0, (int(next_event_ns[courier_index]) - at_time) / NS_PER_MINUTE
                    )
                    arrival_weight = max(0.0, 1.0 - remaining_minutes / horizon)
                else:
                    lat = float(courier_lat[courier_index])
                    lng = float(courier_lng[courier_index])
                    arrival_weight = 1.0
                zone = nearest_snapshot_zone(lat, lng, snapshot)
                courier_zone[courier_index] = zone
                idle_supply_count[zone] += 1
                supply[zone] += arrival_weight * service_capacity[zone]

            soon_free_supply = np.zeros(zone_count, dtype=float)
            if self.config.reposition_include_soon_free_supply:
                horizon_ns = int(round(horizon * NS_PER_MINUTE))
                for courier_index_raw in np.flatnonzero(started & (active_count > 0)):
                    courier_index = int(courier_index_raw)
                    release_time = int(route_release_ns[courier_index])
                    remaining_ns = release_time - at_time
                    if remaining_ns <= 0 or remaining_ns >= horizon_ns:
                        continue
                    future_zone = nearest_snapshot_zone(
                        float(route_release_lat[courier_index]),
                        float(route_release_lng[courier_index]),
                        snapshot,
                    )
                    arrival_weight = max(
                        0.0, 1.0 - remaining_ns / max(1.0, float(horizon_ns))
                    )
                    contribution = arrival_weight * service_capacity[future_zone]
                    soon_free_supply[future_zone] += contribution
                    supply[future_zone] += contribution

            gap = demand - supply
            cooldown_ns = int(
                round(self.config.reposition_cooldown_minutes * NS_PER_MINUTE)
            )
            eligible: list[int] = []
            for courier_index_raw in idle_indices:
                courier_index = int(courier_index_raw)
                if moving[courier_index] or routes[courier_index]:
                    continue
                last_end = int(last_reposition_end_ns[courier_index])
                if last_end != NAT_INT and at_time - last_end < cooldown_ns:
                    continue
                eligible.append(courier_index)
            if not eligible or self.config.reposition_max_idle_fraction <= 0:
                return set()

            max_moves = max(
                1,
                int(
                    math.floor(
                        len(eligible) * self.config.reposition_max_idle_fraction
                    )
                ),
            )
            reserve = self.config.reposition_min_idle_reserve_per_zone
            moved: set[int] = set()
            for _ in range(max_moves):
                best: tuple | None = None
                best_key: tuple[float, float, float, int, int] | None = None
                for courier_index in eligible:
                    if courier_index in moved:
                        continue
                    source_zone = int(courier_zone[courier_index])
                    if (
                        source_zone < 0
                        or idle_supply_count[source_zone] <= reserve
                    ):
                        continue
                    source_supply_loss = float(service_capacity[source_zone])
                    for target_zone_raw in observed_zones:
                        target_zone = int(target_zone_raw)
                        if (
                            target_zone == source_zone
                            or gap[target_zone]
                            <= self.config.reposition_minimum_demand_gap_orders
                        ):
                            continue
                        target_lat = float(snapshot["target_lat"][target_zone])
                        target_lng = float(snapshot["target_lng"][target_zone])
                        leg_km = distance_pair(
                            float(courier_lat[courier_index]),
                            float(courier_lng[courier_index]),
                            target_lat,
                            target_lng,
                            self.config.distance_metric,
                        )
                        if not (
                            self.config.reposition_min_distance_km
                            <= leg_km
                            <= self.config.reposition_max_distance_km
                        ):
                            continue
                        reposition_candidate_count += 1
                        leg_min = float(self._travel_minutes(leg_km))
                        if leg_min > self.config.reposition_max_travel_minutes:
                            continue
                        arrival_weight = max(0.0, 1.0 - leg_min / horizon)
                        if arrival_weight <= 1e-12:
                            continue
                        target_supply_gain = (
                            arrival_weight * service_capacity[target_zone]
                        )
                        target_shortage_reduction = min(
                            max(0.0, float(gap[target_zone])),
                            target_supply_gain,
                        )
                        source_shortage_increase = (
                            max(0.0, float(gap[source_zone]) + source_supply_loss)
                            - max(0.0, float(gap[source_zone]))
                        )
                        expected_late_orders_avoided = (
                            target_shortage_reduction
                            * late_probability[target_zone]
                            - source_shortage_increase
                            * late_probability[source_zone]
                        )
                        if (
                            expected_late_orders_avoided
                            < self.config.reposition_min_expected_net_on_time_gain
                        ):
                            reposition_on_time_gate_rejection_count += 1
                            continue
                        lateness_exposure = (
                            target_shortage_reduction
                            * mean_lateness[target_zone]
                            * (1.0 - arrival_weight)
                            + source_shortage_increase
                            * mean_lateness[source_zone]
                        )
                        secondary_cost = (
                            self.config.distance_weight * leg_km
                            + self.config.reposition_travel_time_penalty * leg_min
                            + self.config.lateness_minute_weight * lateness_exposure
                        )
                        estimated_lateness_reduction = max(
                            0.0,
                            target_shortage_reduction * mean_lateness[target_zone]
                            - source_shortage_increase * mean_lateness[source_zone],
                        )
                        estimated_objective_delta = (
                            self.config.distance_weight * leg_km
                            - self.config.lateness_minute_weight
                            * estimated_lateness_reduction
                            - self.config.late_order_weight
                            * expected_late_orders_avoided
                        )
                        if (
                            self.config.reposition_use_objective_gate
                            and estimated_objective_delta
                            > -self.config.reposition_objective_improvement_margin
                        ):
                            reposition_objective_gate_rejection_count += 1
                            continue
                        key = (
                            -round(float(estimated_objective_delta), 12),
                            round(float(expected_late_orders_avoided), 12),
                            -leg_km,
                            -courier_index,
                            -target_zone,
                        )
                        if best_key is None or key > best_key:
                            best_key = key
                            best = (
                                courier_index,
                                source_zone,
                                target_zone,
                                target_lat,
                                target_lng,
                                leg_km,
                                leg_min,
                                arrival_weight,
                                source_supply_loss,
                                target_supply_gain,
                                target_shortage_reduction,
                                source_shortage_increase,
                                expected_late_orders_avoided,
                                lateness_exposure,
                                secondary_cost,
                                estimated_lateness_reduction,
                                estimated_objective_delta,
                            )
                if best is None:
                    break
                (
                    courier_index,
                    source_zone,
                    target_zone,
                    target_lat,
                    target_lng,
                    leg_km,
                    leg_min,
                    arrival_weight,
                    source_supply_loss,
                    target_supply_gain,
                    target_shortage_reduction,
                    source_shortage_increase,
                    expected_late_orders_avoided,
                    lateness_exposure,
                    secondary_cost,
                    estimated_lateness_reduction,
                    estimated_objective_delta,
                ) = best
                predicted_target_demand = float(demand[target_zone])
                target_supply_before = float(supply[target_zone])
                target_gap_before = float(gap[target_zone])
                capture_probability = min(
                    1.0,
                    target_shortage_reduction
                    / max(1e-9, predicted_target_demand),
                )
                schedule_reposition(
                    courier_index=courier_index,
                    target_zone=target_zone,
                    at_time=at_time,
                    predicted_raw_demand=predicted_target_demand,
                    predicted_weighted_demand=(
                        predicted_target_demand * late_probability[target_zone]
                    ),
                    idle_supply_before=target_supply_before,
                    soon_free_supply=float(soon_free_supply[target_zone]),
                    target_gap_before=target_gap_before,
                    urgency_multiplier=float(late_probability[target_zone]),
                    capture_probability=capture_probability,
                    avoided_pickup_distance_km=capture_probability * leg_km,
                    estimated_lateness_reduction_min=estimated_lateness_reduction,
                    estimated_late_orders_avoided=float(
                        expected_late_orders_avoided
                    ),
                    estimated_objective_delta=float(estimated_objective_delta),
                    target_lat_override=target_lat,
                    target_lng_override=target_lng,
                    prediction_model=self.config.reposition_forecast_mode,
                    diagnostics={
                        "decision_kind": "IDLE_NOW",
                        "poisson_recent_zone_orders": float(
                            snapshot["recent_counts"][target_zone]
                        ),
                        "poisson_cumulative_zone_orders": float(
                            snapshot["cumulative_counts"][target_zone]
                        ),
                        "target_service_capacity_orders": float(
                            service_capacity[target_zone]
                        ),
                        "source_service_capacity_orders": source_supply_loss,
                        "arrival_supply_weight": arrival_weight,
                        "expected_target_orders_covered": target_shortage_reduction,
                        "expected_source_orders_exposed": source_shortage_increase,
                        "expected_avoided_late_orders": float(
                            expected_late_orders_avoided
                        ),
                        "target_late_probability": float(
                            late_probability[target_zone]
                        ),
                        "source_late_probability": float(
                            late_probability[source_zone]
                        ),
                        "expected_lateness_exposure_minutes": float(
                            lateness_exposure
                        ),
                        "relocation_secondary_cost": float(secondary_cost),
                    },
                )
                moved.add(courier_index)
                idle_supply_count[source_zone] -= 1
                idle_supply_count[target_zone] += 1
                supply[source_zone] -= source_supply_loss
                supply[target_zone] += target_supply_gain
                gap[source_zone] += source_supply_loss
                gap[target_zone] -= target_supply_gain
                courier_zone[courier_index] = target_zone

            # Plan cancellable moves for riders projected to finish their current
            # committed route inside the forecast horizon. A later real order
            # cancels the plan; otherwise it starts immediately after final delivery.
            if (
                self.config.reposition_post_service_enabled
                and self.config.reposition_include_soon_free_supply
            ):
                horizon_ns = int(round(horizon * NS_PER_MINUTE))
                busy_candidates: list[tuple[int, int, float, float, int, float]] = []
                for courier_index_raw in np.flatnonzero(started & (active_count > 0)):
                    courier_index = int(courier_index_raw)
                    pending_post_service[courier_index] = None
                    release_time = int(route_release_ns[courier_index])
                    remaining_ns = release_time - at_time
                    if remaining_ns <= 0 or remaining_ns >= horizon_ns:
                        continue
                    origin_lat = float(route_release_lat[courier_index])
                    origin_lng = float(route_release_lng[courier_index])
                    source_zone = nearest_snapshot_zone(origin_lat, origin_lng, snapshot)
                    availability_delay = remaining_ns / NS_PER_MINUTE
                    source_weight = max(0.0, 1.0 - availability_delay / horizon)
                    source_supply_loss = source_weight * service_capacity[source_zone]
                    busy_candidates.append((
                        courier_index, source_zone, origin_lat, origin_lng,
                        release_time, source_supply_loss,
                    ))

                max_plans = max(
                    1,
                    int(math.floor(
                        len(busy_candidates) * self.config.reposition_max_idle_fraction
                    )),
                ) if busy_candidates else 0
                planned: set[int] = set()
                for _ in range(max_plans):
                    best_plan: tuple | None = None
                    best_plan_key: tuple[float, float, float, int, int] | None = None
                    for (
                        courier_index, source_zone, origin_lat, origin_lng,
                        release_time, source_supply_loss,
                    ) in busy_candidates:
                        if courier_index in planned:
                            continue
                        availability_delay = (release_time - at_time) / NS_PER_MINUTE
                        for target_zone_raw in observed_zones:
                            target_zone = int(target_zone_raw)
                            if (
                                target_zone == source_zone
                                or gap[target_zone]
                                <= self.config.reposition_minimum_demand_gap_orders
                            ):
                                continue
                            target_lat = float(snapshot["target_lat"][target_zone])
                            target_lng = float(snapshot["target_lng"][target_zone])
                            leg_km = distance_pair(
                                origin_lat, origin_lng, target_lat, target_lng,
                                self.config.distance_metric,
                            )
                            if not (
                                self.config.reposition_min_distance_km
                                <= leg_km
                                <= self.config.reposition_max_distance_km
                            ):
                                continue
                            leg_min = float(self._travel_minutes(leg_km))
                            if leg_min > self.config.reposition_max_travel_minutes:
                                continue
                            arrival_weight = max(
                                0.0, 1.0 - (availability_delay + leg_min) / horizon
                            )
                            if arrival_weight <= 1e-12:
                                continue
                            reposition_candidate_count += 1
                            target_supply_gain = (
                                arrival_weight * service_capacity[target_zone]
                            )
                            target_reduction = min(
                                max(0.0, float(gap[target_zone])), target_supply_gain
                            )
                            source_increase = (
                                max(0.0, float(gap[source_zone]) + source_supply_loss)
                                - max(0.0, float(gap[source_zone]))
                            )
                            net_on_time_gain = (
                                target_reduction * late_probability[target_zone]
                                - source_increase * late_probability[source_zone]
                            )
                            if (
                                net_on_time_gain
                                < self.config.reposition_min_expected_net_on_time_gain
                            ):
                                reposition_on_time_gate_rejection_count += 1
                                continue
                            lateness_reduction = max(
                                0.0,
                                target_reduction * mean_lateness[target_zone]
                                - source_increase * mean_lateness[source_zone],
                            )
                            objective_delta = (
                                self.config.distance_weight * leg_km
                                - self.config.lateness_minute_weight * lateness_reduction
                                - self.config.late_order_weight * net_on_time_gain
                            )
                            if (
                                self.config.reposition_use_objective_gate
                                and objective_delta
                                > -self.config.reposition_objective_improvement_margin
                            ):
                                reposition_objective_gate_rejection_count += 1
                                continue
                            key = (
                                -round(float(objective_delta), 12),
                                round(float(net_on_time_gain), 12),
                                -leg_km, -courier_index, -target_zone,
                            )
                            if best_plan_key is None or key > best_plan_key:
                                best_plan_key = key
                                best_plan = (
                                    courier_index, source_zone, target_zone,
                                    target_lat, target_lng, release_time, leg_km,
                                    leg_min, source_supply_loss, target_supply_gain,
                                    target_reduction, source_increase, net_on_time_gain,
                                    lateness_reduction, objective_delta, arrival_weight,
                                )
                    if best_plan is None:
                        break
                    (
                        courier_index, source_zone, target_zone, target_lat,
                        target_lng, release_time, leg_km, leg_min,
                        source_supply_loss, target_supply_gain, target_reduction,
                        source_increase, net_on_time_gain, lateness_reduction,
                        objective_delta, arrival_weight,
                    ) = best_plan
                    pending_post_service[courier_index] = {
                        "target_zone": target_zone,
                        "target_lat": target_lat,
                        "target_lng": target_lng,
                        "created_time": at_time,
                        "expiry_time": at_time + horizon_ns,
                        "predicted_raw_demand": float(demand[target_zone]),
                        "predicted_weighted_demand": float(
                            demand[target_zone] * late_probability[target_zone]
                        ),
                        "target_supply_before": float(supply[target_zone]),
                        "target_gap_before": float(gap[target_zone]),
                        "capture_probability": min(
                            1.0, target_reduction / max(1e-9, float(demand[target_zone]))
                        ),
                        "estimated_lateness_reduction": lateness_reduction,
                        "estimated_late_orders_avoided": net_on_time_gain,
                        "estimated_objective_delta": objective_delta,
                        "arrival_supply_weight": arrival_weight,
                        "source_zone": source_zone,
                        "source_supply_loss": source_supply_loss,
                        "target_supply_gain": target_supply_gain,
                        "target_reduction": target_reduction,
                        "source_increase": source_increase,
                        "planned_leg_km": leg_km,
                        "planned_leg_min": leg_min,
                        "predicted_departure_time": release_time,
                    }
                    post_service_plan_count += 1
                    planned.add(courier_index)
                    supply[source_zone] -= source_supply_loss
                    supply[target_zone] += target_supply_gain
                    gap[source_zone] += source_supply_loss
                    gap[target_zone] -= target_supply_gain
            return moved

        def attempt_reposition(at_time: int) -> set[int]:
            nonlocal reposition_tick_count
            nonlocal reposition_candidate_count
            nonlocal reposition_objective_gate_rejection_count
            reposition_tick_count += 1
            if self.config.reposition_policy == "none" or zone_count == 0:
                return set()

            idle_mask = started & (active_count == 0)
            if self.config.respect_observed_shift_end:
                idle_mask &= courier_end_ns >= at_time
            idle_indices = np.flatnonzero(idle_mask)
            if idle_indices.size == 0:
                return set()

            if self.config.reposition_policy == "gamma_poisson":
                return attempt_gamma_poisson_reposition(at_time, idle_indices)

            idle_supply = np.zeros(zone_count, dtype=np.int64)
            courier_zone = np.full(courier_count, -1, dtype=np.int64)
            for courier_index_raw in idle_indices:
                courier_index = int(courier_index_raw)
                if moving[courier_index] and movement_mode[courier_index] == MOVEMENT_REPOSITION:
                    lat = float(shortlist_lat[courier_index])
                    lng = float(shortlist_lng[courier_index])
                else:
                    lat = float(courier_lat[courier_index])
                    lng = float(courier_lng[courier_index])
                zone = nearest_zone(lat, lng)
                courier_zone[courier_index] = zone
                idle_supply[zone] += 1

            # Riders released sooner contribute more to the forecast supply. A rider
            # finishing in 12 minutes cannot protect near-term demand as well as one
            # finishing in 3 minutes, so future supply is deliberately fractional.
            soon_free_supply = np.zeros(zone_count, dtype=float)
            if self.config.reposition_include_soon_free_supply:
                horizon_end = int(
                    at_time + round(self.config.reposition_forecast_horizon_minutes * NS_PER_MINUTE)
                )
                for courier_index_raw in np.flatnonzero(started & (active_count > 0)):
                    courier_index = int(courier_index_raw)
                    projection = project_route(courier_index, routes[courier_index], at_time)
                    if projection.feasible and projection.release_ns <= horizon_end:
                        zone = nearest_zone(projection.release_lat, projection.release_lng)
                        minutes_until_free = max(
                            0.0, (projection.release_ns - at_time) / NS_PER_MINUTE
                        )
                        if minutes_until_free <= self.config.reposition_soon_free_full_weight_minutes:
                            supply_weight = 1.0
                        elif minutes_until_free <= self.config.reposition_soon_free_medium_weight_minutes:
                            supply_weight = self.config.reposition_soon_free_medium_weight
                        else:
                            supply_weight = self.config.reposition_soon_free_far_weight
                        soon_free_supply[zone] += supply_weight

            history_start = int(
                at_time - round(self.config.reposition_forecast_history_minutes * NS_PER_MINUTE)
            )
            recent_mask = (release_ns > history_start) & (release_ns <= at_time)
            recent_indices = np.flatnonzero(recent_mask)
            recent_raw_demand = np.bincount(
                order_zone[recent_indices], minlength=zone_count
            ).astype(float)
            # Recent orders are samples used to forecast *future* demand. Their original
            # promised delivery window is therefore the relevant urgency signal; using
            # deadline-at_time would incorrectly make old observations look overdue.
            promised_window_minutes = (
                deadline_ns[recent_indices] - release_ns[recent_indices]
            ) / NS_PER_MINUTE
            urgency_weights = np.where(
                promised_window_minutes <= self.config.reposition_urgent_deadline_minutes,
                self.config.reposition_urgent_demand_weight,
                np.where(
                    promised_window_minutes <= self.config.reposition_near_deadline_minutes,
                    self.config.reposition_near_demand_weight,
                    1.0,
                ),
            )
            recent_weighted_demand = np.bincount(
                order_zone[recent_indices],
                weights=urgency_weights,
                minlength=zone_count,
            ).astype(float)
            forecast_scale = (
                self.config.reposition_forecast_horizon_minutes
                / self.config.reposition_forecast_history_minutes
            )
            predicted_raw_demand = recent_raw_demand * forecast_scale
            predicted_weighted_demand = recent_weighted_demand * forecast_scale
            urgency_multiplier = np.divide(
                predicted_weighted_demand,
                predicted_raw_demand,
                out=np.ones(zone_count, dtype=float),
                where=predicted_raw_demand > 1e-9,
            )
            # Supply is measured in riders, so the physical shortage must remain in raw
            # order units. Deadline weights rank shortages but do not create fake orders.
            gap = predicted_raw_demand - idle_supply - soon_free_supply
            priority_gap = predicted_weighted_demand - idle_supply - soon_free_supply

            cooldown_ns = int(round(self.config.reposition_cooldown_minutes * NS_PER_MINUTE))
            eligible: list[int] = []
            for courier_index_raw in idle_indices:
                courier_index = int(courier_index_raw)
                if moving[courier_index] or routes[courier_index]:
                    continue
                last_end = int(last_reposition_end_ns[courier_index])
                if last_end != NAT_INT and at_time - last_end < cooldown_ns:
                    continue
                eligible.append(courier_index)
            if not eligible or self.config.reposition_max_idle_fraction <= 0:
                return set()

            max_moves = max(
                1,
                int(math.floor(len(eligible) * self.config.reposition_max_idle_fraction)),
            )
            moved: set[int] = set()
            reserve = self.config.reposition_min_idle_reserve_per_zone

            for _ in range(max_moves):
                best_pair: tuple[
                    float, float, float, int, int, float, float, float, float, float
                ] | None = None
                for courier_index in eligible:
                    if courier_index in moved:
                        continue
                    source_zone = int(courier_zone[courier_index])
                    if source_zone < 0 or idle_supply[source_zone] <= reserve:
                        continue
                    for target_zone in range(zone_count):
                        if target_zone == source_zone or gap[target_zone] <= 0:
                            continue
                        gap_improvement = float(
                            priority_gap[target_zone] - priority_gap[source_zone]
                        )
                        if gap_improvement <= 1e-9:
                            continue
                        leg_km = distance_pair(
                            float(courier_lat[courier_index]),
                            float(courier_lng[courier_index]),
                            float(zone_lat[target_zone]),
                            float(zone_lng[target_zone]),
                            self.config.distance_metric,
                        )
                        if leg_km <= 1e-9 or leg_km > self.config.reposition_max_distance_km:
                            continue
                        reposition_candidate_count += 1
                        leg_min = float(self._travel_minutes(leg_km))
                        target_urgency = float(urgency_multiplier[target_zone])
                        capture_probability = min(
                            1.0,
                            max(0.0, float(gap[target_zone])) / max(1.0, target_urgency),
                        )
                        avoided_pickup_distance_km = capture_probability * leg_km
                        urgency_denominator = max(
                            1e-9, self.config.reposition_urgent_demand_weight - 1.0
                        )
                        late_risk = float(
                            np.clip((target_urgency - 1.0) / urgency_denominator, 0.0, 1.0)
                        )
                        estimated_lateness_reduction_min = (
                            capture_probability * late_risk * leg_min
                        )
                        estimated_late_orders_avoided = (
                            capture_probability
                            * late_risk
                            * min(
                                1.0,
                                leg_min / self.config.reposition_urgent_deadline_minutes,
                            )
                        )
                        estimated_objective_delta = (
                            self.config.distance_weight
                            * (leg_km - avoided_pickup_distance_km)
                            - self.config.lateness_minute_weight
                            * estimated_lateness_reduction_min
                            - self.config.late_order_weight
                            * estimated_late_orders_avoided
                        )
                        if (
                            self.config.reposition_use_objective_gate
                            and estimated_objective_delta >= -1e-9
                        ):
                            reposition_objective_gate_rejection_count += 1
                            continue
                        benefit_density = gap_improvement / (1.0 + leg_km)
                        candidate = (
                            -estimated_objective_delta,
                            benefit_density,
                            -leg_km,
                            courier_index,
                            target_zone,
                            capture_probability,
                            avoided_pickup_distance_km,
                            estimated_lateness_reduction_min,
                            estimated_late_orders_avoided,
                            estimated_objective_delta,
                        )
                        if best_pair is None or candidate > best_pair:
                            best_pair = candidate

                if best_pair is None:
                    break
                (
                    _,
                    _,
                    _,
                    courier_index,
                    target_zone,
                    capture_probability,
                    avoided_pickup_distance_km,
                    estimated_lateness_reduction_min,
                    estimated_late_orders_avoided,
                    estimated_objective_delta,
                ) = best_pair
                source_zone = int(courier_zone[courier_index])
                target_idle_before = int(idle_supply[target_zone])
                target_gap_before = float(gap[target_zone])
                schedule_reposition(
                    courier_index=courier_index,
                    target_zone=target_zone,
                    at_time=at_time,
                    predicted_raw_demand=float(predicted_raw_demand[target_zone]),
                    predicted_weighted_demand=float(predicted_weighted_demand[target_zone]),
                    idle_supply_before=target_idle_before,
                    soon_free_supply=float(soon_free_supply[target_zone]),
                    target_gap_before=target_gap_before,
                    urgency_multiplier=float(urgency_multiplier[target_zone]),
                    capture_probability=capture_probability,
                    avoided_pickup_distance_km=avoided_pickup_distance_km,
                    estimated_lateness_reduction_min=estimated_lateness_reduction_min,
                    estimated_late_orders_avoided=estimated_late_orders_avoided,
                    estimated_objective_delta=estimated_objective_delta,
                )
                moved.add(courier_index)
                idle_supply[source_zone] -= 1
                idle_supply[target_zone] += 1
                courier_zone[courier_index] = target_zone
                gap = predicted_raw_demand - idle_supply - soon_free_supply
                priority_gap = predicted_weighted_demand - idle_supply - soon_free_supply

            return moved

        def activate_due_post_service_repositions(at_time: int) -> None:
            nonlocal post_service_activated_count
            nonlocal post_service_cancelled_count
            for courier_index, plan in enumerate(pending_post_service):
                if plan is None:
                    continue
                if at_time > int(plan["expiry_time"]):
                    pending_post_service[courier_index] = None
                    post_service_cancelled_count += 1
                    continue
                if active_count[courier_index] > 0 or routes[courier_index]:
                    continue
                if moving[courier_index]:
                    pending_post_service[courier_index] = None
                    post_service_cancelled_count += 1
                    continue
                target_zone = int(plan["target_zone"])
                capture_probability = float(plan["capture_probability"])
                schedule_reposition(
                    courier_index=courier_index,
                    target_zone=target_zone,
                    at_time=at_time,
                    predicted_raw_demand=float(plan["predicted_raw_demand"]),
                    predicted_weighted_demand=float(
                        plan["predicted_weighted_demand"]
                    ),
                    idle_supply_before=float(plan["target_supply_before"]),
                    soon_free_supply=0.0,
                    target_gap_before=float(plan["target_gap_before"]),
                    urgency_multiplier=0.0,
                    capture_probability=capture_probability,
                    avoided_pickup_distance_km=(
                        capture_probability * float(plan["planned_leg_km"])
                    ),
                    estimated_lateness_reduction_min=float(
                        plan["estimated_lateness_reduction"]
                    ),
                    estimated_late_orders_avoided=float(
                        plan["estimated_late_orders_avoided"]
                    ),
                    estimated_objective_delta=float(
                        plan["estimated_objective_delta"]
                    ),
                    target_lat_override=float(plan["target_lat"]),
                    target_lng_override=float(plan["target_lng"]),
                    prediction_model=self.config.reposition_forecast_mode,
                    diagnostics={
                        "decision_kind": "POST_SERVICE",
                        "predicted_departure_time": pd.to_datetime(
                            int(plan["predicted_departure_time"])
                        ),
                        "target_service_capacity_orders": float(
                            plan["target_supply_gain"]
                        ),
                        "source_service_capacity_orders": float(
                            plan["source_supply_loss"]
                        ),
                        "arrival_supply_weight": float(
                            plan["arrival_supply_weight"]
                        ),
                        "expected_target_orders_covered": float(
                            plan["target_reduction"]
                        ),
                        "expected_source_orders_exposed": float(
                            plan["source_increase"]
                        ),
                        "expected_avoided_late_orders": float(
                            plan["estimated_late_orders_avoided"]
                        ),
                    },
                )
                pending_post_service[courier_index] = None
                post_service_activated_count += 1

        def attempt_pending(at_time: int) -> set[int]:
            changed_couriers: set[int] = set()
            if not pending:
                return changed_couriers

            # Avoid repeatedly scanning a large waiting queue when every rider is already
            # at the active-order limit. This is especially important in the single-order
            # control run during peak periods.
            if currently_eligible_indices(at_time).size == 0:
                return changed_couriers

            deferred: list[tuple[int, int, int]] = []
            attempts = len(pending)
            for _ in range(attempts):
                if currently_eligible_indices(at_time).size == 0:
                    break
                priority = heapq.heappop(pending)
                order_index = priority[2]
                if assigned[order_index] or rejected[order_index]:
                    continue
                choice = best_insertion(order_index, at_time)
                if choice is None:
                    deferred.append(priority)
                    continue
                if (
                    self.config.enable_active_rejection
                    and choice.score > self.config.unserved_order_penalty + 1e-9
                ):
                    reject_order(order_index, at_time, choice.score)
                    continue
                apply_assignment(order_index, choice, at_time)
                changed_couriers.add(choice.courier_index)
            for item in deferred:
                heapq.heappush(pending, item)
            return changed_couriers

        while True:
            # 1) Release all orders known by the current event time.
            while order_ptr < order_count and release_ns[order_ptr] <= current_time:
                if self.config.order_priority == "earliest_deadline":
                    priority = (int(deadline_ns[order_ptr]), int(release_ns[order_ptr]), order_ptr)
                else:
                    priority = (int(release_ns[order_ptr]), int(deadline_ns[order_ptr]), order_ptr)
                heapq.heappush(pending, priority)
                order_ptr += 1

            # 2) Start riders whose assumed shift start has been reached.
            while courier_ptr < courier_count and courier_start_ns[courier_ptr] <= current_time:
                if not self.config.respect_observed_shift_end or courier_end_ns[courier_ptr] >= current_time:
                    started[courier_ptr] = True
                courier_ptr += 1

            # 3) Complete every route-stop event at this exact time. Riders are left at a
            #    node boundary (moving=False), so same-time new orders may be inserted before
            #    the next unstarted leg.
            stationary_with_routes: set[int] = set()
            while route_events and route_events[0][0] <= current_time:
                event_time, version, courier_index = heapq.heappop(route_events)
                if version != int(route_version[courier_index]) or not moving[courier_index]:
                    continue
                if event_time != int(next_event_ns[courier_index]):
                    continue
                if movement_mode[courier_index] == MOVEMENT_REPOSITION:
                    target_lat = float(shortlist_lat[courier_index])
                    target_lng = float(shortlist_lng[courier_index])
                    courier_reposition_distance_km[courier_index] += float(
                        current_leg_distance_km[courier_index]
                    )
                    courier_reposition_minutes[courier_index] += float(
                        current_leg_minutes[courier_index]
                    )
                    courier_reposition_count[courier_index] += 1
                    courier_lat[courier_index] = target_lat
                    courier_lng[courier_index] = target_lng
                    last_reposition_end_ns[courier_index] = event_time

                    event_index = int(active_reposition_event_index[courier_index])
                    if event_index >= 0:
                        reposition_event_rows[event_index]["actual_arrival_time"] = pd.to_datetime(
                            event_time
                        )
                        reposition_event_rows[event_index]["completed"] = True
                    active_reposition_event_index[courier_index] = -1
                    moving[courier_index] = False
                    movement_mode[courier_index] = MOVEMENT_NONE
                    next_event_ns[courier_index] = NAT_INT
                    next_arrival_ns[courier_index] = NAT_INT
                    next_service_start_ns[courier_index] = NAT_INT
                    current_leg_distance_km[courier_index] = 0.0
                    current_leg_minutes[courier_index] = 0.0
                    if routes[courier_index]:
                        stationary_with_routes.add(courier_index)
                    continue

                if not routes[courier_index]:
                    moving[courier_index] = False
                    movement_mode[courier_index] = MOVEMENT_NONE
                    continue

                stop = routes[courier_index].pop(0)
                order_index, kind = stop
                target_lat, target_lng = stop_location(stop)

                courier_service_distance_km[courier_index] += float(current_leg_distance_km[courier_index])
                courier_lat[courier_index] = target_lat
                courier_lng[courier_index] = target_lng

                if kind == PICKUP:
                    picked[order_index] = True
                    carried_count[courier_index] += 1
                    restaurant_arrival_ns[order_index] = int(next_arrival_ns[courier_index])
                    pickup_ns[order_index] = int(event_time)
                    pickup_leg_km[order_index] = float(current_leg_distance_km[courier_index])
                    pickup_leg_min[order_index] = float(current_leg_minutes[courier_index])
                    restaurant_wait_min[order_index] = (
                        int(next_service_start_ns[courier_index]) - int(next_arrival_ns[courier_index])
                    ) / NS_PER_MINUTE
                else:
                    delivered[order_index] = True
                    carried_count[courier_index] -= 1
                    delivery_ns[order_index] = int(event_time)
                    delivery_leg_km[order_index] = float(current_leg_distance_km[courier_index])
                    delivery_leg_min[order_index] = float(current_leg_minutes[courier_index])
                    on_time[order_index] = event_time <= int(deadline_ns[order_index])
                    active_orders[courier_index].discard(order_index)
                    active_count[courier_index] -= 1
                    if active_count[courier_index] == 0 and courier_busy_start_ns[courier_index] != NAT_INT:
                        courier_busy_minutes[courier_index] += (
                            event_time - int(courier_busy_start_ns[courier_index])
                        ) / NS_PER_MINUTE
                        courier_busy_start_ns[courier_index] = NAT_INT

                moving[courier_index] = False
                movement_mode[courier_index] = MOVEMENT_NONE
                shortlist_lat[courier_index] = target_lat
                shortlist_lng[courier_index] = target_lng
                next_event_ns[courier_index] = NAT_INT
                next_arrival_ns[courier_index] = NAT_INT
                next_service_start_ns[courier_index] = NAT_INT
                current_leg_distance_km[courier_index] = 0.0
                current_leg_minutes[courier_index] = 0.0
                if routes[courier_index]:
                    stationary_with_routes.add(courier_index)
                else:
                    route_release_ns[courier_index] = event_time
                    route_release_lat[courier_index] = target_lat
                    route_release_lng[courier_index] = target_lng

            # 4) Try to assign all pending orders using idle riders + busy riders with spare
            #    active-order capacity.
            changed_couriers = attempt_pending(current_time)

            # Revisit each changed rider once after the same-time assignment batch. This
            # avoids repeatedly repairing the same route while several orders released at
            # the same minute are being inserted.
            for courier_index in changed_couriers:
                optimize_courier_route(courier_index, current_time)

            # A post-service plan is cancellable: real same-time work has first
            # priority, and only a rider still idle after assignment may start it.
            activate_due_post_service_repositions(current_time)

            # 5) Start the next leg only for riders whose state changed at this event time.
            #    Busy riders already travelling keep their committed current leg unchanged.
            for courier_index in stationary_with_routes | changed_couriers:
                if started[courier_index] and not moving[courier_index] and routes[courier_index]:
                    schedule_next_stop(courier_index, current_time)

            # Reposition only after the current-time assignment batch, so a rider is not
            # moved away when an order is already waiting at this event time.
            if (
                self.config.reposition_policy != "none"
                and current_time >= next_reposition_ns
                and (order_ptr < order_count or pending)
            ):
                while next_reposition_ns <= current_time:
                    next_reposition_ns += reposition_interval_ns
                attempt_reposition(current_time)

            # Stop only after all orders are released/handled and all assigned routes finish.
            if order_ptr >= order_count and not pending and not route_events:
                break

            next_times: list[int] = []
            if order_ptr < order_count:
                next_times.append(int(release_ns[order_ptr]))
            if courier_ptr < courier_count:
                next_times.append(int(courier_start_ns[courier_ptr]))
            if route_events:
                next_times.append(int(route_events[0][0]))
            if (
                self.config.reposition_policy != "none"
                and (order_ptr < order_count or pending)
                and next_reposition_ns > current_time
            ):
                next_times.append(int(next_reposition_ns))

            if not next_times:
                # Remaining pending orders have no feasible courier under the current model.
                break
            future = [value for value in next_times if value > current_time]
            current_time = min(future) if future else current_time + 1


        output_columns = [
            column
            for column in (
                "order_id",
                "waybill_id",
                "courier_id",
                "poi_id",
                "da_id",
                "zone_id",
                self.config.release_column,
                self.config.ready_column,
                self.config.deadline_column,
                "arrive_time",
            )
            if column in orders.columns
        ]
        results = orders[output_columns].copy()
        results = results.rename(columns={"courier_id": "historical_courier_id", "arrive_time": "historical_arrive_time"})
        results["simulated_courier_id"] = simulated_courier
        results["assigned"] = assigned
        results["rejected"] = rejected
        results["completed"] = delivered
        results["completion_status"] = np.select(
            [delivered, rejected, assigned],
            ["completed", "rejected", "assigned_unfinished"],
            default="unfinished",
        )
        results["assignment_time"] = pd.to_datetime(assignment_ns)
        results["rejection_time"] = pd.to_datetime(rejection_ns)
        results["decision_weighted_score"] = decision_weighted_score
        results["best_assignment_score_at_decision"] = best_assignment_score_at_decision
        results["decision_incremental_distance_km"] = decision_incremental_distance_km
        results["decision_incremental_lateness_min"] = decision_incremental_lateness_min
        results["decision_incremental_late_orders"] = decision_incremental_late_orders
        results["simulated_restaurant_arrival"] = pd.to_datetime(restaurant_arrival_ns)
        results["simulated_pickup_time"] = pd.to_datetime(pickup_ns)
        results["simulated_delivery_time"] = pd.to_datetime(delivery_ns)
        results["rider_release_time_at_assignment"] = pd.to_datetime(rider_release_at_assignment_ns)
        results["rider_release_lng_at_assignment"] = rider_release_at_assignment_lng
        results["rider_release_lat_at_assignment"] = rider_release_at_assignment_lat
        results["active_orders_at_assignment"] = active_orders_at_assignment
        results["merchant_lng"] = sender_lng
        results["merchant_lat"] = sender_lat
        results["customer_lng"] = recipient_lng
        results["customer_lat"] = recipient_lat
        results["assignment_wait_min"] = np.where(assigned, (assignment_ns - release_ns) / NS_PER_MINUTE, np.nan)
        results["assignment_to_restaurant_arrival_min"] = np.where(
            assigned,
            (restaurant_arrival_ns - assignment_ns) / NS_PER_MINUTE,
            np.nan,
        )
        results["assignment_to_pickup_min"] = np.where(
            assigned,
            (pickup_ns - assignment_ns) / NS_PER_MINUTE,
            np.nan,
        )
        results["pickup_leg_km"] = pickup_leg_km
        results["delivery_leg_km"] = delivery_leg_km
        results["pickup_leg_min"] = pickup_leg_min
        results["delivery_leg_min"] = delivery_leg_min
        results["restaurant_wait_min"] = restaurant_wait_min
        results["simulated_lateness_min"] = np.where(
            delivered,
            np.maximum(0.0, (delivery_ns - deadline_ns) / NS_PER_MINUTE),
            np.nan,
        )
        results["on_time"] = on_time

        courier_summary_columns = ["courier_id", "start_time", "shift_end", "start_lng", "start_lat"]
        if "historical_orders" in couriers.columns:
            courier_summary_columns.append("historical_orders")
        courier_summary = couriers[courier_summary_columns].copy()
        courier_summary["simulated_orders"] = courier_order_count
        courier_summary["service_distance_km"] = courier_service_distance_km
        courier_summary["reposition_distance_km"] = courier_reposition_distance_km
        courier_summary["total_distance_km"] = (
            courier_service_distance_km + courier_reposition_distance_km
        )
        courier_summary["reposition_count"] = courier_reposition_count
        courier_summary["reposition_minutes"] = courier_reposition_minutes
        courier_summary["orders_assigned_during_reposition"] = (
            courier_orders_assigned_during_reposition
        )
        courier_summary["simulated_busy_minutes"] = courier_busy_minutes
        courier_summary["max_active_orders_observed"] = max_active_observed
        courier_summary["final_lng"] = courier_lng
        courier_summary["final_lat"] = courier_lat

        assigned_count = int(assigned.sum())
        rejected_count = int(rejected.sum())
        completed_count = int(delivered.sum())
        on_time_count = int(on_time.sum())
        late_completed_count = int(completed_count - on_time_count)
        unfinished_count = int(order_count - completed_count - rejected_count)
        unserved_count = int(order_count - completed_count)
        runtime_seconds = time.perf_counter() - started_at
        completed_lateness = results.loc[delivered, "simulated_lateness_min"]
        total_lateness_minutes = float(completed_lateness.sum()) if completed_count else 0.0
        assigned_wait = results.loc[assigned, "assignment_wait_min"]
        assignment_to_pickup = results.loc[picked, "assignment_to_pickup_min"]
        total_service_distance = float(courier_service_distance_km.sum())
        total_reposition_distance = float(courier_reposition_distance_km.sum())
        total_distance = total_service_distance + total_reposition_distance
        distance_objective_cost = self.config.distance_weight * total_distance
        unserved_objective_cost = self.config.unserved_order_penalty * unserved_count
        lateness_objective_cost = self.config.lateness_minute_weight * total_lateness_minutes
        late_order_objective_cost = self.config.late_order_weight * late_completed_count
        total_weighted_objective = (
            distance_objective_cost
            + unserved_objective_cost
            + lateness_objective_cost
            + late_order_objective_cost
        )

        metrics: dict[str, float | int | str | bool] = {
            "input_rows": bundle.input_rows,
            "valid_orders": order_count,
            "invalid_or_duplicate_rows": int(len(bundle.invalid_orders)),
            "couriers": courier_count,
            "courier_source": bundle.courier_source,
            "fleet_size_requested": self.config.fleet_size if self.config.fleet_size is not None else courier_count,
            "fleet_selection": self.config.fleet_selection,
            "fleet_random_seed": self.config.fleet_random_seed,
            "all_selected_riders_online_full_period": (
                self.config.rider_start_mode == "simulation_start"
                and not self.config.respect_observed_shift_end
            ),
            "assigned_orders": assigned_count,
            "unassigned_orders": int(order_count - assigned_count),
            "rejected_orders": rejected_count,
            "completed_orders": completed_count,
            "unfinished_orders": unfinished_count,
            "unserved_orders": unserved_count,
            "late_completed_orders": late_completed_count,
            "assignment_rate": assigned_count / order_count,
            "completion_rate": completed_count / order_count,
            "rejection_rate": rejected_count / order_count,
            "on_time_orders": on_time_count,
            "on_time_delivery_rate_overall": on_time_count / order_count,
            "on_time_delivery_rate_completed": on_time_count / completed_count if completed_count else 0.0,
            "historical_on_time_delivery_rate": bundle.historical_on_time_rate,
            "on_time_gap_vs_historical_pp": (on_time_count / order_count - bundle.historical_on_time_rate) * 100.0,
            "orders_with_deadline_before_release": int((deadline_ns < release_ns).sum()),
            "mean_assignment_wait_minutes": float(assigned_wait.mean()) if assigned_count else 0.0,
            "p90_assignment_wait_minutes": float(assigned_wait.quantile(0.9)) if assigned_count else 0.0,
            "median_assignment_to_pickup_minutes": (
                float(assignment_to_pickup.median()) if int(picked.sum()) else 0.0
            ),
            "p90_assignment_to_pickup_minutes": (
                float(assignment_to_pickup.quantile(0.9)) if int(picked.sum()) else 0.0
            ),
            "mean_lateness_minutes_completed": float(completed_lateness.mean()) if completed_count else 0.0,
            "p90_lateness_minutes_completed": float(completed_lateness.quantile(0.9)) if completed_count else 0.0,
            "total_lateness_minutes_completed": total_lateness_minutes,
            "service_route_distance_km": total_service_distance,
            "reposition_distance_km": total_reposition_distance,
            "total_distance_km": total_distance,
            "reposition_policy": self.config.reposition_policy,
            "reposition_moves": int(courier_reposition_count.sum()),
            "riders_with_reposition": int((courier_reposition_count > 0).sum()),
            "reposition_minutes": float(courier_reposition_minutes.sum()),
            "orders_assigned_during_reposition": int(
                courier_orders_assigned_during_reposition.sum()
            ),
            "reposition_share_of_total_distance": (
                total_reposition_distance / total_distance if total_distance else 0.0
            ),
            "reposition_tick_count": reposition_tick_count,
            "reposition_candidates_evaluated": reposition_candidate_count,
            "reposition_candidates_blocked_by_objective_gate": (
                reposition_objective_gate_rejection_count
            ),
            "reposition_candidates_blocked_by_on_time_gate": (
                reposition_on_time_gate_rejection_count
            ),
            "post_service_relocation_enabled": (
                self.config.reposition_post_service_enabled
            ),
            "post_service_relocation_plans": post_service_plan_count,
            "post_service_relocation_activated": post_service_activated_count,
            "post_service_relocation_cancelled": post_service_cancelled_count,
            "effective_speed_kmh": self.speed_kmh,
            "distance_metric": self.config.distance_metric,
            "runtime_seconds": runtime_seconds,
            "throughput_orders_per_second": order_count / runtime_seconds if runtime_seconds else 0.0,
            "order_priority": self.config.order_priority,
            "max_active_orders": self.config.max_active_orders,
            "max_active_orders_observed": int(max_active_observed.max()) if courier_count else 0,
            "riders_reaching_active_order_limit": int(
                (max_active_observed >= self.config.max_active_orders).sum()
            ),
            "mean_active_orders_at_assignment": float(
                active_orders_at_assignment[assigned].mean()
            ) if assigned_count else 0.0,
            "p90_active_orders_at_assignment": float(
                np.quantile(active_orders_at_assignment[assigned], 0.9)
            ) if assigned_count else 0.0,
            "candidate_riders": self.config.candidate_riders,
            "insertion_position_limit": self.config.insertion_position_limit,
            "route_fit_candidate_riders": self.config.route_fit_candidate_riders,
            "lowest_load_candidate_riders": self.config.lowest_load_candidate_riders,
            "earliest_pickup_candidate_riders": self.config.earliest_pickup_candidate_riders,
            "route_fit_prefilter_riders": self.config.route_fit_prefilter_riders,
            "route_fit_prefilter_nearest_riders": (
                self.config.route_fit_prefilter_nearest_riders
            ),
            "route_fit_prefilter_earliest_pickup_riders": (
                self.config.route_fit_prefilter_earliest_pickup_riders
            ),
            "route_fit_prefilter_lowest_load_riders": (
                self.config.route_fit_prefilter_lowest_load_riders
            ),
            "route_fit_rider_evaluations": route_fit_rider_evaluation_count,
            "enable_on_time_protection": self.config.enable_on_time_protection,
            "enable_high_risk_expansion": self.config.enable_high_risk_expansion,
            "high_risk_candidate_riders": self.config.high_risk_candidate_riders,
            "high_risk_insertion_position_limit": (
                self.config.high_risk_insertion_position_limit
            ),
            "high_risk_expansion_orders": high_risk_expansion_count,
            "enable_route_optimization": self.config.enable_route_optimization,
            "route_optimization_min_active_orders": (
                self.config.route_optimization_min_active_orders
            ),
            "route_optimization_max_passes": (
                self.config.route_optimization_max_passes
            ),
            "route_optimization_position_limit": (
                self.config.route_optimization_position_limit
            ),
            "route_optimization_attempts": route_optimization_attempt_count,
            "route_optimization_improved_routes": (
                route_optimization_improved_route_count
            ),
            "route_optimization_accepted_moves": (
                route_optimization_accepted_move_count
            ),
            "route_optimization_candidates_evaluated": (
                route_optimization_candidate_count
            ),
            "route_optimization_projected_distance_reduction_km": (
                route_optimization_distance_reduction_km
            ),
            "route_optimization_projected_lateness_reduction_minutes": (
                route_optimization_lateness_reduction_min
            ),
            "route_optimization_projected_late_orders_reduced": (
                route_optimization_late_orders_reduced
            ),
            "route_optimization_projected_objective_reduction": (
                route_optimization_objective_reduction
            ),
            "route_optimization_runtime_seconds": (
                route_optimization_runtime_seconds
            ),
            "objective_type": "weighted_system_marginal_cost",
            "distance_weight": self.config.distance_weight,
            "unserved_order_penalty": self.config.unserved_order_penalty,
            "lateness_minute_weight": self.config.lateness_minute_weight,
            "late_order_weight": self.config.late_order_weight,
            "enable_active_rejection": self.config.enable_active_rejection,
            "distance_objective_cost": distance_objective_cost,
            "unserved_objective_cost": unserved_objective_cost,
            "lateness_objective_cost": lateness_objective_cost,
            "late_order_objective_cost": late_order_objective_cost,
            "total_weighted_objective": total_weighted_objective,
            "rider_start_mode": self.config.rider_start_mode,
            "shift_start_buffer_minutes": self.config.shift_start_buffer_minutes,
            "respect_observed_shift_end": self.config.respect_observed_shift_end,
            "dispatch_processing_minutes": self.config.dispatch_processing_minutes,
            "pickup_service_minutes": self.config.pickup_service_minutes,
            "delivery_service_minutes": self.config.delivery_service_minutes,
            "ready_time_buffer_minutes": self.config.ready_time_buffer_minutes,
            "release_column": self.config.release_column,
            "deadline_column": self.config.deadline_column,
            "assignment_timing": "event_driven",
            "rolling_horizon_assignment": False,
            "reposition_interval_minutes": self.config.reposition_interval_minutes,
            "reposition_forecast_history_minutes": (
                self.config.reposition_forecast_history_minutes
            ),
            "reposition_forecast_horizon_minutes": (
                self.config.reposition_forecast_horizon_minutes
            ),
            "reposition_warmup_minutes": self.config.reposition_warmup_minutes,
            "reposition_max_distance_km": self.config.reposition_max_distance_km,
            "reposition_max_travel_minutes": self.config.reposition_max_travel_minutes,
            "reposition_max_idle_fraction": self.config.reposition_max_idle_fraction,
            "reposition_min_idle_reserve_per_zone": (
                self.config.reposition_min_idle_reserve_per_zone
            ),
            "reposition_cooldown_minutes": self.config.reposition_cooldown_minutes,
            "reposition_include_soon_free_supply": (
                self.config.reposition_include_soon_free_supply
            ),
            "reposition_post_service_enabled": (
                self.config.reposition_post_service_enabled
            ),
            "reposition_zone_method": self.config.reposition_zone_method,
            "reposition_zone_count": zone_count,
            "reposition_noise_orders_reassigned": (
                reposition_noise_orders_reassigned
            ),
            "reposition_use_objective_gate": self.config.reposition_use_objective_gate,
            "reposition_urgent_deadline_minutes": (
                self.config.reposition_urgent_deadline_minutes
            ),
            "reposition_near_deadline_minutes": self.config.reposition_near_deadline_minutes,
            "reposition_urgent_demand_weight": self.config.reposition_urgent_demand_weight,
            "reposition_near_demand_weight": self.config.reposition_near_demand_weight,
            "reposition_soon_free_full_weight_minutes": (
                self.config.reposition_soon_free_full_weight_minutes
            ),
            "reposition_soon_free_medium_weight_minutes": (
                self.config.reposition_soon_free_medium_weight_minutes
            ),
            "reposition_soon_free_medium_weight": (
                self.config.reposition_soon_free_medium_weight
            ),
            "reposition_soon_free_far_weight": self.config.reposition_soon_free_far_weight,
            "reposition_prediction_model": (
                self.config.reposition_forecast_mode
                if self.config.reposition_policy == "gamma_poisson"
                else self.config.reposition_policy
            ),
            "reposition_forecast_mode": self.config.reposition_forecast_mode,
            "reposition_poisson_history_window_minutes": (
                self.config.reposition_poisson_history_window_minutes
            ),
            "reposition_poisson_prior_exposure_minutes": (
                self.config.reposition_poisson_prior_exposure_minutes
            ),
            "reposition_poisson_zone_share_smoothing": (
                self.config.reposition_poisson_zone_share_smoothing
            ),
            "reposition_hotspot_history_window_minutes": (
                self.config.reposition_hotspot_history_window_minutes
            ),
            "reposition_hotspot_decay_minutes": (
                self.config.reposition_hotspot_decay_minutes
            ),
            "reposition_late_risk_prior_mean": (
                self.config.reposition_late_risk_prior_mean
            ),
            "reposition_late_risk_prior_strength": (
                self.config.reposition_late_risk_prior_strength
            ),
            "reposition_minimum_demand_gap_orders": (
                self.config.reposition_minimum_demand_gap_orders
            ),
            "reposition_min_distance_km": self.config.reposition_min_distance_km,
            "reposition_min_service_time_minutes": (
                self.config.reposition_min_service_time_minutes
            ),
            "reposition_travel_time_penalty": (
                self.config.reposition_travel_time_penalty
            ),
            "reposition_min_expected_net_on_time_gain": (
                self.config.reposition_min_expected_net_on_time_gain
            ),
            "reposition_objective_improvement_margin": (
                self.config.reposition_objective_improvement_margin
            ),
        }
        reposition_columns = [
            "event_id",
            "courier_id",
            "decision_time",
            "origin_lng",
            "origin_lat",
            "source_zone",
            "target_zone",
            "target_lng",
            "target_lat",
            "distance_km",
            "travel_minutes",
            "planned_arrival_time",
            "actual_arrival_time",
            "predicted_target_demand",
            "predicted_target_raw_demand",
            "predicted_target_urgency_weighted_demand",
            "target_idle_supply_before",
            "target_soon_free_supply",
            "target_gap_before",
            "target_urgency_multiplier",
            "estimated_capture_probability",
            "estimated_avoided_pickup_distance_km",
            "estimated_lateness_reduction_minutes",
            "estimated_late_orders_avoided",
            "estimated_reposition_objective_delta",
            "orders_assigned_during_reposition",
            "completed",
            "prediction_model",
            "decision_kind",
            "poisson_recent_zone_orders",
            "poisson_cumulative_zone_orders",
            "target_service_capacity_orders",
            "source_service_capacity_orders",
            "arrival_supply_weight",
            "expected_target_orders_covered",
            "expected_source_orders_exposed",
            "target_late_probability",
            "source_late_probability",
            "expected_avoided_late_orders",
            "expected_lateness_exposure_minutes",
            "relocation_secondary_cost",
        ]
        self.reposition_events = pd.DataFrame(
            reposition_event_rows,
            columns=reposition_columns,
        )
        return results, courier_summary, metrics


def config_as_dict(config: SimulationConfig) -> dict[str, object]:
    return asdict(config)
