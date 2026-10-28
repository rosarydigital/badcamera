"""Entry point for packaged builds (PyInstaller can't start from a package's __main__ with relative imports)."""
from badcamera.__main__ import main

main()
