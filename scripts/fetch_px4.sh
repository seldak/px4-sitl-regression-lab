#!/usr/bin/env bash
set -euo pipefail

PX4_DIR="${PX4_DIR:-external/PX4-Autopilot}"
PX4_TAG="${PX4_TAG:-v1.16.1}"
PX4_REMOTE="${PX4_REMOTE:-https://github.com/PX4/PX4-Autopilot.git}"
PX4_FETCH="${PX4_FETCH:-0}"   # 0 = offline default, 1 = allow network

mkdir -p "$(dirname "$PX4_DIR")"

# Clone if missing (this is the only time we *must* go online)
if [[ ! -d "$PX4_DIR/.git" ]]; then
  echo "[fetch_px4] Cloning PX4 ($PX4_TAG) into $PX4_DIR"
  git clone --branch "$PX4_TAG" --depth 1 --recursive --shallow-submodules "$PX4_REMOTE" "$PX4_DIR"
fi

cd "$PX4_DIR"

# PX4's version-header generator expects release tags in the nested NuttX
# submodule. `git clone --shallow-submodules` omits those tags, which makes a
# clean CI build fail with an IndexError before compilation begins.
ensure_nuttx_tags() {
  local nuttx_dir="platforms/nuttx/NuttX/nuttx"

  [[ -e "$nuttx_dir/.git" ]] || return 0
  [[ -n "$(git -C "$nuttx_dir" tag --list 'nuttx-[0-9]*')" ]] && return 0

  if [[ "$PX4_FETCH" != "1" ]]; then
    echo "[fetch_px4] NuttX release tags are missing from the shallow submodule."
    echo "          Re-run with PX4_FETCH=1 to fetch version metadata."
    exit 2
  fi

  echo "[fetch_px4] Fetching NuttX release tags required by the PX4 build ..."
  git -C "$nuttx_dir" fetch --force --tags --depth 1 origin
}

# Helper: check whether HEAD matches desired tag (when tag exists locally)
head_matches_tag() {
  git rev-parse -q --verify "refs/tags/$PX4_TAG" >/dev/null 2>&1 || return 1
  local want head
  want="$(git rev-list -n 1 "$PX4_TAG")"
  head="$(git rev-parse HEAD)"
  [[ "$head" == "$want" ]]
}

# 1) Fast path: already at requested tag
if head_matches_tag; then
  echo "[fetch_px4] Already at $PX4_TAG."
  # Ensure submodules are present (no network required if already cloned shallow-submodules)
  git submodule update --init --recursive
  ensure_nuttx_tags
  exit 0
fi

# 2) If tag exists locally, checkout without network
if git rev-parse -q --verify "refs/tags/$PX4_TAG" >/dev/null 2>&1; then
  echo "[fetch_px4] Tag exists locally, checking out $PX4_TAG."
  git checkout -q "$PX4_TAG"
  git submodule update --init --recursive
  ensure_nuttx_tags
  exit 0
fi

# 3) Tag not available locally: refuse network unless explicitly allowed
if [[ "$PX4_FETCH" != "1" ]]; then
  echo "[fetch_px4] Tag $PX4_TAG not found locally and PX4_FETCH!=1; refusing network."
  echo "          Run with: PX4_FETCH=1 PX4_TAG=$PX4_TAG ..."
  exit 2
fi

# 4) Network path: fetch exactly what we need
echo "[fetch_px4] Fetching tag $PX4_TAG from remote ..."
git fetch --tags --force --depth 1 "$PX4_REMOTE" "refs/tags/${PX4_TAG}:refs/tags/${PX4_TAG}"
git checkout -q "$PX4_TAG"
git submodule update --init --recursive --depth 1
ensure_nuttx_tags

echo "[fetch_px4] Done."
