# ===== VCMI Linux build environment =====
# This image is only used to build Linux version of VCMI within a container

FROM ubuntu:26.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
        cmake \
        g++ \
        clang \
        libsdl2-dev \
        libsdl2-image-dev \
        libsdl2-ttf-dev \
        libsdl2-mixer-dev \
        zlib1g-dev \
        libavformat-dev \
        libswscale-dev \
        libboost-dev \
        libboost-filesystem-dev \
        libboost-program-options-dev \
        libboost-date-time-dev \
        libboost-iostreams-dev \
        qt6-base-dev \
        qt6-base-dev-tools \
        qt6-tools-dev \
        qt6-tools-dev-tools \
        qt6-l10n-tools \
        qt6-svg-dev \
        libtbb-dev \
        libluajit-5.1-dev \
        liblzma-dev \
        libsqlite3-dev \
        libminizip-dev \
        libsquish-dev \
        libfmt-dev \
        ninja-build \
        ccache \
        git \
    && rm -rf /var/lib/apt/lists/*

CMD ["bash"]
