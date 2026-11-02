#!/usr/bin/env bash
# Adds BadCamera to your app menu (with its icon), pointing at this folder.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/badcamera.desktop <<DESKTOP
[Desktop Entry]
Type=Application
Name=BadCamera
Comment=Live camera effects and a small video editor
Exec="$here/BadCamera"
Icon=$here/_internal/assets/icon.png
Categories=AudioVideo;Video;
StartupWMClass=BadCamera
DESKTOP
echo "Added BadCamera to your applications menu."
