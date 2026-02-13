from __future__ import annotations

import asyncio
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .mavsdk_control import FlightOutcome, connect, run_mission_with_events
from .metrics.extract import extract_metrics, write_plots
from .metrics.report import evaluate, render_markdown, write_json
from .px4_repo import ensure_px4_repo
from .scenario import Scenario
from .sitl import SITLProcess
from .util import ensure_dir, newest_file_by_mtime, utc_timestamp


def _px4_log_root(px4_dir: Path) -> Path:
    # PX4 SITL logs are typically under:
    # build/px4_sitl_default/rootfs/fs/microsd/log/<date>/<log>.ulg
    return px4_dir / "build" / "px4_sitl_default" / "rootfs" / "fs" / "microsd" / "log"


def _collect_ulog(px4_dir: Path, run_dir: Path, before: set[Path]) -> Path:
    log_root = _px4_log_root(px4_dir)
    if not log_root.exists():
        raise FileNotFoundError(f"PX4 log root not found: {log_root}")

    after = set(log_root.rglob("*.ulg"))
    new = list(after - before)

    if new:
        new.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        src = new[0]
    else:
        newest = newest_file_by_mtime(log_root, "*.ulg")
        if newest is None:
            raise FileNotFoundError(f"No .ulg logs found under {log_root}")
        src = newest

    dst = run_dir / "flight.ulg"
    shutil.copy2(src, dst)
    return dst


def run_scenario(
    repo_root: Path,
    scenario: Scenario,
    headless: bool,
    runs_dir: Path,
    system_address: str = "udpin://0.0.0.0:14540",
) -> Tuple[int, Path]:
    run_name = f"{utc_timestamp()}_{scenario.name}"
    run_dir = ensure_dir(runs_dir / run_name)

    # Ensure PX4 is present.
    px4_dir = repo_root / "external" / "PX4-Autopilot"
    ensure_px4_repo(repo_root=repo_root, px4_dir=px4_dir, tag=scenario.px4.tag, remote=scenario.px4.remote)

    # Capture pre-existing logs to identify the one produced by this scenario.
    log_root = _px4_log_root(px4_dir)
    before_logs = set(log_root.rglob("*.ulg")) if log_root.exists() else set()

    sitl = SITLProcess(px4_dir=px4_dir, headless=headless, stdout_path=run_dir / "sitl_stdout.log")

    outcome_dict: Dict[str, Any] = {}
    ulog_path: Optional[Path] = None

    try:
        sitl.start()

        # Run flight.
        async def _go() -> FlightOutcome:
            drone = await connect(system_address=system_address, timeout_s=45.0)
            return await run_mission_with_events(
                drone=drone,
                mission=scenario.mission,
                events=scenario.events,
                timeout_s=scenario.thresholds.timeout_s,
            )

        outcome: FlightOutcome = asyncio.run(_go())
        outcome_dict = asdict(outcome)

    except Exception as ex:
        outcome_dict = {
            "mission_started": False,
            "mission_finished": False,
            "landed": False,
            "timeout": False,
            "exceptions": [f"runner: {type(ex).__name__}: {ex!s}"],
            "executed_events": [],
        }
    finally:
        # Always stop SITL to avoid orphaned processes.
        sitl.stop()

    # Collect artifacts (best effort).
    try:
        ulog_path = _collect_ulog(px4_dir, run_dir, before_logs)
    except Exception as ex:
        outcome_dict.setdefault("exceptions", []).append(f"collect_ulog: {type(ex).__name__}: {ex!s}")

    # Write metadata early.
    write_json(run_dir / "run_metadata.json", {"scenario": scenario.name, "outcome": outcome_dict})

    # If we have a log, compute metrics and gate.
    exit_code = 2
    if ulog_path and ulog_path.exists():
        try:
            metrics = extract_metrics(ulog_path)
            plots = write_plots(ulog_path, run_dir / "plots")
            passed, failures = evaluate(metrics, scenario)

            write_json(run_dir / "metrics.json", metrics)
            report_md = render_markdown(
                scenario=scenario,
                outcome=outcome_dict,
                metrics=metrics,
                passed=passed,
                failures=failures,
                plots=plots,
            )
            (run_dir / "report.md").write_text(report_md, encoding="utf-8")

            exit_code = 0 if passed else 1
        except Exception as ex:
            (run_dir / "report.md").write_text(
                f"# Run report\n\nFailed to compute metrics: {type(ex).__name__}: {ex!s}\n",
                encoding="utf-8",
            )
            exit_code = 2
    else:
        (run_dir / "report.md").write_text(
            "# Run report\n\nNo ULog found; cannot compute metrics.\n",
            encoding="utf-8",
        )
        exit_code = 2

    return exit_code, run_dir
