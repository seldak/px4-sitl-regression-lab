FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    cmake \
    ninja-build \
    python3 \
    python3-pip \
    python3-venv \
    openjdk-17-jre-headless \
    xvfb \
    ca-certificates \
    curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /work

# Python deps (for scenario runner + metrics)
COPY requirements.txt /work/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /work/requirements.txt

# Copy the lab code (small) - PX4 itself is fetched at runtime into external/
COPY px4_lab /work/px4_lab
COPY scripts /work/scripts
COPY scenarios /work/scenarios
COPY pyproject.toml /work/pyproject.toml
COPY README.md /work/README.md

ENV PYTHONUNBUFFERED=1
ENV LIBGL_ALWAYS_SOFTWARE=1
