# Docker notes

This image contains **everything needed to build PX4 SITL + run the lab**, without touching your host.

## Build
```bash
docker build -t px4-reglab -f docker/Dockerfile .
```

## Run (recommended)
```bash
docker run --rm -it \
  --net=host \
  -v "$PWD:/work" \
  -w /work \
  px4-reglab \
  xvfb-run -a python scripts/run_all.py --headless
```

Why `--net=host`? PX4 SITL uses UDP ports for MAVLink, and host networking keeps it simple and predictable.
