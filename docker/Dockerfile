FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG PX4_VERSION=v1.16.1

# Base deps for PX4 SITL + Java (jMAVSim) + Python runner
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates \
    build-essential cmake ninja-build \
    python3 python3-pip python3-venv \
    openjdk-17-jdk-headless \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Clone PX4 into the image (self-contained)
RUN git clone --depth 1 --branch ${PX4_VERSION} https://github.com/PX4/PX4-Autopilot.git /opt/PX4-Autopilot \
 && cd /opt/PX4-Autopilot \
 && git submodule update --init --recursive --depth 1

# Install PX4 python tooling deps
RUN pip3 install --no-cache-dir -r /opt/PX4-Autopilot/Tools/setup/requirements.txt

# Build SITL once during image build (faster runtime)
RUN cd /opt/PX4-Autopilot && HEADLESS=1 make px4_sitl_default jmavsim

WORKDIR /work

# Your runner deps (from the repo you mount at runtime)
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

ENV PX4_HOME=/opt/PX4-Autopilot
ENV PYTHONUNBUFFERED=1

