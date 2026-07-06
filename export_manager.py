"""
export_manager.py - Export captured traffic to various formats.
HAR, CSV, JSON, cURL, Python requests, fetch() snippets.
"""

import csv
import json
import io
import shlex
from typing import List, Dict

from proxy_engine import CapturedRequest
from har_formatter import flows_to_har, save_har


def to_curl(flow: CapturedRequest) -> str:
    """Convert a captured request to cURL command."""
    parts = ["curl", "-X", flow.method]

    # URL (properly shell-quoted)
    parts.append(shlex.quote(flow.url))

    # Headers
    skip_headers = {'host', 'content-length', 'transfer-encoding'}
    for key, value in flow.request_headers.items():
        if key.lower() not in skip_headers:
            header_line = f"{key}: {value}"
            parts.extend(["-H", shlex.quote(header_line)])

    # Body
    if flow.request_body_text and flow.method in ('POST', 'PUT', 'PATCH'):
        parts.extend(["-d", shlex.quote(flow.request_body_text)])

    # Insecure for HTTPS
    if flow.scheme == 'https':
        parts.insert(1, "-k")

    return " \\\n  ".join(parts)


def to_python_requests(flow: CapturedRequest) -> str:
    """Convert a captured request to Python requests code."""
    lines = ["import requests", ""]

    # URL
    lines.append(f"url = {repr(flow.url)}")

    # Headers
    if flow.request_headers:
        skip_headers = {'host', 'content-length', 'transfer-encoding'}
        lines.append("headers = {")
        for key, value in flow.request_headers.items():
            if key.lower() not in skip_headers:
                lines.append(f"    {repr(key)}: {repr(value)},")
        lines.append("}")

    # Body
    body_param = ""
    if flow.request_body_text and flow.method in ('POST', 'PUT', 'PATCH'):
        # Try to parse as JSON regardless of Content-Type header
        parsed_json = None
        try:
            parsed_json = json.loads(flow.request_body_text)
        except (json.JSONDecodeError, ValueError, TypeError):
            parsed_json = None

        if parsed_json is not None:
            # Valid JSON body -> use json= param with parsed dict/list literal
            lines.append(f"json_data = {repr(parsed_json)}")
            body_param = ", json=json_data"
        else:
            # Not valid JSON -> raw data (properly escaped via repr())
            lines.append(f"data = {repr(flow.request_body_text)}")
            body_param = ", data=data"

    # Request
    method = flow.method.lower()
    verify = ", verify=False" if flow.scheme == 'https' else ""
    headers_param = ", headers=headers" if flow.request_headers else ""

    lines.append("")
    lines.append(f"response = requests.{method}(url{headers_param}{body_param}{verify})")
    lines.append("print(response.status_code)")
    lines.append("print(response.text)")

    return "\n".join(lines)


def to_fetch(flow: CapturedRequest) -> str:
    """Convert a captured request to JavaScript fetch() code."""
    options: Dict = {"method": flow.method}

    # Headers
    skip_headers = {'host', 'content-length', 'transfer-encoding'}
    headers = {}
    for key, value in flow.request_headers.items():
        if key.lower() not in skip_headers:
            headers[key] = value
    if headers:
        options["headers"] = headers

    # Body
    if flow.request_body_text and flow.method in ('POST', 'PUT', 'PATCH'):
        options["body"] = flow.request_body_text

    options_json = json.dumps(options, indent=2)

    return f"""fetch({json.dumps(flow.url)}, {options_json})
  .then(response => response.json())
  .then(data => console.log(data))
  .catch(error => console.error('Error:', error));"""


def to_csv_string(flows: List[CapturedRequest]) -> str:
    """Export flows to CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Method", "URL", "Status", "Size (bytes)", "Time (ms)",
        "Content-Type", "Duration", "Host"
    ])
    for flow in flows:
        writer.writerow([
            flow.method,
            flow.url,
            flow.status_code,
            flow.response_size,
            f"{flow.duration * 1000:.0f}",
            flow.content_type,
            f"{flow.duration:.3f}s",
            flow.host,
        ])
    return output.getvalue()


def to_json_string(flows: List[CapturedRequest]) -> str:
    """Export flows to custom JSON format."""
    entries = []
    for flow in flows:
        entry = {
            "id": flow.id,
            "method": flow.method,
            "url": flow.url,
            "status": flow.status_code,
            "statusText": flow.reason,
            "requestSize": flow.request_size,
            "responseSize": flow.response_size,
            "duration": round(flow.duration * 1000, 2),
            "contentType": flow.content_type,
            "host": flow.host,
            "timestamp": flow.request_time,
            "requestHeaders": flow.request_headers,
            "responseHeaders": flow.response_headers,
            "requestBody": flow.request_body_text,
            "responseBody": flow.response_body_text[:10000] if flow.response_body_text else "",
            "bookmarked": flow.bookmarked,
            "stepLabel": flow.step_label,
            "resourceType": flow.resource_type,
        }
        entries.append(entry)

    return json.dumps({
        "version": "1.0",
        "exporter": "Hermes HAR Recorder",
        "count": len(entries),
        "entries": entries,
    }, indent=2)


def save_csv(flows: List[CapturedRequest], filepath: str) -> bool:
    """Save flows to CSV file."""
    try:
        content = to_csv_string(flows)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"[export_manager] Error saving CSV: {e}")
        return False


def save_json(flows: List[CapturedRequest], filepath: str) -> bool:
    """Save flows to JSON file."""
    try:
        content = to_json_string(flows)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"[export_manager] Error saving JSON: {e}")
        return False


def export_full_har(flows: List[CapturedRequest], filepath: str) -> bool:
    """Export all flows to HAR file."""
    har = flows_to_har(flows)
    return save_har(har, filepath)


def export_selected_har(flows: List[CapturedRequest], filepath: str) -> bool:
    """Export selected flows to HAR file."""
    har = flows_to_har(flows, title="Hermes HAR Recorder - Selected Export")
    return save_har(har, filepath)
