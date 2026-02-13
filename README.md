# PX4 SITL Regression Lab

A reproducible PX4 SITL regression test harness.

- Runs **headless PX4 SITL** (PX4 + jMAVSim) for deterministic test scenarios
- Captures **ULog** artifacts for every run
- Extracts **metrics** (tracking error, speed, tilt, flight time, battery, nav state)
- Produces a **Markdown scorecard** + plots
- CI-ready (GitHub Actions) with artifacts uploaded on every run


---

## What you get

### Scenarios (out of the box)
- `baseline_square_rtl`: takeoff → fly a square → RTL → land
- `low_battery_rtl`: triggers battery depletion to validate low-battery behavior
- `gps_failure_mid_mission` *(optional/nightly)*: injects GPS failure mid-mission

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

## Quickstart (recommended: Docker)

### 1) Build the lab image
```bash
docker build -t px4-reglab -f docker/Dockerfile .
```

### 2) Run a scenario (headless)
```bash
docker run --rm -it \
  --net=host \
  -v "$PWD:/work" \
  -w /work \
  px4-reglab \
  xvfb-run -a python scripts/run_scenario.py --scenario scenarios/baseline.yaml --headless
```

> `--net=host` keeps UDP ports simple for SITL/MAVLink.

---

## Quickstart (native Ubuntu)

### Install dependencies
You need a build toolchain, Java (for jMAVSim), and Python deps.

```bash
sudo apt-get update
sudo apt-get install -y \
  git build-essential cmake ninja-build \
  python3 python3-pip python3-venv \
  openjdk-17-jre-headless \
  xvfb
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Fetch PX4 (pinned tag) and run
```bash
./scripts/fetch_px4.sh
python scripts/run_scenario.py --scenario scenarios/baseline.yaml --headless
```

---

## Running all scenarios
```bash
xvfb-run -a python scripts/run_all.py --headless
```

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

- PX4 is fetched as a *separate* repo under `external/PX4-Autopilot/`.
- The tag is pinned (default `v1.16.1`), but you can override it per scenario.
- CI runs headlessly using `xvfb` to avoid graphics-driver issues.

