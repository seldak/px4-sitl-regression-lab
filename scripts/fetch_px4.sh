#!/usr/bin/env bash
set -euo pipefail

PX4_DIR="${PX4_DIR:-external/PX4-Autopilot}"
PX4_TAG="${PX4_TAG:-v1.16.1}"
PX4_REMOTE="${PX4_REMOTE:-https://github.com/PX4/PX4-Autopilot.git}"

mkdir -p "$(dirname "$PX4_DIR")"

if [[ -d "$PX4_DIR/.git" ]]; then
  echo "[fetch_px4] PX4 repo already exists at $PX4_DIR"
else
  echo "[fetch_px4] Cloning PX4 ($PX4_TAG) into $PX4_DIR"
  git clone --branch "$PX4_TAG" --depth 1 --recursive --shallow-submodules "$PX4_REMOTE" "$PX4_DIR"
fi

cd "$PX4_DIR"

echo "[fetch_px4] Ensuring tag/branch: $PX4_TAG"
git fetch --tags --force --depth 1 origin "refs/tags/${PX4_TAG}:refs/tags/${PX4_TAG}" || true
git checkout -f "$PX4_TAG"
git submodule update --init --recursive --depth 1

echo "[fetch_px4] Done."
