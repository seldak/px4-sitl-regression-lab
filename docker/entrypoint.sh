#!/usr/bin/env bash
set -euo pipefail

PX4_DIR="${PX4_DIR:-/work/external/PX4-Autopilot}"
PX4_TAG="${PX4_TAG:-v1.16.1}"
BUILD_JOBS="${BUILD_JOBS:-4}"   # cap CPU usage

mkdir -p /work/external

if [[ ! -d "${PX4_DIR}/.git" ]]; then
  echo "[docker] cloning PX4 into ${PX4_DIR}"
  git clone --recursive https://github.com/PX4/PX4-Autopilot.git "${PX4_DIR}"
fi

git config --global --add safe.directory "${PX4_DIR}" || true

cd "${PX4_DIR}"

# offline by default; only fetch if PX4_FETCH=1
if git rev-parse -q --verify "refs/tags/${PX4_TAG}" >/dev/null 2>&1; then
  git checkout -q "${PX4_TAG}"
elif [[ "${PX4_FETCH:-0}" == "1" ]]; then
  git fetch --tags --force origin "refs/tags/${PX4_TAG}:refs/tags/${PX4_TAG}"
  git checkout -q "${PX4_TAG}"
else
  echo "[docker] tag ${PX4_TAG} not found locally; set PX4_FETCH=1 to fetch"
  exit 2
fi

git submodule update --init --recursive

# build only if px4 binary missing
if [[ ! -x "${PX4_DIR}/build/px4_sitl_default/bin/px4" ]]; then
  echo "[docker] installing PX4 python build deps"
  python3 -m pip install -q --no-cache-dir -r "${PX4_DIR}/Tools/setup/requirements.txt"

  if [[ -f "${PX4_DIR}/build/px4_sitl_default/CMakeCache.txt" ]] && \
      ! grep -q "${PX4_DIR}" "${PX4_DIR}/build/px4_sitl_default/CMakeCache.txt"; then
    echo "[docker] CMakeCache path mismatch; wiping px4_sitl_default"
    rm -rf "${PX4_DIR}/build/px4_sitl_default"
  fi

  echo "[docker] building PX4 SITL (jobs=${BUILD_JOBS})"
  HEADLESS=1 \
  JMAVSIM_NO_GUI=1 \
  LIBGL_ALWAYS_SOFTWARE=1 \
  make -j"${BUILD_JOBS}" px4_sitl_default
else
  echo "[docker] PX4 SITL already built"
fi

cd /work
exec "$@"

