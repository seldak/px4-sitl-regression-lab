#!/usr/bin/env bash
set -euo pipefail

HEADLESS="${HEADLESS:-1}"

if [[ "$HEADLESS" == "1" ]]; then
  HEADLESS_FLAG="--headless"
else
  HEADLESS_FLAG=""
fi

python scripts/run_scenario.py --scenario scenarios/baseline.yaml $HEADLESS_FLAG
python scripts/run_scenario.py --scenario scenarios/low_battery.yaml $HEADLESS_FLAG
