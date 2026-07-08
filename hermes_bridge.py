"""Hermes Capture bridge — WebSocket server hosted by the Hermes desktop app.

The Hermes Capture browser extension connects here (ws://127.0.0.1:PORT/hermes)
and:
  * reports the browser's open windows/tabs (so the app can show a picker), and
  * streams captured network entries from a chosen already-open tab/window.

This lets Hermes record windows that are ALREADY open — something the proxy
approach cannot do (a proxy is only read at browser startup).

Drop this module into the hermes-har-recorder app and drive it from the GUI.
It runs its own asyncio loop in a background thread, mirroring ProxyEngine, and
hands data back via thread-safe callbacks.

Requires:  pip install websockets
"""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

try:
    import websockets
except ImportError as e:  # pragma: no cover
    raise ImportError("hermes_bridge requires the 'websockets' package") from e


DEFAULT_BRIDGE_PORT = 8898


@dataclass
class TabInfo:
    id: int
    title: str
    url: str
    active: bool
    window_id: int
    capturing: bool = False


@dataclass
class WindowInfo:
    id: int
    focused: bool
    incognito: bool
    tabs: List[TabInfo] = field(default_factory=list)


class HermesBridge:
    """WebSocket server the browser extension connects to.

    Callbacks (all invoked from the bridge thread — marshal to the GUI thread
    yourself, e.g. via a Qt signal):
        on_status(connected: bool, browser: str)
        on_windows(browser: str, windows: List[WindowInfo])
        on_entry(entry: dict)      # a captured request/response
        on_capture_started(target: dict)
        on_capture_stopped(reason: str)
        on_error(message: str)
    """

    def __init__(
        self,
        port: int = DEFAULT_BRIDGE_PORT,
        on_status: Optional[Callable[[bool, str], None]] = None,
        on_windows: Optional[Callable[[str, List[WindowInfo]], None]] = None,
        on_entry: Optional[Callable[[dict], None]] = None,
        on_capture_started: Optional[Callable[[dict], None]] = None,
        on_capture_stopped: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.port = port
        self.on_status = on_status
        self.on_windows = on_windows
        self.on_entry = on_entry
        self.on_capture_started = on_capture_started
        self.on_capture_stopped = on_capture_stopped
        self.on_error = on_error

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._client = None  # single active extension connection
        self._browser = "?"
        self._running = False

    # ─── lifecycle ──────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._serve())
            loop.run_forever()
        except Exception as e:  # pragma: no cover
            self._emit_error(f"bridge crashed: {e}")
        finally:
            loop.close()

    async def _serve(self) -> None:
        self._server = await websockets.serve(
            self._handle, "127.0.0.1", self.port, max_size=64 * 1024 * 1024
        )

    # ─── connection handling ────────────────────────────────────────────────
    async def _handle(self, conn):
        self._client = conn
        try:
            async for raw in conn:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self._on_message(msg)
        except Exception:
            pass
        finally:
            if self._client is conn:
                self._client = None
                self._safe(self.on_status, False, self._browser)

    def _on_message(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "hello":
            self._browser = msg.get("browser", "?")
            self._safe(self.on_status, True, self._browser)
        elif t == "windows":
            windows = [
                WindowInfo(
                    id=w["id"], focused=w.get("focused", False),
                    incognito=w.get("incognito", False),
                    tabs=[TabInfo(**{
                        "id": tb["id"], "title": tb.get("title", ""),
                        "url": tb.get("url", ""), "active": tb.get("active", False),
                        "window_id": tb.get("windowId", w["id"]),
                        "capturing": tb.get("capturing", False),
                    }) for tb in w.get("tabs", [])],
                )
                for w in msg.get("windows", [])
            ]
            self._safe(self.on_windows, self._browser, windows)
        elif t == "entry":
            self._safe(self.on_entry, msg.get("entry", {}))
        elif t == "capture_started":
            self._safe(self.on_capture_started, msg.get("target", {}))
        elif t == "capture_stopped":
            self._safe(self.on_capture_stopped, msg.get("reason", "?"))
        elif t == "error":
            self._emit_error(msg.get("message", "unknown"))

    # ─── commands to the extension ──────────────────────────────────────────
    def list_windows(self) -> None:
        self._send({"type": "list_windows"})

    def start_capture(self, tab_id: Optional[int] = None,
                      window_id: Optional[int] = None, follow_new: bool = True) -> None:
        self._send({"type": "start_capture", "tabId": tab_id,
                    "windowId": window_id, "followNew": follow_new})

    def pause(self) -> None:
        self._send({"type": "pause"})

    def resume(self) -> None:
        self._send({"type": "resume"})

    def stop_capture(self) -> None:
        self._send({"type": "stop_capture"})

    @property
    def connected(self) -> bool:
        return self._client is not None

    # ─── internals ──────────────────────────────────────────────────────────
    def _send(self, obj: dict) -> None:
        loop, conn = self._loop, self._client
        if loop and conn and loop.is_running():
            loop.call_soon_threadsafe(asyncio.ensure_future, conn.send(json.dumps(obj)))

    def _safe(self, cb, *args) -> None:
        if cb:
            try:
                cb(*args)
            except Exception as e:
                self._emit_error(f"callback error: {e}")

    def _emit_error(self, msg: str) -> None:
        if self.on_error:
            try:
                self.on_error(msg)
            except Exception:
                pass


def entry_to_captured(entry: dict):
    """Convert an extension network entry into the app's CapturedRequest.

    Import lazily so this file also works standalone (e.g. for tests).
    """
    import base64
    import uuid
    from urllib.parse import urlsplit
    from proxy_engine import CapturedRequest  # type: ignore

    url = entry.get("url", "")
    parts = urlsplit(url)
    scheme = parts.scheme or ""
    host = parts.hostname or ""
    port = parts.port or (443 if scheme == "https" else 80)
    path = parts.path + (("?" + parts.query) if parts.query else "")

    resp_body_text = entry.get("responseBody", "") or ""
    resp_body = b""
    if resp_body_text:
        if entry.get("responseBase64"):
            try:
                resp_body = base64.b64decode(resp_body_text)
                resp_body_text = ""  # binary; keep bytes only
            except Exception:
                resp_body = resp_body_text.encode("utf-8", "replace")
        else:
            resp_body = resp_body_text.encode("utf-8", "replace")

    req_body_text = entry.get("requestBody", "") or ""
    req_body = req_body_text.encode("utf-8", "replace") if req_body_text else b""

    return CapturedRequest(
        id=str(entry.get("requestId") or uuid.uuid4().hex),
        method=entry.get("method", ""),
        url=url,
        scheme=scheme,
        host=host,
        port=port,
        path=path,
        request_headers=entry.get("requestHeaders", {}) or {},
        request_body=req_body,
        request_body_text=req_body_text,
        status_code=int(entry.get("status", 0) or 0),
        reason=entry.get("statusText", "") or "",
        response_headers=entry.get("responseHeaders", {}) or {},
        response_body=resp_body,
        response_body_text=resp_body_text,
        content_type=entry.get("mimeType", "") or "",
    )
