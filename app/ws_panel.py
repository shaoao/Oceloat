"""WebSocket 的界面部分：请求侧的消息编辑器 + 响应侧的帧日志。

和 HTTP 面板保持同一套视觉语言：纯色卡片、白灰层次、反色主按钮。
日志列表按视口绘制，几万帧也不会把界面拖慢。
"""
from __future__ import annotations

import datetime
import json
import math
from bisect import bisect_left, bisect_right
from typing import Any, Dict, List

from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (
    QFileDialog,
    QPlainTextEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import i18n, icons
from .code_editor import CodeView, human_size
from .kv_editor import KVEditor
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

        t = theme()
        # --- 「通讯」页：消息类型 / 输入 / 发送 / 常用消息
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
        tools = HBox(self.kind, 1, self.fmt_btn, self.save_btn, self.send_btn,
                     spacing=8, margins=(0, 0, 0, 0))

        self.editor = CodeView(read_only=False, highlight=True, show_gutter=False)
        self.editor.setMinimumHeight(68)
        self.editor.setPlaceholderText(i18n.tr(
            "输入要发送的内容。连接成功后 ⌘↵ 直接发送；JSON 会自动识别高亮。"))
        # 输入中的草稿写回请求：切走标签再切回来，内容还在。
        self.editor.textChanged.connect(self._on_draft_changed)

        self.saved_note = Label("常用消息", 10.4, t.text_faint)
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

        chat_page = QWidget()
        cl = QVBoxLayout(chat_page)
        cl.setContentsMargins(14, 10, 14, 12)
        cl.setSpacing(8)
        cl.addWidget(tools)
        cl.addWidget(self.editor, 1)
        cl.addWidget(self.saved_note)
        cl.addWidget(self.saved_scroll)

        # --- 「参数」页：查询参数表，连接时拼进地址栏 URL
        self.params = KVEditor("参数名", "值", empty_hint="添加查询参数", with_types=True,
                               allow_file=False)
        self.params.changed.connect(self._on_option)
        # 与 HTTP 参数页一致：粘贴导入 + 批量编辑
        self.paste_btn = Button(i18n.tr("粘贴"), None, kind="ghost", height=24, padding=8,
                                font_size=11.5,
                                tooltip=i18n.tr("从剪贴板批量导入：a=1&b=2 / 多行 key: value / JSON"))
        self.paste_btn.clicked.connect(self._paste_params)
        self.params_bulk_btn = Button(i18n.tr("批量编辑"), None, kind="ghost", height=24,
                                      padding=8, font_size=11.5,
                                      tooltip=i18n.tr("以 key: value 文本一次编辑全部参数"))
        self.params_bulk_btn.clicked.connect(self._toggle_params_bulk)
        self.params_tools = HBox(1, self.paste_btn, self.params_bulk_btn, spacing=4)
        self.params_preview = Label("", 10.5, t.text_faint, mono_font=True)
        self.params_preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.params_preview.setToolTip(i18n.tr("连接时使用的完整地址"))
        params_page = QWidget()
        pal = QVBoxLayout(params_page)
        pal.setContentsMargins(14, 10, 14, 12)
        pal.setSpacing(6)
        pal.addWidget(Label(i18n.tr("查询参数会在连接时拼到地址后面"), 11, t.text_dim))
        pal.addWidget(self.params, 1)
        pal.addWidget(self.params_tools)
        pal.addWidget(self.params_preview)

        # --- 「协议」页：握手级配置，单独成页不干扰日常收发
        self.proto = QLineEdit()
        self.proto.setObjectName("Field")
        self.proto.setFixedHeight(28)
        i18n.placeholder(self.proto, "可留空")
        self.proto.textChanged.connect(self._on_option)
        self.ping = QLineEdit()
        self.ping.setObjectName("Field")
        self.ping.setFixedHeight(28)
        self.ping.setFixedWidth(64)
        i18n.placeholder(self.ping, "0")
        self.ping.setToolTip(i18n.tr("心跳间隔（秒），0 表示不发"))
        self.ping.textChanged.connect(self._on_option)
        self.reconnect_sw = Switch(True)
        self.reconnect_sw.toggled.connect(lambda _v: self._on_option())
        self.clear_sw = Switch(False)
        self.clear_sw.toggled.connect(lambda _v: self._on_option())

        # 低频配置不再套整块灰色卡片：直接铺在页面底色上，靠分组标题 +
        # 细分隔线做层次，左边缘与通讯页 / 顶部方法徽标落在同一条竖线上。
        proto_card = QWidget()
        pcv = QVBoxLayout(proto_card)
        pcv.setContentsMargins(10, 10, 14, 14)
        pcv.setSpacing(12)
        pcv.addWidget(Label(i18n.tr("连接参数"), 11, t.text_dim))
        p1 = QHBoxLayout()
        p1.setSpacing(10)
        p1.addWidget(Label("子协议", 11, t.text_faint))
        p1.addWidget(self.proto, 1)
        p1.addSpacing(10)
        p1.addWidget(Label("心跳", 11, t.text_faint))
        p1.addWidget(self.ping)
        p1.addWidget(Label("秒", 10.4, t.text_faint))
        pcv.addLayout(p1)
        pcv.addWidget(Divider())
        pcv.addWidget(Label(i18n.tr("连接行为"), 11, t.text_dim))
        p2 = QHBoxLayout()
        p2.setSpacing(10)
        p2.addWidget(Label("自动重连", 11, t.text_dim))
        p2.addWidget(self.reconnect_sw)
        p2.addSpacing(10)
        p2.addWidget(Label("发送后清空", 11, t.text_dim))
        p2.addWidget(self.clear_sw)
        p2.addStretch(1)
        self.headers_btn = Button("握手头", "list", kind="ghost", height=26, padding=10,
                                  font_size=11, icon_size=12)
        self.headers_btn.setToolTip(i18n.tr("连接时一起发送的请求头，例如 Authorization"))
        self.headers_btn.clicked.connect(self.headersToggled.emit)
        p2.addWidget(self.headers_btn)
        pcv.addLayout(p2)
        hint = Label(i18n.tr("以上选项在建立连接时生效，断开重连后会重新应用。"),
                     10.4, t.text_faint)
        hint.setWordWrap(True)
        pcv.addWidget(hint)
        pcv.addStretch(1)

        proto_page = QWidget()
        pl = QVBoxLayout(proto_page)
        pl.setContentsMargins(14, 10, 14, 12)
        pl.setSpacing(0)
        pl.addWidget(proto_card, 1)

        # 与 HTTP 请求页同款 underline 页签：通讯 / 参数 / 协议 三页。
        # 14px 与 UrlBar / HTTP 页签栏的左缩进一致，页签文字正好落在顶部
        # 方法徽标文字那条竖线上；内容区沿用 14 + 控件内边距 10 的基准。
        self.tabs = SegmentedTabs([("chat", "通讯"), ("params", "参数"),
                                   ("protocol", "协议")],
                                  style="underline", height=32, pad_h=10, font_size=12.2)
        self.tabs.changed.connect(self._on_tab)
        tab_host = QWidget()
        tab_l = QHBoxLayout(tab_host)
        tab_l.setContentsMargins(14, 0, 0, 0)
        tab_l.setSpacing(0)
        tab_l.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignLeft)
        self.stack = QStackedWidget()
        self.stack.addWidget(chat_page)
        self.stack.addWidget(params_page)
        self.stack.addWidget(proto_page)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(tab_host)
        lay.addWidget(self.stack, 1)
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
            self.params.blockSignals(True)
            self.params.set_rows(req.get("params") or [])
            self.params.blockSignals(False)
            self._refresh_saved()
        finally:
            self._loading = False

    def dump(self, req: Dict[str, Any]) -> None:
        ws = ensure_ws(req)
        req["params"] = self.params.rows()
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

    def _paste_params(self) -> None:
        """从剪贴板批量导入参数；KVEditor.set_rows 会触发 changed，进而同步 URL 预览。"""
        from PyQt6.QtWidgets import QApplication

        text = QApplication.clipboard().text()
        if text.strip():
            self.params.paste_text(text)

    def _toggle_params_bulk(self) -> None:
        self.params.set_bulk(not self.params.is_bulk())
        self.params_bulk_btn.setText(
            i18n.tr("退出批量") if self.params.is_bulk() else i18n.tr("批量编辑"))

    def set_params_preview(self, text: str) -> None:
        """由 RequestEditor 用统一的 URL 拼接算法算好最终地址后传入。"""
        if hasattr(self, "params_preview"):
            self.params_preview.setText(text or "")

    def _on_tab(self, key: str) -> None:
        """通讯 / 参数 / 协议 三页签。"""
        index = {"chat": 0, "params": 1, "protocol": 2}.get(key, 0)
        self.stack.setCurrentIndex(index)

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
        # 空态不再摆一整行说明文案（用户觉得占地方）；胶囊本身就是提示，
        # 悬停有说明。有内容时才显示一个简短计数。
        self.saved_note.setText(i18n.trf("常用消息 · {n}", n=n) if n else "")
        self.saved_note.setVisible(bool(n))
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
              "close": "CLOSE", "error": "ERR", "retry": "RETRY",
              # SSE 的默认事件名就是 message，缩成 MSG 才不会挤到字节数上
              "message": "MSG"}


class ChevronToggle(QWidget):
    """与集合树完全同款的箭头按钮：收起朝右、展开朝下。"""

    toggled = pyqtSignal(bool)

    def __init__(self, expanded: bool = True, parent=None):
        super().__init__(parent)
        self.expanded = bool(expanded)
        self._hover = False
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setToolTip(i18n.tr("折叠内容") if self.expanded else i18n.tr("展开内容"))

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.expanded = not self.expanded
        self.setToolTip(i18n.tr("折叠内容") if self.expanded else i18n.tr("展开内容"))
        self.update()
        self.toggled.emit(self.expanded)

    def enterEvent(self, e):  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.hover))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
        col = C(t.text if self._hover else t.text_dim).name(QColor.NameFormat.HexArgb)
        pm = icons.pixmap("chevron_right", col, 11, 2.0)
        p.save()
        p.translate(self.width() / 2, self.height() / 2)
        if self.expanded:
            p.rotate(90)
        p.drawPixmap(QPointF(-5.5, -5.5), pm)
        p.restore()
        p.end()


class _WheelForward(QObject):
    """把代码区的滚轮事件转交给外层日志滚动区。

    代码区是只读 QPlainTextEdit，即使滚动条关掉、内容又正好装得下，它仍会
    先吃掉滚轮事件（哪怕只滚 1px）。结果鼠标停在展开的卡片上滚动时，
    外层日志列表纹丝不动 —— 用户说的「滑不下去、看不了」。这里在安装到
    代码区的过滤器里把 Wheel 事件原样转发给外层 SmoothScrollArea。
    """

    def __init__(self, target: QWidget, host):
        super().__init__(target)
        self._target = target
        self._host = host

    def eventFilter(self, obj, e):  # noqa: N802
        if e.type() == QEvent.Type.Wheel and (
                obj is self._target or
                (hasattr(self._target, "viewport") and obj is self._target.viewport())):
            host = self._host() if callable(self._host) else self._host
            if host is not None and hasattr(host, "wheelEvent"):
                host.wheelEvent(e)
                return True          # 拦截：不让内层代码区再滚自己
        return False


class FrameCard(QWidget):
    """一条消息展开后的详情卡。

    列表那一行已经写了时间、方向、类型和预览，卡片里不再重复一遍；
    这里只做「内容」：页签 + 复制 + 一个带边框、可折叠、无滚动条的代码框。
    """

    H = 80
    heightChanged = pyqtSignal()

    @staticmethod
    def _looks_json(text: str) -> bool:
        s = (text or "").lstrip()
        if s[:1] not in ("{", "["):
            return False
        try:
            json.loads(s)
            return True
        except Exception:  # noqa: BLE001
            return False

    def __init__(self, frame, parent=None):
        super().__init__(parent)
        self.frame = frame
        self.setObjectName("FrameCard")
        self._raw = frame.preview(20000)
        self._syncing = False

        # 智能判断页签：内容真的是合法 JSON 才给 JSON / Raw 双标签，
        # 普通文本（如「hello asfafsafga」）和系统消息只给一个 Raw —— 跟参考图
        # 保持一致。之前按发送时选的 kind 判断会把纯文本也标成 JSON，用户截图
        # 里整条 ERR 都挂了个 JSON 页，就是这个原因。
        if frame.kind == "binary":
            items = [("hex", "Hex"), ("raw", "Raw")]
        elif self._looks_json(self._raw):
            items = [("pretty", "JSON"), ("raw", "Raw")]
        else:
            items = [("raw", "Raw")]
        # pad_h 与 bar 左边距配合，让 Raw 文字/下划线左边缘与下方代码框左边缘
        # 严格对齐（视觉对齐）。见下方 lay / code_card 的边距设定。
        self.tabs = SegmentedTabs(items, style="underline", height=24,
                                  font_size=10.8, pad_h=0, show_badges=False)
        self.tabs.changed.connect(self._render)
        # 用户要求去掉左上角那个折叠箭头：详情卡固定展开，入口不再显示。
        copy = icon_button("copy", "复制这条消息", 22, 12)
        copy.clicked.connect(self._copy)

        bar = QWidget()
        bl = QHBoxLayout(bar)
        # 左边距 0 + tabs 的 pad_h=0：Raw 文字/下划线从卡片内容左边缘起，
        # 正好与下方代码框左边缘同一条竖线（视觉对齐）。
        bl.setContentsMargins(0, 0, 12, 0)
        bl.setSpacing(4)
        bl.addWidget(self.tabs, 0)
        bl.addStretch(1)
        bl.addWidget(copy, 0)

        # 代码卡与底色同族：参考图的响应体区只比窗口底色深一点点，
        # 不再用偏亮的 elevated，避免黑框里套一块灰板的割裂感。
        self.code_card = Card(radius=8, fill=theme().code_bg)
        cl = QVBoxLayout(self.code_card)
        # 卡片左内边距 8 与 bar 的 8 对齐；代码内容（含行号槽）从同一竖线起。
        cl.setContentsMargins(8, 5, 8, 5)
        cl.setSpacing(0)
        # 内容是 JSON 就开高亮：日志行上的类型来自发送时选的模式，纯文本模式
        # 发出去的 JSON 会被标成 text，照样该有 key / 字符串 / 数字的分色。
        self.body = CodeView(read_only=True, highlight=self._looks_json(self._raw),
                             show_gutter=True)
        # QPlainTextEdit 的 viewport 默认拿 palette 的 base（纯黑），光靠
        # `background: transparent` 盖不住。显式铺一层跟底色同族的代码底色，
        # 既不是死黑，也让整块区域跟卡片背景连成一体。
        t = theme()
        self.body.setStyleSheet(
            f"QPlainTextEdit {{ background: {t.code_bg}; color: {t.code_text}; border: none; }}")
        # 内容再长也不出滚动条：折行 + 卡片跟着内容长高，滚动交给外层日志区
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # 滚轮透传：鼠标压在代码区上时也要能滚动整个日志列表。
        # 滚轮事件实际投递给 QAbstractScrollArea 的 viewport，而不是控件本身，
        # 所以两处都要装过滤器（装 body 上只是兜底）。
        self._wheel_forward = _WheelForward(
            self.body, lambda: self._outer_scroll())
        self.body.viewport().installEventFilter(self._wheel_forward)
        self.body.installEventFilter(self._wheel_forward)
        cl.addWidget(self.body, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 7)
        lay.setSpacing(4)
        lay.addWidget(bar, 0)
        lay.addWidget(self.code_card, 1)
        self._render(self.tabs.current())

    def _outer_scroll(self):
        """沿父链找到承载日志列表的滚动区（延迟查找，构造时还没挂上去）。"""
        from .widgets import _scroll_host

        return _scroll_host(self)

    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.panel_alt))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        p.end()

    def refresh_theme(self) -> None:
        """切换主题时同步代码卡底色与代码区样式（控件是懒创建的）。"""
        t = theme()
        self.code_card._fill = t.code_bg
        self.body.setStyleSheet(
            f"QPlainTextEdit {{ background: {t.code_bg}; color: {t.code_text}; border: none; }}")
        self.code_card.update()
        self.body.update()

    # -------------------------------------------------- 高度
    def sync_height(self) -> bool:
        if self._syncing:
            return False
        self._syncing = True
        try:
            # QPlainTextEdit 的 document().size() 不是像素高度（它报的是块数），
            # 自己按字体行距 × 可视行数算，长 JSON 也能整段铺开而不出滚动条。
            doc = self.body.document()
            fm = QFontMetricsF(self.body.font())
            avail = max(40.0, float(self.body.viewport().width()) - 46)
            lines = 0
            block = doc.begin()
            while block.isValid():
                text = block.text()
                lines += max(1, math.ceil(fm.horizontalAdvance(text) / avail))
                block = block.next()
            h = int(lines * fm.lineSpacing() + doc.documentMargin() * 2 + 6)
            self.body.setFixedHeight(max(26, h))
            self.code_card.setFixedHeight(self.body.height() + 12)
            # 4(top) + 24(tabs) + 4(spacing) + code_card + 7(bottom)
            want = 4 + 24 + 4 + self.code_card.height() + 7
            if abs(self.height() - want) <= 1:
                return False
            self.setFixedHeight(want)
            return True
        finally:
            self._syncing = False

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if self.sync_height():
            self.heightChanged.emit()

    # -------------------------------------------------- 内容
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
        if self.sync_height():
            self.heightChanged.emit()

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
        self._relayouting = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # -------------------------------------------------- 布局
    def _layout_tops(self) -> tuple[List[float], float]:
        """按每张卡片的「当前真实高度」算出所有行的 top 与内容总高。纯计算。"""
        tops: List[float] = []
        top = 4.0
        for frame in self.frames:
            tops.append(top)
            h = (self._card_height(frame) if id(frame) in self._expanded else 0)
            top += self.ROW_H + h
        return tops, top

    def _relayout(self) -> None:
        if self._relayouting:
            return
        self._relayouting = True
        try:
            # 关键：先把所有展开卡片创建出来、并把高度算准，再排布 tops。
            # 之前只在循环里算 tops、拿 _sync_cards() 的返回值当收敛判据——
            # 新展开的卡片在第一轮还不存在（按 CARD_H=80 预估），卡片创建后
            # tops 本该重算，却因返回值误判提前 break，导致长卡片被后续行覆盖、
            # 列表总高算小。这就是「两卡片压一块」「滚到底看不到内容」的根因。
            # 先创建所有展开卡片、拿到真实高度，再进入收敛循环。
            cards_changed = self._sync_cards()
            for _ in range(6):
                new_tops, total = self._layout_tops()
                # total 已经含最后一行展开卡片的完整高度，直接作为内容底边。
                self.setFixedHeight(max(8, int(total + 4)))
                # 用 tops 自身是否变化判断收敛，而不是卡片属性变化：
                # 卡片可能早已 setGeometry 过，但 tops 仍是旧的预估偏移。
                stable = (len(new_tops) == len(self._tops)
                          and all(abs(a - b) <= 0.5
                                  for a, b in zip(new_tops, self._tops)))
                self._tops = new_tops
                cards_changed = self._sync_cards() or cards_changed
                if stable and not cards_changed:
                    break
                cards_changed = False
        finally:
            self._relayouting = False

    def _on_card_height(self) -> None:
        self._relayout()

    def _sync_cards(self) -> bool:
        if not self._expanded and not self._cards:
            return False
        live = set()
        changed = False
        for i, frame in enumerate(self.frames):
            key = id(frame)
            if key not in self._expanded:
                continue
            live.add(key)
            card = self._cards.get(key)
            if card is None:
                card = FrameCard(frame, self)
                card.heightChanged.connect(self._on_card_height)
                self._cards[key] = card
                changed = True
            # 先按当前列宽把卡片放到位（高度用旧的即可），拿到真实 viewport
            # 宽度后再 sync_height 算准行数，最后用准确高度重设 geometry。
            # 顺序反过来会拿 80px 的占位高度摆卡片，长内容就被压住。
            card.setGeometry(QRect(4, int(self._tops[i] + self.ROW_H),
                                   max(80, self.width() - 8), card.height()))
            if card.sync_height():
                changed = True
            card.setGeometry(QRect(4, int(self._tops[i] + self.ROW_H),
                                   max(80, self.width() - 8), card.height()))
            card.show()
        for key, card in list(self._cards.items()):
            if key not in live:
                card.hide()
                card.deleteLater()
                self._cards.pop(key, None)
        return changed

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if self._cards:
            # 列宽变化会让长文本重新折行、卡片变高/变矮，必须整表重排 tops，
            # 否则只摆卡片不更新偏移，同样会出现重叠和底部裁切。
            self._relayout()

    # -------------------------------------------------- 数据
    def set_frames(self, frames: List[Any]) -> None:
        self.frames = list(frames or [])
        self._relayout()
        self.update()

    def _card_height(self, frame) -> int:
        """展开卡片的实际高度；未展开 / 尚未创建时用预估高度。"""
        card = self._cards.get(id(frame))
        return card.height() if card is not None else self.CARD_H

    def append(self, frame) -> None:
        # 增量追加：不要每来一帧就重新遍历几千行算偏移。
        # 关键：上一行如果正展开着，必须用它的「实际」高度。之前这里写死
        # CARD_H=80，长 JSON 卡片 1200px 高却按 80 累加，于是新帧直接盖到
        # 展开卡片身上、滚动范围也跟着缩水 —— 表现为「点开后滑不下去」。
        key = id(frame)
        if self._tops:
            prev = self.frames[-1] if self.frames else None
            prev_h = self.ROW_H + (self._card_height(prev) if prev is not None
                                   and id(prev) in self._expanded else 0)
            top = self._tops[-1] + prev_h
        else:
            top = 4.0
        self.frames.append(frame)
        self._tops.append(top)
        height = top + self.ROW_H + (self._card_height(frame)
                                     if key in self._expanded else 0) + 4
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
        # 时间列固定 62px 在 ui_scale 放大后会被切掉半位数字（显示成 22:00:3|）。
        # 按当前字号量一次「00:00:00」的宽度，多出来的部分整体右移，行与行仍然对齐。
        _tf = mono(9.4)
        _tw = max(62.0, QFontMetricsF(_tf).horizontalAdvance("00:00:00") + 8)
        pad = _tw - 62.0
        for i in range(start, end):
            frame = self.frames[i]
            top = self._tops[i]
            r = QRectF(4, top, self.width() - 8, self.ROW_H - 2)
            opened = id(frame) in self._expanded
            if i == self.index or i == self._hover or opened:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected if (i == self.index or opened) else t.hover))
                p.drawRoundedRect(r, 6, 6)
            p.setFont(_tf)
            p.setPen(C(t.text_faint))
            stamp = datetime.datetime.fromtimestamp(frame.at).strftime("%H:%M:%S")
            p.drawText(QRectF(r.left() + 8, r.top(), _tw, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), stamp)
            arrow = {"in": "↓", "out": "↑"}.get(frame.dir, "·")
            col = {"in": t.success, "out": t.info}.get(frame.dir, t.text_faint)
            if frame.kind == "error":
                col = t.danger
            p.setFont(font(11.6, QFont.Weight.DemiBold))
            p.setPen(C(col))
            p.drawText(QRectF(r.left() + 74 + pad, r.top(), 14, r.height()),
                       int(Qt.AlignmentFlag.AlignCenter), arrow)
            tag = KIND_LABEL.get(frame.kind, frame.kind.upper())
            p.setFont(mono(9.0, QFont.Weight.DemiBold))
            p.setPen(C(col if frame.dir != "sys" else t.text_dim))
            # SSE 的事件名是服务端自定义的（message / update / price-changed…），
            # 固定 46px 会被后面的字节数盖住；按可用宽度省略，绝不重叠。
            tag = QFontMetricsF(p.font()).elidedText(
                tag, Qt.TextElideMode.ElideRight, 44)
            p.drawText(QRectF(r.left() + 92 + pad, r.top(), 46, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), tag)
            p.setFont(mono(9.4))
            p.setPen(C(t.text_faint))
            p.drawText(QRectF(r.left() + 138 + pad, r.top(), 60, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       human_size(frame.size) if frame.kind not in ("open", "close") else "—")
            p.setFont(mono(10.2))
            p.setPen(C(t.text_dim) if frame.dir != "sys" else C(t.text_faint))
            left = r.left() + 202 + pad
            avail = max(20.0, r.right() - left - 24)
            p.drawText(QRectF(left, r.top(), avail, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       QFontMetricsF(p.font()).elidedText(
                           frame.inline_preview(), Qt.TextElideMode.ElideRight,
                           int(avail)))
            col = C(t.text_faint).name(QColor.NameFormat.HexArgb)
            pm = icons.pixmap("chevron_right", col, 11, 2.0)
            p.save()
            p.translate(r.right() - 12, r.center().y())
            if opened:
                p.rotate(90)
            p.drawPixmap(QPointF(-5.5, -5.5), pm)
            p.restore()
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
        # 和 HTTP 空态用同一枚品牌动画（WS / Socket.IO / SSE 共用这个基类），
        # 没帧时也会自己描一遍线，三个实时页的空态视觉统一。
        from .brand import BrandMark

        self.empty_mark = BrandMark(px(56), self.empty, autoplay=True,
                                    token="text_faint", hover_token="text")
        self.empty_label = Label("", 11.6, theme().text_faint)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setText(i18n.tr("还没有消息。连接后收发的内容会实时出现在这里。"))
        el.addStretch(1)
        el.addWidget(self.empty_mark, 0, Qt.AlignmentFlag.AlignHCenter)
        el.addSpacing(px(12))
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
        # 只要还有展开的详情卡，就暂停「自动跟到底」：否则展开一张长卡片时
        # rangeChanged 会把视图猛地拽到列表底部，刚点开的内容反而看不见。
        # 收起全部卡片后自然恢复跟随。
        if self.list._expanded:
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
        path, _ = QFileDialog.getSaveFileName(
            self.window(), i18n.tr("导出消息日志"),
            getattr(self, "_log_name", "websocket-log.json"),
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
