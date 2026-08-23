FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates \
    build-essential cmake ninja-build pkg-config \
    python3 python3-pip python3-venv \
    openjdk-17-jdk ant \
    xvfb \
    libgl1-mesa-dri libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work

# project deps (small, fast)
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

ENV PYTHONUNBUFFERED=1
ENV MAVSDK_CONNECTION_URL=udpin://0.0.0.0:14540
ENV PX4_SKIP_FETCH=1
ENV LIBGL_ALWAYS_SOFTWARE=1
ENV JMAVSIM_NO_GUI=1

WORKDIR /app
COPY . /app
ENV PYTHONPATH=/app
ENV PYTHONPATH=/work

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
