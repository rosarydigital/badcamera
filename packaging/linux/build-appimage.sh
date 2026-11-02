#!/usr/bin/env bash
# Wrap dist/BadCamera in an AppImage. Run from the repo root after pyinstaller. Set APPIMAGETOOL if it isn't on PATH.
set -e
tool="${APPIMAGETOOL:-appimagetool}"
dir="$(mktemp -d)/BadCamera.AppDir"
mkdir -p "$dir"
cp -a "${DIST:-dist/BadCamera}/." "$dir/"
cp assets/icon.png "$dir/badcamera.png"
cat > "$dir/AppRun" <<'RUN'
#!/bin/sh
exec "$(dirname "$(readlink -f "$0")")/BadCamera" "$@"
RUN
chmod +x "$dir/AppRun"
cat > "$dir/badcamera.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=BadCamera
Comment=Live camera effects and a small video editor
Exec=BadCamera
Icon=badcamera
Categories=AudioVideo;Video;
StartupWMClass=BadCamera
DESKTOP
ARCH=x86_64 "$tool" --appimage-extract-and-run "$dir" BadCamera-linux-x64.AppImage
