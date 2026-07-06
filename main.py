"""
main.py - Entry point for Hermes HAR Recorder.
Ties proxy engine and GUI together.
"""

import sys
import os

# Suppress Qt warnings
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from utils import ensure_dirs, load_config, APP_NAME
from gui_main import HARRecorderWindow


def main():
    """Application entry point."""
    # Ensure directories exist
    ensure_dirs()

    # Load config
    config = load_config()

    # Create QApplication
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("NousResearch")

    # Set default font
    font = QFont("Segoe UI", 9)
    app.setFont(font)

    # Create and show main window
    window = HARRecorderWindow(config)
    window.show()

    # Run event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
