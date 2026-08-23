from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ..scenario import Scenario


def evaluate(
    metrics: Dict[str, Any], scenario: Scenario, outcome: Dict[str, Any] | None = None
) -> tuple[bool, List[str]]:
    failures: List[str] = []
    thr = scenario.thresholds

    def chk(name: str, value: float, limit: float) -> None:
        if value != value:  # NaN
            failures.append(f"{name}: missing (NaN)")
            return
        if value > limit:
            failures.append(f"{name}: {value:.3f} > {limit:.3f}")

    chk("max_horiz_error_m", float(metrics.get("max_horiz_error_m", float('nan'))), thr.max_horiz_error_m)
    chk("rms_horiz_error_m", float(metrics.get("rms_horiz_error_m", float('nan'))), thr.rms_horiz_error_m)
    chk("max_speed_m_s", float(metrics.get("max_speed_m_s", float('nan'))), thr.max_speed_m_s)
    chk("max_tilt_deg", float(metrics.get("max_tilt_deg", float('nan'))), thr.max_tilt_deg)

    window = metrics.get("flight_window") or {}
    if not window.get("trusted", False):
        failures.append(
            f"flight_window: untrusted source {window.get('source', 'missing')!r}"
        )
    sample_count = int(window.get("sample_count", 0))
    if sample_count < thr.min_window_samples:
        failures.append(
            f"flight_window.sample_count: {sample_count} < {thr.min_window_samples}"
        )

    flight_time_s = float(metrics.get("flight_time_s", float("nan")))
    if flight_time_s != flight_time_s:
        failures.append("flight_time_s: missing (NaN)")
    elif flight_time_s < thr.min_flight_time_s:
        failures.append(f"flight_time_s: {flight_time_s:.3f} < {thr.min_flight_time_s:.3f}")

    waypoint_distances = metrics.get("mission_waypoint_min_distances_m") or []
    if waypoint_distances:
        reached = sum(float(distance) <= thr.waypoint_radius_m for distance in waypoint_distances)
        completion_ratio = reached / len(waypoint_distances)
        metrics["waypoint_radius_m"] = thr.waypoint_radius_m
        metrics["waypoints_reached"] = reached
        metrics["waypoint_completion_ratio"] = completion_ratio
        if completion_ratio < thr.min_waypoint_completion_ratio:
            failures.append(
                "waypoint_completion_ratio: "
                f"{completion_ratio:.3f} < {thr.min_waypoint_completion_ratio:.3f} "
                f"({reached}/{len(waypoint_distances)} within {thr.waypoint_radius_m:.1f}m)"
            )
    elif thr.min_waypoint_completion_ratio > 0:
        failures.append("waypoint_completion_ratio: missing planned waypoint evidence")

    if outcome is not None:
        if not outcome.get("mission_started", False):
            failures.append("runtime: mission did not start")
        if thr.require_mission_finished and not outcome.get("mission_finished", False):
            failures.append("runtime: mission did not finish")
        if not outcome.get("landed", False):
            failures.append("runtime: landing was not observed")
        if outcome.get("timeout", False):
            failures.append("runtime: scenario timed out")
        exceptions = outcome.get("exceptions") or []
        if exceptions:
            failures.append(f"runtime: {len(exceptions)} exception(s)/warning(s) recorded")
        executed_events = outcome.get("executed_events") or []
        if len(executed_events) < len(scenario.events):
            failures.append(
                f"runtime: only {len(executed_events)}/{len(scenario.events)} configured events executed"
            )

    return (len(failures) == 0), failures


def render_markdown(
    scenario: Scenario,
    outcome: Dict[str, Any],
    metrics: Dict[str, Any],
    passed: bool,
    failures: List[str],
    plots: Dict[str, str],
) -> str:
    status = "PASS ✅" if passed else "FAIL ❌"
    lines: List[str] = []
    lines.append(f"# Run report: `{scenario.name}`")
    lines.append("")
    lines.append(f"**Status:** {status}")
    lines.append("")
    lines.append("## Scenario")
    lines.append(f"- **Description:** {scenario.description}")
    lines.append(f"- **PX4 tag:** `{scenario.px4.tag}`")
    lines.append("")
    lines.append("## Outcome (runtime)")
    for k, v in outcome.items():
        if k in ("exceptions", "executed_events"):
            continue
        lines.append(f"- **{k}:** `{v}`")
    lines.append("")

    if outcome.get("executed_events"):
        lines.append("## Executed events")
        for e in outcome["executed_events"]:
            lines.append(f"- `{e}`")
        lines.append("")

    if outcome.get("exceptions"):
        lines.append("## Exceptions / warnings")
        for ex in outcome["exceptions"]:
            lines.append(f"- `{ex}`")
        lines.append("")

    window = metrics.get("flight_window") or {}
    lines.append("## Trust evidence")
    lines.append(f"- **Window source:** `{window.get('source', 'missing')}`")
    lines.append(f"- **Window trusted:** `{window.get('trusted', False)}`")
    lines.append(f"- **Window duration:** `{window.get('duration_s', 'missing')} s`")
    lines.append(f"- **Window samples:** `{window.get('sample_count', 0)}`")
    lines.append(f"- **Log fraction analyzed:** `{window.get('log_fraction', 'missing')}`")
    lines.append(f"- **Horizontal-error source:** `{metrics.get('horiz_error_source', 'missing')}`")
    lines.append(
        "- **Waypoints reached:** "
        f"`{metrics.get('waypoints_reached', 0)}/{metrics.get('waypoints_total', 0)}`"
    )
    if window.get("diagnostics"):
        lines.append(f"- **Window diagnostics:** `{window['diagnostics']}`")
    lines.append("")

    lines.append("## Metrics")
    for k, v in metrics.items():
        if k == "flight_window":
            continue
        lines.append(f"- **{k}:** `{v}`")
    lines.append("")

    lines.append("## Thresholds")
    thr = scenario.thresholds
    lines.append(f"- timeout_s: `{thr.timeout_s}`")
    lines.append(f"- max_horiz_error_m: `{thr.max_horiz_error_m}`")
    lines.append(f"- rms_horiz_error_m: `{thr.rms_horiz_error_m}`")
    lines.append(f"- max_speed_m_s: `{thr.max_speed_m_s}`")
    lines.append(f"- max_tilt_deg: `{thr.max_tilt_deg}`")
    lines.append(f"- min_flight_time_s: `{thr.min_flight_time_s}`")
    lines.append(
        f"- min_waypoint_completion_ratio: `{thr.min_waypoint_completion_ratio}`"
    )
    lines.append(f"- waypoint_radius_m: `{thr.waypoint_radius_m}`")
    lines.append(f"- min_window_samples: `{thr.min_window_samples}`")
    lines.append(f"- require_mission_finished: `{thr.require_mission_finished}`")
    lines.append("")

    if failures:
        lines.append("## Failures")
        for f in failures:
            lines.append(f"- {f}")
        lines.append("")

    if plots:
        lines.append("## Plots")
        for k, p in plots.items():
            lines.append(f"- {k}: `{p}`")
        lines.append("")

    return "\n".join(lines)


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
