"""WebSocket 的界面部分：请求侧的消息编辑器 + 响应侧的帧日志。

和 HTTP 面板保持同一套视觉语言：纯色卡片、白灰层次、反色主按钮。
日志列表按视口绘制，几万帧也不会把界面拖慢。
"""
from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List

from bisect import bisect_left, bisect_right

from PyQt6.QtCore import QPoint, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import i18n
from .code_editor import CodeView, human_size
from .theme import C, font, mono, px, theme
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
    headersToggled = pyqtSignal()              # 展开 / 收起握手请求头

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ws: Dict[str, Any] = default_ws()
        self._connected = False
        self._loading = False
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
        od = Divider(vertical=True)
        od.setFixedHeight(14)
        ol.addWidget(od)
        self.headers_btn = Button("握手头", "list", kind="ghost", height=24,
                                  padding=8, font_size=10.8, icon_size=11)
        self.headers_btn.setToolTip(i18n.tr("连接时一起发送的请求头，例如 Authorization"))
        self.headers_btn.clicked.connect(self.headersToggled.emit)
        ol.addWidget(self.headers_btn)

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
        self.editor.setMinimumHeight(68)
        self.editor.setPlaceholderText(i18n.tr(
            "输入要发送的内容。连接成功后 ⌘↵ 直接发送；JSON 会自动识别高亮。"))
        # 输入中的草稿写回请求：切走标签再切回来，内容还在。
        self.editor.textChanged.connect(self._on_draft_changed)

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
        self._loading = True
        try:
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
            kind = str(self._ws.get("kind") or "text")
            self.kind.blockSignals(True)
            self.kind.set_current(kind, emit=False)
            self.kind.blockSignals(False)
            self._on_kind(kind)
            self.editor.blockSignals(True)
            self.editor.setPlainText(str(self._ws.get("draft") or ""))
            self.editor.blockSignals(False)
            self._refresh_saved()
        finally:
            self._loading = False

    def dump(self, req: Dict[str, Any]) -> None:
        ws = ensure_ws(req)
        ws["subprotocol"] = self.proto.text().strip()
        try:
            ws["ping"] = max(0, int(self.ping.text().strip() or 0))
        except ValueError:
            ws["ping"] = 0
        ws["auto_reconnect"] = self.reconnect_sw.isChecked()
        ws["clear_after_send"] = self.clear_sw.isChecked()
        ws["kind"] = self.kind_key()
        ws["draft"] = self.editor.toPlainText()

    def _on_draft_changed(self) -> None:
        if self._loading:
            return
        # 只改内存里的请求字典，落盘由主窗口已有的 debounce 定时器负责，
        # 每敲一个字不再多起一个定时器。
        self._ws["draft"] = self.editor.toPlainText()
        self.changed.emit()

    def set_headers_count(self, n: int) -> None:
        self.headers_btn.setText(i18n.trf("握手头 · {n}", n=n) if n
                                 else i18n.tr("握手头"))

    def set_messages_count(self, n: int) -> None:
        self._messages_count = n

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


class WsHeadersPopup(QWidget):
    """握手请求头的编辑弹层。

    为什么不常驻在请求区：WS 页要留给消息编辑器，握手头属于低频配置，展开
    会把下面的输入挤没。做成贴按钮弹出的浮层，改完点空白处就收起。
    """

    changed = pyqtSignal(list)

    def __init__(self, parent, rows: List[Dict[str, Any]]):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        from .kv_editor import COMMON_HEADERS, KVEditor

        self.editor = KVEditor("Header", "值", suggestions=COMMON_HEADERS,
                               empty_hint="添加握手请求头，例如 Authorization")
        self.editor.set_rows(rows or [])
        self.editor.changed.connect(lambda: self.changed.emit(self.editor.rows()))

        card = Card(radius=12)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(6)
        cl.addWidget(Label("握手请求头", 11, theme().text, QFont.Weight.DemiBold))
        cl.addWidget(Label("连接建立时一起发送，例如 Authorization、Origin。", 10.4,
                           theme().text_faint))
        cl.addWidget(self.editor, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(card)
        self.resize(px(520), px(320))

    def popup_at(self, pos) -> None:
        """贴着按钮弹：优先右对齐按钮、向下展开，超出窗口就往上翻。"""
        host = self.parentWidget()
        pos = QPoint(pos)
        if host is not None:
            limit = host.window().mapToGlobal(QPoint(host.window().width(), 0)).x()
            if pos.x() + self.width() > limit - 8:
                pos.setX(max(8, limit - 8 - self.width()))
        self.move(pos)
        self.show()
        self.raise_()
        self.editor.setFocus()


# ---------------------------------------------------------------- 响应侧：帧日志


KIND_LABEL = {"text": "TEXT", "json": "JSON", "binary": "BIN",
              "ping": "PING", "pong": "PONG", "open": "OPEN",
              "close": "CLOSE", "error": "ERR"}


class FrameCard(QWidget):
    """一条消息展开后的详情卡：表头 + Raw / JSON 页签 + 内容。

    只给展开的那几条建控件，没展开的消息仍然只是画一行字，所以几百条日志
    也不会多出几百个 QTextDocument。
    """

    H = 156

    def __init__(self, frame, parent=None):
        super().__init__(parent)
        self.frame = frame
        self.setObjectName("FrameCard")
        self._raw = frame.preview(20000)
        preview = self._raw.splitlines()[0] if self._raw else ""
        arrow = {"in": "↓", "out": "↑"}.get(frame.dir, "·")
        arrow_l = Label(arrow, 12, theme().success if frame.dir == "in" else theme().info,
                        QFont.Weight.DemiBold)
        arrow_l.setFixedWidth(16)
        stamp = Label(datetime.datetime.fromtimestamp(frame.at).strftime("%H:%M:%S"),
                      10, theme().text_faint, mono_font=True)
        stamp.setFixedWidth(58)
        self.preview = Label("", 10.6, theme().text_dim, mono_font=True)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding,
                                   QSizePolicy.Policy.Fixed)
        copy = icon_button("copy", "复制这条消息", 20, 11)
        copy.clicked.connect(self._copy)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(8, 2, 6, 2)
        hl.setSpacing(6)
        hl.addWidget(arrow_l, 0)
        hl.addWidget(stamp, 0)
        hl.addWidget(self.preview, 1)
        hl.addWidget(copy, 0)

        if frame.kind == "json":
            tabs_items = [("pretty", "JSON"), ("raw", "Raw")]
        elif frame.kind == "binary":
            tabs_items = [("hex", "Hex"), ("raw", "Raw")]
        else:
            tabs_items = [("raw", "Raw")]
        self.tabs = SegmentedTabs(tabs_items, style="underline", height=22,
                                  font_size=10.5, pad_h=8, show_badges=False)
        self.body = CodeView(read_only=True, highlight=(frame.kind == "json"),
                             show_gutter=True)
        self.body.setFixedHeight(84)
        self.tabs.changed.connect(self._render)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 6)
        lay.setSpacing(2)
        lay.addWidget(head, 0)
        lay.addWidget(self.tabs, 0)
        lay.addWidget(self.body, 1)
        self._render(self.tabs.current())

    def paintEvent(self, e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(C(t.border), 1))
        p.setBrush(C(t.panel_alt))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        p.end()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        # 表头单行省略，绝不换行把卡片撑高（撑高会打乱懒绘制的行偏移）
        available = max(40, self.width() - 110)
        fm = QFontMetricsF(self.preview.font())
        QLabel.setText(self.preview, fm.elidedText(self._raw.splitlines()[0] if self._raw else "",
                                                   Qt.TextElideMode.ElideRight, int(available)))

    def _render(self, key: str) -> None:
        text = self._raw
        if key == "pretty":
            try:
                text = json.dumps(json.loads(self._raw), ensure_ascii=False, indent=2)
            except Exception:  # noqa: BLE001
                pass
        elif key == "hex":
            text = " ".join(f"{b:02X}" for b in self.frame.data[:2048])
        self.body.setPlainText(text)

    def _copy(self) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._raw)


class FrameList(QWidget):
    """帧列表：只画视口内的行；展开的详情卡是独立控件，可同时开多条。"""

    picked = pyqtSignal(int)
    activated = pyqtSignal(int)      # 双击：把这条内容填回编辑器（重放）

    ROW_H = 30
    CARD_H = FrameCard.H

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames: List[Any] = []
        self.index = -1
        self._hover = -1
        self._tops: List[float] = []
        # dict 保留点击顺序：最多同时展开 12 条，再点新的就收起最早那条，
        # 避免用户一路点下去把几千条消息都变成 QTextDocument。
        self._expanded: Dict[int, None] = {}
        self._cards: Dict[int, FrameCard] = {}
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # -------------------------------------------------- 布局
    def _relayout(self) -> None:
        top = 4.0
        self._tops = []
        for frame in self.frames:
            self._tops.append(top)
            top += self.ROW_H + (self.CARD_H if id(frame) in self._expanded else 0)
        self.setFixedHeight(max(1, int(top + 4)))
        self._sync_cards()

    def _sync_cards(self) -> None:
        if not self._expanded and not self._cards:
            return
        live = set()
        for i, frame in enumerate(self.frames):
            key = id(frame)
            if key not in self._expanded:
                continue
            live.add(key)
            card = self._cards.get(key)
            if card is None:
                card = FrameCard(frame, self)
                self._cards[key] = card
            card.setGeometry(QRect(4, int(self._tops[i] + self.ROW_H),
                                   max(80, self.width() - 8), self.CARD_H))
            card.show()
        for key, card in list(self._cards.items()):
            if key not in live:
                card.hide()
                card.deleteLater()
                self._cards.pop(key, None)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if self._cards:
            self._sync_cards()

    # -------------------------------------------------- 数据
    def set_frames(self, frames: List[Any]) -> None:
        self.frames = list(frames or [])
        self._relayout()
        self.update()

    def append(self, frame) -> None:
        # 增量追加：不要每来一帧就重新遍历几千行算偏移
        key = id(frame)
        if self._tops:
            prev = self.frames[-1] if self.frames else None
            prev_h = self.ROW_H + (self.CARD_H if prev is not None
                                   and id(prev) in self._expanded else 0)
            top = self._tops[-1] + prev_h
        else:
            top = 4.0
        self.frames.append(frame)
        self._tops.append(top)
        height = top + self.ROW_H + (self.CARD_H if key in self._expanded else 0) + 4
        self.setFixedHeight(max(1, int(height)))
        self._sync_cards()
        self.update()

    def clear(self) -> None:
        self.frames = []
        self.index = -1
        self._expanded.clear()
        self._relayout()

    def toggle(self, index: int) -> None:
        """点一行 = 展开 / 收起这一条；可以同时展开多条。"""
        if not (0 <= index < len(self.frames)):
            return
        key = id(self.frames[index])
        if key in self._expanded:
            self._expanded.pop(key, None)
        else:
            self._expanded[key] = None
            if len(self._expanded) > 12:
                self._expanded.pop(next(iter(self._expanded)))
        self.index = index
        self._relayout()
        self.picked.emit(index)
        self.update()

    def _row_at(self, y: float) -> int:
        i = bisect_right(self._tops, y) - 1
        if i < 0 or i >= len(self.frames):
            return -1
        return i if y < self._tops[i] + self.ROW_H else -1

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
        start = max(0, bisect_right(self._tops, offset) - 1)
        end = min(len(self.frames), bisect_left(self._tops, offset + height) + 1)
        return start, end

    # -------------------------------------------------- 交互
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
            self.toggle(idx)

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
            p.end()
            return
        start, end = self.visible_range()
        for i in range(start, end):
            frame = self.frames[i]
            top = self._tops[i]
            r = QRectF(4, top, self.width() - 8, self.ROW_H - 2)
            opened = id(frame) in self._expanded
            if i == self.index or i == self._hover or opened:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected if (i == self.index or opened) else t.hover))
                p.drawRoundedRect(r, 6, 6)
            p.setFont(mono(9.4))
            p.setPen(C(t.text_faint))
            stamp = datetime.datetime.fromtimestamp(frame.at).strftime("%H:%M:%S")
            p.drawText(QRectF(r.left() + 8, r.top(), 62, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), stamp)
            arrow = {"in": "↓", "out": "↑"}.get(frame.dir, "·")
            col = {"in": t.success, "out": t.info}.get(frame.dir, t.text_faint)
            if frame.kind == "error":
                col = t.danger
            p.setFont(font(11.6, QFont.Weight.DemiBold))
            p.setPen(C(col))
            p.drawText(QRectF(r.left() + 74, r.top(), 14, r.height()),
                       int(Qt.AlignmentFlag.AlignCenter), arrow)
            tag = KIND_LABEL.get(frame.kind, frame.kind.upper())
            p.setFont(mono(9.0, QFont.Weight.DemiBold))
            p.setPen(C(col if frame.dir != "sys" else t.text_dim))
            p.drawText(QRectF(r.left() + 92, r.top(), 46, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), tag)
            p.setFont(mono(9.4))
            p.setPen(C(t.text_faint))
            p.drawText(QRectF(r.left() + 138, r.top(), 60, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       human_size(frame.size) if frame.kind not in ("open", "close") else "—")
            p.setFont(mono(10.2))
            p.setPen(C(t.text_dim) if frame.dir != "sys" else C(t.text_faint))
            left = r.left() + 202
            avail = max(20.0, r.right() - left - 24)
            p.drawText(QRectF(left, r.top(), avail, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       QFontMetricsF(p.font()).elidedText(
                           frame.preview(), Qt.TextElideMode.ElideRight, int(avail)))
            p.setFont(font(10))
            p.setPen(C(t.text_faint))
            p.drawText(QRectF(r.right() - 20, r.top(), 16, r.height()),
                       int(Qt.AlignmentFlag.AlignCenter), "⌄" if opened else "›")
        p.end()


class WsLogView(QWidget):
    """响应区的 WebSocket 页面：连接状态 + 统计 + 帧列表 + 详情。"""

    replay = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frames: List[Any] = []
        self._n_in = self._n_out = self._size_in = 0
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
        self.list.setToolTip(i18n.tr("单击展开详情（可同时展开多条），双击填回编辑器"))
        self.list.picked.connect(self._on_picked)
        self.list.activated.connect(self._replay)
        self.scroll = SmoothScrollArea()
        self.scroll.setWidget(self.list)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._stick)

        # 空态单独一页：列表在没帧时高度只有 8px，把提示画在列表里会被压成一条线
        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(24, 0, 24, 0)
        el.setSpacing(0)
        self.empty_label = Label("", 11.6, theme().text_faint)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setText(i18n.tr("还没有消息。连接后收发的内容会实时出现在这里。"))
        el.addStretch(1)
        el.addWidget(self.empty_label)
        el.addStretch(1)

        self.body = QStackedWidget()
        self.body.addWidget(self.empty)
        self.body.addWidget(self.scroll)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(bar)
        lay.addWidget(Divider())
        lay.addWidget(self.body, 1)

    # -------------------------------------------------- 数据
    def set_frames(self, frames: List[Any]) -> None:
        self._frames = list(frames or [])
        self._n_in = sum(1 for f in self._frames if f.dir == "in")
        self._n_out = sum(1 for f in self._frames if f.dir == "out")
        self._size_in = sum(f.size for f in self._frames if f.dir == "in")
        self._rebuild()

    def add_frame(self, frame) -> None:
        self._frames.append(frame)
        if frame.dir == "in":
            self._n_in += 1
            self._size_in += frame.size
        elif frame.dir == "out":
            self._n_out += 1
        if self._match(frame):
            self.list.append(frame)
            self._update_stats()
            self._update_empty(True)

    def clear(self) -> None:
        self._frames = []
        self._n_in = self._n_out = self._size_in = 0
        self.list.clear()
        self._update_stats()
        self._update_empty(False)

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
        shown = [f for f in self._frames if self._match(f)]
        self.list.set_frames(shown)
        self._update_stats()
        self._update_empty(bool(shown))
        if self._auto_scroll:
            self._stick()

    def _update_empty(self, has_rows: bool) -> None:
        """有帧就显示列表，没帧才显示提示；筛选后一条不剩时换一句更准确的话。"""
        self.body.setCurrentIndex(1 if has_rows else 0)
        if has_rows:
            return
        if self._frames:
            self.empty_label.setText(i18n.tr("没有符合条件的内容。清空搜索或换个筛选试试。"))
        else:
            self.empty_label.setText(
                i18n.tr("还没有消息。连接后收发的内容会实时出现在这里。"))

    def _update_stats(self) -> None:
        # 统计数字做一次 280ms 补间：新消息进来是「跳」出来的，不是硬闪一下
        self.stats.animate_number(
            (self._n_in, self._n_out, self._size_in),
            lambda i, o, size: i18n.trf("接收 {i} · 发送 {o} · {size}",
                                        i=int(round(i)), o=int(round(o)),
                                        size=human_size(int(round(size)))))

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

    def _on_picked(self, index: int) -> None:
        """点一行更新复制目标；展开时把这条滚到眼前，别被自动跟随拽走。"""
        self.list.index = index
        if (0 <= index < len(self.list.frames)
                and id(self.list.frames[index]) in self.list._expanded):
            bar = self.scroll.verticalScrollBar()
            bar.setValue(max(0, int(self.list._tops[index]) - 4))

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
