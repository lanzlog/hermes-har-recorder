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

from proxy_engine import CapturedRequest
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


# ─── Main Window ──────────────────────────────────────────────────────────────

class HARRecorderWindow(QMainWindow):
    """Main application window."""

    # Signals for thread-safe communication
    flow_received = pyqtSignal(object)  # CapturedRequest
    proxy_error = pyqtSignal(str)
    replay_complete = pyqtSignal(object, object)  # flow, ReplayResult

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self._flows: List[CapturedRequest] = []
        self._filtered_indices: List[int] = []
        self._bookmarked: Set[str] = set()
        self._domains: Set[str] = set()
        self._step_markers: List[Dict] = []
        self._recording = False

        # Replay engine
        self._replay_engine = ReplayEngine(
            on_complete=lambda f, r: self.replay_complete.emit(f, r)
        )

        self._init_ui()
        self._connect_signals()
        self._apply_dark_theme()
        self._restore_session()

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

        self.btn_record = QPushButton("🔴 Record")
        self.btn_record.setToolTip("Start recording (Ctrl+R)")
        self.btn_record.setFixedHeight(36)
        self.btn_record.setStyleSheet("font-weight:bold; padding: 6px 16px;")
        toolbar_layout.addWidget(self.btn_record)

        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setToolTip("Stop recording (Ctrl+S)")
        self.btn_stop.setFixedHeight(36)
        self.btn_stop.setEnabled(False)
        toolbar_layout.addWidget(self.btn_stop)

        self.btn_clear = QPushButton("🗑 Clear")
        self.btn_clear.setToolTip("Clear all captured requests")
        self.btn_clear.setFixedHeight(36)
        toolbar_layout.addWidget(self.btn_clear)

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

        main_layout.addLayout(filter_layout)

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
        main_layout.addWidget(splitter)

        # ── Menu Bar ──
        self._build_menu_bar()

        # ── Status Bar ──
        self.statusBar().showMessage("Ready")

    def _build_menu_bar(self):
        """Build the menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")
        act_record = QAction("Record", self)
        act_record.setShortcut(QKeySequence("Ctrl+R"))
        act_record.triggered.connect(self._on_record)
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

        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        act_step = QAction("Add Step Marker", self)
        act_step.setShortcut(QKeySequence("Ctrl+M"))
        act_step.triggered.connect(self._add_step_marker)
        tools_menu.addAction(act_step)

        act_extract = QAction("Extract Tokens", self)
        act_extract.triggered.connect(self._extract_all_tokens)
        tools_menu.addAction(act_extract)

        # Help menu
        help_menu = menubar.addMenu("Help")
        act_about = QAction("About", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _connect_signals(self):
        """Connect signals and slots."""
        self.btn_record.clicked.connect(self._on_record)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_export.clicked.connect(self._on_export)

        self.flow_received.connect(self._on_flow_received)
        self.proxy_error.connect(self._on_proxy_error)
        self.replay_complete.connect(self._on_replay_complete)

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

    # ─── Proxy Control ────────────────────────────────────────────────────────

    def _on_record(self):
        """Start recording."""
        from proxy_engine import ProxyEngine, set_system_proxy

        if self._recording:
            return

        port = self.config.get("proxy_port", 8899)

        self._proxy_engine = ProxyEngine(
            port=port,
            on_flow=self._emit_flow,
            on_error=lambda e: self.proxy_error.emit(e),
        )

        if self._proxy_engine.start():
            self._recording = True
            self.btn_record.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.lbl_proxy.setText(f"🟢 Proxy: :{port}")
            self.lbl_proxy.setStyleSheet("color: #98C379;")
            self.statusBar().showMessage(f"Recording on port {port}")

            # Auto-set system proxy on Windows
            if self.config.get("auto_set_proxy", True):
                set_system_proxy(port)
        else:
            QMessageBox.warning(self, "Error", "Failed to start proxy. Port may be in use.")

    def _emit_flow(self, captured: CapturedRequest):
        """Thread-safe flow emission."""
        self.flow_received.emit(captured)

    def _on_stop(self):
        """Stop recording."""
        from proxy_engine import unset_system_proxy

        if not self._recording:
            return

        if hasattr(self, '_proxy_engine'):
            self._proxy_engine.stop()

        self._recording = False
        self.btn_record.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_proxy.setText("🔴 Proxy: Off")
        self.lbl_proxy.setStyleSheet("color: #E06C75;")
        self.statusBar().showMessage(f"Stopped. {len(self._flows)} requests captured.")

        if self.config.get("auto_set_proxy", True):
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

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h2>{APP_NAME}</h2>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p>A desktop HTTP traffic recorder and HAR exporter.</p>"
            f"<p>Captures HTTP/HTTPS traffic using mitmproxy and provides "
            f"a rich UI for inspecting, filtering, and exporting requests.</p>"
            f"<hr><p>Built with Python, PyQt6, and mitmproxy.</p>"
        )

    def _on_proxy_error(self, error: str):
        """Handle proxy errors."""
        self.statusBar().showMessage(f"Proxy error: {error}", 5000)

    def closeEvent(self, event):
        """Handle window close."""
        # Save geometry
        from PyQt6.QtCore import QByteArray
        self.config["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode()

        # Stop proxy
        if self._recording:
            self._on_stop()

        # Auto-save on close
        if self._flows:
            self._auto_save()

        save_config(self.config)
        event.accept()
