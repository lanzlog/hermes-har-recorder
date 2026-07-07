"""
proxy_engine.py - Full Version
Hermes HAR Recorder
"""

import asyncio
import logging
import random
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Dict

from mitmproxy import options as moptions
from mitmproxy.tools.dump import DumpMaster
from mitmproxy import flow as mflow

from utils import safe_decode, get_content_encoding


# ==================== LOGGER ====================
_log_dir = Path.home() / ".hermes-har-recorder"
_log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(_log_dir / "hermes.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("hermes.proxy")


# ==================== APP MODE ====================
class AppMode:
    RECORD = "record"
    HAR_RECORD = "har_record"
    API_TRACE = "api_trace"
    HAR_TRACE = "har_trace"


# ==================== DATA CLASS ====================
@dataclass
class CapturedRequest:
    id: str = ""
    method: str = ""
    url: str = ""
    scheme: str = ""
    host: str = ""
    port: int = 80
    path: str = ""
    http_version: str = "HTTP/1.1"
    request_headers: Dict[str, str] = field(default_factory=dict)
    request_body: Optional[bytes] = None
    request_size: int = 0
    status_code: int = 0
    reason: str = ""
    response_headers: Dict[str, str] = field(default_factory=dict)
    response_body: Optional[bytes] = None
    response_size: int = 0
    content_type: str = ""
    request_time: float = 0.0
    response_time: float = 0.0
    duration: float = 0.0
    bookmarked: bool = False
    step_label: str = ""
    resource_type: str = ""
    is_oauth: bool = False
    request_body_text: str = ""
    response_body_text: str = ""
    request_cookies: Dict[str, str] = field(default_factory=dict)
    response_cookies: Dict[str, str] = field(default_factory=dict)
    tls_version: str = ""
    replayed: bool = False
    trace_status: str = ""


# ==================== ADDON ====================
class HARCaptureAddon:
    def __init__(self, on_flow_complete: Optional[Callable] = None):
        self.on_flow_complete = on_flow_complete
        self._flow_counter = 0

    def response(self, flow: mflow.Flow):
        try:
            captured = self._convert_flow(flow)
            if captured and self.on_flow_complete:
                self.on_flow_complete(captured)
        except Exception as e:
            logger.error(f"Error processing flow: {e}")

    def _convert_flow(self, flow: mflow.Flow) -> Optional[CapturedRequest]:
        if not hasattr(flow, 'request') or not flow.request:
            return None

        req = flow.request
        resp = flow.response
        self._flow_counter += 1
        start_time = getattr(flow, '_har_start_time', time.time())

        cr = CapturedRequest()
        cr.id = f"flow_{self._flow_counter}_{int(start_time * 1000)}"
        cr.method = req.method
        cr.url = req.pretty_url
        cr.scheme = req.scheme
        cr.host = req.host
        cr.port = req.port or (443 if req.scheme == 'https' else 80)
        cr.path = req.path
        cr.http_version = getattr(flow, 'http_version', 'HTTP/1.1') or 'HTTP/1.1'

        cr.request_headers = {k: v for k, v in req.headers.items()} if req.headers else {}
        cr.request_body = req.content
        cr.request_body_text = safe_decode(req.content) if req.content else ""
        cr.request_size = len(req.content) if req.content else 0
        cr.request_time = start_time

        if 'Cookie' in cr.request_headers:
            for part in cr.request_headers['Cookie'].split(';'):
                if '=' in part:
                    k, v = [x.strip() for x in part.split('=', 1)]
                    cr.request_cookies[k] = v

        if resp:
            cr.status_code = resp.status_code
            cr.reason = resp.reason or ""
            cr.response_headers = {k: v for k, v in resp.headers.items()} if resp.headers else {}
            cr.response_body = resp.content
            cr.response_size = len(resp.content) if resp.content else 0
            cr.response_time = time.time()
            cr.duration = cr.response_time - start_time
            cr.content_type = cr.response_headers.get('Content-Type', '')
            cr.response_body_text = safe_decode(resp.content) if resp.content else ""

        return cr


# ==================== PROXY ENGINE ====================
class ProxyEngine:
    def __init__(self, port: int = 8899, on_flow: Optional[Callable] = None, on_error: Optional[Callable] = None):
        self.port = port
        self.on_flow = on_flow
        self.on_error = on_error
        self._master: Optional[DumpMaster] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._addon = HARCaptureAddon(on_flow_complete=self._handle_flow)

    @staticmethod
    def is_port_available(port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.bind(("127.0.0.1", port))
                return True
        except OSError:
            return False

    def find_available_port(self, max_tries: int = 30) -> int:
        for _ in range(max_tries):
            port = random.randint(10000, 65000)
            if self.is_port_available(port):
                return port
        for port in range(50000, 65000):
            if self.is_port_available(port):
                return port
        return 0

    def _handle_flow(self, captured: CapturedRequest):
        if self.on_flow:
            self.on_flow(captured)

    def start(self) -> bool:
        if self._running:
            return True

        if not self.is_port_available(self.port):
            new_port = self.find_available_port()
            if new_port > 0:
                logger.info(f"Port {self.port} busy → using random safe port: {new_port}")
                self.port = new_port
            else:
                err = "Tidak menemukan port tersedia di range aman"
                logger.error(err)
                if self.on_error:
                    self.on_error(err)
                return False

        self._thread = threading.Thread(target=self._run_proxy, daemon=True)
        self._thread.start()

        for _ in range(50):
            if self._running:
                return True
            time.sleep(0.1)
        return self._running

    def _run_proxy(self):
        try:
            opts = moptions.Options(listen_port=self.port, ssl_insecure=True)
            self._master = DumpMaster(opts)
            self._master.addons.add(self._addon)
            self._running = True
            self._master.run()
        except Exception as e:
            logger.error(f"Proxy error: {e}")
            if self.on_error:
                self.on_error(str(e))
            self._running = False

    def stop(self):
        if self._master:
            self._master.shutdown()
        self._running = False
