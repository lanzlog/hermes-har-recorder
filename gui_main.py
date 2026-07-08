"""
gui_main.py - PyQt6 main window for HAR Recorder.
Features: request table, detail panel, filters, search, syntax highlighting.
"""

import os
import sys
import json
import time
import copy
from pathlib import Path
from typing import List, Optional, Dict, Set
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QSplitter, QPushButton,
    QLabel, QLineEdit, QComboBox, QToolBar, QStatusBar, QMenuBar,
    QFileDialog, QMessageBox, QDialog, QFormLayout, QDialogButtonBox,
    QCheckBox, QHeaderView, QApplication, QMenu, QAbstractItemView,
    QGroupBox, QGridLayout, QTextBrowser, QPlainTextEdit, QStyle,
    QStyledItemDelegate,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QThread, QSize, QSortFilterProxyModel,
    QSettings, QMimeData,
)
from PyQt6.QtGui import (
    QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QPalette,
    QAction, QKeySequence, QIcon, QClipboard, QBrush,
)

from proxy_engine import CapturedRequest, AppMode
from utils import (
    format_size, format_duration, get_mime_category, is_static_resource,
    generate_session_name, get_status_class, detect_oauth_flow,
    extract_tokens_from_headers, SESSION_DIR, save_config, load_config,
    APP_NAME, APP_VERSION,
)
from export_manager import (
    to_curl, to_python_requests, to_fetch, export_full_har,
    export_selected_har, save_csv, save_json,
)
from replay_engine import ReplayEngine, replay_request, EditRequestDialog
from trace_engine import TraceEngine, InterceptedRequest


# ─── Syntax Highlighting ──────────────────────────────────────────────────────

class JSONHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for JSON content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules = []

        # Strings
        string_fmt = QTextCharFormat()
        string_fmt.setForeground(QColor("#98C379"))
        self._rules.append((r'"[^"]*"\s*(?=:)', string_fmt))  # keys
        self._rules.append((r':\s*"[^"]*"', string_fmt))  # string values

        # Numbers
        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor("#D19A66"))
        self._rules.append((r'\b-?\d+\.?\d*\b', num_fmt))

        # Booleans & null
        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#56B6C2"))
        self._rules.append((r'\b(true|false|null)\b', kw_fmt))

        # Braces
        brace_fmt = QTextCharFormat()
        brace_fmt.setForeground(QColor("#ABB2BF"))
        self._rules.append((r'[{}\[\]]', brace_fmt))

    def highlightBlock(self, text):
        import re
        for pattern, fmt in self._rules:
            for match in re.finditer(pattern, text):
                start = match.start()
                length = match.end() - start
                self.setFormat(start, length, fmt)


class HTMLHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for HTML content."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def highlightBlock(self, text):
        import re
        # Tags
        tag_fmt = QTextCharFormat()
        tag_fmt.setForeground(QColor("#E06C75"))
        for m in re.finditer(r'</?[\w-]+', text):
            self.setFormat(m.start(), m.end() - m.start(), tag_fmt)

        # Attributes
        attr_fmt = QTextCharFormat()
        attr_fmt.setForeground(QColor("#D19A66"))
        for m in re.finditer(r'\b[\w-]+(?==)', text):
            self.setFormat(m.start(), m.end() - m.start(), attr_fmt)

        # Strings
        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor("#98C379"))
        for m in re.finditer(r'"[^"]*"', text):
            self.setFormat(m.start(), m.end() - m.start(), str_fmt)

        # Comments
        cmt_fmt = QTextCharFormat()
        cmt_fmt.setForeground(QColor("#5C6370"))
        cmt_fmt.setFontItalic(True)
        for m in re.finditer(r'<!--.*?-->', text):
            self.setFormat(m.start(), m.end() - m.start(), cmt_fmt)


class CSSHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for CSS content."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def highlightBlock(self, text):
        import re
        # Selectors
        sel_fmt = QTextCharFormat()
        sel_fmt.setForeground(QColor("#E06C75"))
        for m in re.finditer(r'[\w.#:\-\[\]=]+\s*\{', text):
            self.setFormat(m.start(), m.end() - m.start() - 1, sel_fmt)

        # Properties
        prop_fmt = QTextCharFormat()
        prop_fmt.setForeground(QColor("#D19A66"))
        for m in re.finditer(r'[\w-]+(?=\s*:)', text):
            self.setFormat(m.start(), m.end() - m.start(), prop_fmt)

        # Values
        val_fmt = QTextCharFormat()
        val_fmt.setForeground(QColor("#98C379"))
        for m in re.finditer(r':\s*[^;]+', text):
            self.setFormat(m.start() + 1, m.end() - m.start() - 1, val_fmt)


class JSHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for JavaScript content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules = []

        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#C678DD"))
        keywords = r'\b(function|var|let|const|return|if|else|for|while|class|import|export|from|async|await|new|this|typeof|instanceof|try|catch|throw|switch|case|break|continue|default)\b'
        self._rules.append((keywords, kw_fmt))

        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor("#98C379"))
        self._rules.append((r"'[^']*'", str_fmt))
        self._rules.append((r'"[^"]*"', str_fmt))
        self._rules.append((r'`[^`]*`', str_fmt))

        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor("#D19A66"))
        self._rules.append((r'\b\d+\.?\d*\b', num_fmt))

        cmt_fmt = QTextCharFormat()
        cmt_fmt.setForeground(QColor("#5C6370"))
        cmt_fmt.setFontItalic(True)
        self._rules.append((r'//.*$', cmt_fmt))

    def highlightBlock(self, text):
        import re
        for pattern, fmt in self._rules:
            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


# ─── Edit Request Dialog ──────────────────────────────────────────────────────

class EditRequestDialogUI(QDialog):
    """Dialog to edit and replay a request."""

    def __init__(self, flow: CapturedRequest, parent=None):
        super().__init__(parent)
        self.flow = flow
        self.setWindowTitle(f"Edit & Replay - {flow.method} {flow.url[:80]}")
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        # URL
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("Method:"))
        self.method_combo = QComboBox()
        self.method_combo.addItems(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
        self.method_combo.setCurrentText(flow.method)
        self.method_combo.setFixedWidth(100)
        url_layout.addWidget(self.method_combo)
        url_layout.addWidget(QLabel("URL:"))
        self.url_edit = QLineEdit(flow.url)
        url_layout.addWidget(self.url_edit)
        layout.addLayout(url_layout)

        # Headers
        layout.addWidget(QLabel("Request Headers:"))
        self.headers_edit = QPlainTextEdit()
        headers_text = "\n".join(f"{k}: {v}" for k, v in flow.request_headers.items())
        self.headers_edit.setPlainText(headers_text)
        self.headers_edit.setMaximumHeight(150)
        layout.addWidget(self.headers_edit)

        # Body
        layout.addWidget(QLabel("Request Body:"))
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlainText(flow.request_body_text or "")
        layout.addWidget(self.body_edit)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_modified_data(self):
        """Return modified request data."""
        headers = {}
        for line in self.headers_edit.toPlainText().strip().split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
        return {
            "url": self.url_edit.text(),
            "method": self.method_combo.currentText(),
            "headers": headers,
            "body": self.body_edit.toPlainText(),
        }


# ─── Timeline Waterfall Widget ────────────────────────────────────────────────

class WaterfallWidget(QWidget):
    """Simplified timeline waterfall view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._flows: List[CapturedRequest] = []
        self.setMinimumHeight(100)

    def set_flows(self, flows: List[CapturedRequest]):
        self._flows = flows
        self.update()

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QPen
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self._flows:
            painter.setPen(QColor("#888"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No requests to display")
            return

        w = self.width()
        h = self.height()
        row_h = max(16, min(24, h // max(len(self._flows), 1)))

        # Find time range
        times = [f.request_time for f in self._flows if f.request_time > 0]
        if not times:
            return

        min_time = min(times)
        max_time = max((f.response_time or f.request_time + f.duration for f in self._flows), default=min_time + 1)
        time_range = max(max_time - min_time, 0.001)

        left_margin = 200
        bar_area = w - left_margin - 20

        for i, flow in enumerate(self._flows):
            y = i * row_h
            if y > h:
                break

            # Label
            label = f"{flow.method} {flow.path[:40]}"
            painter.setPen(QColor("#CCC"))
            painter.drawText(5, y + row_h - 4, label)

            # Bar
            start_pct = (flow.request_time - min_time) / time_range
            duration = max(flow.duration, 0.001)
            bar_w = max(2, (duration / time_range) * bar_area)

            x = left_margin + start_pct * bar_area

            # Color by status
            if flow.status_code >= 400:
                color = QColor("#E06C75")
            elif flow.status_code >= 300:
                color = QColor("#E5C07B")
            else:
                color = QColor("#61AFEF")

            painter.fillRect(int(x), y + 2, int(bar_w), row_h - 4, color)

        painter.end()


# ─── Intercept Rules Dialog ────────────────────────────────────────────────

class InterceptRulesDialog(QDialog):
    """Dialog for managing API trace intercept rules."""

    def __init__(self, trace_engine, parent=None):
        super().__init__(parent)
        self._trace_engine = trace_engine
        self.setWindowTitle("Intercept Rules - API Trace Mode")
        self.setMinimumSize(600, 450)

        layout = QVBoxLayout(self)

        # ── Add Rule Section ──
        add_group = QGroupBox("Add New Rule")
        add_layout = QGridLayout(add_group)

        add_layout.addWidget(QLabel("Pattern:"), 0, 0)
        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText("e.g. /api/ or https://example.com/v1/")
        add_layout.addWidget(self.pattern_edit, 0, 1, 1, 2)

        add_layout.addWidget(QLabel("Match Type:"), 1, 0)
        self.match_combo = QComboBox()
        self.match_combo.addItems(["Contains", "Regex", "Exact URL", "Prefix"])
        self.match_combo.setCurrentText("Contains")
        add_layout.addWidget(self.match_combo, 1, 1)

        add_layout.addWidget(QLabel("Method:"), 1, 2)
        self.method_combo = QComboBox()
        self.method_combo.addItems(["ALL", "GET", "POST", "PUT", "PATCH", "DELETE"])
        add_layout.addWidget(self.method_combo, 1, 3)

        btn_add = QPushButton("➕ Add Rule")
        btn_add.setStyleSheet("background-color: #3E5C3E; color: #98C379; font-weight: bold;")
        btn_add.clicked.connect(self._add_rule)
        add_layout.addWidget(btn_add, 0, 3)

        layout.addWidget(add_group)

        # ── Rules List ──
        layout.addWidget(QLabel("Active Rules:"))

        self.rules_list = QTableWidget()
        self.rules_list.setColumnCount(4)
        self.rules_list.setHorizontalHeaderLabels(["Pattern", "Match Type", "Method", "Actions"])
        header = self.rules_list.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.rules_list.setColumnWidth(1, 120)
        self.rules_list.setColumnWidth(2, 80)
        self.rules_list.setColumnWidth(3, 80)
        self.rules_list.verticalHeader().setVisible(False)
        self.rules_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.rules_list)

        # ── Buttons ──
        btn_layout = QHBoxLayout()

        btn_remove_selected = QPushButton("🗑 Remove Selected")
        btn_remove_selected.clicked.connect(self._remove_selected)
        btn_layout.addWidget(btn_remove_selected)

        btn_clear_all = QPushButton("Clear All Rules")
        btn_clear_all.clicked.connect(self._clear_all)
        btn_layout.addWidget(btn_clear_all)

        btn_layout.addStretch()

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

        # Load existing rules
        self._refresh_rules_list()
        self.rules_list.cellClicked.connect(self._on_rule_cell_clicked)

    def _get_match_type_key(self, display: str) -> str:
        """Convert display name to key."""
        mapping = {
            "Contains": "contains",
            "Regex": "regex",
            "Exact URL": "exact",
            "Prefix": "prefix",
        }
        return mapping.get(display, "contains")

    def _get_match_type_display(self, key: str) -> str:
        """Convert key to display name."""
        mapping = {
            "contains": "Contains",
            "regex": "Regex",
            "exact": "Exact URL",
            "prefix": "Prefix",
        }
        return mapping.get(key, key)

    def _add_rule(self):
        """Add a new intercept rule."""
        pattern = self.pattern_edit.text().strip()
        if not pattern:
            QMessageBox.warning(self, "Add Rule", "Pattern cannot be empty.")
            return

        match_type = self._get_match_type_key(self.match_combo.currentText())
        method_filter = self.method_combo.currentText()

        # Validate regex
        if match_type == "regex":
            import re
            try:
                re.compile(pattern)
            except re.error as e:
                QMessageBox.warning(self, "Invalid Regex", f"Invalid regular expression:\n{e}")
                return

        self._trace_engine.add_rule(pattern, match_type, method_filter)
        self.pattern_edit.clear()
        self._refresh_rules_list()

    def _refresh_rules_list(self):
        """Refresh the rules table."""
        self.rules_list.setRowCount(0)
        rules = self._trace_engine.intercept_rules

        for i, rule in enumerate(rules):
            row = self.rules_list.rowCount()
            self.rules_list.insertRow(row)

            pattern_item = QTableWidgetItem(rule.pattern)
            pattern_item.setData(Qt.ItemDataRole.UserRole, i)
            self.rules_list.setItem(row, 0, pattern_item)

            type_item = QTableWidgetItem(self._get_match_type_display(rule.match_type))
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.rules_list.setItem(row, 1, type_item)

            method_item = QTableWidgetItem(rule.method_filter)
            method_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.rules_list.setItem(row, 2, method_item)

            remove_item = QTableWidgetItem("✕ Remove")
            remove_item.setForeground(QColor("#E06C75"))
            remove_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            remove_item.setData(Qt.ItemDataRole.UserRole + 1, i)
            self.rules_list.setItem(row, 3, remove_item)

    def _on_rule_cell_clicked(self, row, col):
        """Handle click on rule row, especially the remove column."""
        if col == 3:  # Actions column
            item = self.rules_list.item(row, col)
            if item:
                idx = item.data(Qt.ItemDataRole.UserRole + 1)
                if idx is not None:
                    self._trace_engine.remove_rule(idx)
                    self._refresh_rules_list()

    def _remove_selected(self):
        """Remove selected rule."""
        rows = self.rules_list.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        item = self.rules_list.item(row, 0)
        if item:
            idx = item.data(Qt.ItemDataRole.UserRole)
            if idx is not None:
                self._trace_engine.remove_rule(idx)
                self._refresh_rules_list()

    def _clear_all(self):
        """Clear all rules."""
        if self._trace_engine.intercept_rules:
            reply = QMessageBox.question(
                self, "Clear Rules", "Remove all intercept rules?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._trace_engine.clear_rules()
                self._refresh_rules_list()


# ─── Main Window ──────────────────────────────────────────────────────────────

class HARRecorderWindow(QMainWindow):
    """Main application window."""

    # Signals for thread-safe communication
    flow_received = pyqtSignal(object)  # CapturedRequest
    proxy_error = pyqtSignal(str)
    replay_complete = pyqtSignal(object, object)  # flow, ReplayResult
    request_intercepted = pyqtSignal(object)  # InterceptedRequest
    request_trace_completed = pyqtSignal(object)  # InterceptedRequest
    bridge_status = pyqtSignal(bool, str)  # connected, browser
    bridge_windows = pyqtSignal(str, object)  # browser, List[WindowInfo]
    bridge_message = pyqtSignal(str)  # status-bar text

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self._flows: List[CapturedRequest] = []
        self._filtered_indices: List[int] = []
        self._bookmarked: Set[str] = set()
        self._domains: Set[str] = set()
        self._step_markers: List[Dict] = []
        self._recording = False
        self._paused = False
        self._app_mode = AppMode.HAR_TRACE  # Combined HAR + Trace mode
        self._proxy_engine = None  # Long-lived; created on first Record

        # Trace engine
        self._trace_engine = TraceEngine()
        self._trace_engine.on_request_intercepted = self._emit_intercepted

        # Replay engine
        self._replay_engine = ReplayEngine(
            on_complete=lambda f, r: self.replay_complete.emit(f, r)
        )

        # Browser-extension bridge: lets us capture already-open browser
        # windows/tabs (Hermes Capture extension connects here). Optional —
        # the app works fine without it (falls back to launch/system proxy).
        self._bridge = None
        self._live_windows = []  # last window list reported by the extension
        self._capturing_live = False  # True when the active capture is via ext
        self._init_bridge()

        self._init_ui()
        self._connect_signals()
        self._apply_dark_theme()
        self._restore_session()
        self._init_mode()  # Set combined HAR+Trace mode

        # Auto-save timer
        self._auto_save_timer = QTimer()
        self._auto_save_timer.timeout.connect(self._auto_save)
        if config.get("auto_save", True):
            self._auto_save_timer.start(config.get("auto_save_interval", 60) * 1000)

    def _init_ui(self):
        """Build the UI."""
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1200, 800)

        # Restore geometry
        geom = self.config.get("window_geometry")
        if geom:
            try:
                from PyQt6.QtCore import QByteArray
                self.restoreGeometry(QByteArray.fromBase64(geom.encode()))
            except Exception:
                pass

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # ── Toolbar ──
        toolbar_layout = QHBoxLayout()

        # ── Three record buttons ──
        #   🔴 Red   = HAR + API Trace   (HAR_TRACE)
        #   🟢 Green = HAR only          (HAR_RECORD)
        #   🔵 Blue  = API Trace only    (API_TRACE)
        self.btn_rec_full = QPushButton("🔴 HAR + API")
        self.btn_rec_full.setToolTip("Record HAR and trace/intercept API (Ctrl+R)")
        self.btn_rec_full.setFixedHeight(36)
        self.btn_rec_full.setStyleSheet(
            "font-weight:bold; padding: 6px 14px; background-color:#5A2530; color:#FFFFFF;")
        toolbar_layout.addWidget(self.btn_rec_full)

        self.btn_rec_har = QPushButton("🟢 HAR")
        self.btn_rec_har.setToolTip("Record HAR only")
        self.btn_rec_har.setFixedHeight(36)
        self.btn_rec_har.setStyleSheet(
            "font-weight:bold; padding: 6px 14px; background-color:#25452B; color:#FFFFFF;")
        toolbar_layout.addWidget(self.btn_rec_har)

        self.btn_rec_api = QPushButton("🔵 API Trace")
        self.btn_rec_api.setToolTip("Trace/intercept API only (no HAR logging)")
        self.btn_rec_api.setFixedHeight(36)
        self.btn_rec_api.setStyleSheet(
            "font-weight:bold; padding: 6px 14px; background-color:#213A55; color:#FFFFFF;")
        toolbar_layout.addWidget(self.btn_rec_api)

        # ── Browser selector: which browser to launch through the proxy ──
        self.browser_combo = QComboBox()
        self.browser_combo.setFixedHeight(36)
        self.browser_combo.setToolTip(
            "Which browser to open through Hermes.\n"
            "'System proxy (all apps)' uses the old behavior; picking a\n"
            "browser launches a clean capture window for just that browser.")
        toolbar_layout.addWidget(self.browser_combo)
        self._populate_browser_combo()

        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.setToolTip(
            "Pause recording without stopping the session.\n"
            "Traffic keeps flowing (browser stays usable) but nothing is\n"
            "captured until you press Continue.")
        self.btn_pause.setFixedHeight(36)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet(
            "font-weight:bold; padding: 6px 14px;")
        toolbar_layout.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setToolTip("Stop recording (Ctrl+S)")
        self.btn_stop.setFixedHeight(36)
        self.btn_stop.setEnabled(False)
        toolbar_layout.addWidget(self.btn_stop)

        self.btn_clear = QPushButton("🗑 Clear")
        self.btn_clear.setToolTip("Clear all captured requests")
        self.btn_clear.setFixedHeight(36)
        toolbar_layout.addWidget(self.btn_clear)

        # Separator
        sep = QLabel("|")
        sep.setFixedWidth(8)
        toolbar_layout.addWidget(sep)

        # Separator
        sep2 = QLabel("|")
        sep2.setFixedWidth(8)
        toolbar_layout.addWidget(sep2)

        self.btn_export = QPushButton("📁 Export")
        self.btn_export.setToolTip("Export captured data (Ctrl+E)")
        self.btn_export.setFixedHeight(36)
        toolbar_layout.addWidget(self.btn_export)

        toolbar_layout.addStretch()

        # Status indicators
        self.lbl_count = QLabel("Requests: 0")
        self.lbl_count.setStyleSheet("font-weight:bold; color: #61AFEF;")
        toolbar_layout.addWidget(self.lbl_count)

        self.lbl_size = QLabel("Total: 0B")
        self.lbl_size.setStyleSheet("font-weight:bold; color: #98C379;")
        toolbar_layout.addWidget(self.lbl_size)

        self.lbl_proxy = QLabel("🔴 Proxy: Off")
        self.lbl_proxy.setStyleSheet("color: #E06C75;")
        toolbar_layout.addWidget(self.lbl_proxy)

        main_layout.addLayout(toolbar_layout)

        # ── Filter Bar ──
        filter_layout = QHBoxLayout()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Search URL, headers, body... (Ctrl+F)")
        self.search_edit.setClearButtonEnabled(True)
        filter_layout.addWidget(self.search_edit, stretch=3)

        self.filter_method = QComboBox()
        self.filter_method.addItems(["ALL", "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
        self.filter_method.setFixedWidth(100)
        filter_layout.addWidget(QLabel("Method:"))
        filter_layout.addWidget(self.filter_method)

        self.filter_status = QComboBox()
        self.filter_status.addItems(["ALL", "2xx", "3xx", "4xx", "5xx", "Error"])
        self.filter_status.setFixedWidth(80)
        filter_layout.addWidget(QLabel("Status:"))
        filter_layout.addWidget(self.filter_status)

        self.filter_type = QComboBox()
        self.filter_type.addItems(["ALL", "XHR", "JS", "CSS", "Image", "Document", "Font", "Media"])
        self.filter_type.setFixedWidth(100)
        filter_layout.addWidget(QLabel("Type:"))
        filter_layout.addWidget(self.filter_type)

        self.filter_domain = QComboBox()
        self.filter_domain.addItem("ALL")
        self.filter_domain.setFixedWidth(150)
        filter_layout.addWidget(QLabel("Domain:"))
        filter_layout.addWidget(self.filter_domain)

        self.chk_hide_static = QCheckBox("Hide Static")
        self.chk_hide_static.setChecked(self.config.get("hide_static", False))
        filter_layout.addWidget(self.chk_hide_static)

        self._filter_bar_widget = QWidget()
        self._filter_bar_widget.setLayout(filter_layout)
        main_layout.addWidget(self._filter_bar_widget)

        # ── Main Splitter ──
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Request Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "★", "Method", "URL", "Status", "Size", "Time", "Type"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 30)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(3, 60)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 80)
        self.table.setColumnWidth(6, 80)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)

        splitter.addWidget(self.table)

        # Detail Panel
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 0, 0, 0)

        self.detail_tabs = QTabWidget()

        # Headers tab
        self.headers_text = QTextBrowser()
        self.headers_text.setOpenExternalLinks(False)
        self.detail_tabs.addTab(self.headers_text, "Headers")

        # Request Body tab
        self.request_body_text = QPlainTextEdit()
        self.request_body_text.setReadOnly(True)
        self.detail_tabs.addTab(self.request_body_text, "Request Body")

        # Response tab
        self.response_text = QPlainTextEdit()
        self.response_text.setReadOnly(True)
        self.response_text.setFont(QFont("Consolas", 10))
        self.detail_tabs.addTab(self.response_text, "Response")

        # Cookies tab
        self.cookies_text = QTextBrowser()
        self.detail_tabs.addTab(self.cookies_text, "Cookies")

        # Timing tab
        self.timing_text = QTextBrowser()
        self.detail_tabs.addTab(self.timing_text, "Timing")

        # Waterfall tab
        self.waterfall = WaterfallWidget()
        self.detail_tabs.addTab(self.waterfall, "Waterfall")

        # Tokens/Keys tab
        self.tokens_text = QTextBrowser()
        self.detail_tabs.addTab(self.tokens_text, "Tokens")

        detail_layout.addWidget(self.detail_tabs)
        splitter.addWidget(detail_widget)

        splitter.setSizes([400, 350])

        # Store HAR view reference
        self._har_view = splitter

        # ── Trace Panel ──
        self._trace_panel = self._build_trace_panel()
        self._trace_panel.setVisible(False)

        # Add both to main layout (visibility controlled by mode switching)
        main_layout.addWidget(self._har_view, stretch=3)
        main_layout.addWidget(self._trace_panel, stretch=2)


        # ── Menu Bar ──
        self._build_menu_bar()

        # ── Status Bar ──
        self.statusBar().showMessage("Ready")

    def _build_menu_bar(self):
        """Build the menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")
        act_record = QAction("Record (HAR + API)", self)
        act_record.setShortcut(QKeySequence("Ctrl+R"))
        act_record.triggered.connect(lambda: self._on_record(AppMode.HAR_TRACE))
        file_menu.addAction(act_record)

        act_stop = QAction("Stop", self)
        act_stop.setShortcut(QKeySequence("Ctrl+S"))
        act_stop.triggered.connect(self._on_stop)
        file_menu.addAction(act_stop)

        file_menu.addSeparator()

        act_export = QAction("Export...", self)
        act_export.setShortcut(QKeySequence("Ctrl+E"))
        act_export.triggered.connect(self._on_export)
        file_menu.addAction(act_export)

        file_menu.addSeparator()

        act_save_session = QAction("Save Session", self)
        act_save_session.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_save_session.triggered.connect(self._save_session)
        file_menu.addAction(act_save_session)

        act_load_session = QAction("Load Session...", self)
        act_load_session.setShortcut(QKeySequence("Ctrl+O"))
        act_load_session.triggered.connect(self._load_session)
        file_menu.addAction(act_load_session)

        file_menu.addSeparator()

        act_quit = QAction("Quit", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        # View menu
        view_menu = menubar.addMenu("View")
        self.act_on_top = QAction("Always on Top", self)
        self.act_on_top.setCheckable(True)
        self.act_on_top.setChecked(self.config.get("always_on_top", False))
        self.act_on_top.triggered.connect(self._toggle_on_top)
        view_menu.addAction(self.act_on_top)

        view_menu.addSeparator()

        view_menu.addSeparator()

        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        act_step = QAction("Add Step Marker", self)
        act_step.setShortcut(QKeySequence("Ctrl+M"))
        act_step.triggered.connect(self._add_step_marker)
        tools_menu.addAction(act_step)

        act_extract = QAction("Extract Tokens", self)
        act_extract.triggered.connect(self._extract_all_tokens)
        tools_menu.addAction(act_extract)

        tools_menu.addSeparator()

        act_manage_rules = QAction("Intercept Rules...", self)
        act_manage_rules.setShortcut(QKeySequence("Ctrl+I"))
        act_manage_rules.triggered.connect(self._show_intercept_rules_dialog)
        tools_menu.addAction(act_manage_rules)

        # Settings menu
        settings_menu = menubar.addMenu("Settings")
        act_port = QAction("Change Proxy Port...", self)
        act_port.triggered.connect(self._change_port)
        settings_menu.addAction(act_port)

        self.act_auto_proxy = QAction("Auto-set System Proxy", self)
        self.act_auto_proxy.setCheckable(True)
        self.act_auto_proxy.setChecked(self.config.get("auto_set_proxy", True))
        self.act_auto_proxy.triggered.connect(self._toggle_auto_proxy)
        settings_menu.addAction(self.act_auto_proxy)

        # Help menu
        help_menu = menubar.addMenu("Help")
        act_about = QAction("About", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _connect_signals(self):
        """Connect signals and slots."""
        self.btn_rec_full.clicked.connect(lambda: self._on_record(AppMode.HAR_TRACE))
        self.btn_rec_har.clicked.connect(lambda: self._on_record(AppMode.HAR_RECORD))
        self.btn_rec_api.clicked.connect(lambda: self._on_record(AppMode.API_TRACE))
        self.btn_pause.clicked.connect(self._on_pause_toggle)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_export.clicked.connect(self._on_export)

        self.flow_received.connect(self._on_flow_received)
        self.proxy_error.connect(self._on_proxy_error)
        self.replay_complete.connect(self._on_replay_complete)
        self.request_intercepted.connect(self._on_request_intercepted)
        self.request_trace_completed.connect(lambda req: self._update_trace_counts())

        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        self.search_edit.textChanged.connect(self._apply_filters)
        self.filter_method.currentTextChanged.connect(self._apply_filters)
        self.filter_status.currentTextChanged.connect(self._apply_filters)
        self.filter_type.currentTextChanged.connect(self._apply_filters)
        self.filter_domain.currentTextChanged.connect(self._apply_filters)
        self.chk_hide_static.stateChanged.connect(self._apply_filters)

    def _apply_dark_theme(self):
        """Apply dark theme stylesheet."""
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #282C34;
                color: #ABB2BF;
            }
            QTableWidget {
                background-color: #21252B;
                alternate-background-color: #282C34;
                color: #ABB2BF;
                gridline-color: #3E4451;
                selection-background-color: #3E4451;
                selection-color: #FFFFFF;
                border: 1px solid #3E4451;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QHeaderView::section {
                background-color: #21252B;
                color: #ABB2BF;
                border: 1px solid #3E4451;
                padding: 4px;
            }
            QTabWidget::pane {
                border: 1px solid #3E4451;
                background-color: #282C34;
            }
            QTabBar::tab {
                background-color: #21252B;
                color: #ABB2BF;
                padding: 6px 12px;
                border: 1px solid #3E4451;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background-color: #282C34;
                color: #FFFFFF;
            }
            QPushButton {
                background-color: #3E4451;
                color: #ABB2BF;
                border: 1px solid #4B5263;
                padding: 6px 12px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #4B5263;
            }
            QPushButton:pressed {
                background-color: #545B6A;
            }
            QPushButton:disabled {
                background-color: #2C313A;
                color: #5C6370;
            }
            QLineEdit, QComboBox {
                background-color: #1E2127;
                color: #ABB2BF;
                border: 1px solid #3E4451;
                padding: 4px 8px;
                border-radius: 3px;
            }
            QLineEdit:focus {
                border-color: #61AFEF;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #1E2127;
                color: #ABB2BF;
                selection-background-color: #3E4451;
            }
            QPlainTextEdit, QTextEdit, QTextBrowser {
                background-color: #1E2127;
                color: #ABB2BF;
                border: 1px solid #3E4451;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 11px;
            }
            QCheckBox {
                color: #ABB2BF;
            }
            QStatusBar {
                background-color: #21252B;
                color: #5C6370;
            }
            QMenuBar {
                background-color: #21252B;
                color: #ABB2BF;
            }
            QMenuBar::item:selected {
                background-color: #3E4451;
            }
            QMenu {
                background-color: #21252B;
                color: #ABB2BF;
                border: 1px solid #3E4451;
            }
            QMenu::item:selected {
                background-color: #3E4451;
            }
            QSplitter::handle {
                background-color: #3E4451;
            }
            QScrollBar:vertical {
                background-color: #21252B;
                width: 10px;
            }
            QScrollBar::handle:vertical {
                background-color: #3E4451;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background-color: #21252B;
                height: 10px;
            }
            QScrollBar::handle:horizontal {
                background-color: #3E4451;
                min-width: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            QLabel {
                color: #ABB2BF;
            }
        """)

    # ─── Trace Mode UI ────────────────────────────────────────────────────────

    def _build_trace_panel(self) -> QWidget:
        """Build the API Trace / Intercept panel."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Intercept Controls ──
        controls_layout = QHBoxLayout()

        self.chk_intercept = QCheckBox("🔴 Intercept: OFF")
        self.chk_intercept.setStyleSheet("font-weight: bold; font-size: 12px;")
        self.chk_intercept.stateChanged.connect(self._toggle_intercept)
        controls_layout.addWidget(self.chk_intercept)

        controls_layout.addSpacing(20)

        # Rules display
        self.lbl_rules = QLabel("Rules: (none)")
        self.lbl_rules.setStyleSheet("color: #5C6370;")
        controls_layout.addWidget(self.lbl_rules)

        btn_manage_rules = QPushButton("⚙️ Manage Rules")
        btn_manage_rules.setFixedHeight(30)
        btn_manage_rules.clicked.connect(self._show_intercept_rules_dialog)
        controls_layout.addWidget(btn_manage_rules)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # ── Splitter: Request list + Detail ──
        trace_splitter = QSplitter(Qt.Orientation.Vertical)

        # Intercepted requests table
        self.trace_table = QTableWidget()
        self.trace_table.setColumnCount(5)
        self.trace_table.setHorizontalHeaderLabels([
            "Status", "Method", "URL", "Timestamp", "Actions"
        ])
        header = self.trace_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.trace_table.setColumnWidth(0, 100)
        self.trace_table.setColumnWidth(1, 80)
        self.trace_table.setColumnWidth(3, 100)
        self.trace_table.setColumnWidth(4, 250)
        self.trace_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.trace_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.trace_table.setAlternatingRowColors(True)
        self.trace_table.verticalHeader().setVisible(False)
        self.trace_table.itemSelectionChanged.connect(self._on_trace_selection_changed)

        trace_splitter.addWidget(self.trace_table)

        # Detail panel for intercepted request
        trace_detail_widget = QWidget()
        trace_detail_layout = QVBoxLayout(trace_detail_widget)
        trace_detail_layout.setContentsMargins(0, 0, 0, 0)

        self.trace_detail_tabs = QTabWidget()

        # Headers tab
        self.trace_headers_text = QTextBrowser()
        self.trace_headers_text.setOpenExternalLinks(False)
        self.trace_detail_tabs.addTab(self.trace_headers_text, "Headers")

        # Body tab
        self.trace_body_text = QPlainTextEdit()
        self.trace_body_text.setReadOnly(True)
        self.trace_detail_tabs.addTab(self.trace_body_text, "Body")

        # Raw request tab
        self.trace_raw_text = QPlainTextEdit()
        self.trace_raw_text.setReadOnly(True)
        self.trace_raw_text.setFont(QFont("Consolas", 10))
        self.trace_detail_tabs.addTab(self.trace_raw_text, "Raw")

        trace_detail_layout.addWidget(self.trace_detail_tabs)

        # Action buttons for selected request
        action_layout = QHBoxLayout()

        btn_forward = QPushButton("▶ Forward")
        btn_forward.setStyleSheet("background-color: #3E5C3E; color: #98C379; font-weight: bold; padding: 8px 16px;")
        btn_forward.clicked.connect(self._trace_forward_selected)
        action_layout.addWidget(btn_forward)

        btn_drop = QPushButton("✕ Drop")
        btn_drop.setStyleSheet("background-color: #5C3E3E; color: #E06C75; font-weight: bold; padding: 8px 16px;")
        btn_drop.clicked.connect(self._trace_drop_selected)
        action_layout.addWidget(btn_drop)

        btn_edit_fwd = QPushButton("✏️ Edit & Forward")
        btn_edit_fwd.setStyleSheet("background-color: #3E3E5C; color: #61AFEF; font-weight: bold; padding: 8px 16px;")
        btn_edit_fwd.clicked.connect(self._trace_edit_and_forward)
        action_layout.addWidget(btn_edit_fwd)

        action_layout.addStretch()

        btn_forward_all = QPushButton("▶ Forward All")
        btn_forward_all.setStyleSheet("background-color: #2D4A2D; padding: 8px 16px;")
        btn_forward_all.clicked.connect(self._trace_forward_all)
        action_layout.addWidget(btn_forward_all)

        btn_drop_all = QPushButton("✕ Drop All")
        btn_drop_all.setStyleSheet("background-color: #4A2D2D; padding: 8px 16px;")
        btn_drop_all.clicked.connect(self._trace_drop_all)
        action_layout.addWidget(btn_drop_all)

        trace_detail_layout.addLayout(action_layout)

        trace_splitter.addWidget(trace_detail_widget)
        trace_splitter.setSizes([300, 400])

        layout.addWidget(trace_splitter)

        # ── History ──
        self.lbl_trace_history = QLabel("Completed: 0 intercepted, 0 forwarded, 0 dropped")
        self.lbl_trace_history.setStyleSheet("color: #5C6370;")
        layout.addWidget(self.lbl_trace_history)

        return panel

    def _toggle_intercept(self, state):
        """Toggle intercept on/off."""
        enabled = state == 2  # Qt.CheckState.Checked
        self._trace_engine.intercept_enabled = enabled
        if enabled:
            self.chk_intercept.setText("🔴 Intercept: ON")
            self.chk_intercept.setStyleSheet("font-weight: bold; font-size: 12px; color: #E06C75;")
            self.statusBar().showMessage("Intercept enabled - matching requests will be paused")
        else:
            self.chk_intercept.setText("🔴 Intercept: OFF")
            self.chk_intercept.setStyleSheet("font-weight: bold; font-size: 12px;")
            self.statusBar().showMessage("Intercept disabled")

    def _show_intercept_rules_dialog(self):
        """Show the intercept rules management dialog."""
        dlg = InterceptRulesDialog(self._trace_engine, self)
        dlg.exec()
        self._update_rules_display()

    def _update_rules_display(self):
        """Update the rules label in the trace panel."""
        rules = self._trace_engine.get_rules_display()
        if rules:
            self.lbl_rules.setText(f"Rules: {', '.join(rules[:3])}" +
                                   (f" (+{len(rules)-3} more)" if len(rules) > 3 else ""))
            self.lbl_rules.setStyleSheet("color: #E5C07B;")
        else:
            self.lbl_rules.setText("Rules: (intercept all when ON)")
            self.lbl_rules.setStyleSheet("color: #5C6370;")

    def _emit_intercepted(self, intercepted: InterceptedRequest):
        """Thread-safe emission of intercepted request signal."""
        self.request_intercepted.emit(intercepted)

    def _on_request_intercepted(self, intercepted: InterceptedRequest):
        """Handle a new intercepted request (main thread)."""
        self._add_trace_table_row(intercepted)
        self._update_trace_counts()
        self.statusBar().showMessage(
            f"⏸️ Intercepted: {intercepted.method} {intercepted.url[:80]}")

    def _add_trace_table_row(self, req: InterceptedRequest):
        """Add a row to the trace table."""
        row = self.trace_table.rowCount()
        self.trace_table.insertRow(row)

        # Status
        status_icons = {
            "intercepted": "⏸️",
            "forwarded": "▶️",
            "dropped": "✕",
            "modified": "✏️",
        }
        status_item = QTableWidgetItem(f"{status_icons.get(req.status, '?')} {req.status}")
        status_item.setData(Qt.ItemDataRole.UserRole, req.id)

        status_colors = {
            "intercepted": "#E5C07B",
            "forwarded": "#98C379",
            "dropped": "#E06C75",
            "modified": "#61AFEF",
        }
        status_item.setForeground(QColor(status_colors.get(req.status, "#ABB2BF")))
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.trace_table.setItem(row, 0, status_item)

        # Method
        method_item = QTableWidgetItem(req.method)
        method_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        method_colors = {
            "GET": "#61AFEF", "POST": "#98C379", "PUT": "#E5C07B",
            "PATCH": "#D19A66", "DELETE": "#E06C75",
        }
        method_item.setForeground(QColor(method_colors.get(req.method, "#ABB2BF")))
        self.trace_table.setItem(row, 1, method_item)

        # URL
        url_item = QTableWidgetItem(req.url)
        url_item.setToolTip(req.url)
        self.trace_table.setItem(row, 2, url_item)

        # Timestamp
        time_str = datetime.fromtimestamp(req.timestamp).strftime("%H:%M:%S.%f")[:-3]
        time_item = QTableWidgetItem(time_str)
        time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.trace_table.setItem(row, 3, time_item)

        # Actions (only for intercepted status)
        actions_item = QTableWidgetItem()
        if req.status == "intercepted":
            actions_item.setText("▶ Forward  |  ✕ Drop  |  ✏️ Edit")
            actions_item.setForeground(QColor("#ABB2BF"))
        else:
            actions_item.setText(f"[{req.status}]")
            actions_item.setForeground(QColor("#5C6370"))
        actions_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.trace_table.setItem(row, 4, actions_item)

        # Auto-scroll
        self.trace_table.scrollToBottom()

    def _on_trace_selection_changed(self):
        """Handle trace table selection change."""
        rows = self.trace_table.selectionModel().selectedRows()
        if not rows:
            return

        row = rows[0].row()
        item = self.trace_table.item(row, 0)
        if not item:
            return

        req_id = item.data(Qt.ItemDataRole.UserRole)
        req = self._trace_engine.get_request_by_id(req_id)
        if req:
            self._show_trace_detail(req)

    def _show_trace_detail(self, req: InterceptedRequest):
        """Show detail for an intercepted request."""
        # Headers tab
        status_colors = {
            "intercepted": "#E5C07B",
            "forwarded": "#98C379",
            "dropped": "#E06C75",
            "modified": "#61AFEF",
        }
        status_color = status_colors.get(req.status, "#ABB2BF")
        html = f"<h3 style='color:#E5C07B;'>{req.method} {req.url}</h3>"
        html += f"<p style='color:#5C6370;'>Status: <b style='color:{status_color};'>{req.status}</b></p>"
        html += "<h3 style='color:#61AFEF;'>Request Headers</h3>"
        html += "<table style='color:#ABB2BF;'>"
        for k, v in req.headers.items():
            html += f"<tr><td style='color:#E5C07B; padding-right:10px;'><b>{k}</b></td><td>{v}</td></tr>"
        html += "</table>"
        self.trace_headers_text.setHtml(html)

        # Body tab
        self.trace_body_text.setPlainText(req.body or "(empty body)")
        if 'json' in req.content_type.lower():
            JSONHighlighter(self.trace_body_text.document())

        # Raw tab
        raw_lines = [f"{req.method} {req.path} HTTP/1.1"]
        for k, v in req.headers.items():
            raw_lines.append(f"{k}: {v}")
        raw_lines.append("")
        raw_lines.append(req.body or "")
        self.trace_raw_text.setPlainText("\n".join(raw_lines))

    def _get_selected_trace_request(self) -> Optional[InterceptedRequest]:
        """Get the currently selected intercepted request."""
        rows = self.trace_table.selectionModel().selectedRows()
        if not rows:
            return None

        row = rows[0].row()
        item = self.trace_table.item(row, 0)
        if not item:
            return None

        req_id = item.data(Qt.ItemDataRole.UserRole)
        return self._trace_engine.get_request_by_id(req_id)

    def _trace_forward_selected(self):
        """Forward the selected intercepted request."""
        req = self._get_selected_trace_request()
        if not req:
            QMessageBox.information(self, "Forward", "No request selected.")
            return
        if req.status != "intercepted":
            QMessageBox.information(self, "Forward", "Request is not in intercepted state.")
            return

        if self._trace_engine.forward_request(req.id):
            self._refresh_trace_table()
            self.statusBar().showMessage(f"▶ Forwarded: {req.method} {req.url[:60]}")
        else:
            QMessageBox.warning(self, "Error", "Failed to forward request.")

    def _trace_drop_selected(self):
        """Drop the selected intercepted request."""
        req = self._get_selected_trace_request()
        if not req:
            QMessageBox.information(self, "Drop", "No request selected.")
            return
        if req.status != "intercepted":
            QMessageBox.information(self, "Drop", "Request is not in intercepted state.")
            return

        reply = QMessageBox.question(
            self, "Drop Request",
            f"Drop this request? The server will not receive it.\n\n{req.method} {req.url[:100]}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self._trace_engine.drop_request(req.id):
                self._refresh_trace_table()
                self.statusBar().showMessage(f"✕ Dropped: {req.method} {req.url[:60]}")

    def _trace_edit_and_forward(self):
        """Edit an intercepted request and forward it."""
        req = self._get_selected_trace_request()
        if not req:
            QMessageBox.information(self, "Edit", "No request selected.")
            return
        if req.status != "intercepted":
            QMessageBox.information(self, "Edit", "Request is not in intercepted state.")
            return

        # Create a CapturedRequest-like object for the edit dialog
        flow = CapturedRequest()
        flow.method = req.method
        flow.url = req.url
        flow.request_headers = req.headers
        flow.request_body_text = req.body

        dlg = EditRequestDialogUI(flow, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_modified_data()
            if self._trace_engine.forward_request(req.id, modified_data=data):
                self._refresh_trace_table()
                self.statusBar().showMessage(f"✏️ Modified & Forwarded: {data['method']} {data['url'][:60]}")
            else:
                QMessageBox.warning(self, "Error", "Failed to forward modified request.")

    def _trace_forward_all(self):
        """Forward all pending intercepted requests."""
        count = self._trace_engine.get_pending_count()
        if count == 0:
            QMessageBox.information(self, "Forward All", "No intercepted requests pending.")
            return

        reply = QMessageBox.question(
            self, "Forward All",
            f"Forward all {count} intercepted request(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._trace_engine.forward_all()
            self._refresh_trace_table()
            self.statusBar().showMessage(f"▶ Forwarded {count} requests")

    def _trace_drop_all(self):
        """Drop all pending intercepted requests."""
        count = self._trace_engine.get_pending_count()
        if count == 0:
            QMessageBox.information(self, "Drop All", "No intercepted requests pending.")
            return

        reply = QMessageBox.question(
            self, "Drop All",
            f"Drop all {count} intercepted request(s)?\nThese requests will NOT reach the server.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._trace_engine.drop_all()
            self._refresh_trace_table()
            self.statusBar().showMessage(f"✕ Dropped {count} requests")

    def _refresh_trace_table(self):
        """Refresh the trace table from trace engine state."""
        self.trace_table.setRowCount(0)

        # Show all requests (pending first, then completed)
        pending = self._trace_engine.get_pending_requests()
        completed = self._trace_engine.get_completed_requests()

        for req in pending + completed:
            self._add_trace_table_row(req)

        self._update_trace_counts()

    def _update_trace_counts(self):
        """Update the trace history label."""
        completed = self._trace_engine.get_completed_requests()
        forwarded = sum(1 for r in completed if r.status in ("forwarded", "modified"))
        dropped = sum(1 for r in completed if r.status == "dropped")
        pending = self._trace_engine.get_pending_count()
        self.lbl_trace_history.setText(
            f"Pending: {pending} | Forwarded: {forwarded} | Dropped: {dropped} | Total: {len(completed)}"
        )

    # ─── Mode ────────────────────────────────────────────────────────────

    def _init_mode(self):
        """Initialize in combined HAR+Trace mode."""
        self._app_mode = AppMode.HAR_TRACE
        self._apply_mode_visibility(self._app_mode)
        self._update_rules_display()

    def _apply_mode_visibility(self, mode: str):
        """Show/hide panels based on the active record mode.

        HAR_TRACE → both HAR table and trace panel.
        HAR_RECORD → HAR table only.
        API_TRACE → trace panel only.
        """
        show_har = mode in (AppMode.HAR_TRACE, AppMode.HAR_RECORD)
        show_trace = mode in (AppMode.HAR_TRACE, AppMode.API_TRACE)
        self._har_view.setVisible(show_har)
        self._filter_bar_widget.setVisible(show_har)
        self._trace_panel.setVisible(show_trace)
        # In any trace mode, interception must be active to catch requests.
        if show_trace:
            self._trace_engine.intercept_enabled = True

    def _populate_browser_combo(self):
        """Fill the browser selector with detected browsers.

        First item is the legacy 'System proxy (all apps)' option (data=None).
        Each detected browser is added with its BrowserInfo as item data.
        Any already-open windows reported by the Hermes Capture extension are
        appended below with a dict payload {"live": True, "tabId": ...}.
        """
        self.browser_combo.clear()
        self.browser_combo.addItem("🌐 System proxy (all apps)", None)
        try:
            from browser_launcher import detect_browsers
            for b in detect_browsers():
                self.browser_combo.addItem(f"🚀 {b.name} (clean capture window)", b)
        except Exception as e:
            print(f"[Hermes] Browser detection failed: {e}")
        # Append live windows from the extension (if any).
        for browser, windows in self._live_windows:
            for w in windows:
                for tab in w.tabs:
                    title = (tab.title or tab.url or "tab")[:45]
                    self.browser_combo.addItem(
                        f"🎯 {browser}: {title}",
                        {"live": True, "tabId": tab.id, "browser": browser})

    # ─── Extension bridge ──────────────────────────────────────────────────────
    def _init_bridge(self):
        """Start the WebSocket bridge the Hermes Capture extension connects to."""
        try:
            from hermes_bridge import HermesBridge, entry_to_captured
        except Exception as e:
            print(f"[Hermes] Extension bridge unavailable: {e}")
            return
        self._entry_to_captured = entry_to_captured
        self.bridge_status.connect(self._on_bridge_status)
        self.bridge_windows.connect(self._on_bridge_windows)
        self.bridge_message.connect(lambda m: self.statusBar().showMessage(m))
        try:
            self._bridge = HermesBridge(
                port=self.config.get("bridge_port", 8898),
                on_status=lambda c, br: self.bridge_status.emit(c, br),
                on_windows=lambda br, w: self.bridge_windows.emit(br, w),
                on_entry=self._on_bridge_entry,
                on_capture_started=lambda t: self.bridge_message.emit(
                    f"Capturing open window: {t.get('title', '')}"),
                on_capture_stopped=lambda r: self.bridge_message.emit(
                    "Extension capture stopped."),
                on_error=lambda m: self.proxy_error.emit(f"[extension] {m}"),
            )
            self._bridge.start()
        except Exception as e:
            print(f"[Hermes] Failed to start bridge: {e}")
            self._bridge = None

    def _on_bridge_entry(self, entry: dict):
        """Convert an extension network entry to a flow (bridge thread-safe)."""
        try:
            captured = self._entry_to_captured(entry)
            self.flow_received.emit(captured)
        except Exception as e:
            self.proxy_error.emit(f"[extension] entry: {e}")

    def _on_bridge_status(self, connected: bool, browser: str):
        if connected:
            self.statusBar().showMessage(
                f"Hermes Capture extension connected ({browser}).")
            if self._bridge:
                self._bridge.list_windows()
        else:
            # Drop that browser's live windows from the picker.
            self._live_windows = [
                (b, w) for (b, w) in self._live_windows if b != browser]
            self._refresh_browser_combo_preserving()

    def _on_bridge_windows(self, browser: str, windows):
        # Replace this browser's entry in the cached list.
        self._live_windows = [
            (b, w) for (b, w) in self._live_windows if b != browser]
        self._live_windows.append((browser, windows))
        self._refresh_browser_combo_preserving()

    def _refresh_browser_combo_preserving(self):
        """Rebuild the combo but keep the current selection where possible."""
        prev = self.browser_combo.currentData()
        self._populate_browser_combo()
        if isinstance(prev, dict) and prev.get("live"):
            for i in range(self.browser_combo.count()):
                d = self.browser_combo.itemData(i)
                if isinstance(d, dict) and d.get("tabId") == prev.get("tabId"):
                    self.browser_combo.setCurrentIndex(i)
                    break

    # ─── Proxy Control ────────────────────────────────────────────────────────

    def _set_record_buttons_enabled(self, enabled: bool):
        """Enable/disable all three record buttons at once."""
        self.btn_rec_full.setEnabled(enabled)
        self.btn_rec_har.setEnabled(enabled)
        self.btn_rec_api.setEnabled(enabled)

    def _on_record(self, mode: str = None):
        """Start recording in the given mode.

        mode is one of AppMode.HAR_TRACE (🔴 red button, HAR + API),
        AppMode.HAR_RECORD (🟢 green, HAR only) or AppMode.API_TRACE
        (🔵 blue, API trace only). Defaults to the combined HAR+Trace mode.
        """
        from proxy_engine import ProxyEngine, set_system_proxy

        if self._recording:
            return

        if mode:
            self._app_mode = mode
        # Reflect the chosen mode on the proxy panels.
        self._apply_mode_visibility(self._app_mode)

        port = self.config.get("proxy_port", 8899)

        # Create the proxy engine once and reuse it. The mitmproxy master is
        # long-lived (a 2nd master in one process hangs), so Record/Stop just
        # resume/pause capture on the same engine.
        if self._proxy_engine is None:
            self._proxy_engine = ProxyEngine(
                port=port,
                on_flow=self._emit_flow,
                on_error=lambda e: self.proxy_error.emit(e),
                trace_engine=self._trace_engine,
            )

        if self._proxy_engine.start(self._app_mode):
            self._recording = True
            self._paused = False
            actual_port = self._proxy_engine.port
            self._set_record_buttons_enabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_pause.setEnabled(True)
            self.btn_pause.setText("⏸ Pause")
            mode_label = {
                AppMode.HAR_TRACE: "HAR + API",
                AppMode.HAR_RECORD: "HAR",
                AppMode.API_TRACE: "API Trace",
            }.get(self._app_mode, "Recording")
            self.lbl_proxy.setText(f"🟢 Proxy: :{actual_port} [{mode_label}]")
            self.lbl_proxy.setStyleSheet("color: #98C379;")
            if actual_port != port:
                self.statusBar().showMessage(f"Port {port} busy, using {actual_port}")
            else:
                self.statusBar().showMessage(f"Recording ({mode_label}) on port {actual_port}")

            # Route traffic: either launch a specific browser through the
            # proxy (recommended, per-browser/profile) or fall back to the
            # old system-wide proxy behavior.
            self._route_traffic(actual_port, set_system_proxy)
        else:
            QMessageBox.warning(self, "Error",
                f"Failed to start proxy on port {port}.\n"
                f"The port may still be in use by a previous session.\n\n"
                f"Check the status bar / log for details, close other proxy "
                f"tools, or change the port in Settings.")

    def _route_traffic(self, actual_port: int, set_system_proxy):
        """Send browser traffic to the proxy based on the browser selector."""
        selected = self.browser_combo.currentData()
        # Live window from the Hermes Capture extension: capture an
        # already-open tab/window (no browser restart, follows new tabs).
        if isinstance(selected, dict) and selected.get("live"):
            if self._bridge and self._bridge.connected:
                self._capturing_live = True
                self._bridge.start_capture(tab_id=selected["tabId"], follow_new=True)
                self.statusBar().showMessage(
                    "Capturing an already-open window via the extension.")
            else:
                QMessageBox.warning(self, "Extension not connected",
                    "The Hermes Capture extension isn't connected.\n"
                    "Open the browser, load the extension, then try again.")
            return
        self._capturing_live = False
        if selected is None:
            # "System proxy (all apps)" chosen — old behavior.
            if self.config.get("auto_set_proxy", True):
                set_system_proxy("127.0.0.1", actual_port)
                self.statusBar().showMessage(
                    "System proxy set — all apps route through Hermes.")
            return
        # A specific browser was chosen: launch a clean capture window.
        try:
            from browser_launcher import launch_browser
            self._browser_proc = launch_browser(selected, actual_port)
            self.statusBar().showMessage(
                f"Launched {selected.name} through Hermes (:{actual_port}). "
                f"Only this window is captured.")
        except Exception as e:
            QMessageBox.warning(self, "Browser launch failed",
                f"Could not launch {selected.name}:\n{e}\n\n"
                f"Falling back to system proxy.")
            if self.config.get("auto_set_proxy", True):
                set_system_proxy("127.0.0.1", actual_port)

    def _emit_flow(self, captured: CapturedRequest):
        """Thread-safe flow emission."""
        self.flow_received.emit(captured)

    def _on_pause_toggle(self):
        """Pause/continue capture without ending the recording session.

        While paused, traffic still flows through the proxy (the browser
        keeps working) but nothing is logged or intercepted — useful to
        keep irrelevant activity out of the HAR (e.g. stepping away).
        """
        if not self._recording or self._proxy_engine is None:
            return
        if not self._paused:
            self._proxy_engine.pause()
            if self._capturing_live and self._bridge:
                self._bridge.pause()
            self._paused = True
            self.btn_pause.setText("▶ Continue")
            self.lbl_proxy.setText(
                f"⏸ Proxy: :{self._proxy_engine.port} [PAUSED]")
            self.lbl_proxy.setStyleSheet("color: #E5C07B;")
            self.statusBar().showMessage(
                "Paused — traffic is NOT being recorded. Press Continue to resume.")
        else:
            self._proxy_engine.resume()
            if self._capturing_live and self._bridge:
                self._bridge.resume()
            self._paused = False
            self.btn_pause.setText("⏸ Pause")
            mode_label = {
                AppMode.HAR_TRACE: "HAR + API",
                AppMode.HAR_RECORD: "HAR",
                AppMode.API_TRACE: "API Trace",
            }.get(self._app_mode, "Recording")
            self.lbl_proxy.setText(
                f"🟢 Proxy: :{self._proxy_engine.port} [{mode_label}]")
            self.lbl_proxy.setStyleSheet("color: #98C379;")
            self.statusBar().showMessage("Recording resumed.")

    def _on_stop(self):
        """Stop recording."""
        from proxy_engine import unset_system_proxy

        if not self._recording:
            return

        if self._proxy_engine is not None:
            self._proxy_engine.stop()
        if self._capturing_live and self._bridge:
            self._bridge.stop_capture()
        self._capturing_live = False

        self._recording = False
        self._paused = False
        self._set_record_buttons_enabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸ Pause")
        self.lbl_proxy.setText("🔴 Proxy: Off")
        self.lbl_proxy.setStyleSheet("color: #E06C75;")
        self.statusBar().showMessage(f"Stopped. {len(self._flows)} requests captured.")

        # Only unset the system proxy if we actually set it (system mode).
        if self.browser_combo.currentData() is None and self.config.get("auto_set_proxy", True):
            unset_system_proxy()

    def _on_clear(self):
        """Clear all captured flows."""
        reply = QMessageBox.question(
            self, "Clear", "Clear all captured requests?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._flows.clear()
            self._bookmarked.clear()
            self._domains.clear()
            self._step_markers.clear()
            self.table.setRowCount(0)
            self._update_counts()
            self.filter_domain.clear()
            self.filter_domain.addItem("ALL")
            self._clear_detail()

    # ─── Flow Handling ─────────────────────────────────────────────────────────

    def _on_flow_received(self, captured: CapturedRequest):
        """Handle a new captured flow (main thread)."""
        # Classify resource type
        captured.resource_type = get_mime_category(captured.content_type, captured.url)

        # Auto-detect OAuth
        if detect_oauth_flow(captured.url, captured.status_code):
            captured.is_oauth = True

        idx = len(self._flows)
        self._flows.append(captured)

        # Track domains
        domain = captured.host
        if domain not in self._domains:
            self._domains.add(domain)
            self.filter_domain.addItem(domain)

        # Check if passes filter
        if self._flow_passes_filter(captured):
            self._add_table_row(captured, idx)

        self._update_counts()

    def _add_table_row(self, captured: CapturedRequest, idx: int):
        """Add a row to the request table."""
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Store index in first column data
        star_item = QTableWidgetItem("★" if captured.bookmarked else "")
        star_item.setData(Qt.ItemDataRole.UserRole, idx)
        star_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 0, star_item)

        method_item = QTableWidgetItem(captured.method)
        method_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        # Color by method
        method_colors = {
            "GET": "#61AFEF", "POST": "#98C379", "PUT": "#E5C07B",
            "PATCH": "#D19A66", "DELETE": "#E06C75",
        }
        color = method_colors.get(captured.method, "#ABB2BF")
        method_item.setForeground(QColor(color))
        self.table.setItem(row, 1, method_item)

        url_item = QTableWidgetItem(captured.url)
        url_item.setToolTip(captured.url)
        if captured.is_oauth:
            url_item.setForeground(QColor("#C678DD"))
        self.table.setItem(row, 2, url_item)

        status_item = QTableWidgetItem(str(captured.status_code))
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        status_class = get_status_class(captured.status_code)
        status_colors = {"2xx": "#98C379", "3xx": "#E5C07B", "4xx": "#E06C75", "5xx": "#BE5046"}
        status_item.setForeground(QColor(status_colors.get(status_class, "#ABB2BF")))
        self.table.setItem(row, 3, status_item)

        size_item = QTableWidgetItem(format_size(captured.response_size))
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        size_item.setData(Qt.ItemDataRole.UserRole, captured.response_size)
        self.table.setItem(row, 4, size_item)

        time_item = QTableWidgetItem(format_duration(captured.duration))
        time_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        time_item.setData(Qt.ItemDataRole.UserRole, captured.duration)
        self.table.setItem(row, 5, time_item)

        type_item = QTableWidgetItem(captured.resource_type)
        type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 6, type_item)

        # Auto-scroll to bottom
        self.table.scrollToBottom()

    def _update_counts(self):
        """Update request count and total size labels."""
        count = len(self._flows)
        total_size = sum(f.response_size for f in self._flows)
        self.lbl_count.setText(f"Requests: {count}")
        self.lbl_size.setText(f"Total: {format_size(total_size)}")

    # ─── Filtering ────────────────────────────────────────────────────────────

    def _flow_passes_filter(self, flow: CapturedRequest) -> bool:
        """Check if a flow passes current filters."""
        # Method filter
        method = self.filter_method.currentText()
        if method != "ALL" and flow.method != method:
            return False

        # Status filter
        status = self.filter_status.currentText()
        if status != "ALL":
            if status == "Error" and flow.status_code > 0:
                return False
            if status == "2xx" and not (200 <= flow.status_code < 300):
                return False
            if status == "3xx" and not (300 <= flow.status_code < 400):
                return False
            if status == "4xx" and not (400 <= flow.status_code < 500):
                return False
            if status == "5xx" and not (500 <= flow.status_code < 600):
                return False

        # Type filter
        ftype = self.filter_type.currentText()
        if ftype != "ALL" and flow.resource_type != ftype:
            return False

        # Domain filter
        domain = self.filter_domain.currentText()
        if domain != "ALL" and flow.host != domain:
            return False

        # Hide static
        if self.chk_hide_static.isChecked() and is_static_resource(flow.content_type, flow.url):
            return False

        # Search
        search = self.search_edit.text().strip().lower()
        if search:
            searchable = (
                flow.url + " " +
                json.dumps(flow.request_headers) + " " +
                json.dumps(flow.response_headers) + " " +
                flow.request_body_text + " " +
                flow.response_body_text
            ).lower()
            if search not in searchable:
                return False

        return True

    def _apply_filters(self):
        """Rebuild table with current filters."""
        self.table.setRowCount(0)
        self._filtered_indices.clear()

        for idx, flow in enumerate(self._flows):
            if self._flow_passes_filter(flow):
                self._filtered_indices.append(idx)
                self._add_table_row(flow, idx)

        self._update_counts()

    # ─── Selection & Detail ───────────────────────────────────────────────────

    def _on_selection_changed(self):
        """Handle table selection change."""
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._clear_detail()
            return

        row = rows[0].row()
        item = self.table.item(row, 0)
        if not item:
            return

        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is None or idx >= len(self._flows):
            return

        self._show_detail(self._flows[idx])

    def _show_detail(self, flow: CapturedRequest):
        """Show details for a flow in the detail tabs."""
        # Headers tab
        html = "<h3 style='color:#61AFEF;'>Request Headers</h3>"
        html += "<table style='color:#ABB2BF;'>"
        for k, v in flow.request_headers.items():
            html += f"<tr><td style='color:#E5C07B; padding-right:10px;'><b>{k}</b></td><td>{v}</td></tr>"
        html += "</table>"

        html += "<h3 style='color:#61AFEF;'>Response Headers</h3>"
        html += "<table style='color:#ABB2BF;'>"
        for k, v in flow.response_headers.items():
            html += f"<tr><td style='color:#E5C07B; padding-right:10px;'><b>{k}</b></td><td>{v}</td></tr>"
        html += "</table>"
        self.headers_text.setHtml(html)

        # Request Body
        self.request_body_text.setPlainText(flow.request_body_text or "(empty)")
        self._apply_highlighter(self.request_body_text, flow.request_headers.get('Content-Type', ''))

        # Response Body
        self.response_text.setPlainText(flow.response_body_text[:100000] or "(empty)")
        self._apply_highlighter(self.response_text, flow.content_type)

        # Cookies
        cookies_html = "<h3 style='color:#61AFEF;'>Request Cookies</h3><table style='color:#ABB2BF;'>"
        for k, v in flow.request_cookies.items():
            cookies_html += f"<tr><td style='color:#E5C07B;'><b>{k}</b></td><td>{v}</td></tr>"
        cookies_html += "</table>"
        cookies_html += "<h3 style='color:#61AFEF;'>Response Cookies</h3><table style='color:#ABB2BF;'>"
        for k, v in flow.response_cookies.items():
            cookies_html += f"<tr><td style='color:#E5C07B;'><b>{k}</b></td><td>{v}</td></tr>"
        cookies_html += "</table>"
        self.cookies_text.setHtml(cookies_html)

        # Timing
        timing_html = f"""
        <h3 style='color:#61AFEF;'>Timing</h3>
        <table style='color:#ABB2BF;'>
        <tr><td style='color:#E5C07B;'><b>Request Time:</b></td><td>{datetime.fromtimestamp(flow.request_time).strftime('%H:%M:%S.%f')[:-3]}</td></tr>
        <tr><td style='color:#E5C07B;'><b>Duration:</b></td><td>{format_duration(flow.duration)}</td></tr>
        <tr><td style='color:#E5C07B;'><b>Status:</b></td><td>{flow.status_code} {flow.reason}</td></tr>
        <tr><td style='color:#E5C07B;'><b>Request Size:</b></td><td>{format_size(flow.request_size)}</td></tr>
        <tr><td style='color:#E5C07B;'><b>Response Size:</b></td><td>{format_size(flow.response_size)}</td></tr>
        <tr><td style='color:#E5C07B;'><b>TLS Version:</b></td><td>{flow.tls_version or 'N/A'}</td></tr>
        <tr><td style='color:#E5C07B;'><b>HTTP Version:</b></td><td>{flow.http_version}</td></tr>
        </table>
        """
        self.timing_text.setHtml(timing_html)

        # Tokens
        tokens = extract_tokens_from_headers(flow.request_headers)
        tokens_html = "<h3 style='color:#61AFEF;'>Extracted Tokens & Keys</h3>"
        if tokens:
            tokens_html += "<table style='color:#ABB2BF;'>"
            for k, v in tokens.items():
                tokens_html += f"<tr><td style='color:#E5C07B;'><b>{k}</b></td><td style='color:#98C379;'>{v}</td></tr>"
            tokens_html += "</table>"
        else:
            tokens_html += "<p style='color:#5C6370;'>No auth tokens or API keys detected in request headers.</p>"
        self.tokens_text.setHtml(tokens_html)

        # Update waterfall with all visible flows
        visible_flows = [self._flows[i] for i in self._filtered_indices] if self._filtered_indices else self._flows
        self.waterfall.set_flows(visible_flows[-100:])  # Last 100 for performance

    def _apply_highlighter(self, text_widget: QPlainTextEdit, content_type: str):
        """Apply syntax highlighting based on content type."""
        # Remove existing highlighter
        old = text_widget.document().parent()
        if isinstance(old, QSyntaxHighlighter):
            old.setDocument(None)

        ct = content_type.lower()
        if 'json' in ct:
            JSONHighlighter(text_widget.document())
        elif 'html' in ct:
            HTMLHighlighter(text_widget.document())
        elif 'css' in ct:
            CSSHighlighter(text_widget.document())
        elif 'javascript' in ct:
            JSHighlighter(text_widget.document())

    def _clear_detail(self):
        """Clear detail panels."""
        self.headers_text.clear()
        self.request_body_text.clear()
        self.response_text.clear()
        self.cookies_text.clear()
        self.timing_text.clear()
        self.tokens_text.clear()

    # ─── Context Menu ─────────────────────────────────────────────────────────

    def _on_context_menu(self, pos):
        """Show right-click context menu."""
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return

        menu = QMenu(self)

        # Get selected flows
        flows = self._get_selected_flows()
        if not flows:
            return

        # Copy as cURL
        act_curl = menu.addAction("📋 Copy as cURL")
        act_curl.triggered.connect(lambda: self._copy_as(to_curl(flows[0])))

        # Copy as Python
        act_python = menu.addAction("🐍 Copy as Python requests")
        act_python.triggered.connect(lambda: self._copy_as(to_python_requests(flows[0])))

        # Copy as fetch
        act_fetch = menu.addAction("🌐 Copy as fetch()")
        act_fetch.triggered.connect(lambda: self._copy_as(to_fetch(flows[0])))

        menu.addSeparator()

        # Replay
        act_replay = menu.addAction("🔄 Replay Request")
        act_replay.triggered.connect(lambda: self._replay_flow(flows[0]))

        # Edit & Replay
        act_edit = menu.addAction("✏️ Edit & Replay")
        act_edit.triggered.connect(lambda: self._edit_and_replay(flows[0]))

        menu.addSeparator()

        # Bookmark
        flow = flows[0]
        if flow.bookmarked:
            act_star = menu.addAction("★ Remove Bookmark")
            act_star.triggered.connect(lambda: self._toggle_bookmark(flow))
        else:
            act_star = menu.addAction("☆ Bookmark")
            act_star.triggered.connect(lambda: self._toggle_bookmark(flow))

        # Step marker
        act_step = menu.addAction("📌 Add Step Marker Here")
        act_step.triggered.connect(lambda: self._add_step_marker())

        menu.addSeparator()

        # Export selected
        act_export_sel = menu.addAction("📁 Export Selected as HAR")
        act_export_sel.triggered.connect(lambda: self._export_selected(flows))

        # Remove
        act_remove = menu.addAction("🗑 Remove Selected")
        act_remove.setShortcut(QKeySequence("Delete"))
        act_remove.triggered.connect(self._remove_selected)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _get_selected_flows(self) -> List[CapturedRequest]:
        """Get flows from selected table rows."""
        flows = []
        for row_idx in self.table.selectionModel().selectedRows():
            row = row_idx.row()
            item = self.table.item(row, 0)
            if item:
                idx = item.data(Qt.ItemDataRole.UserRole)
                if idx is not None and idx < len(self._flows):
                    flows.append(self._flows[idx])
        return flows

    def _copy_as(self, text: str):
        """Copy text to clipboard."""
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Copied to clipboard", 2000)

    def _toggle_bookmark(self, flow: CapturedRequest):
        """Toggle bookmark on a flow."""
        flow.bookmarked = not flow.bookmarked
        self._apply_filters()

    def _remove_selected(self):
        """Remove selected rows."""
        rows = sorted(set(idx.row() for idx in self.table.selectionModel().selectedRows()), reverse=True)
        for row in rows:
            item = self.table.item(row, 0)
            if item:
                idx = item.data(Qt.ItemDataRole.UserRole)
                if idx is not None and idx < len(self._flows):
                    self._flows[idx] = None  # Mark as removed
        self._flows = [f for f in self._flows if f is not None]
        self._apply_filters()

    # ─── Replay ───────────────────────────────────────────────────────────────

    def _replay_flow(self, flow: CapturedRequest):
        """Replay a request."""
        self.statusBar().showMessage(f"Replaying {flow.method} {flow.url[:60]}...")
        self._replay_engine.replay_async(flow)

    def _edit_and_replay(self, flow: CapturedRequest):
        """Open edit dialog and replay."""
        dlg = EditRequestDialogUI(flow, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_modified_data()
            self.statusBar().showMessage(f"Replaying edited request...")
            self._replay_engine.replay_async(
                flow,
                modified_url=data["url"],
                modified_method=data["method"],
                modified_headers=data["headers"],
                modified_body=data["body"],
            )

    def _on_replay_complete(self, original_flow, result):
        """Handle replay completion."""
        from replay_engine import ReplayResult
        if result.success:
            msg = f"Replay complete: {result.status_code} ({format_duration(result.duration)})"
            self.statusBar().showMessage(msg, 5000)

            # Show replay result in a dialog
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Replay Result - {result.status_code}")
            dlg.setMinimumSize(600, 400)
            layout = QVBoxLayout(dlg)

            info = QLabel(f"Status: {result.status_code} {result.reason} | Duration: {format_duration(result.duration)}")
            layout.addWidget(info)

            tabs = QTabWidget()

            resp_text = QPlainTextEdit()
            resp_text.setPlainText(result.body[:100000])
            resp_text.setReadOnly(True)
            tabs.addTab(resp_text, "Response Body")

            headers_text = QPlainTextEdit()
            headers_text.setPlainText(json.dumps(result.headers, indent=2))
            headers_text.setReadOnly(True)
            tabs.addTab(headers_text, "Response Headers")

            layout.addWidget(tabs)
            dlg.exec()
        else:
            QMessageBox.warning(self, "Replay Failed", f"Error: {result.error}")

    # ─── Export ────────────────────────────────────────────────────────────────

    def _on_export(self):
        """Show export options."""
        if not self._flows:
            QMessageBox.information(self, "Export", "No requests to export.")
            return

        menu = QMenu(self)
        act_har = menu.addAction("Export as HAR (.har)")
        act_csv = menu.addAction("Export as CSV (.csv)")
        act_json = menu.addAction("Export as JSON (.json)")
        act_sel_har = menu.addAction("Export Selected as HAR")

        action = menu.exec(self.btn_export.mapToGlobal(self.btn_export.rect().bottomLeft()))
        if not action:
            return

        if action == act_har:
            path, _ = QFileDialog.getSaveFileName(self, "Export HAR", "", "HAR Files (*.har);;All Files (*)")
            if path:
                if export_full_har(self._flows, path):
                    self.statusBar().showMessage(f"Exported to {path}", 5000)
                else:
                    QMessageBox.warning(self, "Error", "Failed to export HAR.")

        elif action == act_csv:
            path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV Files (*.csv);;All Files (*)")
            if path:
                if save_csv(self._flows, path):
                    self.statusBar().showMessage(f"Exported to {path}", 5000)

        elif action == act_json:
            path, _ = QFileDialog.getSaveFileName(self, "Export JSON", "", "JSON Files (*.json);;All Files (*)")
            if path:
                if save_json(self._flows, path):
                    self.statusBar().showMessage(f"Exported to {path}", 5000)

        elif action == act_sel_har:
            flows = self._get_selected_flows()
            if not flows:
                QMessageBox.information(self, "Export", "No requests selected.")
                return
            path, _ = QFileDialog.getSaveFileName(self, "Export Selected HAR", "", "HAR Files (*.har);;All Files (*)")
            if path:
                if export_selected_har(flows, path):
                    self.statusBar().showMessage(f"Exported {len(flows)} requests to {path}", 5000)

    def _export_selected(self, flows: List[CapturedRequest]):
        """Export selected flows to HAR."""
        path, _ = QFileDialog.getSaveFileName(self, "Export Selected HAR", "", "HAR Files (*.har);;All Files (*)")
        if path:
            if export_selected_har(flows, path):
                self.statusBar().showMessage(f"Exported {len(flows)} requests", 5000)

    # ─── Smart Features ───────────────────────────────────────────────────────

    def _add_step_marker(self):
        """Add a step marker at the current position."""
        from PyQt6.QtWidgets import QInputDialog
        label, ok = QInputDialog.getText(self, "Step Marker", "Step label:")
        if ok and label:
            marker = {
                "label": label,
                "index": len(self._flows),
                "timestamp": time.time(),
            }
            self._step_markers.append(marker)
            self.statusBar().showMessage(f"Step marker added: {label}", 3000)

    def _extract_all_tokens(self):
        """Extract tokens from all captured traffic."""
        all_tokens = {}
        for flow in self._flows:
            tokens = extract_tokens_from_headers(flow.request_headers)
            for k, v in tokens.items():
                if k not in all_tokens:
                    all_tokens[k] = []
                all_tokens[k].append({
                    "url": flow.url,
                    "value": v,
                })

        if all_tokens:
            dlg = QDialog(self)
            dlg.setWindowTitle("Extracted Tokens & API Keys")
            dlg.setMinimumSize(600, 400)
            layout = QVBoxLayout(dlg)
            text = QPlainTextEdit()
            text.setPlainText(json.dumps(all_tokens, indent=2))
            text.setReadOnly(True)
            layout.addWidget(text)
            dlg.exec()
        else:
            QMessageBox.information(self, "Tokens", "No auth tokens or API keys found.")

    # ─── Session Management ───────────────────────────────────────────────────

    def _save_session(self):
        """Save current session to file."""
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        name = generate_session_name()
        filepath = SESSION_DIR / f"{name}.json"

        # Serialize flows
        session_data = {
            "version": APP_VERSION,
            "timestamp": datetime.now().isoformat(),
            "flow_count": len(self._flows),
            "flows": [],
            "step_markers": self._step_markers,
        }

        for flow in self._flows:
            fd = {
                "id": flow.id, "method": flow.method, "url": flow.url,
                "status_code": flow.status_code, "reason": flow.reason,
                "request_headers": flow.request_headers,
                "response_headers": flow.response_headers,
                "request_body_text": flow.request_body_text,
                "response_body_text": flow.response_body_text[:50000],
                "request_time": flow.request_time, "response_time": flow.response_time,
                "duration": flow.duration, "request_size": flow.request_size,
                "response_size": flow.response_size, "content_type": flow.content_type,
                "resource_type": flow.resource_type, "bookmarked": flow.bookmarked,
                "step_label": flow.step_label, "host": flow.host,
                "scheme": flow.scheme, "port": flow.port, "path": flow.path,
                "http_version": flow.http_version, "tls_version": flow.tls_version,
                "is_oauth": flow.is_oauth,
                "request_cookies": flow.request_cookies,
                "response_cookies": flow.response_cookies,
            }
            session_data["flows"].append(fd)

        try:
            with open(filepath, 'w') as f:
                json.dump(session_data, f)
            self.statusBar().showMessage(f"Session saved: {filepath.name}", 3000)
            self.config["last_session"] = str(filepath)
            save_config(self.config)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save session: {e}")

    def _load_session(self):
        """Load a session from file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Session", str(SESSION_DIR),
            "Session Files (*.json);;All Files (*)"
        )
        if path:
            self._load_session_file(path)

    def _load_session_file(self, path: str):
        """Load session from a specific file."""
        try:
            with open(path, 'r') as f:
                data = json.load(f)

            self._flows.clear()
            for fd in data.get("flows", []):
                flow = CapturedRequest()
                for k, v in fd.items():
                    if hasattr(flow, k):
                        setattr(flow, k, v)
                self._flows.append(flow)

            self._step_markers = data.get("step_markers", [])
            self._apply_filters()
            self._update_counts()
            self.statusBar().showMessage(f"Session loaded: {len(self._flows)} requests", 3000)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load session: {e}")

    def _restore_session(self):
        """Restore last session on launch."""
        last = self.config.get("last_session")
        if last and Path(last).exists():
            try:
                self._load_session_file(last)
            except Exception:
                pass

    def _auto_save(self):
        """Auto-save current session."""
        if self._flows:
            SESSION_DIR.mkdir(parents=True, exist_ok=True)
            filepath = SESSION_DIR / "autosave.json"
            session_data = {
                "version": APP_VERSION,
                "timestamp": datetime.now().isoformat(),
                "flow_count": len(self._flows),
                "flows": [],
                "step_markers": self._step_markers,
            }
            for flow in self._flows:
                fd = {
                    "id": flow.id, "method": flow.method, "url": flow.url,
                    "status_code": flow.status_code, "reason": flow.reason,
                    "request_headers": flow.request_headers,
                    "response_headers": flow.response_headers,
                    "request_body_text": flow.request_body_text,
                    "response_body_text": flow.response_body_text[:50000],
                    "request_time": flow.request_time, "response_time": flow.response_time,
                    "duration": flow.duration, "request_size": flow.request_size,
                    "response_size": flow.response_size, "content_type": flow.content_type,
                    "resource_type": flow.resource_type, "bookmarked": flow.bookmarked,
                    "step_label": flow.step_label, "host": flow.host,
                    "scheme": flow.scheme, "port": flow.port, "path": flow.path,
                    "http_version": flow.http_version, "tls_version": flow.tls_version,
                    "is_oauth": flow.is_oauth,
                    "request_cookies": flow.request_cookies,
                    "response_cookies": flow.response_cookies,
                }
                session_data["flows"].append(fd)
            try:
                with open(filepath, 'w') as f:
                    json.dump(session_data, f)
            except Exception:
                pass

    # ─── Misc ──────────────────────────────────────────────────────────────────

    def _toggle_on_top(self, checked):
        """Toggle always on top."""
        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self.config["always_on_top"] = checked
        save_config(self.config)

    def _change_port(self):
        """Change proxy port."""
        from PyQt6.QtWidgets import QInputDialog
        current = self.config.get("proxy_port", 8899)
        port, ok = QInputDialog.getInt(
            self, "Proxy Port", "Enter proxy port:", current, 1024, 65535
        )
        if ok:
            self.config["proxy_port"] = port
            save_config(self.config)
            self.statusBar().showMessage(f"Port changed to {port}. Restart recording to apply.")

    def _toggle_auto_proxy(self, checked):
        """Toggle auto-set system proxy."""
        self.config["auto_set_proxy"] = checked
        save_config(self.config)

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h2>{APP_NAME}</h2>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p>A desktop HTTP traffic recorder, API interceptor, and HAR exporter.</p>"
            f"<p><b>HAR Record Mode:</b> Passively captures HTTP/HTTPS traffic using mitmproxy "
            f"with a rich UI for inspecting, filtering, and exporting requests.</p>"
            f"<p><b>API Trace Mode:</b> Actively intercepts API requests like Burp Suite. "
            f"Pause, inspect, modify, forward, or drop requests in real-time.</p>"
            f"<hr><p>Built with Python, PyQt6, and mitmproxy.</p>"
        )

    def _on_proxy_error(self, error: str):
        """Handle proxy errors."""
        self.statusBar().showMessage(f"Proxy error: {error}", 5000)

    def closeEvent(self, event):
        """Handle window close."""
        # Handle pending trace requests
        pending = self._trace_engine.get_pending_count()
        if pending > 0:
            reply = QMessageBox.question(
                self, "Pending Requests",
                f"There are {pending} intercepted request(s) still pending.\n\n"
                "Forward them before closing? (No = drop all)",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            elif reply == QMessageBox.StandardButton.Yes:
                self._trace_engine.forward_all()
            else:
                self._trace_engine.drop_all()

        # Save geometry
        from PyQt6.QtCore import QByteArray
        self.config["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode()

        # Stop proxy
        if self._recording:
            self._on_stop()

        # Fully tear down the proxy master and release the port on close.
        if self._proxy_engine is not None:
            try:
                self._proxy_engine.shutdown()
            except Exception:
                pass
            self._proxy_engine = None

        # Stop the extension bridge.
        if self._bridge is not None:
            try:
                self._bridge.stop()
            except Exception:
                pass
            self._bridge = None

        # Auto-save on close
        if self._flows:
            self._auto_save()

        save_config(self.config)
        event.accept()
