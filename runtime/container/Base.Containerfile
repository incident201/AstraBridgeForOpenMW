# Increment this revision to intentionally refresh distribution packages: 1
ARG BASE_IMAGE=docker.io/library/ubuntu@sha256:496754492fb28b4d3049432f2ca787449331e23fb14f0dd3fffea86bf5a93eb4
FROM ${BASE_IMAGE} AS base
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates python3 python3-venv tini \
    weston xwayland xauth xdotool x11-utils mesa-utils pciutils \
    libgl1-mesa-dri libglx-mesa0 libegl-mesa0 mesa-va-drivers intel-media-va-driver vainfo \
    libva2 libva-drm2 libva-x11-2 libx264-164 libopus0 \
    libopenscenegraph161 libcollada-dom2.5-dp0 libbullet3.24 \
    libsdl2-2.0-0 libopenal1 libyaml-cpp0.8 libluajit-5.1-2 \
    libboost-program-options1.83.0 libboost-filesystem1.83.0 libboost-iostreams1.83.0 \
    libavcodec60 libavformat60 libavutil58 libswscale7 libswresample4 \
    libicu74 libsqlite3-0 libfreetype6 libpng16-16t64 liblz4-1 \
    libxcb-composite0 libxcomposite1 libxrandr2 libxcursor1 libxi6 \
    && rm -rf /var/lib/apt/lists/*

