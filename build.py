import os
import sys
from pathlib import Path

# =============================================
# Hermes HAR Recorder - Build Configuration
# =============================================

os.chdir(Path(__file__).parent)

# Build arguments
build_args = [
    "pyinstaller",
    "--name=HermesHARRecorder",
    "--one-dir",                    # Lebih stabil untuk mitmproxy + PyQt6
    "--windowed",
    "--clean",
    "--noconfirm",
    "--noupx",
    
    # Data files
    "--add-data=README.md;.",
    "--add-data=requirements.txt;.",
    
    # Hidden imports (ini yang biasanya bikin error)
    "--hidden-import=PyQt6.QtCore",
    "--hidden-import=PyQt6.QtGui",
    "--hidden-import=PyQt6.QtWidgets",
    "--hidden-import=PyQt6.sip",
    "--hidden-import=mitmproxy",
    "--hidden-import=mitmproxy.tools.dump",
    "--hidden-import=mitmproxy.proxy",
    "--hidden-import=mitmproxy.addons",
    "--hidden-import=mitmproxy.cert",
    "--hidden-import=asyncio",
    "--hidden-import=threading",
    "--hidden-import=queue",
    "--hidden-import=ssl",
    "--hidden-import=OpenSSL",
    
    # Collect all (paling penting)
    "--collect-all=PyQt6",
    "--collect-all=PyQt6-Qt6",
    "--collect-all=mitmproxy",
    "--collect-all=cryptography",
    
    # Tambahan untuk menghindari error common
    "--additional-hooks-dir=.",
    "--runtime-hook=hook-mitmproxy.py" if Path("hook-mitmproxy.py").exists() else "",
    
    "main.py"
]

# Filter empty string
build_args = [arg for arg in build_args if arg]

if __name__ == "__main__":
    print("🚀 Building Hermes HAR Recorder (Full Mode)...")
    print("📦 Using one-dir mode for better stability")
    
    result = os.system(" ".join(build_args))
    
    if result == 0:
        print("✅ Build berhasil!")
        print("📁 Cek folder: dist/HermesHARRecorder")
    else:
        print("❌ Build gagal. Coba cek error di atas.")
