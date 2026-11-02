# BadCamera

Live desktop camera effects in the style of the *Bleach Bypass* app (digicam, CCD, Nokia, VHS, camcorder, night vision, LCD, datamosh…), rendered on the GPU at 60 fps, with every parameter adjustable and the result available as a virtual webcam. An Editor tab puts the same effects, plus hardware-style sound, on your videos.

## Download

Grab the latest build from the [Releases page](https://github.com/rosarydigital/badcamera/releases/latest).

**Windows 10/11 (64-bit)**
1. Run `BadCamera-windows-x64-setup.exe`, or download `BadCamera-windows-x64.zip` and extract it anywhere (e.g. your Documents folder).
2. Run BadCamera. If SmartScreen warns about an unknown publisher, click *More info → Run anyway* (the build isn't code-signed).
3. *Virtual webcam:* install [OBS Studio](https://obsproject.com/) once. BadCamera uses its virtual camera driver, so press **V** and pick "OBS Virtual Camera" in Discord/Zoom/your browser.
4. *Video recording and export* work out of the box with the included ffmpeg.

**Linux (64-bit)**
1. Download `BadCamera-linux-x64.AppImage`, `chmod +x` it and run it. Or download `BadCamera-linux-x64.tar.gz` and extract it: `tar -xzf BadCamera-linux-x64.tar.gz`
2. For the tarball, run `./BadCamera/BadCamera`. Optional: `./BadCamera/install-desktop-entry.sh` adds it to your app menu with its icon.
3. *Virtual webcam:* `sudo apt install v4l2loopback-dkms`, then `sudo modprobe v4l2loopback video_nr=10 card_label=BadCamera exclusive_caps=1` (once per boot). Press **V** and pick "BadCamera" in other apps.
4. *Sound in the Editor and mic recording:* `sudo apt install libportaudio2`. Video recording and export work out of the box; a system ffmpeg is used when installed, and it adds the real GSM codec for the 2000s cell phone sound (otherwise a close stand-in is used).

Photos, videos (`captures/`) and your saved presets (`presets/user/`) go next to the program. The AppImage and the Windows installer can't write there, so they use `~/.local/share/BadCamera` or `%APPDATA%\BadCamera`. Extra LUTs, fonts, overlays and grain textures go in `_internal/assets/` in a downloaded build.

## Editor

Open the **Editor** tab and drop videos anywhere in the window, or use *Add videos*.

- **Cut:** S cuts at the playhead, Delete removes a clip and closes the gap, Ctrl+Z undoes. Drag a clip's edge to trim it, or drag the clip to reorder.
- **Effects:** click a clip, then pick a preset or add effects in the sidebar. *Apply these effects to all clips* covers the whole video. Picking a preset also picks its matching sound.
- **Sound:** VHS linear SP/EP, VHS Hi-Fi, camcorder mic, old landline, 2000s cell phone, cassette, AM radio and CCTV mic. Noise is set relative to each clip's own level, so dialogue stays on top of it on quiet clips too. *Tape noise* sets the amount per clip, from 0% to 200%.
- **Transitions:** crossfade, fade to black, and tape rewind, pause and stop.
- **Keyframes:** click the diamond beside any slider to animate it along the clip.
- **Projects:** *Save* and *Open* use `.bcproj` files. *Bundle* copies a project and its media into one folder to send to someone. Work is auto-saved, and offered back after a crash.

- **Story tools:** give a clip a date and time, and on-screen clocks show it, carrying on across cuts. Add camera power on/off, a dying battery, handheld motion (or measure it from a real clip), title cards, and CCTV quad splits or switchers.
- **Damage:** place tracking tears, dropouts, signal loss, mic overload, wind or tape slowdown at the playhead. *Tape age* wears the tape down from the start of the film to the end.
- **Layers:** an overlay track for picture-in-picture, and a sound track for room tone and effects. Audio files dropped on the window go to the sound track.
- **Markers:** press M to mark the playhead, and add notes to shots.
- **Long projects:** big or long clips get small stand-in files in the background so scrubbing stays quick. Export always uses the originals.

Export writes to `captures/`. Formats include NTSC, PAL, HD, YouTube, ProRes masters and a 2K flat ProRes to take into DCP software. It isn't a DCP itself. *Render queue* lines up several exports, including a clean version and an aged one, and *Export stems* writes dialogue, noise, sound and full mix WAVs that sum exactly to the mix.

## Sound library

The Library page holds real recordings. *Get sound pack* fetches rated CC0 recordings from Freesound (footsteps, doors, creaks, breathing, ambience, impacts, stingers) once you've pasted a key. *Add sound folder* indexes any folder you own where it sits. If the Blackmagic Fairlight Sound Library is on the computer, it's picked up too; its licence only covers projects finished in DaVinci Resolve, so those sounds are marked.

Drag a sound onto a sound lane, or press Add. A sound set to *Match clip* takes on the hardware of the clip under it. *Room* places a sound or clip in a real space when FL Studio's impulse library is installed: stairwell, dark warehouse, hallway, church, cave, graveyard or behind a door. Those files are read from your own FL Studio install and never shipped, and a simple stand-in is used without them.

Get a free [Freesound API key](https://freesound.org/apiv2/apply) to search Freesound from the same page. CC0 is the default filter. Sounds come in as Freesound's high-quality previews, because full originals need a user login. Every sound keeps its licence, *Save sound credits* writes the list, and non-commercial sounds are flagged, since those can't go in a film you sell.

## DaVinci Resolve

Run `./install-resolve-plugin.sh` from the BadCamera folder and restart Resolve. Every effect appears under **OpenFX > BadCamera**, with its controls and a Mix slider. **BadCamera Look** applies any preset, including your own, from one menu. The plugin hands frames to a BadCamera engine that starts by itself, so looks match the app.

*Send to Resolve* on the Deliver page writes FCPXML, OTIO or EDL, so a cut opens in Resolve with its clips in place. Effects stay in BadCamera; add them in Resolve with the plugin.

`plugins/vst3/` holds the sounds as a VST3 effect: one hardware menu, plus Tape noise, Mix and Output. `bash plugins/vst3/build.sh` fetches Steinberg's SDK, builds the plugin, runs Steinberg's validator and installs it to `~/.vst3`.

## Views

*Studio view* in the top bar switches to a Resolve-style workspace: media pool, viewer, inspector, full-width timeline and pages along the bottom. *Dark mode* is in the Classic view. Your choice is remembered.

## Camera transform

The Transform panel rotates, stretches, squashes, moves and zooms the camera before any effect runs. You can also drag the picture to move it and scroll over it to zoom. It's saved between runs and isn't part of a preset.

## Hardware effects

`tape` runs a signal chain rather than a filter: composite encode, comb separation, band-limited FM luma and colour-under chroma, then replay timing errors, head switching, dropouts and decode. It has VHS SP/LP/EP, S-VHS, Betamax, Video8 and Hi8, in NTSC or PAL, and each generation repeats record and replay. `camcorder_sensor`, `night_vision`, `crt` and `film_damage` cover the rest. On-screen text styles `vcr_osd`, `camcorder_osd` and `cctv_osd` are character-generator lettering drawn on a chip's dot grid (`badcamera/osd.py`), and `film_led` is a seven-segment date back.

`tools/compare_reference.py` measures real and simulated footage the same way. Keep reference footage out of the repo.

Older presets using the `vhs` effect keep working as they did. *New tape copy* under Presets makes a copy that uses `tape`.

## Licences

The DSEG and Fira Sans fonts in `badcamera/fonts/` are under the SIL Open Font License (`DSEG-LICENSE.txt`, `FiraSans-OFL.txt`). Release builds include a static [FFmpeg](https://ffmpeg.org/) build under the GPL, from [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg); its source is at [ffmpeg.org/download.html](https://ffmpeg.org/download.html).

## Run from source

```bash
bash run.sh                      # webcam /dev/video0
bash run.sh --vcam               # also start the virtual webcam (/dev/video10, "BadCamera")
bash run.sh --source clip.mp4    # test with a video file (loops)
bash run.sh --preset VHS         # start on a preset
bash run.sh --open clip.mp4      # open videos or a .bcproj in the Editor
bash run.sh --open a.bcproj --export out.mp4   # render a project, then quit
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
