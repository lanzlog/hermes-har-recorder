"""
build.py - PyInstaller build script for Hermes HAR Recorder.
Creates a single .exe for Windows distribution.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


def build():
    """Build the application using PyInstaller."""
    print("=" * 60)
    print("  Building Hermes HAR Recorder")
    print("=" * 60)

    # Clean previous build
    for d in ["build", "dist"]:
        if Path(d).exists():
            print(f"Cleaning {d}/...")
            shutil.rmtree(d)

    # PyInstaller arguments
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name", "HermesHARRecorder",
        "--windowed",  # No console window
        "--onedir",    # One directory (more reliable than onefile for complex apps)
        "--icon", "NONE",  # No icon by default
        # Hidden imports for mitmproxy
        "--hidden-import", "mitmproxy.tools.dump",
        "--hidden-import", "mitmproxy.net.http",
        "--hidden-import", "mitmproxy.addons",
        "--hidden-import", "mitmproxy.proxy",
        "--hidden-import", "mitmproxy.flow",
        "--hidden-import", "mitmproxy.options",
        "--hidden-import", "mitmproxy.certs",
        "--hidden-import", "mitmproxy.connection",
        "--hidden-import", "cryptography",
        "--hidden-import", "OpenSSL",
        # PyQt6 imports
        "--hidden-import", "PyQt6.QtWidgets",
        "--hidden-import", "PyQt6.QtCore",
        "--hidden-import", "PyQt6.QtGui",
        # Collect all mitmproxy data
        "--collect-all", "mitmproxy",
        # Main script
        "main.py",
    ]

    print("\nRunning PyInstaller...")
    print(" ".join(args))
    print()

    result = subprocess.run(args, capture_output=False)

    if result.returncode != 0:
        print("\nBuild failed!")
        sys.exit(1)

    print("\nBuild successful!")
    print(f"Output: {Path('dist/HermesHARRecorder').absolute()}")

    # Create a portable zip
    dist_dir = Path("dist/HermesHARRecorder")
    if dist_dir.exists():
        zip_name = f"HermesHARRecorder_{get_version()}_win64"
        print(f"\nCreating {zip_name}.zip...")
        shutil.make_archive(
            f"dist/{zip_name}", 'zip',
            root_dir='dist',
            base_dir='HermesHARRecorder'
        )
        print(f"Created dist/{zip_name}.zip")


def build_onefile():
    """Build as a single .exe file."""
    print("=" * 60)
    print("  Building Hermes HAR Recorder (Single File)")
    print("=" * 60)

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name", "HermesHARRecorder",
        "--windowed",
        "--onefile",
        "--hidden-import", "mitmproxy.tools.dump",
        "--hidden-import", "mitmproxy.net.http",
        "--hidden-import", "mitmproxy.addons",
        "--hidden-import", "mitmproxy.proxy",
        "--hidden-import", "mitmproxy.flow",
        "--hidden-import", "mitmproxy.options",
        "--hidden-import", "mitmproxy.certs",
        "--hidden-import", "cryptography",
        "--hidden-import", "OpenSSL",
        "--hidden-import", "PyQt6.QtWidgets",
        "--hidden-import", "PyQt6.QtCore",
        "--hidden-import", "PyQt6.QtGui",
        "--collect-all", "mitmproxy",
        "main.py",
    ]

    result = subprocess.run(args, capture_output=False)
    if result.returncode != 0:
        print("\nBuild failed!")
        sys.exit(1)
    print("\n[OK] Single-file build successful!")


def get_version():
    """Get version string."""
    try:
        from utils import APP_VERSION
        return APP_VERSION
    except Exception:
        return "1.0.0"


if __name__ == "__main__":
    if "--onefile" in sys.argv:
        build_onefile()
    else:
        build()
