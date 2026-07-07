import os
from pathlib import Path

os.chdir(Path(__file__).parent)

# =============================================
# Hermes HAR Recorder - ULTIMATE BUILD
# =============================================

build_cmd = [
    "pyinstaller",
    "--name=HermesHARRecorder",
    "--one-dir",
    "--windowed",
    "--clean",
    "--noconfirm",
    "--noupx",
    
    # Data & Resources
    "--add-data=README.md;.",
    "--add-data=requirements.txt;.",
    
    # Hidden Imports (lengkap banget)
    "--hidden-import=PyQt6",
    "--hidden-import=PyQt6.QtCore",
    "--hidden-import=PyQt6.QtGui",
    "--hidden-import=PyQt6.QtWidgets",
    "--hidden-import=PyQt6.sip",
    "--hidden-import=mitmproxy",
    "--hidden-import=mitmproxy.tools.dump",
    "--hidden-import=mitmproxy.proxy",
    "--hidden-import=mitmproxy.addons",
    "--hidden-import=mitmproxy.cert",
    "--hidden-import=mitmproxy.connection",
    "--hidden-import=mitmproxy.ctx",
    "--hidden-import=asyncio",
    "--hidden-import=threading",
    "--hidden-import=queue",
    "--hidden-import=ssl",
    "--hidden-import=OpenSSL",
    "--hidden-import=cryptography",
    "--hidden-import=urllib3",
    
    # Collect All (super lengkap)
    "--collect-all=PyQt6",
    "--collect-all=PyQt6-Qt6",
    "--collect-all=mitmproxy",
    "--collect-all=cryptography",
    "--collect-all=OpenSSL",
    
    # Performance & Stability
    "--log-level=WARN",
    
    "main.py"
]

if __name__ == "__main__":
    print("🚀 Starting ULTIMATE BUILD Hermes HAR Recorder...")
    print("📦 Mode: one-dir | Full collect | Max hidden imports")
    
    result = os.system(" ".join(build_cmd))
    
    if result == 0:
        print("✅ BUILD BERHASIL!")
        print("📁 Cek folder: dist/HermesHARRecorder")
        print("💡 Jalankan: dist/HermesHARRecorder/HermesHARRecorder.exe")
    else:
        print("❌ Build gagal. Kirim errornya ke aku.")
