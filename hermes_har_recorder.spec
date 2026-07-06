# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Hermes HAR Recorder.
Build with: pyinstaller hermes_har_recorder.spec
"""

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'mitmproxy.tools.dump',
        'mitmproxy.net.http',
        'mitmproxy.addons',
        'mitmproxy.proxy',
        'mitmproxy.flow',
        'mitmproxy.options',
        'mitmproxy.certs',
        'mitmproxy.connection',
        'mitmproxy.contentviews',
        'mitmproxy.contentviews.json',
        'mitmproxy.contentviews.xml_html',
        'mitmproxy.contentviews.css',
        'mitmproxy.contentviews.javascript',
        'mitmproxy.contentviews.image',
        'mitmproxy.contentviews.mqtt',
        'mitmproxy.contentviews.grpc',
        'mitmproxy.contentviews.wbxml',
        'mitmproxy.net.dns',
        'mitmproxy.net.server_spec',
        'mitmproxy.net.tls',
        'mitmproxy.proxy.layers',
        'mitmproxy.proxy.layers.dns',
        'mitmproxy.proxy.layers.http',
        'mitmproxy.proxy.layers.tls',
        'mitmproxy.proxy.layers.websocket',
        'mitmproxy.proxy.server',
        'mitmproxy.proxy.server_hooks',
        'mitmproxy.proxy.mode_servers',
        'mitmproxy.scripts',
        'mitmproxy.utils',
        'cryptography',
        'OpenSSL',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.sip',
        'sqlite3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HermesHARRecorder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HermesHARRecorder',
)
