"""Compact Qt control console. Browser and socket work never run on the GUI thread."""

import json
import sys
from copy import deepcopy
from collections import deque
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QLockFile, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QDialog, QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QSplitter, QTabWidget, QTableWidget, QMenu, QToolButton,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .bridge import Bridge
from .browser_worker import BrowserWorker
from .capture_types import TYPE_LABELS, available_capture_types, selected_capture_types
from .voice_reply_policy import VoiceReplyPolicy, VOICE_REPLY_TYPES, selected_voice_reply_types
from .platforms import PLATFORMS
from .scheduler import Phrase, Product, SequenceScheduler
from .storage import (
    account_profile_path, accounts_for, add_account, bridge_token, data_dir,
    delete_account_profile, load_settings, remove_account, rename_account,
    save_settings, selected_account,
)
from .voice_protocol import to_voice_event
from . import __version__


def _brand_icon_path() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / "assets" / "boleme.png"


STYLE = """
QWidget { background: #181d20; color: #e8efed; font-size: 13px; }
QMainWindow { background: #181d20; }
QLabel#title { font-size: 18px; font-weight: 600; }
QLabel#version { color: #9cabaa; font-size: 12px; }
QLabel#pageTitle { font-size: 17px; font-weight: 600; }
QLabel#muted, QLabel#capability { color: #9cabaa; }
QToolButton#capability { color: #9cabaa; border: 1px solid #3a4a4e; border-radius: 4px; padding: 5px 10px; }
QMenu { background: #20292d; color: #e4eeee; border: 1px solid #3a4a4e; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background: #326d64; }
QLabel#productHint { color: #9cabaa; padding: 0 0 2px 0; }
QLabel#productState { color: #9cabaa; min-width: 44px; }
QLabel#productState[running="true"] { color: #8bd3bf; }
QLabel#status { color: #d19f86; font-weight: 600; }
QLabel#status[connected="true"] { color: #8bd3bf; }
QPushButton { background: #293337; border: 1px solid #435256; border-radius: 4px; padding: 7px 13px; min-height: 19px; }
QPushButton:hover { background: #364549; border-color: #66827d; }
QPushButton:pressed { background: #243d39; }
QPushButton:disabled { color: #788486; background: #21282b; }
QPushButton#primary { background: #2d786a; border-color: #459784; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #398c7c; }
QLineEdit, QTextEdit, QComboBox, QTableWidget, QListWidget { background: #20292d; border: 1px solid #3a4a4e; border-radius: 4px; selection-background-color: #326d64; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QTableWidget:focus { border-color: #5d9f8d; }
QLineEdit, QComboBox { padding: 6px 9px; min-height: 22px; }
QTextEdit { padding: 8px; }
QTableWidget { alternate-background-color: #243035; gridline-color: #354146; }
QTableWidget::item { padding: 3px 7px; }
QListWidget::item { padding: 9px 12px; }
QTableWidget#productTable::item { padding: 5px 10px; }
QHeaderView::section { background: #263338; color: #baccca; padding: 8px; border: 0; border-bottom: 1px solid #3a4a4e; }
QTabWidget::pane { border: 0; border-top: 1px solid #354447; }
QTabBar::tab { background: transparent; color: #a8b6b5; padding: 11px 19px; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: #e8efed; background: #222c2f; }
QTabBar::tab:selected { color: #e8efed; border-bottom-color: #5fb49e; font-weight: 600; }
QCheckBox { spacing: 8px; }
QSplitter::handle:vertical { background: #344449; height: 5px; }
QTextEdit#logView { background: #171d20; }
"""


def _table(columns, stretch=0):
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(38)
    table.setShowGrid(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    return table


class ToggleSwitch(QCheckBox):
    def __init__(self, accessible_name, parent=None):
        super().__init__(parent)
        self.setAccessibleName(accessible_name)
        self.setFixedSize(48, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2d786a" if self.isChecked() else "#435256"))
        painter.drawRoundedRect(1, 2, 46, 22, 11, 11)
        painter.setBrush(QColor("#f4faf7"))
        painter.drawEllipse(26 if self.isChecked() else 4, 4, 18, 18)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor("#8bd3bf"))
            painter.drawRoundedRect(0, 1, 47, 24, 12, 12)


class Console(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.worker = None
        self.connected = False
        self.phrase_schedule = None
        self.product_schedule = None
        self._worker_busy = False
        self._closing = False
        self._pending_account_id = None
        self._pending_platform = None
        self._pending_events = deque(maxlen=2000)
        self._raw_events = {}
        self._event_count = 0
        self._selected_msg_id = ""
        self.voice_reply_policy = VoiceReplyPolicy()
        self.setWindowTitle(f"播了么直播中控助手 v{__version__}")
        self.setWindowIcon(QIcon(str(_brand_icon_path())))
        self.resize(1100, 710)
        self.setMinimumSize(900, 590)
        self.setStyleSheet(STYLE)
        self._build()
        self._load()
        self.bridge = Bridge(bridge_token(self.settings))
        self.bridge.platform = self.platform.currentData()
        self.bridge.send_requested.connect(self._bridge_send)
        self.bridge.platform_requested.connect(self._bridge_select_platform)
        self.bridge.status_changed.connect(self._log)
        self.bridge.start()
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.barrage_timer = QTimer(self)
        self.barrage_timer.setInterval(100)
        self.barrage_timer.timeout.connect(self._flush_barrage)
        self.barrage_timer.start()

    def _build(self):
        base = QWidget()
        self.setCentralWidget(base)
        root = QVBoxLayout(base)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        icon = QLabel()
        icon.setFixedSize(28, 28)
        icon.setPixmap(QPixmap(str(_brand_icon_path())).scaled(
            28, 28, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        header.addWidget(icon)
        title = QLabel("播了么")
        title.setObjectName("title")
        title.setToolTip("播了么直播中控助手")
        header.addWidget(title)
        version = QLabel(f"v{__version__}")
        version.setObjectName("version")
        header.addWidget(version)
        header.addStretch()
        self.platform = QComboBox()
        for spec in PLATFORMS.values():
            self.platform.addItem(spec.name, spec.key)
        self.platform.setMinimumWidth(132)
        self.platform.currentIndexChanged.connect(self._platform_changed)
        header.addWidget(self.platform)
        self.account = QComboBox()
        self.account.setMinimumWidth(125)
        self.account.setMaximumWidth(165)
        self.account.setToolTip("选择账号后自动打开对应的中控台")
        self.account.activated.connect(self._account_activated)
        header.addWidget(self.account)
        manage_accounts = QPushButton("账号管理")
        manage_accounts.clicked.connect(self._manage_accounts)
        header.addWidget(manage_accounts)
        self.connect_button = QPushButton("连接中控台")
        self.connect_button.setObjectName("primary")
        self.connect_button.clicked.connect(self._toggle_connection)
        header.addWidget(self.connect_button)
        self.state = QLabel("未连接")
        self.state.setObjectName("status")
        self.state.setProperty("connected", False)
        self.state.setMaximumWidth(120)
        header.addWidget(self.state)
        save = QPushButton("保存设置")
        save.clicked.connect(self._save)
        header.addWidget(save)
        root.addLayout(header)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.splitter.addWidget(self.tabs)

        live_page = QWidget()
        live_layout = QVBoxLayout(live_page)
        live_layout.setContentsMargins(0, 12, 0, 4)
        live_layout.setSpacing(9)
        live_header = QHBoxLayout()
        self.barrage_count = QLabel("实时弹幕 (0)")
        live_title = self.barrage_count
        live_title.setObjectName("pageTitle")
        live_header.addWidget(live_title)
        live_header.addStretch()
        self.capability = QToolButton()
        self.capability.setObjectName("capability")
        self.capability.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.capability.setToolTip("勾选需要显示并推送到语音引擎的弹幕类型，修改后自动保存。")
        self.capture_type_menu = QMenu(self.capability)
        self.capability.setMenu(self.capture_type_menu)
        self._capture_type_actions = {}
        live_header.addWidget(self.capability)
        self.only_pending = QCheckBox("只看未发送")
        self.only_pending.toggled.connect(self._filter_barrage)
        live_header.addWidget(self.only_pending)
        fields = QPushButton("查看字段")
        fields.setToolTip("查看选中弹幕的原始 JSON 字段，仅在本机显示。")
        fields.clicked.connect(self._show_fields)
        live_header.addWidget(fields)
        clear_barrage = QPushButton("清空")
        clear_barrage.clicked.connect(self._clear_barrage)
        live_header.addWidget(clear_barrage)
        live_layout.addLayout(live_header)
        self.barrage = _table(["时间", "用户昵称", "消息内容", "消息类型", "文字状态", "操作"], stretch=2)
        self.barrage.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.barrage.setColumnWidth(0, 90)
        self.barrage.setColumnWidth(1, 145)
        self.barrage.setColumnWidth(3, 90)
        self.barrage.setColumnWidth(4, 95)
        self.barrage.setColumnWidth(5, 85)
        self.barrage.cellClicked.connect(self._barrage_cell_clicked)
        live_layout.addWidget(self.barrage, 1)
        voice_sync_row = QHBoxLayout()
        voice_sync_row.addWidget(QLabel("语音文案自动发公屏"))
        self.voice_reply_checks = {}
        for kind, label in VOICE_REPLY_TYPES.items():
            checkbox = QCheckBox(label)
            checkbox.setChecked(kind in selected_voice_reply_types(self.settings))
            checkbox.setToolTip("仅发送语音引擎已经生成的文案，不再次查询知识库。" if kind == "comment" else
                                "同一订单最多感谢一次；与其他文字间隔至少30秒，繁忙时跳过，不积压补发。")
            checkbox.toggled.connect(self._voice_reply_types_changed)
            self.voice_reply_checks[kind] = checkbox
            voice_sync_row.addWidget(checkbox)
        voice_sync_row.addStretch()
        order_hint = QLabel("订单：同单一次，间隔至少30秒")
        order_hint.setObjectName("muted")
        voice_sync_row.addWidget(order_hint)
        live_layout.addLayout(voice_sync_row)
        send_row = QHBoxLayout()
        send_row.addWidget(QLabel("公开发言"))
        self.reply_context = QLabel("公开发言")
        self.reply_context.setObjectName("muted")
        send_row.addWidget(self.reply_context)
        self.message = QLineEdit()
        self.message.setPlaceholderText("输入文字，按回车发送")
        self.message.setMaxLength(300)
        self.message.returnPressed.connect(self._send_manual)
        send_row.addWidget(self.message, 1)
        send_button = QPushButton("发送")
        send_button.setObjectName("primary")
        send_button.clicked.connect(self._send_manual)
        send_row.addWidget(send_button)
        live_layout.addLayout(send_row)
        self.tabs.addTab(live_page, "直播互动")

        phrase_page = QWidget()
        phrase_layout = QVBoxLayout(phrase_page)
        phrase_layout.setContentsMargins(0, 12, 0, 4)
        phrase_layout.setSpacing(12)
        phrase_header = QHBoxLayout()
        phrase_title = QLabel("快捷语")
        phrase_title.setObjectName("pageTitle")
        phrase_header.addWidget(phrase_title)
        phrase_header.addStretch()
        self.phrase_enabled = QCheckBox("自动发送")
        self.phrase_enabled.setToolTip("按列表顺序发送，每条使用自己的间隔。连接中控台后可开启。")
        self.phrase_enabled.toggled.connect(self._toggle_phrases)
        phrase_header.addWidget(self.phrase_enabled)
        phrase_layout.addLayout(phrase_header)
        self.phrases = _table(["快捷语", "间隔（秒）"])
        self.phrases.setColumnWidth(1, 150)
        phrase_layout.addWidget(self.phrases, 1)
        phrase_actions = QHBoxLayout()
        add_phrase = QPushButton("添加")
        add_phrase.clicked.connect(lambda: self._add_row(self.phrases, ["", "120"]))
        phrase_actions.addWidget(add_phrase)
        del_phrase = QPushButton("删除选中")
        del_phrase.clicked.connect(lambda: self._delete_row(self.phrases))
        phrase_actions.addWidget(del_phrase)
        phrase_actions.addStretch()
        phrase_layout.addLayout(phrase_actions)
        self.tabs.addTab(phrase_page, "快捷语")

        product_page = QWidget()
        product_layout = QVBoxLayout(product_page)
        product_layout.setContentsMargins(0, 12, 0, 4)
        product_layout.setSpacing(12)
        product_header = QHBoxLayout()
        product_title = QLabel("商品讲解")
        product_title.setObjectName("pageTitle")
        product_header.addWidget(product_title)
        product_header.addStretch()
        product_toggle_label = QLabel("自动讲解")
        product_header.addWidget(product_toggle_label)
        self.product_enabled = ToggleSwitch("自动讲解开关")
        self.product_enabled.setToolTip("启动自动讲解；需先连接中控台")
        self.product_enabled.toggled.connect(self._toggle_products)
        product_header.addWidget(self.product_enabled)
        self.product_state = QLabel("已停止")
        self.product_state.setObjectName("productState")
        self.product_state.setProperty("running", False)
        product_header.addWidget(self.product_state)
        product_layout.addLayout(product_header)
        product_hint = QLabel("单品只需保留一条；商品序号对应中控台编号，点击表格中的数字可修改。")
        product_hint.setObjectName("productHint")
        product_actions = QHBoxLayout()
        product_actions.addWidget(product_hint)
        product_actions.addStretch()
        add_product = QPushButton("添加商品")
        add_product.clicked.connect(self._add_product)
        product_actions.addWidget(add_product)
        self.delete_product_button = QPushButton("删除选中")
        self.delete_product_button.clicked.connect(self._delete_product)
        product_actions.addWidget(self.delete_product_button)
        product_layout.addLayout(product_actions)
        self.products = _table(["商品序号", "重复次数", "间隔（秒）"])
        self.products.setObjectName("productTable")
        self.products.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        for column in range(self.products.columnCount()):
            self.products.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.products.verticalHeader().setDefaultSectionSize(36)
        self.products.cellClicked.connect(self._edit_product_cell)
        self.products.itemSelectionChanged.connect(self._update_product_actions)
        product_layout.addWidget(self.products, 1)
        self.tabs.addTab(product_page, "商品讲解")

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 5, 0, 0)
        log_layout.setSpacing(5)
        log_header = QHBoxLayout()
        log_title = QLabel("运行记录")
        log_header.addWidget(log_title)
        log_header.addStretch()
        clear_logs = QPushButton("清空显示")
        clear_logs.setToolTip("只清空当前显示，不影响正在运行的任务。")
        clear_logs.clicked.connect(self.logs_clear)
        log_header.addWidget(clear_logs)
        log_layout.addLayout(log_header)
        self.logs = QTextEdit()
        self.logs.setObjectName("logView")
        self.logs.setReadOnly(True)
        self.logs.document().setMaximumBlockCount(300)
        self.logs.setPlaceholderText("暂无运行记录")
        log_layout.addWidget(self.logs, 1)
        self.splitter.addWidget(log_panel)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([520, 160])

    def logs_clear(self):
        self.logs.clear()

    def _clear_barrage(self):
        self._pending_events.clear()
        self._raw_events.clear()
        self._event_count = 0
        self._selected_msg_id = ""
        self.reply_context.setText("公开发言")
        self.barrage.setRowCount(0)
        self.barrage_count.setText("实时弹幕 (0)")

    def _flush_barrage(self):
        if not self._pending_events:
            return
        names = {**TYPE_LABELS, "gift": "礼物"}
        self.barrage.setUpdatesEnabled(False)
        try:
            for _ in range(min(60, len(self._pending_events))):
                event = self._pending_events.popleft()
                if event.get("type") not in self._selected_capture_types():
                    continue
                if self.barrage.rowCount() >= 500:
                    first = self.barrage.item(0, 0)
                    if first:
                        self._raw_events.pop(first.data(Qt.ItemDataRole.UserRole), None)
                    self.barrage.removeRow(0)
                row = self.barrage.rowCount()
                self.barrage.insertRow(row)
                key = f"event-{self._event_count}"
                self._event_count += 1
                msg_id = str(event.get("msg_id") or key)
                try:
                    when = datetime.fromtimestamp(int(event.get("time")) / 1000).strftime("%H:%M:%S")
                except (TypeError, ValueError, OSError, OverflowError):
                    when = datetime.now().strftime("%H:%M:%S")
                kind = str(event.get("type") or "")
                status = "待发送" if kind == "comment" else "—"
                values = [when, str(event.get("nickname") or "未提供昵称"),
                          str(event.get("content") or ""), names.get(kind, kind), status,
                           "发文字" if kind == "comment" else "—"]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, key)
                        item.setData(Qt.ItemDataRole.UserRole + 1, msg_id)
                    if column == 2:
                        item.setToolTip(value)
                    if column == 5 and kind == "comment":
                        item.setForeground(QColor("#7dd3be"))
                        item.setToolTip("在公共评论框发送文字，不会艾特或定向回复该用户")
                    self.barrage.setItem(row, column, item)
                self._raw_events[key] = event
                if self.only_pending.isChecked() and kind != "comment":
                    self.barrage.setRowHidden(row, True)
            self.barrage_count.setText(f"实时弹幕 ({self._event_count})")
            self.barrage.scrollToBottom()
        finally:
            self.barrage.setUpdatesEnabled(True)

    def _filter_barrage(self, enabled):
        selected = self._selected_capture_types()
        for row in range(self.barrage.rowCount()):
            status = self.barrage.item(row, 4)
            item = self.barrage.item(row, 0)
            event = self._raw_events.get(item.data(Qt.ItemDataRole.UserRole), {}) if item else {}
            hidden = event.get("type") not in selected or (enabled and (not status or status.text() not in ("待发送", "发送失败")))
            self.barrage.setRowHidden(row, hidden)

    def _barrage_cell_clicked(self, row, column):
        if column != 5 or self.barrage.item(row, 5).text() != "发文字":
            return
        self._selected_msg_id = self.barrage.item(row, 0).data(Qt.ItemDataRole.UserRole + 1)
        nickname = self.barrage.item(row, 1).text()
        self.reply_context.setText(f"参考 {nickname[:12]} · 公开发送")
        self.message.setFocus()

    def _mark_reply(self, msg_id, status):
        if not msg_id:
            return
        self._flush_barrage()
        for row in range(self.barrage.rowCount() - 1, -1, -1):
            item = self.barrage.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole + 1) == msg_id:
                self.barrage.item(row, 4).setText(status)
                self._filter_barrage(self.only_pending.isChecked())
                break

    def _show_fields(self):
        row = self.barrage.currentRow()
        if row < 0:
            QMessageBox.information(self, "弹幕字段", "请先选中一条弹幕。")
            return
        item = self.barrage.item(row, 0)
        event = self._raw_events.get(item.data(Qt.ItemDataRole.UserRole)) if item else None
        if not event:
            return
        content = json.dumps({"标准化事件": {k: v for k, v in event.items() if k != "raw"},
                              "平台原始消息": event.get("raw")}, ensure_ascii=False, indent=2)
        dialog = QDialog(self)
        dialog.setWindowTitle("弹幕字段 · 仅本机查看")
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        field_view = QTextEdit()
        field_view.setReadOnly(True)
        field_view.setPlainText(content)
        layout.addWidget(field_view)
        actions = QHBoxLayout()
        actions.addStretch()
        copy_button = QPushButton("复制 JSON")
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(content))
        actions.addWidget(copy_button)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(dialog.accept)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        dialog.exec()

    def _load(self):
        index = self.platform.findData(self.settings.get("platform", "douyin"))
        self.platform.setCurrentIndex(max(index, 0))
        for values in self.settings.get("phrases", []):
            if isinstance(values, list) and len(values) == 2:
                self._add_row(self.phrases, values)
        for values in self.settings.get("products", []):
            if isinstance(values, list) and len(values) == 3:
                self._add_product_row(values)
        if not self.products.rowCount():
            self._add_product_row(["1", "1", "60"])
        self._update_product_actions()
        self._platform_changed()

    def _platform_changed(self):
        spec = PLATFORMS[self.platform.currentData()]
        order_checkbox = getattr(self, "voice_reply_checks", {}).get("live_order")
        if order_checkbox:
            order_checkbox.setEnabled(spec.capture == "douyin")
        if hasattr(self, 'bridge'):
            self.bridge.platform = spec.key
        self._refresh_capture_types()
        self._refresh_accounts()

    def _selected_capture_types(self):
        return selected_capture_types(self.settings, PLATFORMS[self.platform.currentData()].capture)

    def _refresh_capture_types(self):
        capture = PLATFORMS[self.platform.currentData()].capture
        available = available_capture_types(capture)
        selected = self._selected_capture_types()
        self.capture_type_menu.clear()
        self._capture_type_actions = {}
        for kind in available:
            action = self.capture_type_menu.addAction(TYPE_LABELS[kind])
            action.setCheckable(True)
            action.setChecked(kind in selected)
            action.toggled.connect(self._capture_types_changed)
            self._capture_type_actions[kind] = action
        self.capability.setEnabled(bool(available))
        self._update_capture_types_label()

    def _update_capture_types_label(self):
        available = available_capture_types(PLATFORMS[self.platform.currentData()].capture)
        selected = self._selected_capture_types()
        label = " / ".join(TYPE_LABELS[kind] for kind in selected) or "未选择"
        self.capability.setToolTip(label if available else "暂不支持弹幕")
        if len(available) > 1 and selected == available:
            label = "全部"
        elif len(selected) > 2:
            label = f"已选 {len(selected)} 类"
        self.capability.setText(f"采集类型：{label}" if available else "暂不支持弹幕")

    def _capture_types_changed(self, _checked):
        capture = PLATFORMS[self.platform.currentData()].capture
        candidate = deepcopy(self.settings)
        if not isinstance(candidate.get("capture_types"), dict):
            candidate["capture_types"] = {}
        candidate["capture_types"][capture] = [kind for kind, action in self._capture_type_actions.items() if action.isChecked()]
        try:
            save_settings(candidate)
        except (OSError, TypeError, ValueError) as exc:
            selected = self._selected_capture_types()
            for kind, action in self._capture_type_actions.items():
                blocked = action.blockSignals(True)
                action.setChecked(kind in selected)
                action.blockSignals(blocked)
            self._log(f"弹幕类型保存失败: {exc}")
            return
        self.settings = candidate
        self._update_capture_types_label()
        selected = self._selected_capture_types()
        self._pending_events = deque((event for event in self._pending_events if event.get("type") in selected), maxlen=2000)
        self._filter_barrage(self.only_pending.isChecked())
        self._log("弹幕采集类型已自动保存")

    def _bridge_select_platform(self, platform):
        index = self.platform.findData(platform)
        if index < 0:
            return
        if platform == self.platform.currentData():
            if not (self.worker and self.worker.isRunning()):
                self._start_connection()
            return
        if self.worker and self.worker.isRunning():
            answer = QMessageBox.question(
                self, "切换中控平台",
                "语音引擎请求切换采集平台。当前浏览器和自动任务将停止，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.bridge.broadcast_status("平台切换已取消")
                return
            self._pending_platform = platform
            self._pending_account_id = None
            self.connected = False
            self.phrase_enabled.setChecked(False)
            self.product_enabled.setChecked(False)
            self.connect_button.setText("正在切换…")
            self.connect_button.setEnabled(False)
            self.bridge.broadcast_status("正在切换平台")
            self.worker.stop()
            return
        self.platform.setCurrentIndex(index)
        self._start_connection()

    def _refresh_accounts(self, preferred_id=None):
        platform = self.platform.currentData()
        account_id = preferred_id or selected_account(self.settings, platform)
        blocked = self.account.blockSignals(True)
        try:
            self.account.clear()
            for row in accounts_for(self.settings, platform):
                self.account.addItem(row["name"], row["id"])
            index = self.account.findData(account_id)
            self.account.setCurrentIndex(max(index, 0))
            self.settings.setdefault("selected_accounts", {})[platform] = self.account.currentData()
        finally:
            self.account.blockSignals(blocked)

    def _account_activated(self, index):
        account_id = self.account.itemData(index)
        if not account_id:
            return
        previous = selected_account(self.settings, self.platform.currentData())
        self.settings["selected_accounts"][self.platform.currentData()] = account_id
        if not self._save():
            self._refresh_accounts(previous)
            return
        self._activate_selected_account()

    def _activate_selected_account(self):
        account_id = self.account.currentData()
        if self.worker and self.worker.isRunning():
            if getattr(self.worker, "account_id", "default") == account_id:
                return
            self._pending_account_id = account_id
            self.connected = False
            self.phrase_enabled.setChecked(False)
            self.product_enabled.setChecked(False)
            self.connect_button.setText("正在切换…")
            self.connect_button.setEnabled(False)
            self.account.setEnabled(False)
            self.bridge.broadcast_status("正在切换账号")
            self._log("正在切换账号，等待旧浏览器关闭")
            self.worker.stop()
        else:
            self._start_connection()

    def _manage_accounts(self):
        platform = self.platform.currentData()
        dialog = QDialog(self)
        dialog.setWindowTitle(f"账号管理 · {PLATFORMS[platform].name}")
        dialog.resize(500, 360)
        layout = QVBoxLayout(dialog)
        account_list = QListWidget()
        layout.addWidget(account_list, 1)
        actions = QHBoxLayout()
        add_button = QPushButton("添加账号")
        rename_button = QPushButton("改名")
        remove_button = QPushButton("删除账号")
        use_button = QPushButton("连接此账号")
        use_button.setObjectName("primary")
        close_button = QPushButton("关闭")
        for button in (add_button, rename_button, remove_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(use_button)
        actions.addWidget(close_button)
        layout.addLayout(actions)

        def current_id():
            item = account_list.currentItem()
            return item.data(Qt.ItemDataRole.UserRole) if item else None

        def update_actions():
            account_id = current_id()
            rename_button.setEnabled(bool(account_id))
            remove_button.setEnabled(bool(account_id and account_id != "default" and not (
                self.worker and self.worker.isRunning()
                and getattr(self.worker, "account_id", None) == account_id)))
            use_button.setEnabled(bool(account_id))

        def refresh(preferred_id=None):
            account_list.clear()
            for row in accounts_for(self.settings, platform):
                label = row["name"]
                if self.worker and self.worker.isRunning() and getattr(self.worker, "account_id", None) == row["id"]:
                    label += "  · 当前连接"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, row["id"])
                account_list.addItem(item)
                if row["id"] == (preferred_id or self.account.currentData()):
                    account_list.setCurrentItem(item)
            update_actions()

        def use_selected():
            account_id = current_id()
            if not account_id:
                return
            self._refresh_accounts(account_id)
            if self._save():
                dialog.accept()
                QTimer.singleShot(0, self._activate_selected_account)

        def add():
            name, accepted = QInputDialog.getText(dialog, "添加账号", "账号备注:")
            if not accepted:
                return
            previous_id = selected_account(self.settings, platform)
            try:
                account_id = add_account(self.settings, platform, name)
            except ValueError as exc:
                QMessageBox.warning(dialog, "添加账号", str(exc))
                return
            self._refresh_accounts(account_id)
            if self._save():
                dialog.accept()
                QTimer.singleShot(0, self._activate_selected_account)
            else:
                accounts_for(self.settings, platform)[:] = [
                    row for row in accounts_for(self.settings, platform) if row["id"] != account_id
                ]
                self._refresh_accounts(previous_id)
                refresh()

        def rename():
            account_id = current_id()
            if not account_id:
                return
            old_name = next(row["name"] for row in accounts_for(self.settings, platform) if row["id"] == account_id)
            name, accepted = QInputDialog.getText(dialog, "修改备注", "账号备注:", text=old_name)
            if not accepted:
                return
            try:
                rename_account(self.settings, platform, account_id, name)
            except ValueError as exc:
                QMessageBox.warning(dialog, "修改备注", str(exc))
                return
            if not self._save(expected_account=(platform, account_id, name.strip())):
                rename_account(self.settings, platform, account_id, old_name)
            self._refresh_accounts()
            refresh(account_id)

        def remove():
            account_id = current_id()
            if not account_id or not remove_button.isEnabled():
                return
            answer = QMessageBox.question(
                dialog, "删除账号", "删除该账号及其本机登录资料？此操作无法撤销。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            candidate = deepcopy(self.settings)
            try:
                remove_account(candidate, platform, account_id, delete_profile=False)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(dialog, "删除账号", str(exc))
                return
            previous = self.settings
            self.settings = candidate
            self._refresh_accounts()
            if not self._save():
                self.settings = previous
                self._refresh_accounts()
                refresh(account_id)
                return
            try:
                delete_account_profile(platform, account_id)
            except OSError as exc:
                QMessageBox.warning(dialog, "清理登录资料失败", f"账号已从列表移除，但本机登录资料未能清理。\n{exc}")
            refresh()

        account_list.itemSelectionChanged.connect(update_actions)
        account_list.itemDoubleClicked.connect(lambda _item: use_selected())
        add_button.clicked.connect(add)
        rename_button.clicked.connect(rename)
        remove_button.clicked.connect(remove)
        use_button.clicked.connect(use_selected)
        close_button.clicked.connect(dialog.accept)
        refresh()
        dialog.exec()

    @staticmethod
    def _add_row(table, values):
        row = table.rowCount()
        table.insertRow(row)
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(str(value)))

    def _add_product_row(self, values):
        row = self.products.rowCount()
        self.products.insertRow(row)
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.products.setItem(row, column, item)

    def _add_product(self):
        numbers = []
        for row in range(self.products.rowCount()):
            item = self.products.item(row, 0)
            try:
                number = int(item.text().strip()) if item else 0
            except ValueError:
                continue
            if number > 0:
                numbers.append(number)
        self._add_product_row([str(max(numbers, default=0) + 1), "1", "60"])
        self.products.setCurrentCell(self.products.rowCount() - 1, 0)
        self._update_product_actions()

    def _edit_product_cell(self, row, column):
        item = self.products.item(row, column)
        if item:
            self.products.editItem(item)

    def _delete_product(self):
        if self.products.rowCount() <= 1:
            return
        self._delete_row(self.products)
        self._update_product_actions()

    def _update_product_actions(self):
        self.delete_product_button.setEnabled(self.products.rowCount() > 1 and self.products.currentRow() >= 0)

    @staticmethod
    def _delete_row(table):
        row = table.currentRow()
        if row >= 0:
            table.removeRow(row)

    @staticmethod
    def _rows(table):
        return [[(table.item(row, column).text() if table.item(row, column) else "").strip()
                 for column in range(table.columnCount())] for row in range(table.rowCount())]

    def _save(self, *, expected_account=None):
        platform = self.platform.currentData()
        self.settings.update({"platform": platform, "phrases": self._rows(self.phrases), "products": self._rows(self.products)})
        self.settings.setdefault("selected_accounts", {})[platform] = self.account.currentData()
        try:
            save_settings(self.settings)
            if expected_account is not None:
                platform_key, account_id, expected_name = expected_account
                saved_name = next((row["name"] for row in accounts_for(load_settings(), platform_key)
                                   if row["id"] == account_id), None)
                if saved_name != expected_name:
                    raise OSError("账号备注未能从配置文件中恢复")
        except (OSError, TypeError, ValueError) as exc:
            self._log(f"设置保存失败: {exc}")
            QMessageBox.warning(self, "保存失败", f"账号和设置未能保存，请检查磁盘或目录权限。\n{exc}")
            return False
        if expected_account is not None:
            self._log(f"账号备注已保存到本机（{PLATFORMS[expected_account[0]].name}）")
        else:
            self._log("设置已保存")
        return True

    def _log(self, text):
        self.logs.append(f"[{datetime.now():%H:%M:%S}] {text}")

    def _toggle_connection(self):
        if self.worker and self.worker.isRunning():
            self._pending_account_id = None
            self.connected = False
            self.phrase_enabled.setChecked(False)
            self.product_enabled.setChecked(False)
            self.connect_button.setText("正在断开…")
            self.worker.stop()
            self.connect_button.setEnabled(False)
            return
        self._start_connection()

    def _start_connection(self):
        if not self._save():
            return
        platform = self.platform.currentData()
        account_id = self.account.currentData()
        profile = account_profile_path(platform, account_id)
        self._clear_barrage()
        self.platform.setEnabled(False)
        self.connect_button.setText("断开连接")
        self.connect_button.setEnabled(True)
        self.account.setEnabled(True)
        self.worker = BrowserWorker(
            platform, data_dir() / "profiles", self,
            account_id=account_id, profile_path=profile,
        )
        self.bridge.platform = platform
        self.bridge.session_id = self.worker.session_id
        self.bridge.account_id = account_id
        self.bridge.ready = False
        self.worker.state_changed.connect(self._worker_state)
        self.worker.event_received.connect(self._event)
        self.worker.action_started.connect(self._action_started)
        self.worker.action_result.connect(self._action_result)
        self.worker.capture_notice.connect(self._log)
        self.worker.reply_result.connect(self._reply_result)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()
        self._log("正在启动浏览器")
        self.bridge.broadcast_status("正在启动浏览器", capture_state="starting")

    def _worker_state(self, text):
        self.connected = "已就绪" in text or "监听中" in text
        self.bridge.ready = self.connected
        if "已关闭" in text or text == "已停止":
            self.connect_button.setText("正在重置…")
            self.connect_button.setEnabled(False)
        self.state.setText(text if len(text) <= 16 else text[:15] + "…")
        self.state.setToolTip(text)
        self.state.setProperty("connected", self.connected)
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        self._log(text)
        switching = self._pending_platform or self._pending_account_id
        stopped = "已关闭" in text or text == "已停止"
        if switching:
            capture_state = "switching"
        elif stopped:
            capture_state = "stopped"
        else:
            capture_state = "running" if self.connected else "starting"
        self.bridge.broadcast_status(text, capture_state=capture_state)

    def _worker_finished(self):
        self.connected = False
        self.bridge.ready = False
        self.bridge.session_id = ""
        self.bridge.account_id = ""
        self._worker_busy = False
        self.phrase_enabled.setChecked(False)
        self.product_enabled.setChecked(False)
        self.connect_button.setText("连接中控台")
        self.connect_button.setEnabled(True)
        self.platform.setEnabled(True)
        self.account.setEnabled(True)
        self.state.setText("未连接")
        self.state.setProperty("connected", False)
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        switching = self._pending_platform or self._pending_account_id
        self.bridge.broadcast_status("未连接平台", capture_state="switching" if switching else "stopped")
        if self._closing:
            self.bridge.stop()
            QApplication.quit()
        elif self._pending_platform:
            platform = self._pending_platform
            self._pending_platform = None
            self.platform.setCurrentIndex(self.platform.findData(platform))
            QTimer.singleShot(0, self._start_connection)
        elif self._pending_account_id:
            account_id = self._pending_account_id
            self._pending_account_id = None
            if self.account.currentData() == account_id:
                QTimer.singleShot(0, self._start_connection)

    def _event(self, event):
        if not isinstance(event, dict):
            return
        if event.get("type") not in self._selected_capture_types():
            return
        if not self._event_count and not self._pending_events:
            self._log("已收到首条弹幕")
        self._pending_events.append(event)
        voice_event = to_voice_event(event)
        if voice_event:
            self.bridge.broadcast(voice_event)

    def _action_result(self, action, success, detail):
        if action in ("send", "popup"):
            self._worker_busy = False
        names = {"send": "发送文字", "popup": "商品讲解", "capture": "弹幕采集", "connect": "连接中控台"}
        self._log(f"{'完成' if success else '失败'} · {names.get(action, action)} · {detail}")

    def _action_started(self, action):
        self._worker_busy = True
        if action == "send":
            self.voice_reply_policy.touch_activity()
        self._log("正在发送文字" if action == "send" else "正在弹商品讲解" if action == "popup" else f"正在执行 {action}")

    def _reply_result(self, msg_id, success):
        self._mark_reply(msg_id, "已发送" if success else "发送失败")

    def _send_manual(self):
        value = self.message.text().strip()
        if not value:
            return
        if not self.worker or not self.connected:
            self._log("请先连接中控台，再发送文字")
            return
        payload = {"text": value, "msg_id": self._selected_msg_id} if self._selected_msg_id else value
        if self.worker.command("send", payload):
            self._mark_reply(self._selected_msg_id, "发送中")
            self.message.clear()
            self._selected_msg_id = ""
            self.reply_context.setText("公开发言")

    def _bridge_send(self, command):
        if (self.worker and self.connected
                and command.get("platform") == self.platform.currentData()
                and command.get("session_id") == self.worker.session_id):
            msg_id = str(command.get("msg_id") or "")
            if command.get("type") == "send_public_text":
                reason = self.voice_reply_policy.check(
                    command, selected_voice_reply_types(self.settings), self.account.currentData())
                commands = getattr(self.worker, "commands", None)
                if (command.get("event_type") == "live_order"
                        and (self._worker_busy or (commands is not None and not commands.empty()))):
                    reason = "中控操作繁忙，订单感谢已跳过，不排队补发"
                if reason:
                    self._log(f"文字同步已跳过：{reason}")
                    return
                if self.worker.command("send", command["text"]):
                    self.voice_reply_policy.record(command, self.account.currentData())
                    self._log("语音引擎的公开文字已提交发送")
            elif self.worker.command("send", {"text": command["text"], "msg_id": msg_id}):
                self._mark_reply(msg_id, "发送中")
        else:
            self._log("已忽略过期或跨平台的文字回发")

    def _voice_reply_types_changed(self, _checked):
        candidate = deepcopy(self.settings)
        candidate["voice_reply_types"] = [kind for kind, checkbox in self.voice_reply_checks.items()
                                          if checkbox.isChecked()]
        try:
            save_settings(candidate)
        except (OSError, TypeError, ValueError) as exc:
            for kind, checkbox in self.voice_reply_checks.items():
                blocked = checkbox.blockSignals(True)
                checkbox.setChecked(kind in selected_voice_reply_types(self.settings))
                checkbox.blockSignals(blocked)
            self._log(f"文字同步设置保存失败：{exc}")
            return
        self.settings = candidate
        self._log("文字同步类型已保存")

    def _toggle_phrases(self, enabled):
        if not enabled:
            self.phrase_schedule = None
            return
        try:
            items = [Phrase(text, int(interval)) for text, interval in self._rows(self.phrases) if text]
            if not items or any(item.interval < 1 for item in items):
                raise ValueError("请填写快捷语与大于 0 的间隔")
            if not self.connected:
                raise ValueError("请先连接中控台")
            self.phrase_schedule = SequenceScheduler(items)
            self._save()
        except ValueError as exc:
            QMessageBox.warning(self, "快捷语", str(exc))
            self.phrase_enabled.setChecked(False)

    def _toggle_products(self, enabled):
        if not enabled:
            was_running = self.product_schedule is not None
            self.product_schedule = None
            self._set_product_state(False)
            if was_running:
                self._log("已停止自动讲解")
            return
        try:
            items = [Product(int(number), int(repeats), int(interval)) for number, repeats, interval in self._rows(self.products)]
            if not items or any(item.number < 1 or item.repeats < 1 or item.interval < 1 for item in items):
                raise ValueError("商品序号、重复次数和间隔都必须大于 0")
            if not self.connected:
                raise ValueError("请先连接中控台")
            if not self._save():
                self.product_enabled.setChecked(False)
                return
            self.product_schedule = SequenceScheduler(items)
            self._set_product_state(True)
            self._log("已启动自动讲解")
        except ValueError as exc:
            QMessageBox.warning(self, "商品讲解", str(exc))
            self.product_enabled.setChecked(False)

    def _set_product_state(self, running):
        self.product_state.setText("运行中" if running else "已停止")
        self.product_state.setProperty("running", running)
        self.product_state.style().unpolish(self.product_state)
        self.product_state.style().polish(self.product_state)
        self.product_enabled.setToolTip("停止自动讲解" if running else "启动自动讲解；需先连接中控台")

    def _tick(self):
        if not self.connected or not self.worker:
            return
        if self._worker_busy or not self.worker.commands.empty():
            return
        if self.phrase_schedule:
            item = self.phrase_schedule.due()
            if item:
                self.worker.command("send", item.text)
                return
        if self.product_schedule:
            item = self.product_schedule.due()
            if item:
                self.worker.command("popup", item.number)

    def closeEvent(self, event):
        self._save()
        self.bridge.ready = False
        self.bridge.broadcast_status("中控助手已关闭", capture_state="stopped")
        self.timer.stop()
        self.barrage_timer.stop()
        if self.worker and self.worker.isRunning():
            event.ignore()
            self._closing = True
            self.hide()
            self.worker.stop()
        else:
            self.bridge.stop()
            event.accept()
            QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(_brand_icon_path())))
    app.setQuitOnLastWindowClosed(False)
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(root / "assistant.lock"))
    if not lock.tryLock(100):
        QMessageBox.warning(None, "中控助手已在运行", "请使用已经打开的中控助手窗口。")
        return
    try:
        window = Console()
    except OSError as exc:
        lock.unlock()
        QMessageBox.warning(None, "中控助手已在运行", f"本机通信端口被占用，请使用已打开的助手。\n{exc}")
        return
    window.show()
    try:
        sys.exit(app.exec())
    finally:
        lock.unlock()
