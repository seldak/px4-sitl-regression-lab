from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyulog import ULog


def _load_planned_path_xy(ulog_path: Path):
    md_path = ulog_path.parent / "run_metadata.json"
    if not md_path.exists():
        return None
    try:
        md = json.loads(md_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    pts = md.get("planned_path_xy")
    if not pts or len(pts) < 2:
        return None
    arr = np.array(pts, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2:
        return None
    return arr

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


def _flight_time_window_us(ulog: ULog) -> tuple[int, int]:
    # Prefer land detector if available.
    ld = _get_dataset(ulog, "vehicle_land_detected")
    if ld is not None and "landed" in ld.data:
        t = ld.data["timestamp"].astype(np.int64)
        landed = ld.data["landed"].astype(np.int64)
        # Find first transition to "not landed" and later back to landed.
        idx_takeoff = np.argmax(landed == 0) if np.any(landed == 0) else None
        if idx_takeoff is not None and np.any(landed[idx_takeoff:] == 1):
            idx_land_rel = np.argmax(landed[idx_takeoff:] == 1)
            idx_land = idx_takeoff + idx_land_rel
            return int(t[idx_takeoff]), int(t[idx_land])

    # Fallback to whole log duration.
    start = int(ulog.start_timestamp)
    end = int(ulog.last_timestamp)
    return start, end


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


def extract_metrics(ulog_path: Path) -> Dict[str, Any]:
    ulog = ULog(str(ulog_path))

    t_start, t_end = _flight_time_window_us(ulog)

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
    flight_time_s = float((t_f[-1] - t_f[0]) / 1e6) if len(t_f) > 1 else 0.0

    speed = np.sqrt(vx * vx + vy * vy + vz * vz) if len(vx) else np.array([])
    max_speed = float(np.max(speed)) if len(speed) else float("nan")

    # Setpoint (best-effort) - FIXED: explicit selection that requires x/y
    sp = _select_setpoint_dataset(ulog)

    horiz_err = np.array([])
    rms_horiz_err = float("nan")

    if sp is not None:
        tsp = sp.data["timestamp"].astype(np.int64)
        sx = sp.data["x"].astype(np.float64)
        sy = sp.data["y"].astype(np.float64)
        xsp = _interp_nearest(tsp, sx, t_f)
        ysp = _interp_nearest(tsp, sy, t_f)
        horiz_err = np.sqrt((x - xsp) ** 2 + (y - ysp) ** 2)
        rms_horiz_err = float(np.sqrt(np.mean(horiz_err**2))) if len(horiz_err) else float("nan")

    max_horiz_err = float(np.max(horiz_err)) if len(horiz_err) else float("nan")

    # after computing max_horiz_err / rms_horiz_err from setpoint (or NaN)
    if (math.isnan(max_horiz_err) or math.isnan(rms_horiz_err)) and len(x) and len(y):
        planned = _load_planned_path_xy(ulog_path)
        if planned is not None:
            path_err = _polyline_distance(x, y, planned)
            if len(path_err):
                max_horiz_err = float(np.max(path_err))
                rms_horiz_err = float(np.sqrt(np.mean(path_err**2)))


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
        "flight_time_s": flight_time_s,
        "max_speed_m_s": max_speed,
        "max_horiz_error_m": max_horiz_err,
        "rms_horiz_error_m": rms_horiz_err,
        "max_tilt_deg": max_tilt,
        "min_battery_remaining": min_remaining,
        "nav_state_histogram": nav_states,
    }


def write_plots(ulog_path: Path, out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ulog = ULog(str(ulog_path))
    t_start, t_end = _flight_time_window_us(ulog)

    vpos = _get_dataset(ulog, "vehicle_local_position")
    sp = _select_setpoint_dataset(ulog)

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
    plt.xlabel("x (m, NED)")
    plt.ylabel("y (m, NED)")
    plt.title("XY track")
    plt.legend()
    p = out_dir / "xy_track.png"
    plt.savefig(p, dpi=140, bbox_inches="tight")
    plt.close()
    saved["xy_track"] = str(p)

    # Horizontal error over time
    if sp is not None and "timestamp" in sp.data and "x" in sp.data and "y" in sp.data:
        tsp = sp.data["timestamp"].astype(np.int64)
        xsp = _interp_nearest(tsp, sp.data["x"].astype(np.float64), t[mask])
        ysp = _interp_nearest(tsp, sp.data["y"].astype(np.float64), t[mask])
        err = np.sqrt((x - xsp) ** 2 + (y - ysp) ** 2)

        plt.figure()
        plt.plot(t_f, err)
        plt.xlabel("time (s)")
        plt.ylabel("horizontal error (m)")
        plt.title("Horizontal tracking error")
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

