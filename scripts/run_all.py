#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from px4_lab.runner import run_scenario
from px4_lab.scenario import load_scenario


DEFAULT_SCENARIOS = [
    "scenarios/baseline.yaml",
    "scenarios/low_battery.yaml",
]


OPTIONAL_SCENARIOS = [
    "scenarios/gps_failure.yaml",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a suite of PX4 SITL regression scenarios")
    ap.add_argument("--headless", action="store_true", help="Run simulator headless")
    ap.add_argument("--runs-dir", default="runs", help="Output directory")
    ap.add_argument("--include-optional", action="store_true", help="Also run optional/flakier scenarios")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    runs_dir = repo_root / args.runs_dir

    scenarios = list(DEFAULT_SCENARIOS)
    if args.include_optional:
        scenarios += OPTIONAL_SCENARIOS

    overall = 0
    for s in scenarios:
        scenario = load_scenario(str(repo_root / s))
        code, run_dir = run_scenario(
            repo_root=repo_root,
            scenario=scenario,
            headless=bool(args.headless),
            runs_dir=runs_dir,
        )
        print(f"[run_all] scenario={scenario.name} code={code} dir={run_dir}")
        overall = max(overall, code)

    return overall


if __name__ == "__main__":
    raise SystemExit(main())
