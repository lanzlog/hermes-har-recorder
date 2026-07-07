"""
proxy_engine.py - mitmproxy-based HTTP/HTTPS capture engine
Runs mitmproxy in a background thread, emitting captured flows via callbacks.
"""

import asyncio
import os
import sys
import time
import threading
import socket
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timezone

# mitmproxy imports
from mitmproxy import options as moptions
from mitmproxy.tools.dump import DumpMaster
from mitmproxy import flow as mflow
from utils import safe_decode, get_content_encoding


class AppMode:
    """Application operation mode."""
    RECORD = "record"           # Basic recording (no HAR, no intercept)
    HAR_RECORD = "har_record"   # Record + HAR export
    API_TRACE = "api_trace"     # Intercept only (no passive recording)
    HAR_TRACE = "har_trace"     # Both: record HAR + intercept API


@dataclass
class CapturedRequest:
    """Represents a captured HTTP request/response pair."""
    id: str = ""
    # Request
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
    # Response
    status_code: int = 0
    reason: str = ""
    response_headers: Dict[str, str] = field(default_factory=dict)
    response_body: Optional[bytes] = None
    response_size: int = 0
    content_type: str = ""
    # Timing
    request_time: float = 0.0  # timestamp when request started
    response_time: float = 0.0  # timestamp when response received
    duration: float = 0.0  # seconds
    # Metadata
    bookmarked: bool = False
    step_label: str = ""
    resource_type: str = ""  # Set by GUI after capture
    is_oauth: bool = False
    # Content (decoded)
    request_body_text: str = ""
    response_body_text: str = ""
    # Cookies
    request_cookies: Dict[str, str] = field(default_factory=dict)
    response_cookies: Dict[str, str] = field(default_factory=dict)
    # TLS
    tls_version: str = ""
    # Replay
    replayed: bool = False
    # Trace mode
    trace_status: str = ""  # e.g. "intercepted", "forwarded", "dropped", "modified"


class HARCaptureAddon:
    """mitmproxy addon that captures all HTTP/HTTPS flows.
    Supports both passive HAR recording and active API trace interception.
    """

    def __init__(self, on_flow_complete: Optional[Callable] = None,
                 trace_engine=None):
        self.on_flow_complete = on_flow_complete
        self._flow_counter = 0
        self._trace_engine = trace_engine
        self._app_mode = AppMode.HAR_RECORD
        self._on_request_intercepted: Optional[Callable] = None

    def set_mode(self, mode: str):
        """Switch between HAR_RECORD and API_TRACE mode."""
        self._app_mode = mode

    def set_trace_engine(self, trace_engine):
        """Set the trace engine for intercept mode."""
        self._trace_engine = trace_engine

    def set_on_request_intercepted(self, callback: Optional[Callable]):
        """Set callback for when a request is intercepted (called from proxy thread)."""
        self._on_request_intercepted = callback

    def request(self, flow: mflow.Flow):
        """Called when a request is received."""
        flow._har_start_time = time.time()

        # Check if we should intercept (API_TRACE or HAR_TRACE modes)
        should_intercept = self._app_mode in (AppMode.API_TRACE, AppMode.HAR_TRACE)
        if should_intercept and self._trace_engine is not None:
            url = flow.request.pretty_url
            method = flow.request.method

            if self._trace_engine.should_intercept(url, method):
                try:
                    # Extract request data
                    headers = {}
                    for k, v in flow.request.headers.items():
                        headers[k] = v

                    body = ""
                    if flow.request.content:
                        body = flow.request.content.decode("utf-8", errors="replace")

                    # Intercept the flow (pause it)
                    flow.intercept()

                    # Register with trace engine
                    self._trace_engine.intercept_request(
                        flow_id=str(id(flow)),
                        method=method,
                        url=url,
                        headers=headers,
                        body=body,
                        host=flow.request.host,
                        path=flow.request.path,
                        scheme=flow.request.scheme,
                        port=flow.request.port or (443 if flow.request.scheme == 'https' else 80),
                        flow_obj=flow,
                    )
                except Exception as e:
                    print(f"[HARCaptureAddon] Error intercepting request: {e}")
                return  # Don't process further; flow is paused

    def response(self, flow: mflow.Flow):
        """Called when a response is received."""
        # In API_TRACE-only mode, don't record passively
        if self._app_mode == AppMode.API_TRACE:
            return
        try:
            captured = self._convert_flow(flow)
            if captured and self.on_flow_complete:
                self.on_flow_complete(captured)
        except Exception as e:
            print(f"[HARCaptureAddon] Error processing flow: {e}")

    def _convert_flow(self, flow: mflow.Flow) -> Optional[CapturedRequest]:
        """Convert mitmproxy flow to CapturedRequest."""
        if not hasattr(flow, 'request') or not flow.request:
            return None

        req = flow.request
        resp = flow.response

        self._flow_counter += 1
        start_time = getattr(flow, '_har_start_time', time.time())

        # Parse request
        cr = CapturedRequest()
        cr.id = f"flow_{self._flow_counter}_{int(start_time * 1000)}"
        cr.method = req.method
        cr.url = req.pretty_url
        cr.scheme = req.scheme
        cr.host = req.host
        cr.port = req.port or (443 if req.scheme == 'https' else 80)
        cr.path = req.path
        cr.http_version = getattr(flow, 'http_version', 'HTTP/1.1') or 'HTTP/1.1'

        # Request headers
        cr.request_headers = {}
        if req.headers:
            for k, v in req.headers.items():
                cr.request_headers[k] = v

        # Request body
        cr.request_body = req.content
        cr.request_body_text = safe_decode(req.content) if req.content else ""
        cr.request_size = len(req.content) if req.content else 0
        cr.request_time = start_time

        # Cookies from request
        cr.request_cookies = {}
        cookie_header = cr.request_headers.get('Cookie', '')
        if cookie_header:
            for part in cookie_header.split(';'):
                part = part.strip()
                if '=' in part:
                    k, v = part.split('=', 1)
                    cr.request_cookies[k.strip()] = v.strip()

        # Response
        if resp:
            cr.status_code = resp.status_code
            cr.reason = resp.reason or ""
            cr.response_headers = {}
            if resp.headers:
                for k, v in resp.headers.items():
                    cr.response_headers[k] = v

            cr.response_body = resp.content
            cr.response_size = len(resp.content) if resp.content else 0
            cr.response_time = time.time()
            cr.duration = cr.response_time - start_time

            # Content type
            cr.content_type = cr.response_headers.get('Content-Type', '')

            # Decode response body
            encoding = get_content_encoding(cr.response_headers)
            cr.response_body_text = safe_decode(resp.content, encoding) if resp.content else ""

            # Response cookies
            cr.response_cookies = {}
            set_cookie = cr.response_headers.get('Set-Cookie', '')
            if set_cookie:
                for part in set_cookie.split(','):
                    if '=' in part and not part.strip().startswith('Expires') and not part.strip().startswith('Max-Age'):
                        kv = part.split(';')[0].strip()
                        if '=' in kv:
                            k, v = kv.split('=', 1)
                            cr.response_cookies[k.strip()] = v.strip()

            # TLS
            if hasattr(flow, 'tls_version') and flow.tls_version:
                cr.tls_version = flow.tls_version

        return cr


class ProxyEngine:
    """
    Manages mitmproxy instance in a background thread.
    Provides start/stop control and flow callbacks.
    """

    def __init__(self, port: int = 8899, on_flow: Optional[Callable] = None,
                 on_error: Optional[Callable] = None, cert_dir: Optional[str] = None,
                 trace_engine=None):
        self.port = port
        self._original_port = port
        self.on_flow = on_flow
        self.on_error = on_error
        self._master: Optional[DumpMaster] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._addon = HARCaptureAddon(on_flow_complete=self._handle_flow,
                                       trace_engine=trace_engine)
        self._cert_dir = cert_dir or str(Path.home() / ".hermes-har-recorder" / "certs")
        self._app_mode = AppMode.HAR_RECORD

    def set_mode(self, mode: str):
        """Switch the proxy addon between HAR_RECORD and API_TRACE mode."""
        self._app_mode = mode
        self._addon.set_mode(mode)

    def get_mode(self) -> str:
        """Get current mode."""
        return self._app_mode

    def set_trace_engine(self, trace_engine):
        """Set or update the trace engine on the addon."""
        self._addon.set_trace_engine(trace_engine)

    def set_on_request_intercepted(self, callback: Optional[Callable]):
        """Set callback for intercepted requests."""
        self._addon.set_on_request_intercepted(callback)

    @staticmethod
    def is_port_available(port: int) -> bool:
        """Check if a port is available for use."""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.bind(('127.0.0.1', port))
                return True
        except OSError:
            return False

    def find_available_port(self, start_port: int = 8899, max_tries: int = 50) -> int:
        """Find an available port starting from start_port.
        Falls back to OS-assigned port if no port found in range."""
        for i in range(max_tries):
            port = start_port + i
            if self.is_port_available(port):
                return port
        # Fallback: let OS assign a free port
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', 0))
                return s.getsockname()[1]
        except OSError:
            return start_port

    def _handle_flow(self, captured: CapturedRequest):
        """Forward captured flow to the callback (called from proxy thread)."""
        if self.on_flow:
            # Use a thread-safe call - Qt signals handle this in gui_main
            self.on_flow(captured)

    def start(self) -> bool:
        """Start the proxy in a background thread."""
        if self._running:
            return True

        # Try up to 3 different ports
        original_port = self.port
        for attempt in range(3):
            # Auto-find available port if default is busy
            if not self.is_port_available(self.port):
                new_port = self.find_available_port(self.port)
                if new_port != self.port:
                    print(f"[ProxyEngine] Port {self.port} busy, using {new_port}")
                    self.port = new_port
                else:
                    err = f"Port {self.port} and nearby ports are all in use"
                    print(f"[ProxyEngine] {err}")
                    if self.on_error:
                        self.on_error(err)
                    return False

            # Ensure cert directory exists
            Path(self._cert_dir).mkdir(parents=True, exist_ok=True)

            self._thread = threading.Thread(target=self._run_proxy, daemon=True)
            self._thread.start()

            # Wait for proxy to be ready
            for _ in range(50):  # 5 seconds max
                if self._running:
                    return True
                time.sleep(0.1)

            # Proxy failed to start — try next port
            print(f"[ProxyEngine] Failed on port {self.port}, attempt {attempt+1}/3")
            self._running = False
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2)
            self.port = original_port + (attempt + 1) * 10

        if self.on_error:
            self.on_error(f"Failed to start proxy after 3 attempts")
        self.port = original_port
        return False

    def _run_proxy(self):
        """Run the mitmproxy event loop in a background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._run_proxy_async())
        except Exception as e:
            print(f"[ProxyEngine] Fatal error: {e}")
            if self.on_error:
                self.on_error(str(e))
        finally:
            self._running = False
            self._loop.close()

    async def _run_proxy_async(self):
        """Async proxy runner."""
        try:
            opts = moptions.Options(
                listen_port=self.port,
                ssl_insecure=True,
                upstream_cert=False,
                confdir=self._cert_dir,
            )

            self._master = DumpMaster(options=opts)
            self._master.addons.add(self._addon)
            self._running = True

            # This blocks until master is shut down
            await self._master.run()
        except Exception as e:
            print(f"[ProxyEngine] Async error: {e}")
            if self.on_error:
                self.on_error(str(e))
        finally:
            self._running = False

    def stop(self):
        """Stop the proxy."""
        if not self._running:
            return

        try:
            if self._master and self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._shutdown_master(), self._loop
                )
        except Exception as e:
            print(f"[ProxyEngine] Error stopping: {e}")

        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    async def _shutdown_master(self):
        """Shutdown the mitmproxy master."""
        if self._master:
            try:
                self._master.shutdown()
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        return self._running

    def get_cert_path(self) -> str:
        """Get path to the mitmproxy CA certificate."""
        cert_path = Path(self._cert_dir) / "mitmproxy-ca-cert.pem"
        return str(cert_path)

    def get_listen_info(self) -> str:
        """Get proxy listen address info."""
        hostname = socket.gethostname()
        try:
            local_ip = socket.gethostbyname(hostname)
        except Exception:
            local_ip = "127.0.0.1"
        return f"http://{local_ip}:{self.port}"


def set_system_proxy(port: int) -> bool:
    """Set the system proxy (Windows only, via registry)."""
    try:
        if sys.platform == 'win32':
            import winreg
            internet_settings = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(internet_settings, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(internet_settings, "ProxyServer", 0, winreg.REG_SZ, f"127.0.0.1:{port}")
            winreg.CloseKey(internet_settings)
            return True
    except Exception as e:
        print(f"[set_system_proxy] Error: {e}")
    return False


def unset_system_proxy() -> bool:
    """Remove system proxy settings (Windows only)."""
    try:
        if sys.platform == 'win32':
            import winreg
            internet_settings = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(internet_settings, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(internet_settings)
            return True
    except Exception as e:
        print(f"[unset_system_proxy] Error: {e}")
    return False
