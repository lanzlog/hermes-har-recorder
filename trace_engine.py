"""
trace_engine.py - API Trace / Intercept Mode engine.
Manages request interception, rule matching, and flow control.
Works with mitmproxy's intercept/resume/kill mechanism.
"""

import re
import time
import uuid
import threading
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, List, Any


@dataclass
class InterceptedRequest:
    """A request held for inspection/modification."""
    id: str = ""
    flow_id: str = ""          # reference to mitmproxy flow
    method: str = ""
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    body: str = ""
    content_type: str = ""
    timestamp: float = 0.0
    status: str = "intercepted"  # "intercepted", "forwarded", "dropped", "modified"
    original_headers: Dict[str, str] = field(default_factory=dict)
    original_body: str = ""
    # Extra metadata from flow
    host: str = ""
    path: str = ""
    scheme: str = ""
    port: int = 80


@dataclass
class InterceptRule:
    """A single intercept rule."""
    pattern: str = ""
    match_type: str = "contains"  # contains, regex, exact, prefix
    method_filter: str = "ALL"     # ALL, GET, POST, PUT, DELETE, PATCH
    enabled: bool = True

    def matches(self, url: str, method: str) -> bool:
        """Check if a URL+method matches this rule."""
        # Method filter
        if self.method_filter != "ALL" and method.upper() != self.method_filter.upper():
            return False

        if not self.enabled:
            return False

        try:
            if self.match_type == "contains":
                return self.pattern.lower() in url.lower()
            elif self.match_type == "exact":
                return url == self.pattern
            elif self.match_type == "prefix":
                return url.lower().startswith(self.pattern.lower())
            elif self.match_type == "regex":
                return bool(re.search(self.pattern, url, re.IGNORECASE))
        except re.error:
            return False
        except Exception:
            return False

        return False


class TraceEngine:
    """
    Manages request interception and forwarding for API Trace mode.
    Thread-safe: all state mutations are protected by a lock.
    """

    def __init__(self):
        self.intercept_enabled: bool = False
        self.intercept_rules: List[InterceptRule] = []
        self.pending_requests: List[InterceptedRequest] = []
        self.completed_requests: List[InterceptedRequest] = []  # history
        self.on_request_intercepted: Optional[Callable] = None  # callback(InterceptedRequest)
        self.on_request_completed: Optional[Callable] = None   # callback(InterceptedRequest)
        self._flow_map: Dict[str, Any] = {}  # flow_id -> mitmproxy flow object
        self._lock = threading.Lock()
        self._counter = 0
        # Callable returning the proxy's asyncio loop (set by ProxyEngine).
        # mitmproxy flow.resume()/kill() must run on that loop's thread.
        self._loop_provider: Optional[Callable] = None

    def set_loop_provider(self, provider: Callable):
        """Register a callable that returns the proxy event loop."""
        self._loop_provider = provider

    def _run_on_loop(self, fn):
        """Run a flow operation on the proxy loop thread if available,
        otherwise run it inline."""
        loop = self._loop_provider() if self._loop_provider else None
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(fn)
        else:
            fn()

    def add_rule(self, pattern: str, match_type: str = "contains",
                 method_filter: str = "ALL") -> InterceptRule:
        """Add intercept rule."""
        rule = InterceptRule(
            pattern=pattern,
            match_type=match_type,
            method_filter=method_filter,
            enabled=True,
        )
        with self._lock:
            self.intercept_rules.append(rule)
        return rule

    def remove_rule(self, index: int):
        """Remove intercept rule by index."""
        with self._lock:
            if 0 <= index < len(self.intercept_rules):
                self.intercept_rules.pop(index)

    def clear_rules(self):
        """Remove all intercept rules."""
        with self._lock:
            self.intercept_rules.clear()

    def should_intercept(self, url: str, method: str) -> bool:
        """Check if request matches any intercept rule.
        
        Behavior:
        - Intercept disabled → False
        - Intercept enabled, no rules → True (intercept everything, like Burp)
        - Intercept enabled, rules exist → True only if a rule matches
        """
        if not self.intercept_enabled:
            return False

        with self._lock:
            if not self.intercept_rules:
                # No rules configured: intercept all (Burp-like behavior)
                return True
            for rule in self.intercept_rules:
                if rule.matches(url, method):
                    return True

        return False

    def should_intercept_strict(self, url: str, method: str) -> bool:
        """Only intercept if rules explicitly match. If no rules, don't intercept."""
        if not self.intercept_enabled:
            return False

        with self._lock:
            if not self.intercept_rules:
                return False
            for rule in self.intercept_rules:
                if rule.matches(url, method):
                    return True
        return False

    def intercept_request(self, flow_id: str, method: str, url: str,
                          headers: Dict[str, str], body: str,
                          host: str = "", path: str = "",
                          scheme: str = "", port: int = 80,
                          flow_obj: Any = None) -> InterceptedRequest:
        """Hold a request for inspection."""
        with self._lock:
            self._counter += 1
            req_id = f"trace_{self._counter}_{int(time.time() * 1000)}"

            intercepted = InterceptedRequest(
                id=req_id,
                flow_id=flow_id,
                method=method,
                url=url,
                headers=dict(headers),
                body=body,
                content_type=headers.get("Content-Type", ""),
                timestamp=time.time(),
                status="intercepted",
                original_headers=dict(headers),
                original_body=body,
                host=host,
                path=path,
                scheme=scheme,
                port=port,
            )

            self.pending_requests.append(intercepted)
            if flow_obj is not None:
                self._flow_map[req_id] = flow_obj

        # Notify callback (outside lock to avoid deadlock)
        if self.on_request_intercepted:
            try:
                self.on_request_intercepted(intercepted)
            except Exception as e:
                print(f"[TraceEngine] Callback error: {e}")

        return intercepted

    def forward_request(self, request_id: str, modified_data: Optional[dict] = None) -> bool:
        """
        Forward request (optionally with modifications) to server.
        Returns True if the request was found and forwarded.
        """
        with self._lock:
            req = self._find_pending(request_id)
            if not req:
                return False

            flow = self._flow_map.get(request_id)

            # Apply modifications if provided
            if modified_data:
                try:
                    if flow is not None and "headers" in modified_data:
                        # Clear existing headers and set new ones
                        flow.request.headers.clear()
                        for k, v in modified_data["headers"].items():
                            flow.request.headers[k] = v
                        req.headers = dict(modified_data["headers"])
                    elif "headers" in modified_data:
                        req.headers = dict(modified_data["headers"])

                    if flow is not None and "body" in modified_data:
                        body_bytes = modified_data["body"].encode("utf-8") if isinstance(modified_data["body"], str) else modified_data["body"]
                        flow.request.content = body_bytes
                        req.body = modified_data["body"] if isinstance(modified_data["body"], str) else modified_data["body"].decode("utf-8", errors="replace")
                    elif "body" in modified_data:
                        req.body = modified_data["body"]

                    if flow is not None and "method" in modified_data:
                        flow.request.method = modified_data["method"]
                        req.method = modified_data["method"]
                    elif "method" in modified_data:
                        req.method = modified_data["method"]

                    if flow is not None and "url" in modified_data:
                        # mitmproxy URL changes need special handling
                        from urllib.parse import urlparse
                        parsed = urlparse(modified_data["url"])
                        flow.request.scheme = parsed.scheme
                        flow.request.host = parsed.hostname
                        flow.request.port = parsed.port or (443 if parsed.scheme == "https" else 80)
                        flow.request.path = parsed.path + ("?" + parsed.query if parsed.query else "")
                        req.url = modified_data["url"]
                    elif "url" in modified_data:
                        req.url = modified_data["url"]

                    req.status = "modified"
                except Exception as e:
                    print(f"[TraceEngine] Error modifying request: {e}")
                    req.status = "forwarded"
            else:
                req.status = "forwarded"

            # Move from pending to completed
            self.pending_requests.remove(req)
            self.completed_requests.append(req)

            # Resume the mitmproxy flow (on the proxy loop thread)
            if flow is not None:
                try:
                    self._run_on_loop(flow.resume)
                except Exception as e:
                    print(f"[TraceEngine] Error resuming flow: {e}")
                finally:
                    self._flow_map.pop(request_id, None)

        # Notify callback
        if self.on_request_completed:
            try:
                self.on_request_completed(req)
            except Exception:
                pass

        return True

    def drop_request(self, request_id: str) -> bool:
        """Drop/block the request."""
        with self._lock:
            req = self._find_pending(request_id)
            if not req:
                return False

            flow = self._flow_map.get(request_id)
            req.status = "dropped"

            # Move from pending to completed
            self.pending_requests.remove(req)
            self.completed_requests.append(req)

            # Kill the mitmproxy flow (on the proxy loop thread)
            if flow is not None:
                try:
                    self._run_on_loop(flow.kill)
                except Exception as e:
                    print(f"[TraceEngine] Error killing flow: {e}")
                finally:
                    self._flow_map.pop(request_id, None)

        # Notify callback
        if self.on_request_completed:
            try:
                self.on_request_completed(req)
            except Exception:
                pass

        return True

    def forward_all(self):
        """Forward all pending requests."""
        # Copy list to avoid mutation during iteration
        with self._lock:
            pending_ids = [r.id for r in self.pending_requests]

        for rid in pending_ids:
            self.forward_request(rid)

    def drop_all(self):
        """Drop all pending requests."""
        with self._lock:
            pending_ids = [r.id for r in self.pending_requests]

        for rid in pending_ids:
            self.drop_request(rid)

    def get_pending_count(self) -> int:
        """Get number of pending intercepted requests."""
        with self._lock:
            return len(self.pending_requests)

    def get_rules_display(self) -> List[str]:
        """Get a list of rule descriptions for display."""
        with self._lock:
            result = []
            for rule in self.intercept_rules:
                method_part = f" [{rule.method_filter}]" if rule.method_filter != "ALL" else ""
                match_label = {"contains": "~", "exact": "=", "prefix": "^", "regex": ".*"}.get(rule.match_type, "?")
                enabled_mark = "" if rule.enabled else " (disabled)"
                result.append(f"{match_label} {rule.pattern}{method_part}{enabled_mark}")
            return result

    def get_pending_requests(self) -> List[InterceptedRequest]:
        """Get a copy of pending requests list."""
        with self._lock:
            return list(self.pending_requests)

    def get_completed_requests(self) -> List[InterceptedRequest]:
        """Get a copy of completed requests list."""
        with self._lock:
            return list(self.completed_requests)

    def clear_history(self):
        """Clear completed requests history."""
        with self._lock:
            self.completed_requests.clear()

    def get_request_by_id(self, request_id: str) -> Optional[InterceptedRequest]:
        """Find a request by ID in pending or completed."""
        with self._lock:
            req = self._find_pending(request_id)
            if req:
                return req
            for req in self.completed_requests:
                if req.id == request_id:
                    return req
        return None

    def _find_pending(self, request_id: str) -> Optional[InterceptedRequest]:
        """Find a pending request by ID (must hold lock)."""
        for req in self.pending_requests:
            if req.id == request_id:
                return req
        return None

    def save_rules_to_list(self) -> List[dict]:
        """Serialize rules to a list of dicts for saving."""
        with self._lock:
            return [
                {
                    "pattern": r.pattern,
                    "match_type": r.match_type,
                    "method_filter": r.method_filter,
                    "enabled": r.enabled,
                }
                for r in self.intercept_rules
            ]

    def load_rules_from_list(self, rules_data: List[dict]):
        """Load rules from serialized data."""
        with self._lock:
            self.intercept_rules.clear()
            for rd in rules_data:
                self.intercept_rules.append(InterceptRule(
                    pattern=rd.get("pattern", ""),
                    match_type=rd.get("match_type", "contains"),
                    method_filter=rd.get("method_filter", "ALL"),
                    enabled=rd.get("enabled", True),
                ))
