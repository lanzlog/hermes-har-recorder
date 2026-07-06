# Hermes HAR Recorder

A desktop HTTP/HTTPS traffic recorder and HAR exporter built with Python, PyQt6, and mitmproxy.

## Features

- **One-click Record/Stop** — capture HTTP/HTTPS traffic instantly
- **HTTPS Decryption** — via mitmproxy's certificate system
- **Live Request Table** — method, URL, status, size, time columns
- **Detail Inspector** — headers, request/response body, cookies, timing tabs
- **Syntax Highlighting** — JSON, HTML, CSS, JavaScript
- **Search & Filter** — by URL, method, status, content type, domain
- **Smart Features** — OAuth detection, token extraction, step markers
- **Replay & Edit** — replay requests with modifications
- **Export** — HAR 1.2, CSV, JSON, cURL, Python requests, fetch()
- **Dark Theme** — modern dark UI with colored syntax
- **Session Management** — auto-save and restore sessions

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

1. Click **🔴 Record** to start the proxy (default port: 8899)
2. Configure your browser/system to use proxy `127.0.0.1:8899`
3. Install the mitmproxy CA certificate for HTTPS decryption
4. Browse the web — requests appear in real-time
5. Click **⏹ Stop** when done
6. **📁 Export** to HAR, CSV, or JSON

## Keyboard Shortcuts

- `Ctrl+R` — Start recording
- `Ctrl+S` — Stop recording
- `Ctrl+F` — Focus search bar
- `Ctrl+E` — Export
- `Ctrl+M` — Add step marker
- `Ctrl+Shift+S` — Save session
- `Ctrl+O` — Load session
- `Delete` — Remove selected requests

## Building .exe

```bash
# One-directory build (recommended)
python build.py

# Single-file build
python build.py --onefile

# Or use the spec file directly
pyinstaller hermes_har_recorder.spec
```

## Architecture

- `main.py` — Entry point
- `gui_main.py` — PyQt6 main window, table, detail panels
- `proxy_engine.py` — mitmproxy addon for traffic capture
- `har_formatter.py` — HAR 1.2 format converter
- `export_manager.py` — Multi-format export (HAR, CSV, JSON, cURL, etc.)
- `replay_engine.py` — Request replay with edit capability
- `utils.py` — Utility functions

## Requirements

- Python 3.10+
- PyQt6
- mitmproxy
- requests

## License

MIT
