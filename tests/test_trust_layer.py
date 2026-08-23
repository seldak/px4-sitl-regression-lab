from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from px4_lab.mavsdk_control import arm_with_retry
from px4_lab.metrics.extract import (
    _horizontal_error_series,
    select_flight_window,
    write_plots,
)
from px4_lab.metrics.report import evaluate
from px4_lab.scenario import MissionConfig, PX4Config, Scenario, Thresholds


class FakeDataset:
    def __init__(self, name: str, data: dict[str, np.ndarray]):
        self.name = name
        self.data = data


class FakeULog:
    def __init__(self, datasets: list[FakeDataset], start_us: int, end_us: int):
        self.data_list = datasets
        self.start_timestamp = start_us
        self.last_timestamp = end_us


def make_vpos_ulog(include_flight: bool = True, include_init_spike: bool = False) -> FakeULog:
    timestamp_us = np.arange(0, 101, 0.1) * 1e6
    speed = np.zeros_like(timestamp_us, dtype=np.float64)
    z = np.zeros_like(timestamp_us, dtype=np.float64)
    if include_init_spike:
        speed[(timestamp_us >= 5e6) & (timestamp_us <= 5.3e6)] = 3.0
    if include_flight:
        airborne = (timestamp_us >= 20e6) & (timestamp_us <= 80e6)
        speed[airborne] = 5.0
        z[airborne] = -10.0
    return FakeULog(
        [
            FakeDataset(
                "vehicle_local_position",
                {
                    "timestamp": timestamp_us.astype(np.int64),
                    "vx": speed,
                    "vy": np.zeros_like(speed),
                    "vz": np.zeros_like(speed),
                    "z": z,
                },
            )
        ],
        0,
        int(100e6),
    )


def baseline_scenario() -> Scenario:
    return Scenario(
        name="baseline",
        description="test",
        px4=PX4Config(),
        mission=MissionConfig(10.0, 5.0, [(40.0, 0.0, 10.0)]),
        events=[],
        thresholds=Thresholds(
            timeout_s=180.0,
            max_horiz_error_m=6.0,
            rms_horiz_error_m=3.0,
            max_speed_m_s=18.0,
            max_tilt_deg=60.0,
            min_flight_time_s=30.0,
            min_waypoint_completion_ratio=0.75,
            waypoint_radius_m=8.0,
            min_window_samples=100,
            require_mission_finished=True,
        ),
    )


class FlightWindowTests(unittest.TestCase):
    def test_kinematic_window_includes_full_flight_with_padding(self) -> None:
        window = select_flight_window(make_vpos_ulog())
        self.assertTrue(window.trusted)
        self.assertEqual(window.source, "debounced_kinematic")
        self.assertAlmostEqual(window.start_us / 1e6, 18.0, delta=0.2)
        self.assertAlmostEqual(window.end_us / 1e6, 82.0, delta=0.2)
        self.assertGreater(window.sample_count, 600)

    def test_short_initial_movement_spike_is_rejected(self) -> None:
        window = select_flight_window(make_vpos_ulog(include_init_spike=True))
        self.assertGreaterEqual(window.start_us, int(17.8e6))
        self.assertTrue(any("sustained_active_regions=1" in item for item in window.diagnostics))

    def test_whole_log_fallback_is_untrusted(self) -> None:
        window = select_flight_window(make_vpos_ulog(include_flight=False))
        self.assertFalse(window.trusted)
        self.assertEqual(window.source, "full_log_fallback")

    def test_incomplete_setpoints_fall_back_for_the_entire_error_series(self) -> None:
        timestamp_us = np.array([0, 1_000_000, 2_000_000], dtype=np.int64)
        setpoint = FakeDataset(
            "vehicle_local_position_setpoint",
            {
                "timestamp": timestamp_us,
                "x": np.array([0.0, np.nan, 2.0]),
                "y": np.array([0.0, np.nan, 0.0]),
            },
        )
        error, source = _horizontal_error_series(
            np.array([0.0, 1.0, 2.0]),
            np.zeros(3),
            timestamp_us,
            setpoint,
            np.array([[0.0, 0.0], [2.0, 0.0]]),
        )
        self.assertEqual(source, "planned_path_polyline")
        np.testing.assert_allclose(error, np.zeros(3))


class TrustGateTests(unittest.TestCase):
    def good_metrics(self) -> dict:
        return {
            "flight_window": {
                "source": "debounced_kinematic",
                "trusted": True,
                "sample_count": 1000,
            },
            "flight_time_s": 65.0,
            "max_horiz_error_m": 1.0,
            "rms_horiz_error_m": 0.2,
            "max_speed_m_s": 5.2,
            "max_tilt_deg": 20.0,
            "mission_waypoint_min_distances_m": [1.0, 2.0, 2.0, 1.0],
        }

    def good_outcome(self) -> dict:
        return {
            "mission_started": True,
            "mission_finished": True,
            "landed": True,
            "timeout": False,
            "exceptions": [],
            "executed_events": [],
        }

    def test_complete_run_passes_trust_gates(self) -> None:
        passed, failures = evaluate(
            self.good_metrics(), baseline_scenario(), self.good_outcome()
        )
        self.assertTrue(passed, failures)

    def test_fragment_cannot_pass_on_good_performance_metrics(self) -> None:
        metrics = self.good_metrics()
        metrics["flight_time_s"] = 22.0
        metrics["flight_window"]["sample_count"] = 41
        metrics["mission_waypoint_min_distances_m"] = [1.0, 30.0, 45.0, 35.0]
        passed, failures = evaluate(metrics, baseline_scenario(), self.good_outcome())
        self.assertFalse(passed)
        self.assertTrue(any("flight_time_s" in failure for failure in failures))
        self.assertTrue(any("sample_count" in failure for failure in failures))
        self.assertTrue(any("waypoint_completion_ratio" in failure for failure in failures))

    def test_runtime_failure_overrides_good_metrics(self) -> None:
        outcome = self.good_outcome()
        outcome["landed"] = False
        outcome["exceptions"] = ["event failed"]
        passed, failures = evaluate(self.good_metrics(), baseline_scenario(), outcome)
        self.assertFalse(passed)
        self.assertTrue(any("landing" in failure for failure in failures))
        self.assertTrue(any("exception" in failure for failure in failures))

    def test_untrusted_window_does_not_generate_flight_plots(self) -> None:
        plots = write_plots(
            Path("does-not-need-to-exist.ulg"),
            Path("/tmp/unused-trust-plots"),
            {"trusted": False, "source": "full_log_fallback"},
        )
        self.assertEqual(plots, {})


class ArmRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_arm_denials_are_retried(self) -> None:
        class FakeAction:
            def __init__(self) -> None:
                self.attempts = 0

            async def arm(self) -> None:
                self.attempts += 1
                if self.attempts < 3:
                    raise RuntimeError("COMMAND_DENIED")

        class FakeDrone:
            def __init__(self) -> None:
                self.action = FakeAction()

        drone = FakeDrone()
        await arm_with_retry(drone, timeout_s=1.0, retry_interval_s=0.001)
        self.assertEqual(drone.action.attempts, 3)


if __name__ == "__main__":
    unittest.main()
