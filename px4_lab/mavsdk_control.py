from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

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


def _now() -> float:
    return time.monotonic()


async def connect(system_address: str = "udpin://0.0.0.0:14540", timeout_s: float = 30.0) -> System:
    print(f"[mavsdk] connect({system_address})", flush=True)
    async def _connect_and_wait() -> System:
        drone = System()
        # Starting mavsdk_server is part of the connection deadline. Previously
        # this await sat outside wait_for(), so a server startup problem could
        # leave CI blocked indefinitely before it began watching heartbeats.
        await drone.connect(system_address=system_address)
        async for state in drone.core.connection_state():
            if state.is_connected:
                print("[mavsdk] connected", flush=True)
                return drone
        raise TimeoutError("Connection state stream ended unexpectedly")

    try:
        return await asyncio.wait_for(_connect_and_wait(), timeout=timeout_s)
    except asyncio.TimeoutError as ex:
        raise TimeoutError(
            f"MAVSDK did not connect to PX4 at {system_address} within {timeout_s:.1f}s"
        ) from ex


async def wait_for_global_position(
    drone: System, timeout_s: float = 60.0, stable_s: float = 3.0
) -> None:
    print(f"[mavsdk] wait_for_global_position (stable for {stable_s:.1f}s)...", flush=True)

    async def _wait() -> None:
        healthy_since: Optional[float] = None
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                if healthy_since is None:
                    healthy_since = _now()
                if _now() - healthy_since >= stable_s:
                    print("[mavsdk] global+home position stable", flush=True)
                    return
            else:
                healthy_since = None

    await asyncio.wait_for(_wait(), timeout=timeout_s)


async def arm_with_retry(
    drone: System, timeout_s: float = 35.0, retry_interval_s: float = 2.0
) -> None:
    """Retry transient SITL preflight denials while health checks settle."""
    deadline = _now() + timeout_s
    attempt = 0
    last_exception: Optional[Exception] = None

    while _now() < deadline:
        attempt += 1
        try:
            await asyncio.wait_for(drone.action.arm(), timeout=min(8.0, timeout_s))
            print(f"[mission] armed (attempt {attempt})", flush=True)
            return
        except Exception as ex:
            last_exception = ex
            remaining_s = max(0.0, deadline - _now())
            print(
                f"[mission] arm attempt {attempt} denied; waiting for preflight health "
                f"({remaining_s:.1f}s remaining)",
                flush=True,
            )
            if remaining_s > 0:
                await asyncio.sleep(min(retry_interval_s, remaining_s))

    if last_exception is not None:
        raise last_exception
    raise TimeoutError(f"Arming did not complete within {timeout_s:.1f}s")


async def _get_first_position(drone: System, timeout_s: float = 20.0):
    async def _wait():
        async for pos in drone.telemetry.position():
            return pos

    return await asyncio.wait_for(_wait(), timeout=timeout_s)


async def set_param_best_effort(drone: System, name: str, value: Union[int, float, str, bool]) -> None:
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


async def _cancel_tasks_best_effort(tasks: List[asyncio.Task], timeout_s: float = 2.0) -> None:
    """Cancel tasks and wait briefly; never block forever."""
    for t in tasks:
        t.cancel()

    for t in tasks:
        try:
            await asyncio.wait_for(t, timeout=timeout_s)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception:
            pass


async def _observe_end_condition(drone: System, running_tasks: List[asyncio.Task]) -> None:
    """
    Return when we've seen the vehicle in-air at least once AND then it lands,
    OR when it disarms after being armed (robust fallback).

    IMPORTANT: cancellation of background tasks must be best-effort only,
    otherwise we can hang after landing.
    """
    was_in_air = False
    was_armed = False

    in_air_stream = drone.telemetry.in_air()
    armed_stream = drone.telemetry.armed()

    async def _pump_in_air():
        nonlocal was_in_air
        async for v in in_air_stream:
            if v:
                was_in_air = True
            if was_in_air and not v:
                return "landed"

    async def _pump_armed():
        nonlocal was_armed
        async for v in armed_stream:
            if v:
                was_armed = True
            if was_armed and not v:
                return "disarmed"

    done, pending = await asyncio.wait(
        {asyncio.create_task(_pump_in_air()), asyncio.create_task(_pump_armed())},
        return_when=asyncio.FIRST_COMPLETED,
    )

    # Stop whichever detector didn't win (best effort)
    for t in pending:
        t.cancel()
    for t in pending:
        try:
            await asyncio.wait_for(t, timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception:
            pass

    # Stop background tasks (best effort; do NOT hang here)
    await _cancel_tasks_best_effort(running_tasks, timeout_s=2.0)

    _ = list(done)[0].result()


async def _execute_events(
    drone: System,
    events: List[Event],
    t0_monotonic: float,
    executed: List[Dict[str, Any]],
    exceptions: List[str],
) -> None:
    events_sorted = sorted(events, key=lambda e: e.at_s)
    idx = 0
    try:
        while idx < len(events_sorted):
            await asyncio.sleep(0.1)
            elapsed = _now() - t0_monotonic
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
    except asyncio.CancelledError:
        return


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

    print("[mission] setup params", flush=True)

    # SITL: avoid RC-link-loss action by default
    try:
        await set_param_best_effort(drone, "NAV_RCL_ACT", 0)
    except Exception as ex:
        exceptions.append(f"set NAV_RCL_ACT: {type(ex).__name__}: {ex!s}")

    # Enable failure injection
    try:
        await set_param_best_effort(drone, "SYS_FAILURE_EN", 1)
    except Exception as ex:
        exceptions.append(f"set SYS_FAILURE_EN: {type(ex).__name__}: {ex!s}")

    # Optional: allow arming without GPS in SITL to reduce flakes
    try:
        await set_param_best_effort(drone, "COM_ARM_WO_GPS", 1)
    except Exception as ex:
        exceptions.append(f"set COM_ARM_WO_GPS: {type(ex).__name__}: {ex!s}")

    await wait_for_global_position(drone, timeout_s=min(60.0, timeout_s))

    pos = await _get_first_position(drone, timeout_s=20.0)
    home_lat, home_lon = pos.latitude_deg, pos.longitude_deg

    mission_items = _build_mission_items(home_lat, home_lon, mission)
    mission_plan = MissionPlan(mission_items)

    print("[mission] upload mission", flush=True)
    await asyncio.wait_for(drone.mission.set_return_to_launch_after_mission(True), timeout=10.0)
    await asyncio.wait_for(drone.mission.upload_mission(mission_plan), timeout=20.0)

    print("[mission] arm", flush=True)
    await arm_with_retry(drone, timeout_s=min(35.0, max(15.0, timeout_s / 4.0)))

    print("[mission] takeoff", flush=True)
    await asyncio.wait_for(drone.action.takeoff(), timeout=20.0)

    await asyncio.sleep(3.0)

    print("[mission] start_mission", flush=True)
    await asyncio.wait_for(drone.mission.start_mission(), timeout=20.0)
    mission_started = True

    t0 = _now()
    progress_task = asyncio.create_task(_print_mission_progress(drone))
    events_task = asyncio.create_task(_execute_events(drone, events, t0, executed_events, exceptions))
    termination_task = asyncio.create_task(_observe_end_condition(drone, [progress_task, events_task]))

    try:
        await asyncio.wait_for(termination_task, timeout=timeout_s)
        landed = True
    except asyncio.TimeoutError:
        timeout = True
        exceptions.append("mission timeout")
        try:
            print("[mission] timeout -> RTL", flush=True)
            await asyncio.wait_for(drone.action.return_to_launch(), timeout=10.0)
        except Exception as ex:
            exceptions.append(f"RTL after timeout: {type(ex).__name__}: {ex!s}")

    # Best-effort mission finished: bounded wait to avoid hanging forever
    try:
        async def _one_progress():
            async for mp in drone.mission.mission_progress():
                return mp

        mp = await asyncio.wait_for(_one_progress(), timeout=2.0)
        mission_finished = (mp.current == mp.total)
    except Exception:
        # If we already detected landing, treat as finished for reporting
        if landed:
            mission_finished = True

    # Best-effort disarm
    try:
        await asyncio.wait_for(drone.action.disarm(), timeout=10.0)
    except Exception:
        pass

    # Ensure background tasks don't hang us
    await _cancel_tasks_best_effort([progress_task, events_task], timeout_s=2.0)

    print("[mission] done", flush=True)

    return FlightOutcome(
        mission_started=mission_started,
        mission_finished=mission_finished,
        landed=landed,
        timeout=timeout,
        exceptions=exceptions,
        executed_events=executed_events,
    )


async def _print_mission_progress(drone: System) -> None:
    try:
        async for _ in drone.mission.mission_progress():
            await asyncio.sleep(0)
    except asyncio.CancelledError:
        return
    except Exception:
        return
