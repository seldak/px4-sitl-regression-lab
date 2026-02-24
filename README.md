# PX4 SITL Regression Lab

A reproducible PX4 SITL regression test harness.

- Runs **headless PX4 SITL** (PX4 + jMAVSim) for deterministic scenarios
- Captures **ULog** artifacts for every run
- Extracts **metrics** (tracking error, speed, tilt, flight time, battery, nav state)
- Produces a **Markdown scorecard** + plots
- CI-ready (GitHub Actions) with artifacts uploaded on every run

---

## What you get

### Scenarios (out of the box)
- `baseline_square_rtl`: takeoff → fly a square → RTL → land
- `low_battery_rtl`: triggers battery depletion to validate low-battery behavior
- `gps_failure_mid_mission` *(optional/nightly)*: injects GPS failure mid-mission (can be timing-sensitive)

### Artifacts
Each run creates a folder like:

```
runs/2026-02-13T12-34-56Z_baseline_square_rtl/
  sitl_stdout.log
  flight.ulg
  run_metadata.json
  metrics.json
  report.md
  plots/
    xy_track.png
    horiz_error.png
    speed.png
    battery.png
```

---

## Quickstart (native Ubuntu)

### 1) System dependencies
PX4 provides a helper installer, but the two common “gotchas” are:
- **`ant`** (needed for jMAVSim)
- JDK/JRE installed (Java runtime)

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git ant
```

If PX4 deps are not installed yet:

```bash
bash external/PX4-Autopilot/Tools/setup/ubuntu.sh
```

### 2) Python deps
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 3) Run baseline (headless)
```bash
export PX4_SKIP_FETCH=1
export MAVSDK_CONNECTION_URL="udpin://0.0.0.0:14540"
export PYTHONPATH="$(pwd)"

python -u scripts/run_scenario.py --scenario scenarios/baseline.yaml --headless
```

---

## Running all scenarios

Recommended (stable-by-default):
```bash
export PX4_SKIP_FETCH=1
export MAVSDK_CONNECTION_URL="udpin://0.0.0.0:14540"
export PYTHONPATH="$(pwd)"

python -u scripts/run_all.py --headless
```

If `gps_drop.yaml` is flaky on your machine, run it manually and/or move it to nightly CI.

---

## Metrics

Horizontal tracking error is computed as:
1) **setpoint-based error** if setpoint topics exist in the log, otherwise
2) **geometric fallback**: distance from actual XY track to the planned mission polyline stored in `run_metadata.json`.

This avoids depending on PX4 internal setpoint topics that can vary across versions/backends.

---

## Docker (not yet verified)

Docker support exists, but it has not been validated end-to-end across setups yet.
For now, the recommended path is the **native quickstart** above.

If you try Docker and hit issues, please open an issue with:
- host OS version
- `docker build` output
- `runs/*/sitl_stdout.log` and `report.md`

(If/when Docker is validated, this section will be promoted to the recommended path.)

---

## Adding a new scenario

Create a new file in `scenarios/`:

```yaml
name: my_new_scenario
description: Example
px4:
  tag: v1.16.1
mission:
  takeoff_alt_m: 10
  cruise_speed_m_s: 5
  relative_waypoints_m:
    - [40, 0, 10]
    - [40, 40, 10]
events:
  - at_s: 20
    type: set_param
    name: SIM_BAT_MIN_PCT
    value: 5
thresholds:
  timeout_s: 180
  max_horiz_error_m: 6
  rms_horiz_error_m: 3
  max_speed_m_s: 15
  max_tilt_deg: 55
```

---

## Notes on reproducibility

- PX4 is fetched as a separate repo under `external/PX4-Autopilot/`.
- The tag is pinned (default `v1.16.1`), but you can override it per scenario.
- CI runs headlessly using `xvfb` to avoid graphics-driver issues.
