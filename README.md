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

### 1) Fetch PX4 and install system dependencies

PX4 provides a helper installer, but the two common “gotchas” are:
- **`ant`** (needed for jMAVSim)
- JDK/JRE installed (Java runtime)

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git ant openjdk-17-jdk
PX4_FETCH=1 bash scripts/fetch_px4.sh
```

Then install the remaining PX4 build dependencies:

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

The GPS-failure scenario is excluded by default because simulator timing can make it less stable. Run it explicitly when needed:

```bash
python -u scripts/run_scenario.py --scenario scenarios/gps_failure.yaml --headless
```

---

## Metrics

Horizontal tracking error is computed as:
1) **setpoint-based error** if setpoint topics exist in the log, otherwise
2) **geometric fallback**: distance from actual XY track to the planned mission polyline stored in `run_metadata.json`.

This avoids depending on PX4 internal setpoint topics that can vary across versions/backends.

### Trust and pass/fail gates

A run cannot pass from a short or incomplete log fragment. The report checks:

- mission start, completion, landing, timeout, and runtime exceptions
- a trusted, sustained flight window rather than simulator initialization noise
- minimum flight duration and sample coverage
- waypoint completion ratio
- horizontal error, speed, tilt, and scenario-specific thresholds

If the flight window is not trustworthy, flight plots are suppressed instead of presenting misleading data.

---

## Docker

Docker can be used for both headless runs and interactive jMAVSim on Ubuntu. Build the image from the repository root:

```bash
sudo docker build -t px4-reglab -f docker/Dockerfile .
```

If your account can access the Docker daemon directly, omit `sudo` from these commands.

### Headless run

Run the default scenario suite without opening the simulator window:

```bash
sudo docker run --rm -it \
  --net=host \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e MPLCONFIGDIR=/tmp/matplotlib \
  -e PYTHONPATH=/work \
  -e MAVSDK_CONNECTION_URL="udpin://0.0.0.0:14540" \
  -e PX4_SKIP_FETCH=1 \
  -v "$PWD:/work" \
  -w /work \
  px4-reglab \
  python3 -u scripts/run_all.py --headless
```

The first run clones and builds pinned PX4 dependencies under `external/`; later runs reuse that build. Reports, logs, ULogs, and plots are written to `runs/`. The user mapping prevents the container from leaving root-owned files in either directory.

### Interactive simulator with NVIDIA acceleration

This requires a working host NVIDIA driver and NVIDIA Container Toolkit configured for Docker:

```bash
sudo docker run --rm -it \
  --runtime=nvidia \
  --net=host \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e MPLCONFIGDIR=/tmp/matplotlib \
  -e PYTHONPATH=/work \
  -e DISPLAY="$DISPLAY" \
  -e MAVSDK_CONNECTION_URL="udpin://0.0.0.0:14540" \
  -e PX4_SKIP_FETCH=1 \
  -e LIBGL_ALWAYS_SOFTWARE=0 \
  -e JMAVSIM_NO_GUI=0 \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=graphics,utility,display \
  -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
  -v "$PWD:/work" \
  -w /work \
  px4-reglab \
  python3 -u scripts/run_scenario.py \
    --scenario scenarios/baseline.yaml
```

On hosts where NVIDIA Toolkit reports that Docker is using CDI mode, use `--runtime=nvidia` as shown above. Do not combine it with `--gpus all`. A `render` group does not need to be added for this NVIDIA path.

For a CPU-rendered window, remove the NVIDIA runtime and NVIDIA environment variables, then set `LIBGL_ALWAYS_SOFTWARE=1` instead. It is substantially slower on many systems.

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
