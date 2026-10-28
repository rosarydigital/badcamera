# Build: pyinstaller badcamera.spec  ->  dist/BadCamera/
import sys

from PyInstaller.utils.hooks import collect_all

datas = [("assets", "assets"), ("presets/builtin.json", "presets"), ("badcamera/shaders", "badcamera/shaders")]
binaries, hiddenimports = [], ["moderngl_window.context.glfw"]
# These load backends / native libs dynamically, which PyInstaller can't see on its own.
for pkg in ("imgui_bundle", "glfw", "glcontext", "pyvirtualcam", "moderngl_window"):
    d, b, h = collect_all(pkg)
    datas, binaries, hiddenimports = datas + d, binaries + b, hiddenimports + h

a = Analysis(["badcamera_app.py"], datas=datas, binaries=binaries, hiddenimports=hiddenimports, excludes=["tkinter"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BadCamera", console=False,
          icon="assets/icon.ico" if sys.platform == "win32" else None)
coll = COLLECT(exe, a.binaries, a.datas, name="BadCamera")
