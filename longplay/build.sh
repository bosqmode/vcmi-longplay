#!/usr/bin/env bash

echo "===================================="
echo "VCMI Longplay Builder Script"
echo "===================================="

echo
echo "[1/2] Building builder Docker image..."
docker build -f longplay/builder/Dockerfile -t vcmi-builder ..
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to build Docker image"
    exit 1
fi
echo "Builder image built successfully."

echo
echo "[2/2] Compiling source within container..."
docker run --rm -it -v "$(pwd):/src" vcmi-builder bash -c "cd /src/longplay/builder/build && cmake -S ../../../ -DENABLE_CCACHE=OFF -DENABLE_TEST=OFF -DENABLE_MMAI=OFF -DENABLE_LAUNCHER=OFF -DCMAKE_BUILD_TYPE=Release -DENABLE_STATIC=ON && cmake --build . -j8"
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to compile within container"
    exit 1
fi

echo
echo "===================================="
echo "Build completed successfully!"
echo "===================================="