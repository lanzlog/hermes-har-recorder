"""
har_formatter.py - Convert captured flows to HAR 1.2 format.
HAR spec: http://www.softwareishard.com/blog/har-12-spec/
"""

import json
import datetime
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs

from proxy_engine import CapturedRequest
from utils import APP_NAME, APP_VERSION, safe_decode


def _format_cookies(cookies: Dict[str, str]) -> List[Dict[str, Any]]:
    """Format cookies dict to HAR cookies array."""
    result = []
    for name, value in cookies.items():
        result.append({
            "name": name,
            "value": value,
            "httpOnly": False,
            "secure": False,
        })
    return result


def _format_headers(headers: Dict[str, str]) -> List[Dict[str, Any]]:
    """Format headers dict to HAR headers array."""
    result = []
    for name, value in headers.items():
        result.append({"name": name, "value": value})
    return result


def _format_query_string(url: str) -> List[Dict[str, Any]]:
    """Extract query string parameters from URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    result = []
    for name, values in params.items():
        for value in values:
            result.append({"name": name, "value": value})
    return result


def _get_content(body: Optional[bytes], headers: Dict[str, str],
                  text: str = "") -> Dict[str, Any]:
    """Build HAR content object."""
    content: Dict[str, Any] = {
        "size": len(body) if body else 0,
        "compression": 0,
        "mimeType": headers.get("Content-Type", headers.get("content-type", "")),
    }

    if text:
        content["text"] = text
        # Try to detect encoding
        ct = content["mimeType"].lower()
        if "charset=" in ct:
            encoding = ct.split("charset=")[-1].split(";")[0].strip()
            content["encoding"] = encoding

    return content


def _format_timings(captured: CapturedRequest) -> Dict[str, Any]:
    """Format timing information for HAR."""
    duration_ms = captured.duration * 1000 if captured.duration else 0
    return {
        "blocked": -1,
        "dns": -1,
        "connect": -1,
        "send": 0,
        "wait": duration_ms,
        "receive": 0,
        "ssl": -1,
    }


def flow_to_har_entry(captured: CapturedRequest) -> Dict[str, Any]:
    """Convert a CapturedRequest to a HAR entry."""
    # Parse URL for path
    parsed = urlparse(captured.url)
    full_url = captured.url

    # Request
    request = {
        "method": captured.method,
        "url": full_url,
        "httpVersion": captured.http_version,
        "cookies": _format_cookies(captured.request_cookies),
        "headers": _format_headers(captured.request_headers),
        "queryString": _format_query_string(full_url),
        "postData": _get_content(captured.request_body, captured.request_headers,
                                  captured.request_body_text),
        "headersSize": -1,
        "bodySize": captured.request_size,
    }

    # Response
    response = {
        "status": captured.status_code,
        "statusText": captured.reason,
        "httpVersion": captured.http_version,
        "cookies": _format_cookies(captured.response_cookies),
        "headers": _format_headers(captured.response_headers),
        "content": _get_content(captured.response_body, captured.response_headers,
                                 captured.response_body_text),
        "redirectURL": captured.response_headers.get("Location", ""),
        "headersSize": -1,
        "bodySize": captured.response_size,
    }

    # Entry
    start_time = datetime.datetime.fromtimestamp(
        captured.request_time, tz=datetime.timezone.utc
    )

    entry = {
        "startedDateTime": start_time.isoformat(),
        "time": captured.duration * 1000,  # milliseconds
        "request": request,
        "response": response,
        "cache": {},
        "timings": _format_timings(captured),
        "serverIPAddress": captured.host,
        "connection": str(captured.port),
        "comment": captured.step_label if captured.step_label else "",
        "_resourceType": captured.resource_type,
    }

    return entry


def flows_to_har(flows: List[CapturedRequest],
                  title: str = "Hermes HAR Recorder Export") -> Dict[str, Any]:
    """Convert a list of CapturedRequests to a complete HAR 1.2 document."""
    if not flows:
        earliest = datetime.datetime.now(tz=datetime.timezone.utc)
        latest = earliest
    else:
        earliest = datetime.datetime.fromtimestamp(
            min(f.request_time for f in flows), tz=datetime.timezone.utc
        )
        latest = datetime.datetime.fromtimestamp(
            max(f.response_time or f.request_time for f in flows),
            tz=datetime.timezone.utc
        )

    har = {
        "log": {
            "version": "1.2",
            "creator": {
                "name": APP_NAME,
                "version": APP_VERSION,
                "comment": "https://github.com/NousResearch/hermes-har-recorder",
            },
            "pages": [
                {
                    "startedDateTime": earliest.isoformat(),
                    "id": "page_1",
                    "title": title,
                    "pageTimings": {
                        "onContentLoad": -1,
                        "onLoad": -1,
                    },
                }
            ],
            "entries": [],
            "comment": f"Exported {len(flows)} entries on {datetime.datetime.now().isoformat()}",
        }
    }

    for flow in flows:
        try:
            entry = flow_to_har_entry(flow)
            entry["pageref"] = "page_1"
            har["log"]["entries"].append(entry)
        except Exception as e:
            print(f"[har_formatter] Error converting flow {flow.id}: {e}")

    return har


def save_har(har_data: Dict[str, Any], filepath: str) -> bool:
    """Save HAR data to a JSON file."""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(har_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[har_formatter] Error saving HAR: {e}")
        return False


def har_to_json_string(har_data: Dict[str, Any]) -> str:
    """Convert HAR data to formatted JSON string."""
    return json.dumps(har_data, indent=2, ensure_ascii=False)
