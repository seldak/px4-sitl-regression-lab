from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan
from mavsdk.failure import FailureUnit, FailureType

from .geo import add_ned_offset_to_gps
from .scenario import Event, EventInjectFailure, EventSetParam, MissionConfig


@dataclass
class FlightOutcome:
    mission_started: bool
    mission_finished: bool
    landed: bool
    timeout: bool
    exceptions: List[str]
    executed_events: List[Dict[str, Any]]


async def connect(system_address: str = "udpin://0.0.0.0:14540", timeout_s: float = 30.0) -> System:
    drone = System()
    await drone.connect(system_address=system_address)

    t0 = time.monotonic()
    async for state in drone.core.connection_state():
        if state.is_connected:
            return drone
        if time.monotonic() - t0 > timeout_s:
            raise TimeoutError(f"Timed out waiting for MAVSDK connection on {system_address}")

    raise TimeoutError("Connection state stream ended unexpectedly")


async def wait_for_global_position(drone: System, timeout_s: float = 60.0) -> None:
    t0 = time.monotonic()
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            return
        if time.monotonic() - t0 > timeout_s:
            raise TimeoutError("Timed out waiting for global/home position estimate")


async def set_param_best_effort(drone: System, name: str, value: Union[int, float, str]) -> None:
    # MAVSDK is strongly typed; PX4 params are strongly typed too.
    # We try the most likely setter first, but fall back if needed.
    if isinstance(value, bool):
        await drone.param.set_param_int(name, int(value))
        return

    if isinstance(value, int):
        try:
            await drone.param.set_param_int(name, value)
            return
        except Exception:
            await drone.param.set_param_float(name, float(value))
            return

    if isinstance(value, float):
        try:
            await drone.param.set_param_float(name, float(value))
            return
        except Exception:
            await drone.param.set_param_int(name, int(value))
            return

    await drone.param.set_param_custom(name, str(value))


def _map_failure_unit(unit: str) -> FailureUnit:
    u = unit.strip().lower()
    mapping = {
        "gyro": FailureUnit.SENSOR_GYRO,
        "accel": FailureUnit.SENSOR_ACCEL,
        "mag": FailureUnit.SENSOR_MAG,
        "baro": FailureUnit.SENSOR_BARO,
        "gps": FailureUnit.SENSOR_GPS,
        "optical_flow": FailureUnit.SENSOR_OPTICAL_FLOW,
        "vio": FailureUnit.SENSOR_VIO,
        "distance_sensor": FailureUnit.SENSOR_DISTANCE_SENSOR,
        "airspeed": FailureUnit.SENSOR_AIRSPEED,
        "battery": FailureUnit.SYSTEM_BATTERY,
        "motor": FailureUnit.SYSTEM_MOTOR,
        "servo": FailureUnit.SYSTEM_SERVO,
        "avoidance": FailureUnit.SYSTEM_AVOIDANCE,
        "rc_signal": FailureUnit.SYSTEM_RC_SIGNAL,
        "mavlink_signal": FailureUnit.SYSTEM_MAVLINK_SIGNAL,
    }
    if u not in mapping:
        raise ValueError(f"Unknown failure unit: {unit!r}. Supported: {sorted(mapping.keys())}")
    return mapping[u]


def _map_failure_type(failure: str) -> FailureType:
    f = failure.strip().lower()
    mapping = {
        "ok": FailureType.OK,
        "off": FailureType.OFF,
        "stuck": FailureType.STUCK,
        "garbage": FailureType.GARBAGE,
        "wrong": FailureType.WRONG,
        "slow": FailureType.SLOW,
        "delayed": FailureType.DELAYED,
        "intermittent": FailureType.INTERMITTENT,
    }
    if f not in mapping:
        raise ValueError(f"Unknown failure type: {failure!r}. Supported: {sorted(mapping.keys())}")
    return mapping[f]


def _build_mission_items(home_lat: float, home_lon: float, mission: MissionConfig) -> List[MissionItem]:
    items: List[MissionItem] = []

    for (north_m, east_m, alt_m) in mission.relative_waypoints_m:
        lat, lon = add_ned_offset_to_gps(home_lat, home_lon, north_m, east_m)
        items.append(
            MissionItem(
                lat,
                lon,
                float(alt_m),
                float(mission.cruise_speed_m_s),
                True,  # fly-through
                float("nan"),  # gimbal pitch
                float("nan"),  # gimbal yaw
                MissionItem.CameraAction.NONE,
                float("nan"),  # loiter time
                float("nan"),  # photo interval
                float("nan"),  # acceptance radius
                float("nan"),  # yaw
                float("nan"),  # photo distance
                MissionItem.VehicleAction.NONE,
            )
        )

    return items


async def _observe_is_in_air(drone: System, running_tasks: List[asyncio.Task]) -> None:
    """Returns after the vehicle has flown and then landed."""
    was_in_air = False
    async for is_in_air in drone.telemetry.in_air():
        if is_in_air:
            was_in_air = True
        if was_in_air and not is_in_air:
            for t in running_tasks:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
            return


async def _execute_events(
    drone: System,
    events: List[Event],
    t0_monotonic: float,
    executed: List[Dict[str, Any]],
    exceptions: List[str],
) -> None:
    events_sorted = sorted(events, key=lambda e: e.at_s)
    idx = 0

    while idx < len(events_sorted):
        await asyncio.sleep(0.1)
        elapsed = time.monotonic() - t0_monotonic
        if elapsed < events_sorted[idx].at_s:
            continue

        e = events_sorted[idx]
        idx += 1

        try:
            if isinstance(e, EventSetParam):
                await set_param_best_effort(drone, e.name, e.value)
                executed.append({"type": "set_param", "at_s": e.at_s, "name": e.name, "value": e.value})
            elif isinstance(e, EventInjectFailure):
                unit = _map_failure_unit(e.unit)
                ftype = _map_failure_type(e.failure)
                await drone.failure.inject(unit, ftype, int(e.instance))
                executed.append(
                    {"type": "inject_failure", "at_s": e.at_s, "unit": e.unit, "failure": e.failure, "instance": e.instance}
                )
            else:
                raise RuntimeError(f"Unknown event: {e}")
        except Exception as ex:
            exceptions.append(f"event@{e.at_s}s {e}: {type(ex).__name__}: {ex!s}")


async def run_mission_with_events(
    drone: System,
    mission: MissionConfig,
    events: List[Event],
    timeout_s: float,
) -> FlightOutcome:
    exceptions: List[str] = []
    executed_events: List[Dict[str, Any]] = []
    mission_started = False
    mission_finished = False
    landed = False
    timeout = False

    # Disable RC-link-loss action by default (many SITL setups have no RC),
    # while keeping MAVLink present through MAVSDK.
    try:
        await set_param_best_effort(drone, "NAV_RCL_ACT", 0)
    except Exception as ex:
        exceptions.append(f"set NAV_RCL_ACT: {type(ex).__name__}: {ex!s}")

    # Enable failure injection (needed for gps_failure scenario).
    try:
        await set_param_best_effort(drone, "SYS_FAILURE_EN", 1)
    except Exception as ex:
        exceptions.append(f"set SYS_FAILURE_EN: {type(ex).__name__}: {ex!s}")

    await wait_for_global_position(drone)

    # Home is simply the first reliable global position.
    async for pos in drone.telemetry.position():
        home_lat = pos.latitude_deg
        home_lon = pos.longitude_deg
        break

    mission_items = _build_mission_items(home_lat, home_lon, mission)
    mission_plan = MissionPlan(mission_items)

    await drone.mission.set_return_to_launch_after_mission(True)
    await drone.mission.upload_mission(mission_plan)

    # Takeoff is handled by Action; the mission items are just waypoints.
    await drone.action.arm()
    await drone.action.takeoff()

    # Give it a second to clear the ground.
    await asyncio.sleep(3.0)

    await drone.mission.start_mission()
    mission_started = True

    # Background: observe landing and execute scheduled events.
    t0 = time.monotonic()
    progress_task = asyncio.create_task(_print_mission_progress(drone))
    events_task = asyncio.create_task(_execute_events(drone, events, t0, executed_events, exceptions))
    termination_task = asyncio.create_task(_observe_is_in_air(drone, [progress_task, events_task]))

    try:
        await asyncio.wait_for(termination_task, timeout=timeout_s)
        landed = True
    except asyncio.TimeoutError:
        timeout = True
        # Try to recover gracefully.
        try:
            await drone.action.return_to_launch()
        except Exception as ex:
            exceptions.append(f"RTL after timeout: {type(ex).__name__}: {ex!s}")

    # Determine whether mission finished (best effort).
    try:
        async for mp in drone.mission.mission_progress():
            mission_finished = (mp.current == mp.total)
            break
    except Exception:
        pass

    # Ensure vehicle is disarmed (best effort).
    try:
        await drone.action.disarm()
    except Exception:
        pass

    # Cancel background tasks.
    for t in [progress_task, events_task]:
        if not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    return FlightOutcome(
        mission_started=mission_started,
        mission_finished=mission_finished,
        landed=landed,
        timeout=timeout,
        exceptions=exceptions,
        executed_events=executed_events,
    )


async def _print_mission_progress(drone: System) -> None:
    async for mission_progress in drone.mission.mission_progress():
        # Intentionally minimal output (CI-friendly).
        # Consumers can parse run_metadata.json for details.
        _ = mission_progress
        await asyncio.sleep(0)
