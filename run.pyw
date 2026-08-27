"""Silent-Launcher für den Tray-Client (Doppelklick / Autostart, kein Konsolenfenster)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from timetracker.app import main, setup_logging

if __name__ == "__main__":
    setup_logging()
    raise SystemExit(main())
