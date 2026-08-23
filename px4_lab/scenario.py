from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml


@dataclass(frozen=True)
class PX4Config:
    tag: str = "v1.16.1"
    remote: str = "https://github.com/PX4/PX4-Autopilot.git"


@dataclass(frozen=True)
class MissionConfig:
    takeoff_alt_m: float
    cruise_speed_m_s: float
    relative_waypoints_m: List[Tuple[float, float, float]]  # (north, east, alt)


@dataclass(frozen=True)
class EventSetParam:
    at_s: float
    name: str
    value: Union[int, float, str]


@dataclass(frozen=True)
class EventInjectFailure:
    at_s: float
    unit: str  # e.g. "gps", "rc_signal"
    failure: str  # "off", "ok", "stuck", "garbage", ...
    instance: int = 0


Event = Union[EventSetParam, EventInjectFailure]


@dataclass(frozen=True)
class Thresholds:
    timeout_s: float
    max_horiz_error_m: float
    rms_horiz_error_m: float
    max_speed_m_s: float
    max_tilt_deg: float
    min_flight_time_s: float = 10.0
    min_waypoint_completion_ratio: float = 0.0
    waypoint_radius_m: float = 8.0
    min_window_samples: int = 100
    require_mission_finished: bool = False


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    px4: PX4Config
    mission: MissionConfig
    events: List[Event]
    thresholds: Thresholds


def _require(d: Dict[str, Any], key: str) -> Any:
    if key not in d:
        raise ValueError(f"Missing required key: {key}")
    return d[key]


def load_scenario(path: str) -> Scenario:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    name = str(_require(raw, "name"))
    description = str(raw.get("description", ""))

    px4_raw = raw.get("px4", {}) or {}
    px4 = PX4Config(
        tag=str(px4_raw.get("tag", "v1.16.1")),
        remote=str(px4_raw.get("remote", "https://github.com/PX4/PX4-Autopilot.git")),
    )

    mission_raw = _require(raw, "mission")
    wps = []
    for item in _require(mission_raw, "relative_waypoints_m"):
        if not (isinstance(item, (list, tuple)) and len(item) == 3):
            raise ValueError("Each waypoint must be [north_m, east_m, alt_m]")
        wps.append((float(item[0]), float(item[1]), float(item[2])))

    mission = MissionConfig(
        takeoff_alt_m=float(_require(mission_raw, "takeoff_alt_m")),
        cruise_speed_m_s=float(_require(mission_raw, "cruise_speed_m_s")),
        relative_waypoints_m=wps,
    )

    events: List[Event] = []
    for e in raw.get("events", []) or []:
        etype = str(_require(e, "type"))
        at_s = float(_require(e, "at_s"))
        if etype == "set_param":
            events.append(EventSetParam(at_s=at_s, name=str(_require(e, "name")), value=_require(e, "value")))
        elif etype == "inject_failure":
            events.append(
                EventInjectFailure(
                    at_s=at_s,
                    unit=str(_require(e, "unit")),
                    failure=str(_require(e, "failure")),
                    instance=int(e.get("instance", 0)),
                )
            )
        else:
            raise ValueError(f"Unknown event type: {etype}")

    thr_raw = _require(raw, "thresholds")
    thresholds = Thresholds(
        timeout_s=float(_require(thr_raw, "timeout_s")),
        max_horiz_error_m=float(_require(thr_raw, "max_horiz_error_m")),
        rms_horiz_error_m=float(_require(thr_raw, "rms_horiz_error_m")),
        max_speed_m_s=float(_require(thr_raw, "max_speed_m_s")),
        max_tilt_deg=float(_require(thr_raw, "max_tilt_deg")),
        min_flight_time_s=float(thr_raw.get("min_flight_time_s", 10.0)),
        min_waypoint_completion_ratio=float(
            thr_raw.get("min_waypoint_completion_ratio", 0.0)
        ),
        waypoint_radius_m=float(thr_raw.get("waypoint_radius_m", 8.0)),
        min_window_samples=int(thr_raw.get("min_window_samples", 100)),
        require_mission_finished=bool(thr_raw.get("require_mission_finished", False)),
    )
    if thresholds.min_flight_time_s < 0:
        raise ValueError("thresholds.min_flight_time_s must be >= 0")
    if not 0.0 <= thresholds.min_waypoint_completion_ratio <= 1.0:
        raise ValueError("thresholds.min_waypoint_completion_ratio must be between 0 and 1")
    if thresholds.waypoint_radius_m <= 0:
        raise ValueError("thresholds.waypoint_radius_m must be > 0")
    if thresholds.min_window_samples < 2:
        raise ValueError("thresholds.min_window_samples must be >= 2")

    return Scenario(
        name=name,
        description=description,
        px4=px4,
        mission=mission,
        events=events,
        thresholds=thresholds,
    )
