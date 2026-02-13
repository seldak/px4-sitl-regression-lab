from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..scenario import Scenario


def evaluate(metrics: Dict[str, Any], scenario: Scenario) -> tuple[bool, List[str]]:
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

    lines.append("## Metrics")
    for k, v in metrics.items():
        lines.append(f"- **{k}:** `{v}`")
    lines.append("")

    lines.append("## Thresholds")
    thr = scenario.thresholds
    lines.append(f"- timeout_s: `{thr.timeout_s}`")
    lines.append(f"- max_horiz_error_m: `{thr.max_horiz_error_m}`")
    lines.append(f"- rms_horiz_error_m: `{thr.rms_horiz_error_m}`")
    lines.append(f"- max_speed_m_s: `{thr.max_speed_m_s}`")
    lines.append(f"- max_tilt_deg: `{thr.max_tilt_deg}`")
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
