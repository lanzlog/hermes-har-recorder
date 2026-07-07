"""
utils.py - Utility functions for HAR Recorder
"""

import os
import sys
import json
import hashlib
import platform
import datetime
from pathlib import Path
from typing import Optional, Dict, Any


# --- Paths & Config ---

APP_NAME = "Hermes HAR Recorder"
APP_VERSION = "1.0.0"
SESSION_DIR = Path.home() / ".hermes-har-sessions"
CONFIG_FILE = Path.home() / ".hermes-har-recorder" / "config.json"

# Resource type extensions for classification
STATIC_EXTENSIONS = {
    'js', 'css', 'png', 'jpg', 'jpeg', 'gif', 'svg', 'ico', 'woff', 'woff2',
    'ttf', 'eot', 'map', 'webp', 'avif', 'bmp', 'tiff', 'mp3', 'mp4',
    'webm', 'ogg', 'flac', 'wav', 'avi', 'mov', 'wmv', 'pdf', 'zip',
    'tar', 'gz', 'rar', '7z', 'exe', 'dll', 'so', 'dylib', 'class',
}

XHR_CONTENT_TYPES = {
    'application/json', 'application/xml', 'text/xml', 'application/x-ndjson',
}

AUTH_DOMAINS = {
    'accounts.google.com', 'login.microsoftonline.com', 'login.live.com',
    'github.com/login', 'api.twitter.com/oauth', 'facebook.com/v*/dialog/oauth',
    'auth0.com', 'okta.com', 'cognito-idp', 'oauth2', 'authorize', 'token',
    'login', 'signin', 'auth', 'sso',
}


def ensure_dirs():
    """Create application directories."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, Any]:
    """Load application configuration."""
    defaults = {
        "proxy_port": 8899,
        "auto_set_proxy": True,
        "dark_theme": True,
        "always_on_top": False,
        "auto_save": True,
        "auto_save_interval": 60,
        "hide_static": False,
        "window_geometry": None,
        "last_session": None,
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved = json.load(f)
            defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_config(config: Dict[str, Any]):
    """Save application configuration."""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save config: {e}")


def get_mime_category(content_type: str, url: str = "") -> str:
    """Classify content type into a category."""
    ct = content_type.lower() if content_type else ""
    url_lower = url.lower()

    if not ct and url:
        ext = url_lower.rsplit('.', 1)[-1].split('?')[0] if '.' in url_lower else ''
        if ext in {'js', 'mjs'}:
            return 'JS'
        if ext == 'css':
            return 'CSS'
        if ext in {'png', 'jpg', 'jpeg', 'gif', 'svg', 'ico', 'webp', 'avif', 'bmp'}:
            return 'Image'
        if ext in {'woff', 'woff2', 'ttf', 'eot'}:
            return 'Font'
        if ext in {'mp4', 'webm', 'avi', 'mov'}:
            return 'Media'
        if ext == 'html' or ext == 'htm':
            return 'Document'

    if 'json' in ct or 'xml' in ct:
        return 'XHR'
    if 'javascript' in ct:
        return 'JS'
    if 'css' in ct:
        return 'CSS'
    if 'image/' in ct:
        return 'Image'
    if 'font/' in ct or 'woff' in ct:
        return 'Font'
    if 'html' in ct:
        return 'Document'
    if 'video/' in ct or 'audio/' in ct:
        return 'Media'
    if 'text/plain' in ct:
        return 'Document'

    # Default heuristic from URL
    if any(url_lower.endswith(ext) for ext in ('.js', '.mjs')):
        return 'JS'
    if url_lower.endswith('.css'):
        return 'CSS'
    if any(url_lower.endswith(f'.{e}') for e in ('png', 'jpg', 'jpeg', 'gif', 'svg', 'ico', 'webp')):
        return 'Image'

    return 'XHR'  # Default to XHR for unknown


def is_static_resource(content_type: str, url: str) -> bool:
    """Check if a resource is static (images, fonts, etc.)."""
    cat = get_mime_category(content_type, url)
    return cat in ('Image', 'Font', 'Media', 'CSS', 'JS')


def format_size(size_bytes: Optional[int]) -> str:
    """Format byte size to human-readable string."""
    if size_bytes is None or size_bytes < 0:
        return "0B"
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


def format_duration(seconds: Optional[float]) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds is None or seconds < 0:
        return "0ms"
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.0f}µs"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    return f"{seconds:.2f}s"


def generate_session_name() -> str:
    """Generate a session filename with timestamp."""
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"session_{now}"


def get_status_class(status_code: int) -> str:
    """Classify HTTP status code."""
    if 200 <= status_code < 300:
        return "2xx"
    if 300 <= status_code < 400:
        return "3xx"
    if 400 <= status_code < 500:
        return "4xx"
    if 500 <= status_code < 600:
        return "5xx"
    return "other"


def detect_oauth_flow(url: str, status_code: int) -> bool:
    """Detect if a request is part of an OAuth flow."""
    if status_code not in (301, 302, 303, 307, 308):
        return False
    url_lower = url.lower()
    return any(domain in url_lower for domain in AUTH_DOMAINS)


def extract_tokens_from_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Extract auth tokens and API keys from headers."""
    tokens = {}
    for key, value in headers.items():
        key_lower = key.lower()
        if key_lower in ('authorization', 'x-api-key', 'x-auth-token',
                          'x-access-token', 'cookie'):
            # Mask long values
            if len(value) > 50:
                tokens[key] = value[:50] + "..."
            else:
                tokens[key] = value
    return tokens


def safe_decode(data: Optional[bytes], encoding: str = 'utf-8') -> str:
    """Safely decode bytes to string."""
    if data is None:
        return ""
    try:
        return data.decode(encoding, errors='replace')
    except Exception:
        return data.decode('latin-1', errors='replace')


def get_content_encoding(headers: Dict[str, str]) -> str:
    """Get content encoding from headers."""
    for key, value in headers.items():
        if key.lower() == 'content-type':
            if 'charset=' in value.lower():
                charset = value.lower().split('charset=')[-1].split(';')[0].strip()
                return charset
    return 'utf-8'


def is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system() == 'Windows'
