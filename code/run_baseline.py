from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from baseline import GreedyAssignmentRoutingSimulator, SimulationConfig, config_as_dict, load_and_prepare


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT.parent / "data_global" / "merchant_data_full_with_zones_global.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Route-fit deadline-aware Assignment + Routing experiment")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Order input (CSV, or XLSX when --courier-input is supplied)")
    parser.add_argument("--sheet-name", default=None, help="XLSX worksheet containing orders; defaults to the first sheet")
    parser.add_argument("--courier-input", type=Path, default=None, help="Optional independent courier-pool CSV; omit to preserve legacy rider reconstruction")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "latest")
    parser.add_argument("--speed-kmh", type=float, default=20.0, help="Movement speed; default is 20 km/h")
    parser.add_argument("--calibrate-speed", action="store_true", help="Use the historical median effective speed instead")
    parser.add_argument("--min-travel-minutes", type=float, default=1.0)
    parser.add_argument("--order-priority", choices=["earliest_deadline", "fifo"], default="earliest_deadline")
    parser.add_argument("--max-active-orders", type=int, default=8, help="Maximum unfinished orders held by one courier")
    parser.add_argument("--candidate-riders", type=int, default=8, help="Total riders evaluated by the full weighted insertion search")
    parser.add_argument("--insertion-position-limit", type=int, default=3, help="Maximum pickup positions and delivery positions retained per candidate rider")
    parser.add_argument("--route-fit-candidate-riders", type=int, default=4, help="Riders contributed by exact minimum route-distance increase")
    parser.add_argument("--lowest-load-candidate-riders", type=int, default=2, help="Riders contributed by the lowest active-order count")
    parser.add_argument("--earliest-pickup-candidate-riders", type=int, default=2, help="Riders contributed by the earliest complete pickup estimate")
    parser.add_argument("--route-fit-prefilter-riders", type=int, default=256, help="Wide pool traversed for exact route fit; use 0 for every eligible rider")
    parser.add_argument("--route-fit-prefilter-nearest-riders", type=int, default=128)
    parser.add_argument("--route-fit-prefilter-earliest-pickup-riders", type=int, default=96)
    parser.add_argument("--route-fit-prefilter-lowest-load-riders", type=int, default=32)
    parser.add_argument("--disable-on-time-protection", action="store_true")
    parser.add_argument("--disable-high-risk-expansion", action="store_true")
    parser.add_argument("--high-risk-candidate-riders", type=int, default=12)
    parser.add_argument("--high-risk-insertion-position-limit", type=int, default=4)
    parser.add_argument("--disable-route-optimization", action="store_true")
    parser.add_argument("--route-optimization-min-active-orders", type=int, default=3)
    parser.add_argument("--route-optimization-max-passes", type=int, default=2)
    parser.add_argument("--route-optimization-position-limit", type=int, default=4)
    parser.add_argument("--distance-weight", type=float, default=1.0)
    parser.add_argument("--unserved-order-penalty", type=float, default=1000.0)
    parser.add_argument("--lateness-minute-weight", type=float, default=5.0)
    parser.add_argument("--late-order-weight", type=float, default=100.0)
    parser.add_argument("--disable-active-rejection", action="store_true", help="Never reject an order solely because its best weighted insertion cost exceeds the unserved-order penalty")
    parser.add_argument("--rider-start-mode", choices=["reconstructed", "first_grab", "simulation_start"], default="simulation_start")
    parser.add_argument("--shift-start-buffer-minutes", type=float, default=35.0, help="For reconstructed rider starts: minutes before first observed grab; provisional calibration default=35")
    parser.add_argument("--fleet-size", type=int, default=800, help="Number of couriers kept in the simulation; current default dataset uses 800")
    parser.add_argument("--fleet-selection", choices=["most_active", "random"], default="most_active")
    parser.add_argument("--fleet-random-seed", type=int, default=42)
    parser.add_argument("--dispatch-processing-minutes", type=float, default=1.0, help="Small assignment/response allowance before an idle rider starts the first leg")
    parser.add_argument("--pickup-service-minutes", type=float, default=1.0, help="Pickup handoff/service time after food is ready")
    parser.add_argument("--delivery-service-minutes", type=float, default=2.0, help="Customer handoff/service time at delivery")
    parser.add_argument("--ready-time-buffer-minutes", type=float, default=0.0, help="Buffer added to estimated meal-ready time; optimized default is zero")
    parser.add_argument("--respect-observed-shift-end", action="store_true")
    parser.add_argument("--coordinate-scale", type=float, default=1_000_000.0)
    parser.add_argument("--longitude-offset", type=float, default=62.0)
    parser.add_argument("--distance-metric", choices=["rectilinear", "haversine"], default="rectilinear")
    parser.add_argument(
        "--reposition-policy",
        choices=["none", "demand_gap_greedy"],
        default="none",
        help="Use none for the control or demand_gap_greedy for periodic zone repositioning",
    )
    parser.add_argument(
        "--reposition-zone-method",
        choices=["zone_id", "da_id"],
        default="zone_id",
        help="Global zone_id is recommended for the new global-clustering datasets",
    )
    parser.add_argument("--reposition-interval-minutes", type=float, default=5.0)
    parser.add_argument("--reposition-forecast-history-minutes", type=float, default=30.0)
    parser.add_argument("--reposition-forecast-horizon-minutes", type=float, default=15.0)
    parser.add_argument("--reposition-warmup-minutes", type=float, default=10.0)
    parser.add_argument("--reposition-max-distance-km", type=float, default=3.0)
    parser.add_argument("--reposition-max-idle-fraction", type=float, default=0.30)
    parser.add_argument("--reposition-min-idle-reserve-per-zone", type=int, default=1)
    parser.add_argument("--reposition-cooldown-minutes", type=float, default=10.0)
    parser.add_argument("--disable-reposition-objective-gate", action="store_true")
    parser.add_argument("--reposition-urgent-deadline-minutes", type=float, default=15.0)
    parser.add_argument("--reposition-near-deadline-minutes", type=float, default=30.0)
    parser.add_argument("--reposition-urgent-demand-weight", type=float, default=3.0)
    parser.add_argument("--reposition-near-demand-weight", type=float, default=2.0)
    parser.add_argument("--reposition-soon-free-full-weight-minutes", type=float, default=5.0)
    parser.add_argument("--reposition-soon-free-medium-weight-minutes", type=float, default=10.0)
    parser.add_argument("--reposition-soon-free-medium-weight", type=float, default=0.6)
    parser.add_argument("--reposition-soon-free-far-weight", type=float, default=0.3)
    parser.add_argument(
        "--exclude-soon-free-supply",
        action="store_true",
        help="Ignore riders projected to finish their current route within the forecast horizon",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = SimulationConfig(
        order_priority=args.order_priority,
        max_active_orders=args.max_active_orders,
        candidate_riders=args.candidate_riders,
        insertion_position_limit=args.insertion_position_limit,
        route_fit_candidate_riders=args.route_fit_candidate_riders,
        lowest_load_candidate_riders=args.lowest_load_candidate_riders,
        earliest_pickup_candidate_riders=args.earliest_pickup_candidate_riders,
        route_fit_prefilter_riders=args.route_fit_prefilter_riders,
        route_fit_prefilter_nearest_riders=(
            args.route_fit_prefilter_nearest_riders
        ),
        route_fit_prefilter_earliest_pickup_riders=(
            args.route_fit_prefilter_earliest_pickup_riders
        ),
        route_fit_prefilter_lowest_load_riders=(
            args.route_fit_prefilter_lowest_load_riders
        ),
        enable_on_time_protection=not args.disable_on_time_protection,
        enable_high_risk_expansion=not args.disable_high_risk_expansion,
        high_risk_candidate_riders=args.high_risk_candidate_riders,
        high_risk_insertion_position_limit=args.high_risk_insertion_position_limit,
        enable_route_optimization=not args.disable_route_optimization,
        route_optimization_min_active_orders=(
            args.route_optimization_min_active_orders
        ),
        route_optimization_max_passes=args.route_optimization_max_passes,
        route_optimization_position_limit=args.route_optimization_position_limit,
        distance_weight=args.distance_weight,
        unserved_order_penalty=args.unserved_order_penalty,
        lateness_minute_weight=args.lateness_minute_weight,
        late_order_weight=args.late_order_weight,
        enable_active_rejection=not args.disable_active_rejection,
        rider_start_mode=args.rider_start_mode,
        shift_start_buffer_minutes=args.shift_start_buffer_minutes,
        respect_observed_shift_end=args.respect_observed_shift_end,
        fleet_size=args.fleet_size,
        fleet_selection=args.fleet_selection,
        fleet_random_seed=args.fleet_random_seed,
        dispatch_processing_minutes=args.dispatch_processing_minutes,
        pickup_service_minutes=args.pickup_service_minutes,
        delivery_service_minutes=args.delivery_service_minutes,
        ready_time_buffer_minutes=args.ready_time_buffer_minutes,
        coordinate_scale=args.coordinate_scale,
        longitude_offset=args.longitude_offset,
        distance_metric=args.distance_metric,
        speed_kmh=None if args.calibrate_speed else args.speed_kmh,
        min_travel_minutes=args.min_travel_minutes,
        reposition_policy=args.reposition_policy,
        reposition_zone_method=args.reposition_zone_method,
        reposition_interval_minutes=args.reposition_interval_minutes,
        reposition_forecast_history_minutes=args.reposition_forecast_history_minutes,
        reposition_forecast_horizon_minutes=args.reposition_forecast_horizon_minutes,
        reposition_warmup_minutes=args.reposition_warmup_minutes,
        reposition_max_distance_km=args.reposition_max_distance_km,
        reposition_max_idle_fraction=args.reposition_max_idle_fraction,
        reposition_min_idle_reserve_per_zone=args.reposition_min_idle_reserve_per_zone,
        reposition_cooldown_minutes=args.reposition_cooldown_minutes,
        reposition_include_soon_free_supply=not args.exclude_soon_free_supply,
        reposition_use_objective_gate=not args.disable_reposition_objective_gate,
        reposition_urgent_deadline_minutes=args.reposition_urgent_deadline_minutes,
        reposition_near_deadline_minutes=args.reposition_near_deadline_minutes,
        reposition_urgent_demand_weight=args.reposition_urgent_demand_weight,
        reposition_near_demand_weight=args.reposition_near_demand_weight,
        reposition_soon_free_full_weight_minutes=(
            args.reposition_soon_free_full_weight_minutes
        ),
        reposition_soon_free_medium_weight_minutes=(
            args.reposition_soon_free_medium_weight_minutes
        ),
        reposition_soon_free_medium_weight=args.reposition_soon_free_medium_weight,
        reposition_soon_free_far_weight=args.reposition_soon_free_far_weight,
    )
    bundle = load_and_prepare(
        args.input,
        config,
        courier_path=args.courier_input,
        sheet_name=args.sheet_name,
    )
    simulator = GreedyAssignmentRoutingSimulator(config, bundle.speed_kmh)
    order_results, courier_summary, metrics = simulator.run(bundle)

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    order_results.to_csv(output_dir / "order_results.csv", index=False, encoding="utf-8-sig")
    courier_summary.to_csv(output_dir / "courier_summary.csv", index=False, encoding="utf-8-sig")
    simulator.reposition_events.to_csv(
        output_dir / "reposition_events.csv", index=False, encoding="utf-8-sig"
    )
    bundle.invalid_orders.to_csv(output_dir / "invalid_orders.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([metrics]).to_csv(output_dir / "metrics.csv", index=False, encoding="utf-8-sig")
    summary_results = pd.DataFrame([{
        "total_drive_cost_km": metrics["total_distance_km"],
        "completion_rate": metrics["completion_rate"],
        "on_time_rate_overall": metrics["on_time_delivery_rate_overall"],
        "total_overtime_minutes": metrics["total_lateness_minutes_completed"],
    }])
    summary_results.to_csv(output_dir / "summary_results.csv", index=False, encoding="utf-8-sig")
    with (output_dir / "metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2)
    run_config = config_as_dict(config)
    run_config["input_path"] = str(args.input.resolve())
    run_config["courier_input_path"] = str(args.courier_input.resolve()) if args.courier_input else None
    run_config["sheet_name"] = args.sheet_name
    with (output_dir / "run_config.json").open("w", encoding="utf-8") as handle:
        json.dump(run_config, handle, ensure_ascii=False, indent=2)

    print(f"Output directory: {output_dir}")
    print(f"Valid orders: {metrics['valid_orders']:,}")
    print(f"Selected couriers: {metrics['couriers']:,}")
    print(f"Assigned orders: {metrics['assigned_orders']:,}")
    print(f"Rejected orders: {metrics['rejected_orders']:,}")
    print(f"Completed orders: {metrics['completed_orders']:,}")
    print(f"Overall on-time delivery rate: {metrics['on_time_delivery_rate_overall']:.2%}")
    print(f"Historical on-time delivery rate: {metrics['historical_on_time_delivery_rate']:.2%}")
    print(f"Gap vs historical: {(metrics['on_time_delivery_rate_overall'] - metrics['historical_on_time_delivery_rate']) * 100:+.2f} percentage points")
    print(f"Mean assignment wait: {metrics['mean_assignment_wait_minutes']:.2f} min")
    print(f"Median assignment-to-pickup time: {metrics['median_assignment_to_pickup_minutes']:.2f} min")
    print(f"High-risk expanded orders: {metrics['high_risk_expansion_orders']:,}")
    print(f"Route-optimization attempts: {metrics['route_optimization_attempts']:,}")
    print(f"Route-optimization improved routes: {metrics['route_optimization_improved_routes']:,}")
    print(f"Route-optimization accepted moves: {metrics['route_optimization_accepted_moves']:,}")
    print(f"Route-optimization runtime: {metrics['route_optimization_runtime_seconds']:.3f} s")
    print(f"Service-route distance: {metrics['service_route_distance_km']:.2f} km")
    print(f"Reposition distance: {metrics['reposition_distance_km']:.2f} km")
    print(f"Reposition moves: {metrics['reposition_moves']:,}")
    print(f"Total distance: {metrics['total_distance_km']:.2f} km")
    print(f"Total lateness: {metrics['total_lateness_minutes_completed']:.2f} min")
    print(f"Weighted system objective: {metrics['total_weighted_objective']:.2f}")
    print(f"Max active orders per rider: {metrics['max_active_orders']}")
    print(f"Effective speed: {metrics['effective_speed_kmh']:.2f} km/h")
    print(f"Runtime: {metrics['runtime_seconds']:.3f} s")


if __name__ == "__main__":
    main()
