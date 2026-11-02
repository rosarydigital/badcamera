"""Entry point for packaged builds (PyInstaller can't start from a package's __main__ with relative imports)."""
import os
import sys

if getattr(sys, "frozen", False):
    # PyInstaller points LD_LIBRARY_PATH at its bundled libs. Child programs (ffmpeg, file dialogs) must not inherit that.
    os.environ["LD_LIBRARY_PATH"] = os.environ.pop("LD_LIBRARY_PATH_ORIG", "")

from badcamera.__main__ import main

main()
