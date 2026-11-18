"""WebSocket 的界面部分：请求侧的消息编辑器 + 响应侧的帧日志。

和 HTTP 面板保持同一套视觉语言：纯色卡片、白灰层次、反色主按钮。
日志列表按视口绘制，几万帧也不会把界面拖慢。
"""
from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import i18n
from .code_editor import CodeView, human_size
from .theme import C, font, mono, theme
from .widgets import (
    Button,
    Card,
    Divider,
    HBox,
    Label,
    SegmentedTabs,
    SmoothScrollArea,
    Switch,
    icon_button,
)

# 消息类型：文本 / JSON / 二进制（base64 输入）
KINDS = [("text", "文本"), ("json", "JSON"), ("binary", "二进制")]


def default_ws() -> Dict[str, Any]:
    return {"messages": [], "subprotocol": "", "ping": 0,
            "auto_reconnect": True, "clear_after_send": False}


def ensure_ws(req: Dict[str, Any]) -> Dict[str, Any]:
    ws = req.get("ws")
    if not isinstance(ws, dict):
        ws = default_ws()
        req["ws"] = ws
    for key, value in default_ws().items():
        ws.setdefault(key, value)
    if not isinstance(ws.get("messages"), list):
        ws["messages"] = []
    return ws


# ---------------------------------------------------------------- 已保存消息


class MsgChip(QWidget):
    """一条常用消息的小胶囊：点名字填入编辑器，点右侧 ✕ 删除。

    横向排一行、放不下就横向滚动 —— 竖排列表在请求区被压扁时会把整页顶出滚动条。
    """

    load = pyqtSignal(dict)
    delete = pyqtSignal(str)

    H = 24

    def __init__(self, item: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.item = item
        self._hover = False
        self._hover_x = False
        self.setFixedHeight(self.H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        name = str(item.get("name") or i18n.tr("未命名"))
        fm = QFontMetricsF(font(11))
        self._w = int(min(190, fm.horizontalAdvance(name) + 34))
        self._name = name
        self.setFixedWidth(self._w)
        self.setToolTip(i18n.trf("{name}\n点击填入编辑器，点右侧 ✕ 删除", name=name))

    def _close_rect(self) -> QRectF:
        return QRectF(self._w - 20, 4, 16, self.H - 8)

    def mouseMoveEvent(self, e):  # noqa: N802
        inside = self._close_rect().contains(e.position())
        if inside != self._hover_x:
            self._hover_x = inside
            self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover_x = False
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._close_rect().contains(e.position()):
            self.delete.emit(self.item.get("id", ""))
        else:
            self.load.emit(self.item)

    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(C(t.border), 1))
        p.setBrush(C(t.selected if self._hover_x else t.panel_alt))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.setFont(font(11, QFont.Weight.Medium))
        p.setPen(C(t.text_dim))
        p.drawText(QRectF(8, 0, self._w - 28, self.H),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   QFontMetricsF(p.font()).elidedText(self._name, Qt.TextElideMode.ElideRight,
                                                     self._w - 28))
        p.setFont(font(10))
        p.setPen(C(t.text if self._hover_x else t.text_faint))
        p.drawText(self._close_rect(), int(Qt.AlignmentFlag.AlignCenter), "✕")
        p.end()

    def enterEvent(self, e):  # noqa: N802
        self._hover = True
        self.update()


# ---------------------------------------------------------------- 请求侧


class WsComposer(QWidget):
    """「消息」页：写消息、发消息、管理常用消息，外加连接级选项。"""

    sendRequested = pyqtSignal(str, bool)      # 内容, 是否二进制
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ws: Dict[str, Any] = default_ws()
        self._connected = False
        self._chips: List[MsgChip] = []

        # --- 连接选项（子协议 / 心跳 / 重连）
        self.proto = QLineEdit()
        self.proto.setObjectName("Field")
        self.proto.setFixedHeight(26)
        self.proto.setFixedWidth(132)
        i18n.placeholder(self.proto, "可留空")
        self.proto.textChanged.connect(self._on_option)
        self.ping = QLineEdit()
        self.ping.setObjectName("Field")
        self.ping.setFixedHeight(26)
        self.ping.setFixedWidth(52)
        i18n.placeholder(self.ping, "0")
        self.ping.setToolTip(i18n.tr("心跳间隔（秒），0 表示不发"))
        self.ping.textChanged.connect(self._on_option)
        self.reconnect_sw = Switch(True)
        self.reconnect_sw.toggled.connect(lambda _v: self._on_option())
        self.clear_sw = Switch(False)
        self.clear_sw.toggled.connect(lambda _v: self._on_option())
        opts = Card(radius=9)
        ol = QHBoxLayout(opts)
        ol.setContentsMargins(12, 6, 12, 6)
        ol.setSpacing(10)
        ol.addWidget(Label("子协议", 10.6, theme().text_faint))
        ol.addWidget(self.proto)
        ol.addSpacing(4)
        ol.addWidget(Label("心跳", 10.6, theme().text_faint))
        ol.addWidget(self.ping)
        ol.addWidget(Label("秒", 10.4, theme().text_faint))
        ol.addStretch(1)
        ol.addWidget(Label("自动重连", 10.9, theme().text_dim))
        ol.addWidget(self.reconnect_sw)
        ol.addSpacing(6)
        ol.addWidget(Label("发送后清空", 10.9, theme().text_dim))
        ol.addWidget(self.clear_sw)

        # --- 消息编辑
        self.kind = SegmentedTabs([(k, label) for k, label in KINDS],
                                  style="pill", height=26, font_size=11.4, pad_h=11)
        self.kind.changed.connect(self._on_kind)
        self.fmt_btn = Button("格式化", "code", kind="ghost", height=24, padding=8,
                              font_size=11, icon_size=11)
        self.fmt_btn.setToolTip(i18n.tr("把 JSON 排版成易读的缩进格式"))
        self.fmt_btn.clicked.connect(self._format)
        self.save_btn = Button("保存这条", "plus", kind="ghost", height=24, padding=8,
                               font_size=11, icon_size=11)
        self.save_btn.setToolTip(i18n.tr("存进常用消息，下次一点就填"))
        self.save_btn.clicked.connect(self._save_current)
        self.send_btn = Button("发送", "send", kind="primary", height=26, padding=12,
                               font_size=11.6, icon_size=12)
        self.send_btn.clicked.connect(self._send)
        tools = HBox(self.kind, 0, self.fmt_btn, 1, self.save_btn, self.send_btn,
                     spacing=8, margins=(0, 0, 0, 0))

        self.editor = CodeView(read_only=False, highlight=True, show_gutter=False)
        self.editor.setMinimumHeight(96)
        self.editor.setPlaceholderText(i18n.tr(
            "输入要发送的内容。连接成功后 ⌘↵ 直接发送；JSON 会自动识别高亮。"))

        # --- 常用消息：横向一条胶囊，放不下就横向滚
        self.saved_note = Label("常用消息", 10.4, theme().text_faint)
        self.saved_host = QWidget()
        self.saved_lay = QHBoxLayout(self.saved_host)
        self.saved_lay.setContentsMargins(0, 0, 4, 0)
        self.saved_lay.setSpacing(6)
        self.saved_scroll = SmoothScrollArea()
        self.saved_scroll.setWidget(self.saved_host)
        self.saved_scroll.setFixedHeight(34)
        self.saved_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.saved_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.saved_scroll.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 10)
        lay.setSpacing(8)
        lay.addWidget(opts)
        lay.addWidget(tools)
        lay.addWidget(self.editor, 1)
        lay.addWidget(self.saved_note)
        lay.addWidget(self.saved_scroll)
        self._refresh_saved()

    # -------------------------------------------------- 数据
    def load(self, req: Dict[str, Any]) -> None:
        self._ws = ensure_ws(req)
        for w, value in ((self.proto, self._ws.get("subprotocol", "")),
                         (self.ping, str(self._ws.get("ping", 0) or 0))):
            w.blockSignals(True)
            w.setText(str(value or ""))
            w.blockSignals(False)
        for sw, key, default in ((self.reconnect_sw, "auto_reconnect", True),
                                 (self.clear_sw, "clear_after_send", False)):
            sw.blockSignals(True)
            sw.setChecked(bool(self._ws.get(key, default)))
            sw.blockSignals(False)
        self.editor.setPlainText("")
        self._refresh_saved()

    def dump(self, req: Dict[str, Any]) -> None:
        ws = ensure_ws(req)
        ws["subprotocol"] = self.proto.text().strip()
        try:
            ws["ping"] = max(0, int(self.ping.text().strip() or 0))
        except ValueError:
            ws["ping"] = 0
        ws["auto_reconnect"] = self.reconnect_sw.isChecked()
        ws["clear_after_send"] = self.clear_sw.isChecked()

    def payload(self) -> str:
        return self.editor.toPlainText()

    def kind_key(self) -> str:
        return self.kind.current() or "text"

    def set_connected(self, on: bool) -> None:
        self._connected = on
        self.send_btn.setEnabled(on)
        self.send_btn.setToolTip("" if on else i18n.tr("先连接再发送消息"))
        self.editor.setPlaceholderText(
            i18n.tr("输入要发送的内容。连接成功后 ⌘↵ 直接发送。") if on
            else i18n.tr("还没连接：点左上角「连接」建立 WebSocket 连接。"))

    def _on_option(self) -> None:
        self.changed.emit()

    def _on_kind(self, key: str) -> None:
        self.editor.set_language("json" if key == "json" else None)
        self.fmt_btn.setVisible(key == "json")

    def _format(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            return
        try:
            data = json.loads(text)
        except Exception:  # noqa: BLE001
            return
        self.editor.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))

    # -------------------------------------------------- 发送 / 常用消息
    def _send(self) -> None:
        text = self.payload()
        if not text.strip():
            return
        binary = self.kind_key() == "binary"
        self.sendRequested.emit(text, binary)
        if self.clear_sw.isChecked():
            self.editor.setPlainText("")

    def _save_current(self) -> None:
        text = self.payload().strip()
        if not text:
            return
        name = self._suggest_name(text)
        from .store import uid

        messages = self._ws.setdefault("messages", [])
        if any(m.get("payload") == text for m in messages):
            return
        messages.append({"id": uid(), "name": name, "payload": text,
                         "binary": self.kind_key() == "binary"})
        self._refresh_saved()
        self.changed.emit()

    @staticmethod
    def _suggest_name(text: str) -> str:
        """给消息起个短名字：优先用 JSON 里的 op / type / event，否则取首行。"""
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for key in ("op", "type", "event", "action", "cmd", "method", "channel"):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()[:24]
        except Exception:  # noqa: BLE001
            pass
        first = text.splitlines()[0].strip()
        return (first[:24] or i18n.tr("消息"))

    def _delete(self, msg_id: str) -> None:
        self._ws["messages"] = [m for m in self._ws.get("messages", [])
                                if m.get("id") != msg_id]
        self._refresh_saved()
        self.changed.emit()

    def _load_msg(self, item: Dict[str, Any]) -> None:
        self.editor.setPlainText(str(item.get("payload") or ""))
        key = "binary" if item.get("binary") else "text"
        self.kind.set_current(key, emit=True)

    def _refresh_saved(self) -> None:
        for chip in self._chips:
            chip.setParent(None)
            chip.deleteLater()
        self._chips = []
        while self.saved_lay.count():
            item = self.saved_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        messages = [m for m in self._ws.get("messages", []) if isinstance(m, dict)]
        for msg in messages:
            chip = MsgChip(msg)
            chip.load.connect(self._load_msg)
            chip.delete.connect(self._delete)
            self.saved_lay.addWidget(chip)
            self._chips.append(chip)
        self.saved_lay.addStretch(1)
        n = len(messages)
        self.saved_note.setText(i18n.trf("常用消息 · {n}", n=n) if n
                                else i18n.tr("常用消息：把要反复发的内容存下来，点击即填入"))
        self.saved_scroll.setVisible(bool(n))


# ---------------------------------------------------------------- 响应侧：帧日志


KIND_LABEL = {"text": "TEXT", "json": "JSON", "binary": "BIN",
              "ping": "PING", "pong": "PONG", "open": "OPEN",
              "close": "CLOSE", "error": "ERR"}


class FrameList(QWidget):
    """按视口绘制的帧列表：几万帧也只画看得见的那几十行。"""

    picked = pyqtSignal(int)
    activated = pyqtSignal(int)      # 双击：把这条内容填回编辑器（重放）

    ROW_H = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames: List[Any] = []
        self.index = -1
        self._hover = -1
        self._tops: List[float] = []
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_frames(self, frames: List[Any]) -> None:
        self.frames = frames
        self._tops = [4 + i * self.ROW_H for i in range(len(frames))]
        self.setFixedHeight(max(1, 8 + len(frames) * self.ROW_H))
        self.update()

    def append(self, frame) -> None:
        self.frames.append(frame)
        self._tops.append(4 + (len(self.frames) - 1) * self.ROW_H)
        self.setFixedHeight(max(1, 8 + len(self.frames) * self.ROW_H))
        self.update()

    def clear(self) -> None:
        self.set_frames([])
        self.index = -1

    def _row_at(self, y: float) -> int:
        i = int((y - 4) // self.ROW_H)
        return i if 0 <= i < len(self.frames) else -1

    def visible_range(self) -> tuple:
        from .widgets import _scroll_host

        view = _scroll_host(self)
        offset = 0
        height = self.height()
        if view is not None:
            try:
                offset = view.verticalScrollBar().value()
                height = view.viewport().height()
            except RuntimeError:
                pass
        start = max(0, int((offset - 4) // self.ROW_H) - 1)
        end = min(len(self.frames), int((offset + height) // self.ROW_H) + 2)
        return start, end

    def mouseMoveEvent(self, e):  # noqa: N802
        idx = self._row_at(e.position().y())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        idx = self._row_at(e.position().y())
        if idx >= 0:
            self.index = idx
            self.picked.emit(idx)
            self.update()

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        idx = self._row_at(e.position().y())
        if idx >= 0:
            self.index = idx
            self.activated.emit(idx)
            self.update()

    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        if not self.frames:
            p.setFont(font(11.5))
            p.setPen(C(t.text_faint))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter),
                       i18n.tr("还没有消息。连接后收发的内容会实时出现在这里。"))
            p.end()
            return
        start, end = self.visible_range()
        for i in range(start, end):
            frame = self.frames[i]
            top = 4 + i * self.ROW_H
            r = QRectF(4, top, self.width() - 8, self.ROW_H - 2)
            if i == self.index or i == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected if i == self.index else t.hover))
                p.drawRoundedRect(r, 6, 6)
            # 时间
            p.setFont(mono(9.4))
            p.setPen(C(t.text_faint))
            stamp = datetime.datetime.fromtimestamp(frame.at).strftime("%H:%M:%S")
            p.drawText(QRectF(r.left() + 8, r.top(), 62, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), stamp)
            # 方向
            arrow = {"in": "↓", "out": "↑"}.get(frame.dir, "·")
            col = {"in": t.success, "out": t.info}.get(frame.dir, t.text_faint)
            if frame.kind == "error":
                col = t.danger
            p.setFont(font(11.6, QFont.Weight.DemiBold))
            p.setPen(C(col))
            p.drawText(QRectF(r.left() + 74, r.top(), 14, r.height()),
                       int(Qt.AlignmentFlag.AlignCenter), arrow)
            # 类型标签
            tag = KIND_LABEL.get(frame.kind, frame.kind.upper())
            p.setFont(mono(9.0, QFont.Weight.DemiBold))
            p.setPen(C(col if frame.dir != "sys" else t.text_dim))
            p.drawText(QRectF(r.left() + 92, r.top(), 46, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), tag)
            # 大小
            p.setFont(mono(9.4))
            p.setPen(C(t.text_faint))
            p.drawText(QRectF(r.left() + 138, r.top(), 60, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       human_size(frame.size) if frame.kind not in ("open", "close") else "—")
            # 内容预览
            p.setFont(mono(10.2))
            p.setPen(C(t.text_dim) if frame.dir != "sys" else C(t.text_faint))
            left = r.left() + 202
            p.drawText(QRectF(left, r.top(), max(20.0, r.right() - left - 8), r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       QFontMetricsF(p.font()).elidedText(
                           frame.preview(), Qt.TextElideMode.ElideRight,
                           int(max(20.0, r.right() - left - 8))))
        p.end()


class WsLogView(QWidget):
    """响应区的 WebSocket 页面：连接状态 + 统计 + 帧列表 + 详情。"""

    replay = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frames: List[Any] = []
        self._filter = "all"
        self._query = ""
        self._auto_scroll = True

        self.search = QLineEdit()
        self.search.setObjectName("Field")
        self.search.setFixedHeight(26)
        self.search.setFixedWidth(170)
        i18n.placeholder(self.search, "过滤消息内容")
        self.search.textChanged.connect(self._on_search)
        self.filter = SegmentedTabs([("all", "全部"), ("in", "接收"), ("out", "发出")],
                                    style="pill", height=24, font_size=10.8, pad_h=9)
        self.filter.changed.connect(self._on_filter)
        self.copy_btn = icon_button("copy", "复制这条消息", 24, 13)
        self.copy_btn.clicked.connect(self._copy_current)
        self.save_btn = icon_button("download", "导出日志…", 24, 13)
        self.save_btn.clicked.connect(self._export)
        self.clear_btn = icon_button("trash", "清空日志", 24, 13)
        self.clear_btn.clicked.connect(self.clear)
        self.auto_sw = Switch(True)
        self.auto_sw.setToolTip(i18n.tr("自动滚动到最新一条"))
        self.auto_sw.toggled.connect(self._on_auto)

        self.stats = Label("", 10.5, theme().text_faint, mono_font=True)
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 6, 12, 6)
        bl.setSpacing(8)
        bl.addWidget(self.filter, 0)
        bl.addSpacing(4)
        bl.addWidget(self.stats, 0)
        bl.addStretch(1)
        bl.addWidget(self.search, 0)
        bl.addWidget(self.copy_btn, 0)
        bl.addWidget(self.save_btn, 0)
        bl.addWidget(self.clear_btn, 0)

        self.list = FrameList()
        self.list.setToolTip(i18n.tr("单击看完整内容，双击把收到的消息填回编辑器"))
        self.list.picked.connect(self._show_detail)
        self.list.activated.connect(self._replay)
        self.scroll = SmoothScrollArea()
        self.scroll.setWidget(self.list)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._stick)

        self.detail = CodeView(read_only=True, highlight=True, show_gutter=False)
        self.detail.setFixedHeight(112)
        self.detail.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(bar)
        lay.addWidget(Divider())
        lay.addWidget(self.scroll, 1)
        lay.addWidget(self.detail)

    # -------------------------------------------------- 数据
    def set_frames(self, frames: List[Any]) -> None:
        self._frames = list(frames or [])
        self._rebuild()

    def add_frame(self, frame) -> None:
        self._frames.append(frame)
        if self._match(frame):
            self.list.append(frame)
            self._update_stats()

    def clear(self) -> None:
        self._frames = []
        self.list.clear()
        self.detail.hide()
        self._update_stats()

    def frames(self) -> List[Any]:
        return list(self._frames)

    def set_state(self, state: str) -> None:
        self._update_stats()

    def _match(self, frame) -> bool:
        if self._filter in ("in", "out") and frame.dir != self._filter:
            return False
        if self._query:
            return self._query in frame.preview(4000).lower()
        return True

    def _rebuild(self) -> None:
        self.list.set_frames([f for f in self._frames if self._match(f)])
        self._update_stats()
        if self._auto_scroll:
            self._stick()

    def _update_stats(self) -> None:
        n_in = sum(1 for f in self._frames if f.dir == "in")
        n_out = sum(1 for f in self._frames if f.dir == "out")
        size_in = sum(f.size for f in self._frames if f.dir == "in")
        self.stats.setText(i18n.trf("接收 {i} · 发送 {o} · {size}",
                                    i=n_in, o=n_out, size=human_size(size_in)))

    def _on_filter(self, key: str) -> None:
        self._filter = key
        self._rebuild()

    def _on_search(self, text: str) -> None:
        self._query = (text or "").strip().lower()
        self._rebuild()

    def _on_auto(self, on: bool) -> None:
        self._auto_scroll = bool(on)
        if on:
            self._stick()

    def _stick(self, *_a) -> None:
        if not self._auto_scroll:
            return
        bar = self.scroll.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    def _show_detail(self, index: int) -> None:
        items = self.list.frames
        if not (0 <= index < len(items)):
            return
        frame = items[index]
        self.detail.setPlainText(frame.preview(20000))
        self.detail.set_language("json" if frame.kind == "json" else None)
        self.detail.show()

    def _replay(self, index: int) -> None:
        items = self.list.frames
        if not (0 <= index < len(items)):
            return
        frame = items[index]
        if frame.kind in ("text", "json"):
            self.replay.emit(frame.preview(200000))

    def _copy_current(self) -> None:
        from PyQt6.QtWidgets import QApplication

        items = self.list.frames
        idx = self.list.index
        if 0 <= idx < len(items):
            QApplication.clipboard().setText(items[idx].preview(200000))

    def _export(self) -> None:
        if not self._frames:
            return
        path, _ = QFileDialog.getSaveFileName(self.window(), i18n.tr("导出消息日志"),
                                              "websocket-log.json",
                                              i18n.tr("JSON (*.json);;文本 (*.log)"))
        if not path:
            return
        rows = [{"time": datetime.datetime.fromtimestamp(f.at).isoformat(timespec="milliseconds"),
                 "direction": ("recv" if f.dir == "in" else ("send" if f.dir == "out" else "info")),
                 "type": f.kind, "size": f.size, "data": f.preview(200000)}
                for f in self._frames]
        try:
            with open(path, "w", encoding="utf-8") as fh:
                if path.lower().endswith(".log"):
                    fh.write("\n".join(f"{r['time']} {r['direction']} {r['type']} "
                                       f"{r['size']}B {r['data']}" for r in rows))
                else:
                    json.dump(rows, fh, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            return
