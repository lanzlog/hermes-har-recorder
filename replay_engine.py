"""
replay_engine.py - Replay captured HTTP requests with edit capability.
Uses the requests library to replay captured flows.
"""

import json
import time
import threading
from typing import Optional, Callable, Dict, Any
from urllib.parse import urlparse

import requests as req_lib

from proxy_engine import CapturedRequest


class ReplayResult:
    """Result of a replayed request."""

    def __init__(self):
        self.status_code: int = 0
        self.reason: str = ""
        self.headers: Dict[str, str] = {}
        self.body: str = ""
        self.body_bytes: bytes = b""
        self.duration: float = 0.0
        self.error: str = ""
        self.success: bool = False


def replay_request(flow: CapturedRequest,
                    modified_url: Optional[str] = None,
                    modified_method: Optional[str] = None,
                    modified_headers: Optional[Dict[str, str]] = None,
                    modified_body: Optional[str] = None,
                    timeout: int = 30) -> ReplayResult:
    """
    Replay a captured request with optional modifications.
    Runs synchronously - call from a thread if needed.
    """
    result = ReplayResult()

    url = modified_url or flow.url
    method = (modified_method or flow.method).upper()
    headers = modified_headers if modified_headers is not None else flow.request_headers
    body = modified_body if modified_body is not None else flow.request_body_text

    # Remove problematic headers
    clean_headers = {}
    skip = {'host', 'content-length', 'transfer-encoding', 'accept-encoding'}
    for k, v in headers.items():
        if k.lower() not in skip:
            clean_headers[k] = v

    try:
        start = time.time()
        response = req_lib.request(
            method=method,
            url=url,
            headers=clean_headers,
            data=body if body else None,
            timeout=timeout,
            verify=self._get_verify(),
            allow_redirects=True,
        )
        result.duration = time.time() - start
        result.status_code = response.status_code
        result.reason = response.reason
        result.headers = dict(response.headers)
        result.body_bytes = response.content
        result.body = response.text
        result.success = True

    except req_lib.exceptions.Timeout:
        result.error = "Request timed out"
    except req_lib.exceptions.ConnectionError as e:
        result.error = f"Connection error: {str(e)}"
    except req_lib.exceptions.RequestException as e:
        result.error = f"Request error: {str(e)}"
    except Exception as e:
        result.error = f"Unexpected error: {str(e)}"

    return result


class ReplayEngine:
    """
    Manages request replay in background threads.
    Notifies GUI via callback when replay completes.
    """

    def __init__(self, on_complete: Optional[Callable] = None,
                 on_error: Optional[Callable] = None):
        self.on_complete = on_complete
        self.on_error = on_error

    def _get_verify(self):
        """Return cert path for TLS verification, or False as fallback."""
        from pathlib import Path
        cert = Path.home() / ".hermes-har-recorder" / "certs" / "mitmproxy-ca-cert.pem"
        return str(cert) if cert.exists() else False

    def replay_async(self, flow: CapturedRequest,
                      modified_url: Optional[str] = None,
                      modified_method: Optional[str] = None,
                      modified_headers: Optional[Dict[str, str]] = None,
                      modified_body: Optional[str] = None):
        """Replay a request in a background thread."""
        thread = threading.Thread(
            target=self._do_replay,
            args=(flow, modified_url, modified_method, modified_headers, modified_body),
            daemon=True,
        )
        thread.start()

    def _do_replay(self, flow, url, method, headers, body):
        """Execute replay and notify callback."""
        try:
            result = replay_request(flow, url, method, headers, body)
            if self.on_complete:
                self.on_complete(flow, result)
        except Exception as e:
            if self.on_error:
                self.on_error(str(e))


class EditRequestDialog:
    """
    Data holder for request editing (actual dialog is in GUI).
    Stores the modified request fields.
    """

    def __init__(self, flow: CapturedRequest):
        self.original_flow = flow
        self.url = flow.url
        self.method = flow.method
        self.headers = dict(flow.request_headers)
        self.body = flow.request_body_text
        self.headers_text = self._headers_to_text(flow.request_headers)

    def _headers_to_text(self, headers: Dict[str, str]) -> str:
        """Convert headers dict to text format."""
        return "\n".join(f"{k}: {v}" for k, v in headers.items())

    def parse_headers_text(self, text: str) -> Dict[str, str]:
        """Parse headers from text format."""
        headers = {}
        for line in text.strip().split("\n"):
            line = line.strip()
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip()] = value.strip()
        return headers

    def get_headers(self) -> Dict[str, str]:
        """Get modified headers."""
        return self.parse_headers_text(self.headers_text)
