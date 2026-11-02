#!/usr/bin/env bash
# Builds "BadCamera Hardware.vst3" with Steinberg's SDK, runs their validator, and installs it to ~/.vst3.
# Takes a few minutes the first time. Run it yourself from anywhere: bash plugins/vst3/build.sh
set -e
here="$(cd "$(dirname "$0")" && pwd)"
work="${BADCAMERA_BUILD:-$HOME/BadCamera-build}"
mkdir -p "$work/sdk"
[ -d "$work/sdk/vst3sdk/public.sdk" ] || git clone --depth 1 --recursive --shallow-submodules https://github.com/steinbergmedia/vst3sdk "$work/sdk/vst3sdk"
cmake -S "$here" -B "$work/vstbuild" -Dvst3sdk_SOURCE_DIR="$work/sdk/vst3sdk" -DCMAKE_BUILD_TYPE=Release
cmake --build "$work/vstbuild" -j"$(nproc)"
mkdir -p ~/.vst3
cp -r "$work"/vstbuild/VST3/Release/*.vst3 ~/.vst3/
echo "Installed to ~/.vst3. If the validator lines above show 0 failed, it's good."
