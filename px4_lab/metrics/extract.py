from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

import matplotlib.pyplot as plt
import numpy as np

if TYPE_CHECKING:
    from pyulog import ULog
else:
    ULog = Any


def _load_run_metadata(ulog_path: Path) -> dict[str, Any]:
    md_path = ulog_path.parent / "run_metadata.json"
    if not md_path.exists():
        return {}
    try:
        return json.loads(md_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_planned_path_xy(ulog_path: Path):
    md = _load_run_metadata(ulog_path)
    pts = md.get("planned_path_xy")
    if not pts or len(pts) < 2:
        return None
    arr = np.array(pts, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2:
        return None
    return arr


def _load_mission_waypoints_xy(ulog_path: Path) -> Optional[np.ndarray]:
    pts = _load_run_metadata(ulog_path).get("planned_waypoints_m")
    if not pts:
        return None
    arr = np.array(pts, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] < 2:
        return None
    return arr[:, :2]

def _point_to_segment_dist(px, py, ax, ay, bx, by):
    # distance from point P to segment AB (vectorized over points P)
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    denom = abx*abx + aby*aby
    # handle degenerate segments
    denom = np.where(denom == 0.0, 1e-12, denom)
    t = (apx*abx + apy*aby) / denom
    t = np.clip(t, 0.0, 1.0)
    cx = ax + t*abx
    cy = ay + t*aby
    dx = px - cx
    dy = py - cy
    return np.sqrt(dx*dx + dy*dy)

def _polyline_distance(px, py, path_xy: np.ndarray) -> np.ndarray:
    # For each point (px,py), compute min distance to any segment in the polyline
    # path_xy shape: (M,2), segments are (i -> i+1)
    mins = np.full_like(px, np.inf, dtype=np.float64)
    for i in range(len(path_xy) - 1):
        ax, ay = path_xy[i]
        bx, by = path_xy[i + 1]
        d = _point_to_segment_dist(px, py, ax, ay, bx, by)
        mins = np.minimum(mins, d)
    return mins

def _get_dataset(ulog: ULog, name: str):
    for d in ulog.data_list:
        if d.name == name:
            return d
    return None


@dataclass(frozen=True)
class FlightWindow:
    start_us: int
    end_us: int
    source: str
    sample_count: int
    log_fraction: float
    trusted: bool
    diagnostics: list[str]

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.end_us - self.start_us) / 1e6)


def _true_runs(timestamp_us: np.ndarray, mask: np.ndarray, min_duration_s: float) -> list[tuple[int, int]]:
    """Return inclusive index ranges that remain true for at least min_duration_s."""
    if len(mask) == 0:
        return []
    changes = np.flatnonzero(np.diff(mask.astype(np.int8)) != 0) + 1
    starts = np.r_[0, changes]
    ends = np.r_[changes - 1, len(mask) - 1]
    runs: list[tuple[int, int]] = []
    for start, end in zip(starts, ends):
        if not mask[start]:
            continue
        duration_s = (int(timestamp_us[end]) - int(timestamp_us[start])) / 1e6
        if duration_s >= min_duration_s:
            runs.append((int(start), int(end)))
    return runs


def _bridge_short_false_gaps(
    timestamp_us: np.ndarray, mask: np.ndarray, max_gap_s: float
) -> np.ndarray:
    """Fill brief inactive gaps between active regions, preserving leading/trailing idle."""
    result = mask.astype(bool).copy()
    if len(result) < 3:
        return result
    false_runs = _true_runs(timestamp_us, ~result, 0.0)
    for start, end in false_runs:
        if start == 0 or end == len(result) - 1:
            continue
        duration_s = (int(timestamp_us[end]) - int(timestamp_us[start])) / 1e6
        if duration_s <= max_gap_s:
            result[start : end + 1] = True
    return result


def _window_sample_count(ulog: ULog, start_us: int, end_us: int) -> int:
    vpos = _get_dataset(ulog, "vehicle_local_position")
    if vpos is None or "timestamp" not in vpos.data:
        return 0
    timestamp_us = vpos.data["timestamp"].astype(np.int64)
    return int(np.count_nonzero((timestamp_us >= start_us) & (timestamp_us <= end_us)))


def _make_window(
    ulog: ULog,
    start_us: int,
    end_us: int,
    source: str,
    trusted: bool,
    diagnostics: list[str],
) -> FlightWindow:
    log_duration_us = max(1, int(ulog.last_timestamp) - int(ulog.start_timestamp))
    start_us = max(int(ulog.start_timestamp), int(start_us))
    end_us = min(int(ulog.last_timestamp), int(end_us))
    return FlightWindow(
        start_us=start_us,
        end_us=end_us,
        source=source,
        sample_count=_window_sample_count(ulog, start_us, end_us),
        log_fraction=float(max(0, end_us - start_us) / log_duration_us),
        trusted=trusted,
        diagnostics=diagnostics,
    )


def select_flight_window(ulog: ULog) -> FlightWindow:
    """Select a defensible flight window and retain evidence about fallbacks.

    High-rate local-position movement and altitude are authoritative. Sparse nav-state
    samples are useful diagnostics, but cannot define the scored window by themselves.
    """
    diagnostics: list[str] = []
    vehicle_status = _get_dataset(ulog, "vehicle_status")
    if vehicle_status is not None and all(
        key in vehicle_status.data for key in ("timestamp", "nav_state")
    ):
        nav_timestamp_us = vehicle_status.data["timestamp"].astype(np.int64)
        nav_state = vehicle_status.data["nav_state"].astype(np.int64)
        mission_indices = np.flatnonzero(nav_state == 5)
        if len(mission_indices):
            mission_span_s = (
                int(nav_timestamp_us[mission_indices[-1]])
                - int(nav_timestamp_us[mission_indices[0]])
            ) / 1e6
            diagnostics.append(
                f"auto_mission_samples={len(mission_indices)}, span_s={mission_span_s:.3f}"
            )

    vpos = _get_dataset(ulog, "vehicle_local_position")
    if vpos is not None and all(k in vpos.data for k in ("timestamp", "vx", "vy", "vz")):
        timestamp_us = vpos.data["timestamp"].astype(np.int64)
        vx = vpos.data["vx"].astype(np.float64)
        vy = vpos.data["vy"].astype(np.float64)
        vz = vpos.data["vz"].astype(np.float64)
        speed = np.sqrt(vx * vx + vy * vy + vz * vz)
        active = np.isfinite(speed) & (speed > 0.5)

        source = "debounced_speed"
        if "z" in vpos.data and len(timestamp_us):
            z = vpos.data["z"].astype(np.float64)
            ground_end_us = int(timestamp_us[0]) + int(5e6)
            ground_samples = z[(timestamp_us <= ground_end_us) & np.isfinite(z)]
            if len(ground_samples):
                ground_z = float(np.median(ground_samples))
                airborne = np.isfinite(z) & (np.abs(z - ground_z) > 0.75)
                active |= airborne
                source = "debounced_kinematic"
                diagnostics.append(f"ground_z_m={ground_z:.3f}")

        active = _bridge_short_false_gaps(timestamp_us, active, max_gap_s=3.0)
        runs = _true_runs(timestamp_us, active, min_duration_s=1.0)
        if runs:
            first_start = runs[0][0]
            last_end = runs[-1][1]
            start_us = int(timestamp_us[first_start]) - int(2e6)
            end_us = int(timestamp_us[last_end]) + int(2e6)
            diagnostics.append(f"sustained_active_regions={len(runs)}")
            return _make_window(ulog, start_us, end_us, source, True, diagnostics)
        diagnostics.append("kinematic candidate rejected: no sustained activity")
    else:
        diagnostics.append("kinematic candidate unavailable: velocity topic/fields missing")

    # A debounced landed transition is a lower-confidence but usable fallback.
    ld = _get_dataset(ulog, "vehicle_land_detected")
    if ld is not None and all(k in ld.data for k in ("timestamp", "landed")):
        timestamp_us = ld.data["timestamp"].astype(np.int64)
        landed = ld.data["landed"].astype(np.int64)
        airborne_runs = _true_runs(timestamp_us, landed == 0, min_duration_s=2.0)
        if airborne_runs:
            start_idx, end_idx = airborne_runs[0][0], airborne_runs[-1][1]
            diagnostics.append(f"sustained_airborne_regions={len(airborne_runs)}")
            return _make_window(
                ulog,
                int(timestamp_us[start_idx]) - int(2e6),
                int(timestamp_us[end_idx]) + int(2e6),
                "debounced_land_detector",
                True,
                diagnostics,
            )
        diagnostics.append("land-detector candidate rejected: no sustained airborne state")
    else:
        diagnostics.append("land-detector candidate unavailable")

    diagnostics.append("untrusted fallback: whole ULog selected")
    return _make_window(
        ulog,
        int(ulog.start_timestamp),
        int(ulog.last_timestamp),
        "full_log_fallback",
        False,
        diagnostics,
    )


def _flight_time_window_us(ulog: ULog) -> tuple[int, int]:
    """Compatibility wrapper for callers that only need window boundaries."""
    window = select_flight_window(ulog)
    return window.start_us, window.end_us

def _interp_nearest(ts_src: np.ndarray, val_src: np.ndarray, ts_query: np.ndarray) -> np.ndarray:
    # Nearest-neighbor interpolation based on timestamps.
    idx = np.searchsorted(ts_src, ts_query, side="left")
    idx = np.clip(idx, 0, len(ts_src) - 1)
    # Compare left neighbor where possible.
    left = np.clip(idx - 1, 0, len(ts_src) - 1)
    choose_left = np.abs(ts_query - ts_src[left]) < np.abs(ts_query - ts_src[idx])
    idx = np.where(choose_left, left, idx)
    return val_src[idx]


def _quat_to_roll_pitch_deg(q0: np.ndarray, q1: np.ndarray, q2: np.ndarray, q3: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # PX4 uses quaternion [w, x, y, z]
    # roll (x-axis rotation)
    sinr_cosp = 2 * (q0 * q1 + q2 * q3)
    cosr_cosp = 1 - 2 * (q1 * q1 + q2 * q2)
    roll = np.arctan2(sinr_cosp, cosr_cosp)

    # pitch (y-axis rotation)
    sinp = 2 * (q0 * q2 - q3 * q1)
    sinp = np.clip(sinp, -1.0, 1.0)
    pitch = np.arcsin(sinp)

    return np.degrees(roll), np.degrees(pitch)


def _select_setpoint_dataset(ulog: ULog):
    """
    Choose a setpoint dataset that actually contains timestamp/x/y.
    Preference:
      1) vehicle_local_position_setpoint
      2) trajectory_setpoint
    """
    sp = _get_dataset(ulog, "vehicle_local_position_setpoint")
    if sp is not None and "timestamp" in sp.data and "x" in sp.data and "y" in sp.data:
        return sp

    sp = _get_dataset(ulog, "trajectory_setpoint")
    if sp is not None and "timestamp" in sp.data and "x" in sp.data and "y" in sp.data:
        return sp

    return None


def _horizontal_error_series(
    x: np.ndarray,
    y: np.ndarray,
    timestamp_us: np.ndarray,
    setpoint: Any,
    planned: Optional[np.ndarray],
    preferred_source: Optional[str] = None,
) -> tuple[np.ndarray, str]:
    """Return one complete error series and its provenance.

    A partially populated setpoint topic is not suitable for gating. If any selected
    setpoint is non-finite, use the planned-path fallback for the entire window.
    """
    allow_setpoint = preferred_source not in ("planned_path_polyline", "missing")
    if allow_setpoint and setpoint is not None:
        tsp = setpoint.data["timestamp"].astype(np.int64)
        xsp = _interp_nearest(tsp, setpoint.data["x"].astype(np.float64), timestamp_us)
        ysp = _interp_nearest(tsp, setpoint.data["y"].astype(np.float64), timestamp_us)
        error = np.hypot(x - xsp, y - ysp)
        if len(error) and np.all(np.isfinite(error)):
            return error, setpoint.name

    if planned is not None and len(x) and len(y):
        error = _polyline_distance(x, y, planned)
        if len(error) and np.all(np.isfinite(error)):
            return error, "planned_path_polyline"

    return np.array([]), "missing"


def extract_metrics(ulog_path: Path) -> Dict[str, Any]:
    from pyulog import ULog

    ulog = ULog(str(ulog_path))

    window = select_flight_window(ulog)
    t_start, t_end = window.start_us, window.end_us

    vpos = _get_dataset(ulog, "vehicle_local_position")
    if vpos is None:
        raise RuntimeError("ULog is missing vehicle_local_position")

    t = vpos.data["timestamp"].astype(np.int64)
    mask = (t >= t_start) & (t <= t_end)

    x = vpos.data.get("x", np.array([]))[mask].astype(np.float64)
    y = vpos.data.get("y", np.array([]))[mask].astype(np.float64)
    z = vpos.data.get("z", np.array([]))[mask].astype(np.float64)
    vx = vpos.data.get("vx", np.array([]))[mask].astype(np.float64)
    vy = vpos.data.get("vy", np.array([]))[mask].astype(np.float64)
    vz = vpos.data.get("vz", np.array([]))[mask].astype(np.float64)

    t_f = t[mask]
    if len(t_f) < 2:
        raise RuntimeError(
            f"Selected flight window contains too few local-position samples: {len(t_f)}"
        )
    flight_time_s = float((t_f[-1] - t_f[0]) / 1e6) if len(t_f) > 1 else 0.0

    speed = np.sqrt(vx * vx + vy * vy + vz * vz) if len(vx) else np.array([])
    max_speed = float(np.max(speed)) if len(speed) else float("nan")

    # Setpoint (best-effort) - FIXED: explicit selection that requires x/y
    sp = _select_setpoint_dataset(ulog)

    planned = _load_planned_path_xy(ulog_path)
    horiz_err, horiz_error_source = _horizontal_error_series(x, y, t_f, sp, planned)
    max_horiz_err = float(np.max(horiz_err)) if len(horiz_err) else float("nan")
    rms_horiz_err = (
        float(np.sqrt(np.mean(horiz_err**2))) if len(horiz_err) else float("nan")
    )

    waypoint_distances: list[float] = []
    waypoint_radius_m = 8.0
    mission_waypoints = _load_mission_waypoints_xy(ulog_path)
    if mission_waypoints is not None and len(x) and len(y):
        for wx, wy in mission_waypoints:
            waypoint_distances.append(float(np.min(np.hypot(x - wx, y - wy))))
    waypoints_reached = sum(distance <= waypoint_radius_m for distance in waypoint_distances)
    waypoint_completion_ratio = (
        float(waypoints_reached / len(waypoint_distances)) if waypoint_distances else float("nan")
    )


    # Attitude / tilt (best-effort)
    att = _get_dataset(ulog, "vehicle_attitude")
    max_tilt = float("nan")
    if att is not None and "q[0]" in att.data:
        ta = att.data["timestamp"].astype(np.int64)
        # Interpolate to flight window timestamps (nearest).
        q0 = _interp_nearest(ta, att.data["q[0]"].astype(np.float64), t_f)
        q1 = _interp_nearest(ta, att.data["q[1]"].astype(np.float64), t_f)
        q2 = _interp_nearest(ta, att.data["q[2]"].astype(np.float64), t_f)
        q3 = _interp_nearest(ta, att.data["q[3]"].astype(np.float64), t_f)
        roll_deg, pitch_deg = _quat_to_roll_pitch_deg(q0, q1, q2, q3)
        tilt_deg = np.sqrt(roll_deg**2 + pitch_deg**2)
        max_tilt = float(np.max(np.abs(tilt_deg))) if len(tilt_deg) else float("nan")

    # Battery (best-effort)
    bat = _get_dataset(ulog, "battery_status")
    min_remaining = float("nan")
    if bat is not None and "remaining" in bat.data:
        tb = bat.data["timestamp"].astype(np.int64)
        rem = bat.data["remaining"].astype(np.float64)
        rem_f = rem[(tb >= t_start) & (tb <= t_end)]
        if len(rem_f):
            # remaining is often 0..1 in PX4 logs
            min_remaining = float(np.min(rem_f))

    # Nav state (best-effort)
    vs = _get_dataset(ulog, "vehicle_status")
    nav_states = None
    if vs is not None and "nav_state" in vs.data:
        tvs = vs.data["timestamp"].astype(np.int64)
        ns = vs.data["nav_state"].astype(np.int64)
        ns_f = ns[(tvs >= t_start) & (tvs <= t_end)]
        if len(ns_f):
            # Return counts of each nav state value for debugging.
            uniq, cnt = np.unique(ns_f, return_counts=True)
            nav_states = {int(u): int(c) for u, c in zip(uniq, cnt)}

    return {
        "flight_window": {**asdict(window), "duration_s": window.duration_s},
        "flight_time_s": flight_time_s,
        "max_speed_m_s": max_speed,
        "max_horiz_error_m": max_horiz_err,
        "rms_horiz_error_m": rms_horiz_err,
        "horiz_error_source": horiz_error_source,
        "max_tilt_deg": max_tilt,
        "min_battery_remaining": min_remaining,
        "nav_state_histogram": nav_states,
        "mission_waypoint_min_distances_m": waypoint_distances,
        "waypoint_radius_m": waypoint_radius_m,
        "waypoints_reached": waypoints_reached,
        "waypoints_total": len(waypoint_distances),
        "waypoint_completion_ratio": waypoint_completion_ratio,
    }


def write_plots(
    ulog_path: Path,
    out_dir: Path,
    flight_window: Optional[Dict[str, Any]] = None,
    horiz_error_source: Optional[str] = None,
) -> Dict[str, str]:
    if flight_window is not None and not flight_window.get("trusted", False):
        return {}

    from pyulog import ULog

    out_dir.mkdir(parents=True, exist_ok=True)
    ulog = ULog(str(ulog_path))
    if flight_window is None:
        window = select_flight_window(ulog)
        t_start, t_end = window.start_us, window.end_us
    else:
        t_start = int(flight_window["start_us"])
        t_end = int(flight_window["end_us"])

    vpos = _get_dataset(ulog, "vehicle_local_position")
    sp = _select_setpoint_dataset(ulog)
    planned = _load_planned_path_xy(ulog_path)

    if vpos is None:
        return {}

    t = vpos.data["timestamp"].astype(np.int64)
    mask = (t >= t_start) & (t <= t_end)
    t_f = (t[mask] - t_start) / 1e6

    x = vpos.data.get("x", np.array([]))[mask].astype(np.float64)
    y = vpos.data.get("y", np.array([]))[mask].astype(np.float64)

    saved: Dict[str, str] = {}

    # XY track
    plt.figure()
    plt.plot(x, y, label="actual")
    if sp is not None and "timestamp" in sp.data and "x" in sp.data and "y" in sp.data:
        tsp = sp.data["timestamp"].astype(np.int64)
        xsp = _interp_nearest(tsp, sp.data["x"].astype(np.float64), t[mask])
        ysp = _interp_nearest(tsp, sp.data["y"].astype(np.float64), t[mask])
        plt.plot(xsp, ysp, label="setpoint")
    elif planned is not None:
        plt.plot(planned[:, 0], planned[:, 1], "--", label="planned path")
    plt.xlabel("x (m, NED)")
    plt.ylabel("y (m, NED)")
    plt.title("XY track")
    plt.legend()
    p = out_dir / "xy_track.png"
    plt.savefig(p, dpi=140, bbox_inches="tight")
    plt.close()
    saved["xy_track"] = str(p)

    # Horizontal error over time
    err, plotted_error_source = _horizontal_error_series(
        x,
        y,
        t[mask],
        sp,
        planned,
        preferred_source=horiz_error_source,
    )
    error_title = f"Horizontal tracking error ({plotted_error_source})"

    if len(err):
        plt.figure()
        plt.plot(t_f, err)
        plt.xlabel("time (s)")
        plt.ylabel("horizontal error (m)")
        plt.title(error_title)
        p = out_dir / "horiz_error.png"
        plt.savefig(p, dpi=140, bbox_inches="tight")
        plt.close()
        saved["horiz_error"] = str(p)

    # Speed
    vx = vpos.data.get("vx", np.array([]))[mask].astype(np.float64)
    vy = vpos.data.get("vy", np.array([]))[mask].astype(np.float64)
    vz = vpos.data.get("vz", np.array([]))[mask].astype(np.float64)
    if len(vx):
        speed = np.sqrt(vx * vx + vy * vy + vz * vz)
        plt.figure()
        plt.plot(t_f, speed)
        plt.xlabel("time (s)")
        plt.ylabel("speed (m/s)")
        plt.title("Speed magnitude")
        p = out_dir / "speed.png"
        plt.savefig(p, dpi=140, bbox_inches="tight")
        plt.close()
        saved["speed"] = str(p)

    # Battery remaining
    bat = _get_dataset(ulog, "battery_status")
    if bat is not None and "remaining" in bat.data:
        tb = bat.data["timestamp"].astype(np.int64)
        maskb = (tb >= t_start) & (tb <= t_end)
        t_b = (tb[maskb] - t_start) / 1e6
        rem = bat.data["remaining"].astype(np.float64)[maskb]
        plt.figure()
        plt.plot(t_b, rem)
        plt.xlabel("time (s)")
        plt.ylabel("remaining")
        plt.title("Battery remaining (fraction)")
        p = out_dir / "battery.png"
        plt.savefig(p, dpi=140, bbox_inches="tight")
        plt.close()
        saved["battery"] = str(p)

    return saved
