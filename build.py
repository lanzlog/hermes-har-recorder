import os
import sys
import subprocess
from pathlib import Path

os.chdir(Path(__file__).parent)

# Always invoke via the same Python that runs this script. Bare 'pyinstaller'
# on PATH can point at a different env / missing modules on the Actions runner.
build_cmd = [
    sys.executable, "-m", "PyInstaller",
    "--name=HermesHARRecorder",
    "--onedir",
    "--windowed",
    "--clean",
    "--noconfirm",
    "--noupx",
    # Windows uses ';' as the add-data separator; on other OS it's ':'.
    # This script is intended for the Windows CI runner.
    "--add-data=README.md;.",
    "--add-data=requirements.txt;.",
    "--hidden-import=PyQt6",
    "--hidden-import=PyQt6.QtCore",
    "--hidden-import=PyQt6.QtGui",
    "--hidden-import=PyQt6.QtWidgets",
    "--hidden-import=PyQt6.sip",
    "--hidden-import=mitmproxy",
    "--hidden-import=mitmproxy.tools.dump",
    "--hidden-import=mitmproxy.proxy",
    "--hidden-import=mitmproxy.addons",
    "--hidden-import=mitmproxy.certs",
    "--hidden-import=mitmproxy.connection",
    "--hidden-import=asyncio",
    "--hidden-import=threading",
    "--hidden-import=queue",
    "--hidden-import=ssl",
    "--hidden-import=OpenSSL",
    "--hidden-import=cryptography",
    "--hidden-import=websockets",
    "--hidden-import=hermes_bridge",
    "--hidden-import=browser_launcher",
    "--hidden-import=proxy_engine",
    "--hidden-import=trace_engine",
    "--hidden-import=export_manager",
    "--hidden-import=har_formatter",
    "--hidden-import=replay_engine",
    "--hidden-import=utils",
    "--collect-all=PyQt6",
    "--collect-all=PyQt6-Qt6",
    "--collect-all=mitmproxy",
    "--collect-all=cryptography",
    "--log-level=WARN",
    "main.py",
]


if __name__ == "__main__":
    # No emoji — Windows cp1252 console chokes on them and aborts the build.
    print("Starting build: Hermes HAR Recorder")
    print("Mode: onedir | Full collect | Max hidden imports")
    print("Command:", " ".join(build_cmd))
    result = subprocess.call(build_cmd)
    if result == 0:
        print("BUILD OK")
        print("Output: dist/HermesHARRecorder")
        print("Run: dist/HermesHARRecorder/HermesHARRecorder.exe")
    else:
        print(f"BUILD FAILED (exit {result})")
        sys.exit(result)
