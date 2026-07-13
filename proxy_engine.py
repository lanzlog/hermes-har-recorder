"""
proxy_engine.py - Hermes HAR Recorder proxy core
mitmproxy 10+ compatible, robust port discovery, long-lived master.
"""

import asyncio
import logging
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Dict, List

# winreg only exists on Windows. Guard the import so the module can be
# imported (and unit-tested) on any platform without crashing.
try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover - non-Windows
    winreg = None

from mitmproxy import options as moptions
from mitmproxy.tools.dump import DumpMaster
from mitmproxy import flow as mflow

from utils import safe_decode, get_content_encoding


# ==================== LOGGER ====================
_log_dir = Path.home() / ".hermes-har-recorder"
_log_dir.mkdir(parents=True, exist_ok=True)
_cert_dir = _log_dir / "certs"
_cert_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(_log_dir / "hermes.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hermes.proxy")


class AppMode:
    RECORD = "record"
    HAR_RECORD = "har_record"
    API_TRACE = "api_trace"
    HAR_TRACE = "har_trace"


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


class HARCaptureAddon:
    def __init__(self, on_flow_complete: Optional[Callable] = None,
                 trace_engine=None):
        self.on_flow_complete = on_flow_complete
        self._flow_counter = 0
        self._app_mode = AppMode.HAR_RECORD
        self._trace_engine = trace_engine
        # When paused, traffic still passes through the proxy transparently
        # but we neither log HAR nor intercept. This lets us keep a single
        # long-lived mitmproxy master across Record/Stop/Record cycles
        # (spinning up a 2nd master in the same process hangs).
        self._capturing = False

    def set_mode(self, mode: str):
        self._app_mode = mode

    def set_capturing(self, capturing: bool):
        self._capturing = capturing

    def requestheaders(self, flow: mflow.Flow):
        # Stamp start time as early as possible for accurate duration.
        if not hasattr(flow, "_har_start_time"):
            flow._har_start_time = time.time()

    def request(self, flow: mflow.Flow):
        if not self._capturing:
            return
        """Intercept requests for API Trace / HAR+Trace modes.

        In trace modes we hand matching requests to the TraceEngine and
        pause the mitmproxy flow. The GUI later calls forward/drop which
        resume or kill the flow. In pure HAR record mode we do nothing here
        (requests pass straight through and get logged on response).
        """
        if self._app_mode not in (AppMode.API_TRACE, AppMode.HAR_TRACE):
            return
        if self._trace_engine is None:
            return
        try:
            req = flow.request
            if not self._trace_engine.should_intercept(req.pretty_url, req.method):
                return
            # Pause the flow until the user forwards/drops it.
            flow.intercept()
            headers = {k: v for k, v in req.headers.items()} if req.headers else {}
            body = safe_decode(req.content) if req.content else ""
            self._trace_engine.intercept_request(
                flow_id=flow.id,
                method=req.method,
                url=req.pretty_url,
                headers=headers,
                body=body,
                host=req.host,
                path=req.path,
                scheme=req.scheme,
                port=req.port or (443 if req.scheme == "https" else 80),
                flow_obj=flow,
            )
        except Exception as e:
            logger.error(f"Error intercepting request: {e}")

    def response(self, flow: mflow.Flow):
        if not self._capturing:
            return
        if self._app_mode == AppMode.API_TRACE:
            return
        try:
            captured = self._convert_flow(flow)
            if captured and self.on_flow_complete:
                self.on_flow_complete(captured)
        except Exception as e:
            logger.error(f"Error processing flow: {e}")

    def _convert_flow(self, flow: mflow.Flow) -> Optional[CapturedRequest]:
        if not hasattr(flow, "request") or not flow.request:
            return None

        req = flow.request
        resp = flow.response
        self._flow_counter += 1
        start_time = getattr(flow, "_har_start_time", time.time())

        cr = CapturedRequest()
        cr.id = f"flow_{self._flow_counter}_{int(start_time * 1000)}"
        cr.method = req.method
        cr.url = req.pretty_url
        cr.scheme = req.scheme
        cr.host = req.host
        cr.port = req.port or (443 if req.scheme == "https" else 80)
        cr.path = req.path
        cr.http_version = getattr(flow, "http_version", "HTTP/1.1") or "HTTP/1.1"

        cr.request_headers = {k: v for k, v in req.headers.items()} if req.headers else {}
        cr.request_body = req.content
        cr.request_body_text = safe_decode(req.content) if req.content else ""
        cr.request_size = len(req.content) if req.content else 0
        cr.request_time = start_time

        if "Cookie" in cr.request_headers:
            for part in cr.request_headers["Cookie"].split(";"):
                if "=" in part:
                    k, v = [x.strip() for x in part.split("=", 1)]
                    cr.request_cookies[k] = v

        if resp:
            cr.status_code = resp.status_code
            cr.reason = resp.reason or ""
            cr.response_headers = {k: v for k, v in resp.headers.items()} if resp.headers else {}
            cr.response_body = resp.content
            cr.response_size = len(resp.content) if resp.content else 0
            cr.response_time = time.time()
            cr.duration = cr.response_time - start_time
            cr.content_type = cr.response_headers.get("Content-Type", "")
            cr.response_body_text = safe_decode(resp.content) if resp.content else ""

            # Response cookies
            set_cookie = cr.response_headers.get("Set-Cookie", "")
            if set_cookie:
                for part in set_cookie.split(","):
                    first = part.split(";", 1)[0]
                    if "=" in first:
                        k, v = [x.strip() for x in first.split("=", 1)]
                        if k:
                            cr.response_cookies[k] = v

        return cr


class ProxyEngine:
    def __init__(self, port: int = 8899, on_flow: Optional[Callable] = None,
                 on_error: Optional[Callable] = None, trace_engine=None):
        self.port = int(port) if port else 8899
        self.preferred_port = self.port
        self.on_flow = on_flow
        self.on_error = on_error
        self._master: Optional[DumpMaster] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._start_error: Optional[str] = None
        self._started_event = threading.Event()
        self._addon = HARCaptureAddon(on_flow_complete=self._handle_flow,
                                      trace_engine=trace_engine)
        self._trace_engine = trace_engine
        # Give the trace engine a way to run flow ops (resume/kill) on the
        # proxy's own event loop thread-safely.
        if trace_engine is not None and hasattr(trace_engine, "set_loop_provider"):
            trace_engine.set_loop_provider(lambda: self._loop)

    def set_mode(self, mode: str):
        self._addon.set_mode(mode)

    @staticmethod
    def is_port_available(port: int) -> bool:
        """Return True if we can bind the proxy port on IPv4.

        Notes / past bugs this fixes:
        - Do NOT set SO_REUSEADDR on the probe. On Windows that can report a
          port as free while another process still holds it, which then makes
          mitmproxy fail to bind and the GUI shows 'port busy' forever.
        - Probe 127.0.0.1 only (what browsers/proxy clients actually hit).
          Probing 0.0.0.0 + :: was flaky: IPv6/permission failures on some
          machines made every port look busy.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                # Intentionally NO SO_REUSEADDR — we want a real free port.
                s.bind(("127.0.0.1", int(port)))
            return True
        except OSError:
            return False
        except Exception:
            return False

    def find_available_port(self, start: Optional[int] = None,
                            max_tries: int = 50) -> int:
        """Find a free port, preferring sequential ports near the preferred one.

        Order:
          1) preferred/start port
          2) start+1 .. start+max_tries
          3) OS-assigned ephemeral port (bind port 0)
        Returns 0 if nothing works.
        """
        base = int(start if start is not None else self.preferred_port or 8899)
        if base < 1024:
            base = 8899

        candidates: List[int] = [base]
        for i in range(1, max_tries + 1):
            candidates.append(base + i)

        seen = set()
        for port in candidates:
            if port in seen or port > 65535:
                continue
            seen.add(port)
            if self.is_port_available(port):
                return port

        # Last resort: let the OS pick any free port.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                free = s.getsockname()[1]
            if free and self.is_port_available(free):
                return free
            return free or 0
        except OSError as e:
            logger.error(f"OS port allocation failed: {e}")
            return 0

    def _handle_flow(self, captured: CapturedRequest):
        if self.on_flow:
            self.on_flow(captured)

    def start(self, mode: Optional[str] = None) -> bool:
        """Start (or resume) capturing.

        The mitmproxy master is long-lived: it's launched once and then kept
        alive across Record/Stop/Record cycles, because starting a second
        DumpMaster in the same process hangs. 'Stop' just pauses capture, so
        'start' here means: ensure the master is up, set the mode, and turn
        capture back on.
        """
        if mode is not None:
            self.set_mode(mode)

        if self._running and self._thread is not None and self._thread.is_alive():
            # Master already up (was paused) — just resume capturing.
            self._addon.set_capturing(True)
            return True

        # Previous thread died / first start — clean stale state.
        if self._thread is not None and not self._thread.is_alive():
            self._running = False
            self._master = None
            self._loop = None
            self._thread = None

        # Try preferred port, then nearby ports, then OS-assigned.
        # Retry the whole start a few times because Windows can race us
        # during TIME_WAIT after a previous unclean exit.
        last_err = None
        for attempt in range(3):
            port = self.find_available_port(
                start=self.preferred_port + (attempt * 10)
            )
            if port <= 0:
                last_err = "Tidak menemukan port tersedia"
                continue

            self.port = port
            self._start_error = None
            self._started_event.clear()
            self._running = False

            self._thread = threading.Thread(
                target=self._run_proxy, daemon=True, name="hermes-proxy"
            )
            self._thread.start()

            # Wait until the proxy thread reports success or failure (max ~12s).
            if self._started_event.wait(timeout=12.0) and self._running:
                self._addon.set_capturing(True)
                if self.port != self.preferred_port:
                    logger.info(
                        f"Port {self.preferred_port} busy → using {self.port}"
                    )
                return True

            last_err = self._start_error or "Proxy gagal start"
            logger.warning(
                f"Proxy start attempt {attempt + 1} failed on :{port}: {last_err}"
            )

            # Ensure dead thread is cleaned before next attempt.
            try:
                if self._thread is not None and self._thread.is_alive():
                    # Best-effort: schedule shutdown if loop came up partially.
                    loop = self._loop
                    master = self._master
                    if master is not None and loop is not None and loop.is_running():
                        loop.call_soon_threadsafe(master.shutdown)
                    self._thread.join(timeout=3.0)
            except Exception:
                pass
            self._running = False
            self._master = None
            self._loop = None
            self._thread = None
            time.sleep(0.3)

        msg = last_err or "Proxy gagal start"
        if self.on_error:
            self.on_error(msg)
        return False

    def _run_proxy(self):
        """Run mitmproxy inside its own asyncio event loop.

        mitmproxy 10+ requires a running event loop to construct DumpMaster
        and `master.run()` is a coroutine. Previously this ran in a bare
        thread with no loop, so DumpMaster raised `no running event loop`
        immediately — that was the silent crash. We now create a dedicated
        loop for this thread and drive the proxy through it.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._serve())
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"Proxy loop error: {e}")
            self._start_error = str(e)
            self._running = False
            self._started_event.set()
        finally:
            try:
                # Cancel leftover tasks so loop.close() is clean.
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass
            self._loop = None
            self._running = False

    async def _serve(self):
        try:
            opts = moptions.Options(
                listen_host="127.0.0.1",
                listen_port=self.port,
                ssl_insecure=True,
                confdir=str(_cert_dir),
            )
            # with_termlog=False keeps mitmproxy from writing to stdout in a
            # windowed .exe (no console) which itself can crash the app.
            self._master = DumpMaster(opts, with_termlog=False, with_dumper=False)
            self._master.addons.add(self._addon)
        except Exception as e:
            logger.error(f"Proxy init error: {e}")
            self._start_error = f"Gagal inisialisasi proxy: {e}"
            self._running = False
            self._started_event.set()
            return

        self._running = True
        self._started_event.set()
        logger.info(f"Proxy listening on 127.0.0.1:{self.port}")
        try:
            await self._master.run()
        except OSError as e:
            # Port bind failures surface here (e.g. address already in use).
            logger.error(f"Proxy bind/run error: {e}")
            self._start_error = f"Port {self.port} tidak bisa dipakai: {e}"
            self._running = False
            # Don't call on_error here — start() will surface _start_error and
            # may still retry another port. Double-emitting confuses the GUI.
        except Exception as e:
            logger.error(f"Proxy run error: {e}")
            self._start_error = str(e)
            self._running = False
        finally:
            # If run() exits early before waiters saw failure, wake them.
            self._started_event.set()

    def stop(self):
        """Pause capturing (keeps the proxy master alive).

        We intentionally do NOT tear down mitmproxy here. Starting a second
        DumpMaster in the same process hangs, so the master stays up between
        Record sessions and 'stop' simply stops logging/intercepting. Full
        teardown happens in shutdown() on app close.
        """
        self._addon.set_capturing(False)
        # Forward any requests still held by the interceptor so the browser
        # doesn't hang waiting on a paused session.
        if self._trace_engine is not None:
            try:
                self._trace_engine.forward_all()
            except Exception as e:
                logger.error(f"Error forwarding pending on stop: {e}")

    def pause(self):
        """Temporarily suspend capture without ending the session.

        Traffic keeps flowing through the proxy (the browser stays usable)
        but nothing is logged or intercepted until resume() is called.
        Pending intercepted requests are forwarded so the browser doesn't
        hang while paused.
        """
        self._addon.set_capturing(False)
        if self._trace_engine is not None:
            try:
                self._trace_engine.forward_all()
            except Exception as e:
                logger.error(f"Error forwarding pending on pause: {e}")

    def resume(self):
        """Resume capturing after pause()."""
        self._addon.set_capturing(True)

    def shutdown(self):
        """Fully stop the proxy and release the port (call on app close).

        mitmproxy's shutdown must be scheduled on its own event loop from
        another thread; calling it directly does nothing and leaves the
        port bound. We schedule shutdown thread-safely and join the thread
        so the socket is fully released before returning.
        """
        self._addon.set_capturing(False)
        master = self._master
        loop = self._loop
        if master is not None and loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(master.shutdown)
            except Exception as e:
                logger.error(f"Error scheduling shutdown: {e}")
        elif master is not None:
            try:
                master.shutdown()
            except Exception:
                pass

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        self._running = False
        self._master = None
        self._thread = None
        self._loop = None


def _refresh_wininet():
    """Notify WinINet that proxy settings changed so they take effect now
    (without a reboot / browser restart)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        internet_set_option = ctypes.windll.Wininet.InternetSetOptionW
        INTERNET_OPTION_SETTINGS_CHANGED = 39
        INTERNET_OPTION_REFRESH = 37
        internet_set_option(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        internet_set_option(0, INTERNET_OPTION_REFRESH, 0, 0)
    except Exception as e:
        logger.error(f"WinINet refresh failed: {e}")


def set_system_proxy(host: str = "127.0.0.1", port: int = 8899):
    """Set Windows system proxy. Accepts (host, port) OR a single int port
    for backwards-compat with older GUI call sites that did
    set_system_proxy(actual_port).
    """
    # Back-compat: set_system_proxy(8899) used to pass port as host.
    if isinstance(host, int) and port == 8899:
        port = host
        host = "127.0.0.1"
    if winreg is None:
        logger.warning("set_system_proxy skipped: not on Windows")
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{int(port)}")
        winreg.CloseKey(key)
        _refresh_wininet()
        logger.info(f"System proxy set to {host}:{port}")
        return True
    except Exception as e:
        logger.error(f"Set system proxy failed: {e}")
        return False


def unset_system_proxy():
    if winreg is None:
        logger.warning("unset_system_proxy skipped: not on Windows")
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        _refresh_wininet()
        logger.info("System proxy disabled")
        return True
    except Exception as e:
        logger.error(f"Unset system proxy failed: {e}")
        return False
