# Docker usage

The image contains the tools needed to build PX4 SITL and run the scenarios. PX4 sources, build outputs, and run artifacts remain in the bind-mounted repository.

## Build

```bash
sudo docker build -t px4-reglab -f docker/Dockerfile .
```

## Headless suite

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

`--net=host` keeps the UDP MAVLink connection predictable. The first run clones and builds PX4 under `external/`; subsequent runs reuse it. Outputs are written under `runs/`.

## Interactive jMAVSim with NVIDIA

The host must have a working NVIDIA driver and NVIDIA Container Toolkit configured for Docker.

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

If NVIDIA Toolkit is configured in CDI mode, use `--runtime=nvidia`; do not add `--gpus all`. The NVIDIA path also does not require `--group-add render`.
