#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from px4_lab.runner import run_scenario
from px4_lab.scenario import load_scenario


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one PX4 SITL regression scenario")
    ap.add_argument("--scenario", required=True, help="Path to scenario YAML (e.g., scenarios/baseline.yaml)")
    ap.add_argument("--headless", action="store_true", help="Run simulator headless (recommended for CI)")
    ap.add_argument("--runs-dir", default="runs", help="Where to store outputs (default: runs/)")
    ap.add_argument(
        "--system-address",
        default="udpin://0.0.0.0:14540",
        help="MAVSDK system_address (default: udpin://0.0.0.0:14540)",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    scenario = load_scenario(str(Path(args.scenario)))

    code, run_dir = run_scenario(
        repo_root=repo_root,
        scenario=scenario,
        headless=bool(args.headless),
        runs_dir=repo_root / args.runs_dir,
        system_address=args.system_address,
    )

    print(f"[run_scenario] exit_code={code}")
    print(f"[run_scenario] run_dir={run_dir}")

    # If in GitHub Actions, append the report to the job summary.
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    report_path = run_dir / "report.md"
    if summary_path and report_path.exists():
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n\n")
            f.write(report_path.read_text(encoding="utf-8"))

    return code


if __name__ == "__main__":
    raise SystemExit(main())
