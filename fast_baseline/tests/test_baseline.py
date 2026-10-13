from __future__ import annotations

import sys
import tempfile
import unittest
import random
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baseline import (  # noqa: E402
    DataBundle,
    GreedyAssignmentRoutingSimulator,
    SimulationConfig,
    load_and_prepare,
)


def make_bundle(orders: list[dict], couriers: list[dict], speed_kmh: float = 60.0) -> DataBundle:
    order_df = pd.DataFrame(orders)
    courier_df = pd.DataFrame(couriers)
    return DataBundle(order_df, courier_df, pd.DataFrame(), speed_kmh, len(order_df), 0.0)


class GreedyBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SimulationConfig(speed_kmh=60.0, min_travel_minutes=0.0, max_active_orders=1)

    def test_optimized_defaults(self) -> None:
        config = SimulationConfig()
        self.assertEqual(config.max_active_orders, 8)
        self.assertEqual(config.ready_time_buffer_minutes, 0.0)
        self.assertTrue(config.enable_on_time_protection)
        self.assertTrue(config.enable_high_risk_expansion)
        self.assertEqual(config.high_risk_candidate_riders, 12)
        self.assertEqual(config.high_risk_insertion_position_limit, 4)
        self.assertTrue(config.enable_route_optimization)
        self.assertEqual(config.route_optimization_min_active_orders, 3)
        self.assertEqual(config.route_optimization_max_passes, 2)
        self.assertEqual(config.route_optimization_position_limit, 4)

    def test_intra_route_optimization_improves_late_route(self) -> None:
        t0 = pd.Timestamp("2022-10-17 11:00:00")
        rng = random.Random(20260818)
        orders = []
        # The fourth deterministic draw produces a greedy route that has a strict
        # precedence-safe relocate improvement.
        for _ in range(4):
            orders = []
            for order_id in range(1, 6):
                merchant_lng = 112.0 + rng.uniform(0.0, 0.08)
                customer_lng = 112.0 + rng.uniform(0.0, 0.08)
                deadline = rng.randint(5, 25)
                orders.append({
                    "order_id": order_id,
                    "waybill_id": order_id,
                    "courier_id": 99,
                    "order_push_time": t0,
                    "estimate_meal_prepare_time": t0,
                    "estimate_arrived_time": t0 + pd.Timedelta(minutes=deadline),
                    "arrive_time": t0,
                    "_sender_lat": 45.0,
                    "_sender_lng": merchant_lng,
                    "_recipient_lat": 45.0,
                    "_recipient_lng": customer_lng,
                })
        couriers = [{
            "courier_id": 1,
            "start_time": t0,
            "shift_end": t0 + pd.Timedelta(hours=2),
            "start_lat": 45.0,
            "start_lng": 112.0,
        }]
        common = dict(
            speed_kmh=60.0,
            min_travel_minutes=0.0,
            max_active_orders=8,
            candidate_riders=1,
            insertion_position_limit=3,
            enable_high_risk_expansion=False,
            enable_active_rejection=False,
            dispatch_processing_minutes=0.0,
            pickup_service_minutes=0.0,
            delivery_service_minutes=0.0,
            ready_time_buffer_minutes=0.0,
        )
        control = SimulationConfig(**common, enable_route_optimization=False)
        repaired = SimulationConfig(**common, enable_route_optimization=True)
        _, _, control_metrics = GreedyAssignmentRoutingSimulator(control, 60.0).run(
            make_bundle(orders, couriers)
        )
        _, _, repaired_metrics = GreedyAssignmentRoutingSimulator(repaired, 60.0).run(
            make_bundle(orders, couriers)
        )

        self.assertGreaterEqual(
            repaired_metrics["on_time_orders"], control_metrics["on_time_orders"]
        )
        self.assertLess(
            repaired_metrics["total_weighted_objective"],
            control_metrics["total_weighted_objective"],
        )
        self.assertGreater(repaired_metrics["route_optimization_attempts"], 0)
        self.assertGreater(repaired_metrics["route_optimization_improved_routes"], 0)
        self.assertGreater(
            repaired_metrics["route_optimization_projected_objective_reduction"], 0
        )

    def test_nearest_idle_courier_is_selected(self) -> None:
        t0 = pd.Timestamp("2022-10-17 11:00:00")
        orders = [{
            "order_id": 1, "waybill_id": 1, "courier_id": 99,
            "order_push_time": t0, "estimate_meal_prepare_time": t0,
            "estimate_arrived_time": t0 + pd.Timedelta(minutes=30), "arrive_time": t0,
            "_sender_lat": 45.0, "_sender_lng": 112.0,
            "_recipient_lat": 45.0, "_recipient_lng": 112.01,
        }]
        couriers = [
            {"courier_id": 10, "start_time": t0, "shift_end": t0 + pd.Timedelta(hours=1), "start_lat": 45.0, "start_lng": 112.001},
            {"courier_id": 20, "start_time": t0, "shift_end": t0 + pd.Timedelta(hours=1), "start_lat": 45.0, "start_lng": 112.1},
        ]
        results, _, metrics = GreedyAssignmentRoutingSimulator(self.config, 60.0).run(make_bundle(orders, couriers))
        self.assertEqual(results.loc[0, "simulated_courier_id"], 10)
        self.assertTrue(bool(results.loc[0, "on_time"]))
        self.assertEqual(metrics["completion_rate"], 1.0)
        expected_pickup_minutes = (
            results.loc[0, "simulated_pickup_time"] - results.loc[0, "assignment_time"]
        ).total_seconds() / 60.0
        self.assertAlmostEqual(
            results.loc[0, "assignment_to_pickup_min"], expected_pickup_minutes
        )

    def test_demand_gap_reposition_creates_real_travel_events(self) -> None:
        t0 = pd.Timestamp("2022-10-17 11:00:00")
        orders = []
        for order_id in range(1, 7):
            orders.append({
                "order_id": order_id, "waybill_id": order_id, "courier_id": 99,
                "da_id": "B", "order_push_time": t0,
                "estimate_meal_prepare_time": t0,
                "estimate_arrived_time": t0 + pd.Timedelta(minutes=10), "arrive_time": t0,
                "_sender_lat": 45.0, "_sender_lng": 112.12,
                "_recipient_lat": 45.0, "_recipient_lng": 112.13,
            })
        orders.append({
            "order_id": 7, "waybill_id": 7, "courier_id": 99,
            "da_id": "A", "order_push_time": t0 + pd.Timedelta(minutes=20),
            "estimate_meal_prepare_time": t0 + pd.Timedelta(minutes=20),
            "estimate_arrived_time": t0 + pd.Timedelta(hours=2), "arrive_time": t0,
            "_sender_lat": 45.0, "_sender_lng": 112.0,
            "_recipient_lat": 45.0, "_recipient_lng": 112.01,
        })
        couriers = [
            {"courier_id": courier_id, "start_time": t0,
             "shift_end": t0 + pd.Timedelta(hours=3),
             "start_lat": 45.0, "start_lng": 112.0}
            for courier_id in range(1, 11)
        ]
        config = SimulationConfig(
            speed_kmh=60.0,
            min_travel_minutes=0.0,
            max_active_orders=15,
            dispatch_processing_minutes=0.0,
            pickup_service_minutes=0.0,
            delivery_service_minutes=0.0,
            ready_time_buffer_minutes=0.0,
            reposition_policy="demand_gap_greedy",
            reposition_warmup_minutes=5.0,
            reposition_interval_minutes=5.0,
            reposition_forecast_history_minutes=30.0,
            reposition_forecast_horizon_minutes=15.0,
            reposition_max_distance_km=20.0,
            reposition_max_idle_fraction=0.5,
            reposition_include_soon_free_supply=False,
        )
        simulator = GreedyAssignmentRoutingSimulator(config, 60.0)
        _, courier_summary, metrics = simulator.run(make_bundle(orders, couriers))

        self.assertGreater(metrics["reposition_moves"], 0)
        self.assertGreater(metrics["reposition_distance_km"], 0.0)
        self.assertTrue(bool(simulator.reposition_events["completed"].all()))
        self.assertTrue(
            bool((simulator.reposition_events["target_urgency_multiplier"] > 1.0).all())
        )
        self.assertTrue(
            bool(
                (
                    simulator.reposition_events["estimated_reposition_objective_delta"]
                    < 0.0
                ).all()
            )
        )
        self.assertAlmostEqual(
            metrics["total_distance_km"],
            metrics["service_route_distance_km"] + metrics["reposition_distance_km"],
        )
        self.assertAlmostEqual(
            courier_summary["total_distance_km"].sum(), metrics["total_distance_km"]
        )

    def test_busy_courier_releases_before_second_assignment(self) -> None:
        t0 = pd.Timestamp("2022-10-17 11:00:00")
        common = {
            "courier_id": 99, "_sender_lat": 45.0, "_sender_lng": 112.0,
            "_recipient_lat": 45.0, "_recipient_lng": 112.1, "arrive_time": t0,
        }
        orders = [
            {**common, "order_id": 1, "waybill_id": 1, "order_push_time": t0,
             "estimate_meal_prepare_time": t0, "estimate_arrived_time": t0 + pd.Timedelta(hours=1)},
            {**common, "order_id": 2, "waybill_id": 2, "order_push_time": t0 + pd.Timedelta(minutes=1),
             "estimate_meal_prepare_time": t0, "estimate_arrived_time": t0 + pd.Timedelta(hours=1)},
        ]
        couriers = [{"courier_id": 10, "start_time": t0, "shift_end": t0 + pd.Timedelta(hours=2), "start_lat": 45.0, "start_lng": 112.0}]
        results, _, _ = GreedyAssignmentRoutingSimulator(self.config, 60.0).run(make_bundle(orders, couriers))
        self.assertGreater(results.loc[1, "assignment_time"], t0 + pd.Timedelta(minutes=1))
        self.assertEqual(results["assigned"].sum(), 2)

    def test_unassigned_order_counts_against_overall_rate(self) -> None:
        t0 = pd.Timestamp("2022-10-17 11:00:00")
        orders = [{
            "order_id": 1, "waybill_id": 1, "courier_id": 99,
            "order_push_time": t0, "estimate_meal_prepare_time": t0,
            "estimate_arrived_time": t0 + pd.Timedelta(minutes=30), "arrive_time": t0,
            "_sender_lat": 45.0, "_sender_lng": 112.0,
            "_recipient_lat": 45.0, "_recipient_lng": 112.01,
        }]
        empty_couriers = pd.DataFrame(columns=["courier_id", "start_time", "shift_end", "start_lat", "start_lng"])
        bundle = DataBundle(pd.DataFrame(orders), empty_couriers, pd.DataFrame(), 60.0, 1, 0.0)
        results, _, metrics = GreedyAssignmentRoutingSimulator(self.config, 60.0).run(bundle)
        self.assertFalse(bool(results.loc[0, "assigned"]))
        self.assertEqual(metrics["unassigned_orders"], 1)
        self.assertEqual(metrics["on_time_delivery_rate_overall"], 0.0)

    def test_multi_order_capacity_is_enforced(self) -> None:
        t0 = pd.Timestamp("2022-10-17 11:00:00")
        orders = []
        for order_id in range(1, 4):
            orders.append({
                "order_id": order_id,
                "waybill_id": order_id,
                "courier_id": 99,
                "order_push_time": t0,
                "estimate_meal_prepare_time": t0,
                "estimate_arrived_time": t0 + pd.Timedelta(hours=2),
                "arrive_time": t0,
                "_sender_lat": 45.0,
                "_sender_lng": 112.0,
                "_recipient_lat": 45.0,
                "_recipient_lng": 112.0,
            })
        couriers = [{
            "courier_id": 10,
            "start_time": t0,
            "shift_end": t0 + pd.Timedelta(hours=2),
            "start_lat": 45.0,
            "start_lng": 112.0,
        }]
        config = SimulationConfig(
            speed_kmh=60.0,
            min_travel_minutes=0.0,
            max_active_orders=2,
            candidate_riders=1,
            dispatch_processing_minutes=0.0,
            pickup_service_minutes=0.0,
            delivery_service_minutes=0.0,
            ready_time_buffer_minutes=0.0,
        )
        results, courier_summary, metrics = GreedyAssignmentRoutingSimulator(config, 60.0).run(
            make_bundle(orders, couriers)
        )
        self.assertEqual(results.loc[0, "assignment_time"], t0)
        self.assertEqual(results.loc[1, "assignment_time"], t0)
        self.assertGreater(results.loc[2, "assignment_time"], t0)
        self.assertEqual(int(courier_summary.loc[0, "max_active_orders_observed"]), 2)
        self.assertEqual(metrics["max_active_orders"], 2)

    def test_order_is_rejected_when_best_insertion_exceeds_penalty(self) -> None:
        t0 = pd.Timestamp("2022-10-17 11:00:00")
        orders = [{
            "order_id": 1,
            "waybill_id": 1,
            "courier_id": 99,
            "order_push_time": t0,
            "estimate_meal_prepare_time": t0,
            "estimate_arrived_time": t0 + pd.Timedelta(hours=2),
            "arrive_time": t0,
            "_sender_lat": 45.0,
            "_sender_lng": 112.0,
            "_recipient_lat": 45.0,
            "_recipient_lng": 112.1,
        }]
        couriers = [{
            "courier_id": 10,
            "start_time": t0,
            "shift_end": t0 + pd.Timedelta(hours=2),
            "start_lat": 45.0,
            "start_lng": 112.0,
        }]
        config = SimulationConfig(
            speed_kmh=60.0,
            min_travel_minutes=0.0,
            max_active_orders=1,
            unserved_order_penalty=1.0,
            dispatch_processing_minutes=0.0,
            pickup_service_minutes=0.0,
            delivery_service_minutes=0.0,
            ready_time_buffer_minutes=0.0,
        )
        results, _, metrics = GreedyAssignmentRoutingSimulator(config, 60.0).run(
            make_bundle(orders, couriers)
        )
        self.assertFalse(bool(results.loc[0, "assigned"]))
        self.assertTrue(bool(results.loc[0, "rejected"]))
        self.assertEqual(results.loc[0, "completion_status"], "rejected")
        self.assertGreater(results.loc[0, "best_assignment_score_at_decision"], 1.0)
        self.assertEqual(metrics["rejected_orders"], 1)
        self.assertEqual(metrics["unfinished_orders"], 0)
        self.assertAlmostEqual(metrics["total_weighted_objective"], 1.0)

    def test_weighted_objective_matches_realised_components(self) -> None:
        t0 = pd.Timestamp("2022-10-17 11:00:00")
        orders = [{
            "order_id": 1,
            "waybill_id": 1,
            "courier_id": 99,
            "order_push_time": t0,
            "estimate_meal_prepare_time": t0,
            "estimate_arrived_time": t0 + pd.Timedelta(hours=2),
            "arrive_time": t0,
            "_sender_lat": 45.0,
            "_sender_lng": 112.0,
            "_recipient_lat": 45.0,
            "_recipient_lng": 112.01,
        }]
        couriers = [{
            "courier_id": 10,
            "start_time": t0,
            "shift_end": t0 + pd.Timedelta(hours=2),
            "start_lat": 45.0,
            "start_lng": 112.0,
        }]
        results, _, metrics = GreedyAssignmentRoutingSimulator(self.config, 60.0).run(
            make_bundle(orders, couriers)
        )
        expected = (
            metrics["distance_objective_cost"]
            + metrics["unserved_objective_cost"]
            + metrics["lateness_objective_cost"]
            + metrics["late_order_objective_cost"]
        )
        self.assertTrue(bool(results.loc[0, "completed"]))
        self.assertAlmostEqual(metrics["total_weighted_objective"], expected)

    def test_external_courier_pool_does_not_require_historical_courier_columns(self) -> None:
        t0 = pd.Timestamp("2022-10-17 11:00:00")
        orders = pd.DataFrame([{
            "order_id": 1,
            "order_push_time": t0,
            "estimate_meal_prepare_time": t0,
            "estimate_arrived_time": t0 + pd.Timedelta(minutes=30),
            "arrive_time": t0 + pd.Timedelta(minutes=10),
            "sender_lng_normalized": 112.0,
            "sender_lat_normalized": 45.0,
            "recipient_lng_normalized": 112.01,
            "recipient_lat_normalized": 45.0,
        }])
        couriers = pd.DataFrame([{
            "courier_id": 10,
            "start_lng": 112.0,
            "start_lat": 45.0,
        }])
        with tempfile.TemporaryDirectory() as temp_dir:
            order_path = Path(temp_dir) / "orders.csv"
            courier_path = Path(temp_dir) / "couriers.csv"
            orders.to_csv(order_path, index=False)
            couriers.to_csv(courier_path, index=False)
            config = SimulationConfig(fleet_size=1, speed_kmh=60.0, min_travel_minutes=0.0)
            bundle = load_and_prepare(order_path, config, courier_path=courier_path)

        self.assertEqual(len(bundle.orders), 1)
        self.assertEqual(len(bundle.couriers), 1)
        self.assertEqual(bundle.courier_source, "external_file")
        self.assertNotIn("courier_id", bundle.orders.columns)
        self.assertEqual(bundle.couriers.loc[0, "courier_id"], 10)


if __name__ == "__main__":
    unittest.main()
