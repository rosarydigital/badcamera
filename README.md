# BadCamera

Live desktop camera effects in the style of the *Bleach Bypass* app (digicam, CCD, Nokia, VHS, LCD, datamosh…), rendered on the GPU at 60 fps, with every parameter adjustable and the result available as a virtual webcam.

## Download

Grab the latest build from the [Releases page](https://github.com/rosarydigital/badcamera/releases/latest).

**Windows 10/11 (64-bit)**
1. Download `BadCamera-windows-x64.zip` and extract it anywhere (e.g. your Documents folder).
2. Run `BadCamera\BadCamera.exe`. If SmartScreen warns about an unknown publisher, click *More info → Run anyway* (the build isn't code-signed).
3. *Virtual webcam:* install [OBS Studio](https://obsproject.com/) once. BadCamera uses its virtual camera driver, so press **V** and pick "OBS Virtual Camera" in Discord/Zoom/your browser.
4. *Video recording:* needs ffmpeg on your PATH, e.g. `winget install ffmpeg`.

**Linux (64-bit)**
1. Download `BadCamera-linux-x64.tar.gz` and extract it: `tar -xzf BadCamera-linux-x64.tar.gz`
2. Run `./BadCamera/BadCamera`. Optional: `./BadCamera/install-desktop-entry.sh` adds it to your app menu with its icon.
3. *Virtual webcam:* `sudo apt install v4l2loopback-dkms`, then `sudo modprobe v4l2loopback video_nr=10 card_label=BadCamera exclusive_caps=1` (once per boot). Press **V** and pick "BadCamera" in other apps.
4. *Video recording:* `sudo apt install ffmpeg`.

Photos, videos (`captures/`) and your saved presets (`presets/user/`) go next to the program. Extra LUTs, fonts, overlays and grain textures go in `_internal/assets/` in a downloaded build.

## Run from source

```bash
bash run.sh                      # webcam /dev/video0
bash run.sh --vcam               # also start the virtual webcam (/dev/video10, "BadCamera")
bash run.sh --source clip.mp4    # test with a video file (loops)
bash run.sh --preset VHS         # start on a preset
```

Other options: `--cam-size 1280x720`, `--cam-fps 30`, `--out-fps 60`, `--vcam-device /dev/video10`.

| Key | Action |
|---|---|
| ← / → | previous / next preset |
| Space | snapshot (PNG in `captures/`) |
| R | start / stop recording (MP4 in `captures/`) |
| V | virtual webcam on / off |
| B | show original (bypass) |
| F | fullscreen |

## Customising

- **Panel:** each preset is a stack of steps. Steps can be toggled, reordered (Up/Down), copied, reset, randomised and removed. New steps are added from the dropdown at the bottom. Every parameter is a slider. **Save preset** writes `presets/user/<name>.json`.
- **Styles:** every effect has a *Style* dropdown of ready-made settings (e.g. JPEG: High / Medium / Low / Potato / 360p; VHS: Clean / Worn / Destroyed tape). *Save style* stores the current settings in `presets/user/styles.json`.
- **Text stamps:** four styles: `digicam` (slanted 7-segment LCD with glow and a white-hot core), `vcr` (5×7 character-generator font, hard black outline), `dotmatrix` (round-dot viewfinder LCD) and `clean` (any TrueType font; drop `.ttf`/`.otf` files into `assets/fonts/`). Text takes strftime codes plus `{tc}` (running counter) and `{tcf}` (timecode with frames); `|` starts a new line; `blink` makes it flash. Put a stamp *before* JPEG/noise/VHS steps to burn it into the picture, or after them for a crisp overlay.
- **LUTs:** drop any `.cube` file into `assets/luts/` and it appears in the `lut` step's dropdown.
- **Overlays / grain:** drop PNGs into `assets/overlays/` or `assets/grain/`.
- **New effects:** add a shader to `badcamera/shaders/` and a small `@effect` class to `badcamera/effects.py`. Its `params` list becomes the UI automatically.

Steps: color_grade, lut, gaussian_blur, bloom, overlay, sharpen, noise, grain, jpeg (real 8×8 DCT on the GPU; `video` mode adds codec skip-blocks and keyframe quality breathing), vignette, clarity, bilateral, desaturate, blur_pixelate, bleach_bypass, vhs, lcd, datamosh, lightburst, chromatic_aberration, ccd_smear, flash, bit_depth, text_stamp, camera_life (lagging auto exposure / white balance and exposure hunting), sensor_noise (shot noise, chroma blotches, row banding, hot pixels), lens_flare (ghosts that follow bright lights), light_leak, interlace, frame_rate.

Nothing in the built-in looks is static: `python -m tests.test_core` fails if any preset renders the same image twice from a frozen input.

## Setup from source

Linux:
```bash
sudo apt install python3-venv python3-pip v4l-utils v4l2loopback-dkms ffmpeg
python3 -m venv ~/.local/share/badcamera/venv     # keep it on a Linux filesystem (exFAT has no symlinks)
~/.local/share/badcamera/venv/bin/python -m pip install -r requirements.txt
~/.local/share/badcamera/venv/bin/python tools/make_assets.py   # generates LUTs, overlays, grain and the icon into assets/
bash run.sh
```

Windows (PowerShell, Python 3.12+):
```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python tools\make_assets.py
.venv\Scripts\python -m badcamera
```

## Build the downloadable apps

```bash
pip install pyinstaller
python tools/make_assets.py
pyinstaller --noconfirm badcamera.spec     # -> dist/BadCamera/ (BadCamera.exe on Windows)
```

PyInstaller only builds for the system it runs on, so Windows builds are made on Windows. Publishing a GitHub release runs `.github/workflows/release.yml`, which builds both platforms and attaches `BadCamera-windows-x64.zip` and `BadCamera-linux-x64.tar.gz` to the release. It can also be started by hand from the Actions tab.

## Check

```bash
~/.local/share/badcamera/venv/bin/python -m tests.test_core
```

This runs every preset headless, compares the GPU JPEG with libjpeg, prints ms/frame at 720p, and writes preview PNGs to `captures/test/`.

Notes: rendering, animated effects and outputs run at 60 fps; the camera image itself updates at whatever rate the webcam delivers (often 30 fps, less in dim light). The looks are original recreations; no assets from the Bleach Bypass app are used.
