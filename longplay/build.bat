@echo off
setlocal enabledelayedexpansion

echo ====================================
echo VCMI Longplay Builder Script
echo ====================================

echo.
echo [1/3] Building builder Docker image...
docker build -f longplay/builder/Dockerfile -t vcmi-builder ..
if %errorlevel% neq 0 (
    echo ERROR: Failed to build Docker image
    pause
    exit /b 1
)
echo Builder image built successfully.

echo.
echo [2/3] Compiling source within container...
docker run --rm -it -v "%CD%:/src" vcmi-builder bash -c "cd /src/longplay/builder/build && cmake -S ../../../ -DENABLE_CCACHE=OFF -DENABLE_TEST=OFF -DENABLE_MMAI=OFF -DENABLE_LAUNCHER=OFF -DENABLE_DISCORD=OFF -DCMAKE_BUILD_TYPE=Release -DENABLE_STATIC=ON && cmake --build . -j8"
if %errorlevel% neq 0 (
    echo ERROR: Failed to compile within container
    pause
    exit /b 1
)

echo.
echo ====================================
echo Build completed successfully!
echo ====================================