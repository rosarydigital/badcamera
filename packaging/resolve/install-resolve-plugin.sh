#!/usr/bin/env bash
# Installs the BadCamera effects into DaVinci Resolve. Run from the BadCamera folder, then restart Resolve.
# OpenFX plugins live in a system folder, so this asks for your password once.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
target=/usr/OFX/Plugins/BadCamera.ofx.bundle
sudo mkdir -p "$target/Contents/Linux-x86-64"
sudo cp "$here/BadCamera.ofx" "$target/Contents/Linux-x86-64/BadCamera.ofx"
mkdir -p ~/.config/badcamera
printf '%s' "$here/BadCamera" > ~/.config/badcamera/engine
echo "Installed. Restart Resolve, then look under OpenFX > BadCamera."
