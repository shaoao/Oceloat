"""请求编辑器：URL 栏 + 参数 / 请求头 / 请求体 / 认证 四个编辑面板。"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import (QPoint, QPointF, QRectF, QSize, Qt, QTimer,
                          QUrl, QUrlQuery, pyqtSignal)
from PyQt6.QtGui import (QColor, QDesktopServices, QFont, QFontMetricsF, QGuiApplication,
                         QPainter, QPen, QPixmap)
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import i18n, icons
from .code_editor import CodeView, pretty_json
from .kv_editor import COMMON_CONTENT_TYPES, COMMON_HEADERS, KVEditor
from .scripts import script_parts
from .store import BODY_CONTENT_TYPES, Store, kv, resolve_vars
from .anim import running as _anim_running, stop as _anim_stop
from .theme import C, S, method_color, font, mono, theme
from .widgets import (
    Button,
    Card,
    ChoiceMenu,
    popup_hidden_tabs,
    Divider,
    ElideLabel,
    FadeStack,
    HBox,
    Label,
    Menu,
    SegmentedTabs,
    SmoothScrollArea,
    SuggestPopup,
    VBox,
    animate,
    fade_in,
    icon_button,
)

# 与参考图一致：GET / POST / PUT / DELETE / OPTIONS / HEAD / PATCH / TRACE
# WebSocket 不是 HTTP 方法：它是一类独立的请求，只能从「新建」里创建，
# 所以不出现在这张下拉表里，避免把普通请求切成一个半 HTTP 半 WS 的怪东西。
METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"]
WS_METHOD = "WS"
SIO_METHOD = "SIO"
SSE_METHOD = "SSE"
# 实时协议：都不是「发一次、收一次」的 HTTP 请求，界面与传输都另走一套
REALTIME_METHODS = (WS_METHOD, SIO_METHOD, SSE_METHOD)

# HTTP 请求区的标签集合；WebSocket 有自己的一整页（见 RequestEditor.ws_page），
# 不共用这套页签。
HTTP_TABS = [("params", "参数"), ("body", "请求体"), ("headers", "请求头"),
             ("cookies", "Cookies"), ("auth", "认证"),
             ("pre", "前置脚本"), ("post", "后置脚本")]

# 与 Postman / Hoppscotch 对齐的 body 类型；显示英文名，i18n 会保留原词。
# 存储层仍用短 key（form = form-data，urlencoded = x-www-form-urlencoded），
# 旧数据天然兼容；XML 是新增的独立类型，走代码编辑器 + application/xml。
BODY_MODES = [
    ("none", "none"),
    ("form", "form-data"),
    ("urlencoded", "x-www-form-urlencoded"),
    ("raw", "Raw"),
    ("json", "JSON"),
    ("xml", "XML"),
    ("text", "Text"),
    ("binary", "Binary"),
]
# 旧数据的 mode 值直接沿用，这里只做「截图的显示名 → 存储 key」的反向兼容说明：
# form-data → form, x-www-form-urlencoded → urlencoded。导入器若写入长名，先归一化。
# raw 是独立模式（带语言下拉），不能再折成 text，否则 Raw 页永远显示不出来。
_MODE_ALIAS = {
    "form-data": "form", "multipart/form-data": "form",
    "x-www-form-urlencoded": "urlencoded", "url-encoded": "urlencoded",
    "application/json": "json", "file": "binary",
}
# Raw 模式下可选的语法语言，决定高亮 / 格式化 / Content-Type。
RAW_LANGS = [("json", "JSON"), ("xml", "XML"), ("html", "HTML"), ("text", "Text")]

# 认证类型英文名与主流客户端对齐；Inherit 是专有名词，中英文界面都只显示英文。
AUTH_TYPES = [("none", "无"), ("inherit", "Inherit"), ("bearer", "Bearer"),
              ("basic", "Basic"), ("apikey", "API Key"), ("jwt", "JWT"),
              ("oauth2", "OAuth 2.0"), ("awsv4", "AWS SigV4"), ("digest", "Digest")]


# ---------------------------------------------------------------- 方法菜单


class MethodMenu(QWidget):
    """自绘方法下拉：方法色 + 当前项对号 + 悬停灰层 + 淡入动效。"""

    ROW_H = 28
    PAD = 6
    picked = pyqtSignal(str)

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._current = (current or "GET").upper()
        self._hover = -1
        self._items = list(METHODS)      # 去掉「自定义…」入口，菜单只留标准方法
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        w = 168
        h = self.PAD * 2 + len(self._items) * self.ROW_H + 6
        self.resize(w, h)

    def set_current(self, method: str) -> None:
        self._current = (method or "GET").upper()
        self._hover = -1
        self.update()

    def _row_rect(self, i: int) -> QRectF:
        return QRectF(self.PAD, self.PAD + i * self.ROW_H, self.width() - self.PAD * 2, self.ROW_H - 2)

    def _row_at(self, y: float) -> int:
        i = int((y - self.PAD) // self.ROW_H)
        return i if 0 <= i < len(self._items) else -1

    def popup(self, global_pos: QPoint) -> None:
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = global_pos.x()
        y = global_pos.y()
        if y + self.height() > geo.bottom():
            y = max(geo.top() + 8, geo.bottom() - self.height() - 8)
        if x + self.width() > geo.right():
            x = geo.right() - self.width() - 8
        self.move(x, y)
        self._hover = -1          # popup 会抓鼠标，先清掉上次的灰条
        self.update()
        self.show()
        self.raise_()
        fade_in(self, 90)

    # -------------------------------------------------- 事件
    def mouseMoveEvent(self, e):
        # Popup 窗口抓着鼠标，鼠标在菜单外移动时也会收到事件；
        # 必须先判断是不是真的落在菜单里，否则灰条会「追着鼠标跑」。
        if not self.rect().contains(e.position().toPoint()):
            if self._hover != -1:
                self._hover = -1
                self.update()
            return
        idx = self._row_at(e.position().y())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def enterEvent(self, e):
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._hover != -1:
            self._hover = -1
            self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        idx = self._row_at(e.position().y())
        if idx >= 0:
            self.picked.emit(self._items[idx])
            self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.elevated))
        p.drawRoundedRect(r, 10, 10)
        for i, name in enumerate(self._items):
            rr = self._row_rect(i)
            if i == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected))
                p.drawRoundedRect(rr, 7, 7)
            p.setFont(mono(11.5, QFont.Weight.Bold))
            p.setPen(C(method_color(name, t)))
            p.drawText(QRectF(rr.left() + 12, rr.top(), rr.width() - 36, rr.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)
            if name == self._current:
                pm = icons.pixmap("check", t.text, 12, 1.9)
                p.drawPixmap(QPointF(rr.right() - 19, rr.center().y() - 6), pm)
        p.end()


# ---------------------------------------------------------------- 方法选择器


class MethodSelector(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, method: str = "GET", parent=None):
        super().__init__(parent)
        self._method = (method or "GET").upper()
        self.setFixedSize(92, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hover = False
        self._locked = False
        self.setToolTip("选择请求方法")
        self._menu: Optional[MethodMenu] = None

    def method(self) -> str:
        return self._method

    def set_method(self, method: str) -> None:
        self._method = (method or "GET").upper()
        self.update()

    def set_locked(self, locked: bool) -> None:
        """WebSocket / Socket.IO 的方法固定：不弹下拉、不画箭头，收窄成协议徽标，
        把腾出的横向空间让给地址输入框（实时页地址通常很长）。"""
        self._locked = bool(locked)
        self.setFixedSize(52 if locked else 92, 30)
        self.setCursor(Qt.CursorShape.ArrowCursor if locked
                       else Qt.CursorShape.PointingHandCursor)
        self.setToolTip("" if locked else "选择请求方法")
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if self._locked or e.button() != Qt.MouseButton.LeftButton:
            return
        self._open_menu()

    def _open_menu(self) -> None:
        # 菜单常驻复用：MethodMenu 带 Popup 标志，关掉后若再 .close() 会
        # RuntimeError: wrapped C/C++ object of type MethodMenu has been deleted
        if self._menu is None:
            self._menu = MethodMenu(self._method, self)
            self._menu.picked.connect(self._on_picked)
        self._menu.set_current(self._method)
        self._menu.popup(self.mapToGlobal(QPoint(self.rect().left(), self.rect().bottom() + 4)))

    def _on_picked(self, method: str) -> None:
        self._choose(method)

    def _choose(self, method: str):
        if method != self._method:
            self._method = method
            self.update()
            self.changed.emit(method)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(0, 0.5, -0.5, -0.5)
        if self._hover and not self._locked:
            p.setPen(QPen(C(t.border), 1))
            p.setBrush(C(t.panel_alt))
            p.drawRoundedRect(r, 7, 7)
        p.setFont(mono(11, QFont.Weight.Bold))
        p.setPen(C(method_color(self._method, t)))
        p.drawText(self.rect().adjusted(10, 0, -20 if not self._locked else -8, 0),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._method)
        if not self._locked:
            pm = icons.pixmap("chevron_down", t.text_faint, 11, 1.8)
            p.drawPixmap(QPointF(self.width() - 19, self.height() / 2 - 5), pm)
        p.end()


# ---------------------------------------------------------------- URL 栏


class UrlBar(QWidget):
    sendRequested = pyqtSignal()
    cancelRequested = pyqtSignal()
    methodChanged = pyqtSignal(str)
    urlChanged = pyqtSignal(str)
    codeRequested = pyqtSignal()
    moreRequested = pyqtSignal(object)
    mockRequested = pyqtSignal()
    mockizeRequested = pyqtSignal()
    duplicateRequested = pyqtSignal()
    saveRequested = pyqtSignal()

    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store
        self._busy = False
        self._ws_mode = False
        self._ws_state = "idle"
        self.method = MethodSelector("GET")
        self.method.changed.connect(self.methodChanged.emit)
        self.method.changed.connect(self._on_method_mode)

        self.url = QLineEdit()
        self.url.setObjectName("Url")
        i18n.placeholder(self.url, "输入请求地址，例如 https://httpbin.org/get")
        self.url.setFont(mono(12.2))
        self.url.setFixedHeight(30)
        self.url.textChanged.connect(self.urlChanged.emit)
        self.url.returnPressed.connect(self._on_enter)
        # 地址栏自动补全：只补历史里出现过的地址，输入时按包含匹配弹候选
        self._url_history: List[str] = []
        self._url_popup: Optional[SuggestPopup] = None
        self.url.textEdited.connect(self._on_url_typed)
        self.url.installEventFilter(self)
        self._url_card = Card(radius=8)
        self._url_card.setFixedHeight(32)
        lay = QHBoxLayout(self._url_card)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(4)
        lay.addWidget(self.url, 1)

        self.send_btn = Button("发送", "send", kind="primary", height=32, padding=14,
                               radius=8, font_size=12.5, tooltip="发送请求  ⌘↵")
        self.send_btn.clicked.connect(self._on_send)
        self.save_btn = icon_button("download", "保存到集合  ⌘S", 30, 15)
        self.save_btn.clicked.connect(self.saveRequested.emit)
        self.code_btn = icon_button("code", "生成代码片段  ⌘⇧C", 30, 15)
        self.code_btn.clicked.connect(self.codeRequested.emit)
        self.more_btn = icon_button("more", "更多操作", 30, 15)
        self.more_btn.clicked.connect(lambda: self.moreRequested.emit(self.more_btn))

        # 右侧工具组：与发送按钮同高、间距统一、无多余描边
        tools = QWidget()
        tl = QHBoxLayout(tools)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(2)
        tl.addWidget(self.save_btn)
        tl.addWidget(self.code_btn)
        tl.addWidget(self.more_btn)

        from .node_panel import NodeButton

        self.node_btn = NodeButton()
        self.node_btn.clicked.connect(self._open_nodes)

        lay_row = QHBoxLayout(self)
        lay_row.setContentsMargins(14, 6, 14, 2)
        lay_row.setSpacing(8)
        lay_row.addWidget(self.method, 0, Qt.AlignmentFlag.AlignVCenter)
        lay_row.addWidget(self._url_card, 1)
        lay_row.addWidget(self.send_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        lay_row.addWidget(self.node_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        lay_row.addSpacing(2)
        lay_row.addWidget(tools, 0, Qt.AlignmentFlag.AlignVCenter)

    # -------------------------------------------------- 节点
    def _refresh_url_suggestions(self) -> None:
        """把历史地址缓存到内存；真正的候选在每次输入时临时筛。"""
        self._url_history = []
        if self.store is None:
            return
        seen, out = set(), []
        for entry in self.store.history:
            url = (entry.get("url") or "").strip()
            if url and url not in seen:
                seen.add(url)
                out.append(url)
            if len(out) >= 80:
                break
        self._url_history = out

    def _ensure_url_popup(self) -> SuggestPopup:
        if self._url_popup is None:
            self._url_popup = SuggestPopup(self, "clock")
            self._url_popup.picked.connect(self._apply_url_suggestion)
        return self._url_popup

    def _on_url_typed(self, text: str) -> None:
        needle = text.strip().lower()
        popup = self._ensure_url_popup()
        if not needle or not self._url_history:
            popup.hide()
            return
        hits = [u for u in self._url_history
                if needle in u.lower() and u.lower() != needle]
        if not hits:
            popup.hide()
            return
        popup.set_items(hits)
        popup.popup_below(self._url_card, width=max(self._url_card.width(), 380))

    def _apply_url_suggestion(self, url: str) -> None:
        self.url.setText(url)
        self.url.setCursorPosition(len(url))
        self.url.setFocus()

    def _hide_url_popup(self) -> None:
        if self._url_popup is not None:
            self._url_popup.hide()

    def eventFilter(self, obj, event):
        if obj is self.url:
            kind = event.type()
            if kind == event.Type.FocusIn:
                self._refresh_url_suggestions()
            elif kind == event.Type.FocusOut:
                self._hide_url_popup()
            elif kind == event.Type.KeyPress:
                popup = self._url_popup
                if popup is not None and popup.isVisible():
                    key = event.key()
                    if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                        popup.step(1 if key == Qt.Key.Key_Down else -1)
                        return True
                    if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                        text = popup.current()
                        self._hide_url_popup()
                        if text:
                            self._apply_url_suggestion(text)
                            return True
                    if key == Qt.Key.Key_Escape:
                        self._hide_url_popup()
                        return True
        return super().eventFilter(obj, event)

    def _open_nodes(self) -> None:
        from .node_panel import NodePicker

        if getattr(self, "_node_picker", None) is None:
            self._node_picker = NodePicker(self._node_book(), self)
            self._node_picker.picked.connect(lambda _i: self.refresh_node())
        self._node_picker.refresh_current()
        self._node_picker.popup(self.node_btn.mapToGlobal(
            QPoint(0, self.node_btn.height() + 4)))

    def _node_book(self):
        if getattr(self, "_book", None) is None:
            from .nodes import NodeBook

            self._book = NodeBook(self.store)
        return self._book

    def refresh_node(self) -> None:
        node = self._node_book().current()
        self.node_btn.set_node(node)
        self.node_btn.setToolTip(
            i18n.tr("从本机直接发出") if node.get("kind") == "local"
            else i18n.trf("经由节点：{name}", name=node.get("name")))

    def _on_enter(self):
        if not self._busy:
            self.sendRequested.emit()

    def _on_send(self):
        # WebSocket 已连接（或正在连）时，同一颗按钮是「断开 / 取消」
        if self._ws_mode and self._ws_state in ("open", "connecting", "closing"):
            self.cancelRequested.emit()
            return
        if self._busy:
            self.cancelRequested.emit()
        else:
            self.sendRequested.emit()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if self._ws_mode:
            # HTTP 那条 busy 收尾不能把一条活着的 WS 连接显示成 idle
            if self._ws_state in ("open", "connecting", "closing"):
                self.set_ws_state(self._ws_state)
            else:
                self.set_ws_state("idle")
            return
        if busy:
            self.send_btn.setText("取消")
            self.send_btn.set_icon("stop")
            self.send_btn.set_kind("subtle")
            self.send_btn.set_busy(True)
        else:
            self.send_btn.set_busy(False)
            self.send_btn.setText("发送")
            self.send_btn.set_icon("send")
            self.send_btn.set_kind("primary")

    def _on_method_mode(self, method: str) -> None:
        """切到 WS / Socket.IO 时地址栏、按钮、提示全换成连接语义。"""
        upper = (method or "").upper()
        realtime = upper in REALTIME_METHODS
        sio = upper == SIO_METHOD
        sse = upper == SSE_METHOD
        self._ws_mode = realtime
        i18n.placeholder(
            self.url,
            ("ws:// 或 wss:// 地址，例如 ws://localhost:3000/socket.io" if sio
             else ("http(s):// 地址，例如 https://example.com/events" if sse
                   else "ws:// 或 wss:// 地址，例如 wss://echo.websocket.org"))
            if realtime else "输入请求地址，例如 https://httpbin.org/get")
        self.url.setToolTip("" if not realtime else i18n.tr(
            "SSE 走普通 HTTP，填 http(s):// 地址即可") if sse else i18n.tr(
            "支持 ws:// wss://；直接粘 http(s) 地址会自动补全 Socket.IO 路径")
            if sio else i18n.tr("支持 ws:// wss://；直接粘 http(s) 地址会自动改写"))
        self.method.set_locked(realtime)
        # 节点 = HTTP 代理出口（node_proxy / relay_node 只有 http_client 读），
        # WS / Socket.IO / SSE 的连接根本不经过它；摆在那里只会误导，收起来。
        self.node_btn.setVisible(not realtime)
        if realtime:
            # 已连接时重新 load（切标签 / 刷新界面）不能把按钮打回「连接」。
            if self._ws_state not in ("open", "connecting", "closing"):
                self.set_ws_state("idle")
            else:
                self.set_ws_state(self._ws_state)
        else:
            self.set_busy(False)
            self.send_btn.setToolTip("发送请求  ⌘↵")

    def set_ws_state(self, state: str) -> None:
        """连接状态 → 按钮文案。连接中可取消，已连接则是「断开」。"""
        self._ws_state = state
        self.send_btn.set_busy(False)
        if state == "open":
            # 断开 = 危险操作：红字 + 一层薄红底，和「发送 / 连接」一眼分开
            self.send_btn.setText("断开")
            self.send_btn.set_icon("stop")
            self.send_btn.set_kind("danger")
            self.send_btn.setToolTip("断开连接  ⌘↵")
        elif state in ("connecting", "closing"):
            self.send_btn.setText("取消")
            self.send_btn.set_icon("stop")
            self.send_btn.set_kind("subtle")
            self.send_btn.setToolTip("取消连接")
        else:
            self.send_btn.setText("连接")
            self.send_btn.set_icon("link")
            self.send_btn.set_kind("primary")
            self.send_btn.setToolTip("建立连接  ⌘↵")

    def set_method(self, method: str):
        self.method.set_method(method)

    def set_url(self, url: str):
        self.url.blockSignals(True)
        self.url.setText(url)
        self.url.blockSignals(False)

    def url_text(self) -> str:
        return self.url.text()

    def focus_url(self):
        self.url.setFocus()
        self.url.selectAll()


# ---------------------------------------------------------------- 请求体面板


class BodyPage(QWidget):
    changed = pyqtSignal()
    aiRequested = pyqtSignal()      # 点「AI 生成」：由 RequestEditor 拼上下文并调模型

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._mode = "none"

        self.modes = SegmentedTabs([(m, l) for m, l in BODY_MODES], style="pill", height=28,
                                   font_size=12, pad_h=12)
        self.modes.changed.connect(self._on_mode)
        self.type_label = Label("", 10.5, theme().text_faint, mono_font=True)

        top = HBox(self.modes, 1, self.type_label, spacing=8)
        top.layout().setContentsMargins(0, 0, 2, 0)

        # JSON / XML / 文本 —— 共用代码编辑器，按类型切高亮语言
        self.code = CodeView(read_only=False, highlight=True, show_gutter=True, wrap=False)
        self.code.textChanged.connect(self._on_code_changed)
        self.code_frame = Card(radius=9)
        cf = QVBoxLayout(self.code_frame)
        cf.setContentsMargins(0, 6, 0, 6)
        cf.addWidget(self.code, 1)

        self.json_status = Label("", 10.5, theme().text_faint, mono_font=True)
        self.ai_btn = Button("AI 生成", "spark", kind="ghost", height=24, padding=8,
                             font_size=11.5, icon_size=12,
                             tooltip="按字段名生成一份真实数据，边生成边写进编辑器")
        self.ai_btn.clicked.connect(self.aiRequested.emit)
        self.format_btn = Button("Format", None, kind="ghost", height=24, padding=8, font_size=11.5)
        self.format_btn.clicked.connect(self._format)
        self.minify_btn = Button("Minify", None, kind="ghost", height=24, padding=8, font_size=11.5)
        self.minify_btn.clicked.connect(self._minify)
        # Raw 的语言下拉：决定高亮 / 格式化 / Content-Type，选中即写回 body.raw_lang
        self.raw_lang_tabs = SegmentedTabs(RAW_LANGS, style="pill", height=22,
                                           font_size=10.5, pad_h=8)
        self.raw_lang_tabs.changed.connect(self._on_raw_lang)
        self._raw_lang = "json"
        self.code_tools = HBox(self.raw_lang_tabs, 4, self.json_status, 1,
                               self.ai_btn, self.format_btn, self.minify_btn, spacing=4)

        # 表单（带类型列：File 类型直接选文件上传，走 multipart/form-data）
        self.form = KVEditor("字段", "值", empty_hint="添加表单字段",
                             with_types=True, with_desc=False)
        self.form.changed.connect(self._on_form_changed)
        self.form_hint = Label("类型选 File 点击即可选文件上传 · 值以 @ 开头也会按文件发送",
                               10.5, theme().text_faint, mono_font=True)
        self.form_host = VBox(self.form, 1, self.form_hint, margins=(0, 0, 0, 0), spacing=4)

        # 文件
        self._file_path = ""          # 真实路径；显示文字会被翻译，不能拿来当数据用
        self.file_name = Label(i18n.tr("未选择文件"), 12, theme().text_dim, mono_font=True)
        self.pick_btn = Button("选择文件", "file", kind="subtle", height=28, padding=10, font_size=12)
        self.pick_btn.clicked.connect(self._pick_file)
        self.clear_file_btn = Button("清除", None, kind="ghost", height=28, padding=8, font_size=12)
        self.clear_file_btn.clicked.connect(self._clear_file)
        self.file_frame = Card(radius=9)
        fl = QHBoxLayout(self.file_frame)
        fl.setContentsMargins(14, 12, 14, 12)
        fl.setSpacing(10)
        fl.addWidget(icons_icon_label("file"), 0)
        fl.addWidget(self.file_name, 1)
        fl.addWidget(self.pick_btn)
        fl.addWidget(self.clear_file_btn)
        self.file_host = VBox(self.file_frame, 1, margins=(0, 0, 0, 0))

        self.stack = FadeStack()
        self.stack.add("code", self._page(self.code_frame, self.code_tools))
        self.stack.add("form", self._page(self.form_host))
        self.stack.add("file", self._page(self.file_host))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(8)
        lay.addWidget(top)
        lay.addWidget(self.stack, 1)
        self._sync_tools()

    def _page(self, *widgets) -> QWidget:
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for i, item in enumerate(widgets):
            if isinstance(item, QWidget):
                lay.addWidget(item, 1 if i == 0 else 0)
        return w

    # -------------------------------------------------- 模式
    def _code_mode(self) -> str:
        """代码页的有效语法模式：raw 按语言下拉展开，其他模式原样返回。"""
        return self._raw_lang if self._mode == "raw" else self._mode

    def _on_mode(self, mode: str) -> None:
        mode = _MODE_ALIAS.get(mode, mode)
        self._mode = mode
        if mode in ("raw", "json", "xml", "text"):
            self.stack.set_current("code")
        elif mode in ("form", "urlencoded"):
            self.stack.set_current("form")
        elif mode == "binary":
            self.stack.set_current("file")
        else:
            self.stack.set_current("code")
        if mode == "none":
            self.code.setEnabled(False)
            self.code.setStyleSheet("QPlainTextEdit { color: rgba(128,128,138,120); }")
        else:
            self.code.setEnabled(True)
            self.code.setStyleSheet("QPlainTextEdit { background: transparent; border: none; }")
        self._sync_code_language()
        self._sync_tools()
        if not self._loading:
            self.changed.emit()

    def _sync_code_language(self) -> None:
        """JSON 走 JSON 规则；XML/HTML 走通用标记规则；纯文本不高亮。"""
        lang = self._code_mode()
        if lang == "text":
            self.code.set_highlight(False)
        else:
            # set_language(None) 会按需建 JsonHighlighter；不必再调 set_highlight，
            # 否则会先建再拆，白做一次全文档 rehighlight。
            self.code.set_language("xml" if lang in ("xml", "html") else None)

    def _on_raw_lang(self, lang: str) -> None:
        if self._loading:
            return
        self._raw_lang = lang
        self._sync_code_language()
        self._sync_tools()
        self._validate_json()
        self.changed.emit()

    def _sync_tools(self) -> None:
        mode = self._mode
        eff = self._code_mode()
        self.type_label.setText(
            BODY_CONTENT_TYPES.get(eff, "") if mode == "raw" else {
                "json": "application/json", "xml": "application/xml",
                "text": "text/plain",
                "urlencoded": "x-www-form-urlencoded", "form": "multipart/form-data",
                "binary": "application/octet-stream", "none": "",
            }.get(mode, ""))
        self.raw_lang_tabs.setVisible(mode == "raw")
        self.code_tools.setVisible(mode in ("raw", "json", "xml", "text"))
        self.format_btn.setVisible(eff in ("json", "xml"))
        self.minify_btn.setVisible(eff == "json")
        self.ai_btn.setVisible(eff == "json")
        self.json_status.setVisible(eff in ("json", "xml"))
        self.code.setVisible(mode != "none")

    def _on_code_changed(self) -> None:
        if self._loading:
            return
        if self._code_mode() in ("json", "xml"):
            self._validate_json()
        self.changed.emit()

    def refresh_theme(self) -> None:
        if self._code_mode() in ("json", "xml") and self.code.toPlainText().strip():
            self._validate_json()

    def _validate_json(self) -> None:
        text = self.code.toPlainText().strip()
        if not text or self._code_mode() not in ("json", "xml"):
            self.json_status.setText("")
            return
        if self._code_mode() == "xml":
            from PyQt6.QtXml import QDomDocument

            doc = QDomDocument()
            ok = doc.setContent(text)
            self.json_status.setText("✓ XML" if ok else "✕ XML")
            self.json_status.setStyleSheet(
                f"color: {theme().success if ok else theme().danger}; background: transparent;")
            return
        try:
            data = json.loads(text)
            n = len(data) if isinstance(data, (dict, list)) else 1
            self.json_status.setText(
                i18n.trf("✓ 合法 JSON · {n} 个字段", n=n) if isinstance(data, dict)
                else i18n.trf("✓ 合法 JSON · {n} 项", n=n))
            self.json_status.setStyleSheet(f"color: {theme().success}; background: transparent;")
        except Exception as exc:
            msg = str(exc)
            self.json_status.setText("✕ " + msg)
            self.json_status.setStyleSheet(f"color: {theme().danger}; background: transparent;")

    def _format(self) -> None:
        if self._code_mode() == "xml":
            from ..code_editor import _format_xml

            out = _format_xml(self.code.toPlainText())
            if out:
                self.code.setPlainText(out)
            return
        formatted, ok = pretty_json(self.code.toPlainText())
        if ok:
            self.code.setPlainText(formatted)

    def _minify(self) -> None:
        try:
            data = json.loads(self.code.toPlainText())
            self.code.setPlainText(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
        except Exception:
            pass

    def _on_form_changed(self) -> None:
        if not self._loading:
            self.changed.emit()

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("选择请求体文件"), "", i18n.tr("所有文件 (*)"))
        if path:
            self._file_path = path
            self.file_name.setText(path)
            self.file_name.setToolTip(path)
            self.changed.emit()

    def _clear_file(self) -> None:
        self._file_path = ""
        self.file_name.setText(i18n.tr("未选择文件"))
        self.changed.emit()

    # -------------------------------------------------- 数据
    def load(self, body: Dict[str, Any]) -> None:
        self._loading = True
        mode = body.get("mode", "none") or "none"
        mode = _MODE_ALIAS.get(mode, mode)
        self._mode = mode
        self._raw_lang = body.get("raw_lang", "json") or "json"
        if self._raw_lang not in dict(RAW_LANGS):
            self._raw_lang = "json"
        self.modes.set_current(mode, emit=False)
        self.raw_lang_tabs.set_current(self._raw_lang, emit=False)
        self.code.setPlainText(body.get("raw", "") or "")
        self.form.set_rows(body.get("form", []) or [])
        path = body.get("file", "")
        self._file_path = path or ""
        self.file_name.setText(path or i18n.tr("未选择文件"))
        self.file_name.setToolTip(path)
        if mode in ("raw", "json", "xml", "text"):
            self.stack.set_current("code")
        elif mode in ("form", "urlencoded"):
            self.stack.set_current("form")
        elif mode == "binary":
            self.stack.set_current("file")
        else:
            self.stack.set_current("code")
        self._sync_code_language()
        self._sync_tools()
        if self._code_mode() in ("json", "xml"):
            self._validate_json()
        self._loading = False

    def dump(self) -> Dict[str, Any]:
        return {
            "mode": self._mode,
            "raw": self.code.toPlainText(),
            "raw_lang": self._raw_lang,
            "form": self.form.rows(),
            "file": self._file_path,
        }

    def has_content(self) -> bool:
        """有没有内容（给徽标用）。不复制整段正文 —— 大请求体每次敲键都 toPlainText 很贵。"""
        if self._mode == "none":
            return False
        if self._mode == "binary":
            return bool(self._file_path)
        if self._mode in ("form", "urlencoded"):
            return bool(self.form.rows())
        return self.code.document().characterCount() > 1


def icons_icon_label(name: str) -> Label:
    lbl = Label("", 12)
    lbl.setFixedSize(16, 16)
    from . import icons as _i

    lbl.setPixmap(_i.pixmap(name, theme().text_dim, 15, 1.6))
    return lbl


# ---------------------------------------------------------------- 认证面板


class AuthPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, store: Optional[Store] = None, parent=None):
        super().__init__(parent)
        self.store = store
        self._loading = False
        self._type = "none"
        self._request_id = ""
        self._oauth_was_manual = False
        self._oauth_auto_adv = False

        # 自适应：认证方式有 9 种，面板变窄时多余的收进「更多」，不硬挤成一团
        self.types = SegmentedTabs([(k, l) for k, l in AUTH_TYPES], style="pill", height=28,
                                   font_size=12, pad_h=11, adaptive=True)
        self.types.changed.connect(self._on_type)
        self.types.more_clicked.connect(self._on_types_more)
        self._types_menu: Optional[ChoiceMenu] = None

        self.bearer_token = self._field("Token", "粘贴 Bearer Token，例如 eyJhbGciOi…")
        self.basic_user = self._field("用户名", "username")
        self.basic_pass = self._field("密码", "password", password=True)
        self.api_key = self._field("Key 名称", "X-API-Key")
        self.api_value = self._field("Value", "密钥值")
        self.api_add = SegmentedTabs([("header", "添加为请求头"), ("query", "添加为查询参数")],
                                     style="pill", height=26, font_size=11.5, pad_h=11)

        self.bearer_box = self._group("Bearer Token", "请求将以 Authorization: Bearer <token> 发送。", self.bearer_token)
        self.basic_box = self._group("Basic Auth", "用户名与密码将进行 Base64 编码后放入 Authorization。",
                                     self.basic_user, self.basic_pass)
        self.api_box = self._group("API Key", "选择一个位置注入密钥。", self.api_key, self.api_value, self.api_add)
        self.none_box = self._group("无认证", "该请求不携带任何认证凭据。")

        # Inherit：显示从哪个集合继承、继承到哪种方式
        self.inherit_source = Label("", 12.5, theme().text, weight=QFont.Weight.DemiBold)
        self.inherit_detail = Label("", 11.5, theme().text_faint)
        self.inherit_detail.setWordWrap(True)
        self.inherit_box = self._group(
            "Inherit", "从所属集合继承认证配置。集合未设置认证时不带任何凭据。",
            self.inherit_source, self.inherit_detail)

        # JWT：自动生成签名令牌 / 手动粘贴，两种模式
        from .jwt_auth import ALGORITHMS

        self.jwt_mode = SegmentedTabs(
            [("auto", "自动生成"), ("manual", "手动输入")],
            style="pill", height=26, font_size=11.5, pad_h=11)
        self.jwt_mode.changed.connect(self._on_jwt_mode)
        self.jwt_alg = SegmentedTabs(
            [(a, a) for a in ALGORITHMS], style="pill", height=26, font_size=11.5, pad_h=10)
        self.jwt_alg.set_current("HS256", emit=False)
        self.jwt_alg.changed.connect(self._on_jwt_change)
        self.jwt_payload = self._field("Payload", '{"sub": "123", "name": "Ocelot"}')
        self.jwt_secret = self._field("密钥", "your-256-bit-secret", password=True)
        self.jwt_token = self._field("Token", "粘贴现成的 JWT")
        self.jwt_status = Label("", 10.8, theme().text_faint, mono_font=True)
        self.jwt_status.setWordWrap(True)

        auto_w = QWidget()
        al = QVBoxLayout(auto_w)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(9)
        al.addWidget(Label("算法", 11.3, theme().text_dim, weight=QFont.Weight.DemiBold))
        al.addWidget(self.jwt_alg)
        al.addWidget(Label("载荷", 11.3, theme().text_dim, weight=QFont.Weight.DemiBold))
        al.addWidget(self.jwt_payload)
        al.addWidget(Label("密钥", 11.3, theme().text_dim, weight=QFont.Weight.DemiBold))
        al.addWidget(self.jwt_secret)
        manual_w = QWidget()
        ml = QVBoxLayout(manual_w)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(9)
        ml.addWidget(self.jwt_token)
        self.jwt_pages = FadeStack()
        self.jwt_pages.add("auto", auto_w)
        self.jwt_pages.add("manual", manual_w)
        self.jwt_pages.set_current("auto", animate=False)

        jwt_inner = QWidget()
        jil = QVBoxLayout(jwt_inner)
        jil.setContentsMargins(0, 0, 0, 0)
        jil.setSpacing(10)
        jil.addWidget(self.jwt_mode)
        jil.addWidget(self.jwt_pages, 1)
        jil.addWidget(self.jwt_status)
        self.jwt_box = self._group(
            "JWT",
            "填写 Payload 与密钥后自动生成签名令牌，发送时作为 Authorization: Bearer <token> 携带。",
            jwt_inner)

        # OAuth 2.0：四种 grant + PKCE + token 缓存状态
        from .oauth2_auth import GRANTS, GRANT_LABELS

        self.oauth_grant = SegmentedTabs(
            [(g, GRANT_LABELS[g]) for g in GRANTS], style="pill", height=26,
            font_size=11, pad_h=9, adaptive=True)
        self.oauth_grant.set_current("client_credentials", emit=False)
        self.oauth_grant.changed.connect(self._on_oauth_grant)
        self.oauth_grant.more_clicked.connect(self._on_grant_more)
        self._grant_menu: Optional[ChoiceMenu] = None
        self.oauth_issuer = self._field("Issuer", "https://example.com（OIDC 自动发现）")
        self.oauth_auth_url = self._field("授权地址", "https://example.com/oauth/authorize")
        self.oauth_token_url = self._field("Token 地址", "https://example.com/oauth/token")
        self.oauth_client_id = self._field("Client ID", "client id")
        self.oauth_client_secret = self._field("Client Secret", "client secret", password=True)
        self.oauth_scope = self._field("Scope", "read write")
        self.oauth_username = self._field("用户名", "username")
        self.oauth_password = self._field("密码", "password", password=True)
        self.oauth_code = self._field("授权码", "从浏览器回调里复制 code")
        self.oauth_redirect_uri = self._field("回调地址", "http://localhost:8080/callback")
        self.oauth_code_verifier = self._field("PKCE Verifier", "点「打开授权页」自动生成")
        self.oauth_state = self._field("State", "打开授权页时自动生成")
        self.oauth_state_returned = self._field("回调 State", "从浏览器回调复制，可留空")
        self.oauth_access_token = self._field("Access Token", "手动 Token 模式下粘贴")
        self.oauth_refresh_token = self._field("Refresh Token", "自动回填，过期时用来刷新")
        self.oauth_token_key = self._field("Token 参数名", "access_token")
        self.oauth_token_auth_method = SegmentedTabs(
            [("client_secret_post", "Secret 在表单"), ("client_secret_basic", "Secret 在 Header")],
            style="pill", height=26, font_size=11.2, pad_h=10)
        self.oauth_token_auth_method.set_current("client_secret_post", emit=False)
        self.oauth_placement = SegmentedTabs(
            [("header", "请求头"), ("query", "查询参数")],
            style="pill", height=26, font_size=11.5, pad_h=11)
        self.oauth_placement.set_current("header", emit=False)
        self.oauth_status = Label("", 10.8, theme().text_faint, mono_font=True)
        self.oauth_status.setWordWrap(True)
        self.oauth_open_btn = Button("打开授权页", "external", kind="ghost", height=26,
                                     padding=9, font_size=11.5,
                                     tooltip="打开授权页并自动写入 PKCE Verifier 与 State")
        self.oauth_pkce_btn = Button("生成 Verifier", "refresh", kind="ghost", height=26,
                                     padding=9, font_size=11.5,
                                     tooltip="生成新的 PKCE code_verifier")
        self.oauth_fetch_btn = Button("获取 Token", "refresh", kind="ghost", height=26,
                                      padding=9, font_size=11.5,
                                      tooltip="立即调用 Token 地址换取 access_token")
        self.oauth_discover_btn = Button("OIDC 自动发现", "spark", kind="subtle", height=26,
                                         padding=9, font_size=11.5,
                                         tooltip="从 Issuer 的 well-known 配置回填授权与 Token 地址")
        self.oauth_clear_btn = Button("清除缓存", "trash", kind="ghost", height=26,
                                      padding=9, font_size=11.5,
                                      tooltip="删掉本机缓存的 Token，下次发送重新换取")
        self.oauth_open_btn.clicked.connect(self._on_oauth_open)
        self.oauth_pkce_btn.clicked.connect(self._on_oauth_pkce)
        self.oauth_fetch_btn.clicked.connect(self._on_oauth_fetch)
        self.oauth_discover_btn.clicked.connect(self._on_oauth_discover)
        self.oauth_clear_btn.clicked.connect(self._on_oauth_clear)
        oauth_inner = QWidget()
        ol = QVBoxLayout(oauth_inner)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(8)
        ol.addWidget(Label("授权方式", 11.3, theme().text_dim, weight=QFont.Weight.DemiBold))
        ol.addWidget(self.oauth_grant)
        # 常用区：每种 grant 只铺自己必需的几行，其余收进「高级设置」
        ol.addWidget(self.oauth_auth_url)
        ol.addWidget(self.oauth_token_url)
        self.oauth_row_cred = HBox(self.oauth_client_id, self.oauth_client_secret, 1, spacing=8)
        ol.addWidget(self.oauth_row_cred)
        ol.addWidget(self.oauth_redirect_uri)
        ol.addWidget(self.oauth_code)
        self.oauth_row_userpass = HBox(self.oauth_username, self.oauth_password, 1, spacing=8)
        ol.addWidget(self.oauth_row_userpass)
        ol.addWidget(self.oauth_scope)
        ol.addWidget(self.oauth_access_token)
        # 常用区只放「现在就要按」的两颗；OIDC 发现与清缓存属于低频操作，
        # 收进高级区，窄面板下按钮行也不会挤成两行或被裁掉
        self.oauth_actions = HBox(self.oauth_open_btn, self.oauth_fetch_btn, 1, spacing=6)
        ol.addWidget(self.oauth_actions)

        # 高级区：Secret 位置、Token 参数名/放置、PKCE、State、Refresh —— 默认收起
        self.oauth_secret_pos_label = Label("Secret 发送位置", 11.3, theme().text_dim,
                                            weight=QFont.Weight.DemiBold)
        self.oauth_placement_label = Label("Token 放在哪里", 11.3, theme().text_dim,
                                           weight=QFont.Weight.DemiBold)
        self.oauth_adv_body = QWidget()
        av = QVBoxLayout(self.oauth_adv_body)
        av.setContentsMargins(0, 4, 0, 0)
        av.setSpacing(8)
        av.addWidget(self.oauth_issuer)
        av.addWidget(HBox(self.oauth_discover_btn, self.oauth_clear_btn, 1, spacing=6))
        av.addWidget(self.oauth_secret_pos_label)
        av.addWidget(self.oauth_token_auth_method)
        av.addWidget(self.oauth_token_key)
        av.addWidget(self.oauth_placement_label)
        av.addWidget(self.oauth_placement)
        av.addWidget(self.oauth_refresh_token)
        av.addWidget(self.oauth_code_verifier)
        av.addWidget(self.oauth_state)
        av.addWidget(self.oauth_state_returned)
        av.addWidget(self.oauth_pkce_btn)
        self.oauth_adv_body.setVisible(False)
        self.oauth_adv_btn = Button("高级设置", "chevron_right", kind="ghost", height=24,
                                    padding=6, icon_size=11, gap=5, font_size=11.5,
                                    tooltip="Secret 发送位置 / Token 参数名与放置 / PKCE / State / Refresh Token")
        self.oauth_adv_btn.clicked.connect(self._toggle_oauth_adv)
        ol.addWidget(self.oauth_adv_btn, 0, Qt.AlignmentFlag.AlignLeft)
        ol.addWidget(self.oauth_adv_body)
        ol.addWidget(self.oauth_status)
        self.oauth_box = self._group(
            "OAuth 2.0",
            "授权码 + PKCE / 客户端凭证 / 密码 / 手动 Token；Token 自动缓存并在过期前刷新。",
            oauth_inner)

        # AWS SigV4：每次发送前基于最终请求重新签名
        self.aws_access = self._field("Access Key ID", "AKIA...")
        self.aws_secret = self._field("Secret Access Key", "secret", password=True)
        self.aws_session = self._field("Session Token", "可选，STS 临时凭证")
        self.aws_region = self._field("Region", "us-east-1")
        self.aws_service = self._field("Service", "execute-api")
        self.aws_sign_body = SegmentedTabs(
            [("yes", "签名 Body"), ("no", "不签名 Body")],
            style="pill", height=26, font_size=11.5, pad_h=11)
        self.aws_sign_body.set_current("yes", emit=False)
        self.aws_status = Label("签名基于最终 method / URL / 请求头 / 请求体，每次发送自动重签。",
                                10.8, theme().text_faint)
        self.aws_status.setWordWrap(True)
        self.aws_detail = Label("", 10.4, theme().text_dim, mono_font=True)
        self.aws_detail.setWordWrap(True)
        self.aws_infer_btn = Button("自动推断区域 / 服务", "spark", kind="subtle", height=26,
                                    padding=9, font_size=11.5,
                                    tooltip="根据当前请求 URL 推断 AWS region 与 service")
        self.aws_presign_btn = Button("生成预签名 URL", "external", kind="ghost", height=26,
                                      padding=9, font_size=11.5,
                                      tooltip="用当前 URL 生成 1 小时有效的预签名链接")
        self.aws_infer_btn.clicked.connect(self._on_aws_infer)
        self.aws_presign_btn.clicked.connect(self._on_aws_presign)
        self.aws_box = self._group(
            "AWS SigV4",
            "为 AWS API Gateway / S3 / EC2 等接口生成 AWS4-HMAC-SHA256 签名，可推断区域、预览签名明细、生成预签名 URL。",
            self.aws_access, self.aws_secret, self.aws_session,
            self.aws_region, self.aws_service, self.aws_sign_body,
            HBox(self.aws_infer_btn, self.aws_presign_btn, 1, spacing=6),
            self.aws_status, self.aws_detail)

        # Digest：401 挑战 → 自动重发，标准库实现
        self.digest_user = self._field("用户名", "username")
        self.digest_pass = self._field("密码", "password", password=True)
        self.digest_algorithm = SegmentedTabs(
            [("MD5", "MD5"), ("SHA-256", "SHA-256"), ("SHA-512-256", "SHA-512-256")],
            style="pill", height=26, font_size=11.2, pad_h=10)
        self.digest_algorithm.set_current("MD5", emit=False)
        self.digest_qop = SegmentedTabs(
            [("auto", "自动"), ("auth", "auth"), ("auth-int", "auth-int")],
            style="pill", height=26, font_size=11.2, pad_h=10)
        self.digest_qop.set_current("auto", emit=False)
        self.digest_realm = self._field("Realm", "可选，留空则用服务器挑战值")
        self.digest_nonce = self._field("Nonce", "可选，留空则等 401 挑战")
        self.digest_opaque = self._field("Opaque", "可选，服务器返回时自动带")
        self.digest_status = Label("收到 401 Digest 挑战后自动重发，nonce / nc 由 Ocelot 管理。",
                                   10.8, theme().text_faint)
        self.digest_status.setWordWrap(True)
        self.digest_box = self._group(
            "Digest",
            "支持 MD5 / SHA-256 / SHA-512-256、qop=auth / auth-int、userhash；401 挑战自动处理。",
            self.digest_user, self.digest_pass,
            Label("算法", 11.3, theme().text_dim, weight=QFont.Weight.DemiBold),
            self.digest_algorithm,
            Label("质量保护（qop）", 11.3, theme().text_dim,
                  weight=QFont.Weight.DemiBold),
            self.digest_qop,
            self.digest_realm, self.digest_nonce, self.digest_opaque,
            self.digest_status)

        self.stack = FadeStack()
        self.stack.add("none", self.none_box)
        self.stack.add("inherit", self.inherit_box)
        self.stack.add("bearer", self.bearer_box)
        self.stack.add("basic", self.basic_box)
        self.stack.add("apikey", self.api_box)
        self.stack.add("jwt", self.jwt_box)
        self.stack.add("oauth2", self.oauth_box)
        self.stack.add("awsv4", self.aws_box)
        self.stack.add("digest", self.digest_box)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(10)
        lay.addWidget(self.types)
        lay.addWidget(self.stack, 1)

    def _field(self, placeholder: str, ph: str = "", password: bool = False) -> QLineEdit:
        e = QLineEdit()
        e.setObjectName("Field")
        i18n.placeholder(e, ph or placeholder)
        e.setFont(mono(11.8))
        e.setFixedHeight(30)
        # 认证页有并排两列的字段：单个最少宽度给太大，分栏后整页会被横向裁掉
        e.setMinimumWidth(140)
        if password:
            e.setEchoMode(QLineEdit.EchoMode.Password)
        e.textChanged.connect(self._on_change)
        return e

    def _group(self, title: str, desc: str, *widgets) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(9)
        desc_label = Label(desc, 11.5, theme().text_faint)
        # 说明文字必须能换行：否则它把整页的最小宽度撑到 800+，
        # 左右分栏后页面被横向裁掉，页签行也跟着「消失」。
        desc_label.setWordWrap(True)
        desc_label.setMinimumWidth(1)
        head = VBox(Label(title, 12.5, theme().text, weight=QFont.Weight.DemiBold),
                    desc_label, spacing=3)
        lay.addWidget(head)
        for item in widgets:
            if isinstance(item, QLineEdit):
                lay.addWidget(item)
            else:
                lay.addWidget(item, 0)
        lay.addStretch(1)
        return w

    def _on_type(self, key: str) -> None:
        self._type = key
        self.stack.set_current(key)
        if key == "inherit":
            self._refresh_inherit()
        elif key == "jwt":
            self._refresh_jwt()
        elif key == "oauth2":
            # 首次切进认证页时也要按当前 grant 条件渲染，避免所有字段一次性铺开
            self._on_oauth_grant()
        if not self._loading:
            self.changed.emit()

    def _popup_more(self, attr: str, tabs, pos) -> None:
        popup_hidden_tabs(self, attr, tabs, pos)

    def _on_grant_more(self, global_pos) -> None:
        self._popup_more("_grant_menu", self.oauth_grant, global_pos)

    def _on_types_more(self, global_pos) -> None:
        self._popup_more("_types_menu", self.types, global_pos)

    def _on_jwt_mode(self, mode: str) -> None:
        self.jwt_pages.set_current(mode)
        self._refresh_jwt()
        if not self._loading:
            self.changed.emit()

    def _on_jwt_change(self, _key: str = "") -> None:
        self._refresh_jwt()
        if not self._loading:
            self.changed.emit()

    def _refresh_jwt(self) -> None:
        from .jwt_auth import make_jwt

        if self.jwt_mode.current() != "auto":
            self.jwt_status.setText("")
            return
        payload = self.jwt_payload.text().strip()
        if not payload:
            self.jwt_status.setText("")
            return
        token, err = make_jwt(payload, self.jwt_secret.text(), self.jwt_alg.current(),
                              self.store.env_vars() if self.store else {},
                              error_hint=i18n.tr("Payload 不是合法 JSON"))
        if err:
            self.jwt_status.setText("✕ " + err)
            self.jwt_status.setStyleSheet(f"color: {theme().danger}; background: transparent;")
        else:
            self.jwt_status.setText(i18n.trf("已生成 · {n} 字符", n=len(token)))
            self.jwt_status.setStyleSheet(f"color: {theme().success}; background: transparent;")

    def _refresh_inherit(self) -> None:
        auth = None
        if self.store and self._request_id:
            try:
                auth = self.store.inherited_auth(self._request_id)
            except Exception:  # noqa: BLE001
                auth = None
        if auth:
            kind = auth.get("type") or "none"
            label = dict(AUTH_TYPES).get(kind, kind)
            self.inherit_source.setText(i18n.trf("集合认证：{kind}", kind=i18n.tr(label)))
            self.inherit_detail.setText(i18n.tr("从所属集合继承认证配置。集合未设置认证时不带任何凭据。"))
            self.inherit_detail.setStyleSheet("")
        else:
            self.inherit_source.setText(i18n.tr("当前集合未设置认证，请求将不带凭据。"))
            self.inherit_detail.setText(i18n.tr("从所属集合继承认证配置。集合未设置认证时不带任何凭据。"))

    def refresh_theme(self) -> None:
        """语言切换后重译状态行；SegmentedTabs 自带重译，字段占位符由 i18n 处理。"""
        self._refresh_oauth_status()
        self.aws_status.setText(i18n.tr(
            "签名基于最终 method / URL / 请求头 / 请求体，每次发送自动重签。"))
        self.digest_status.setText(i18n.tr(
            "收到 401 Digest 挑战后自动重发，nonce / nc 由 Ocelot 管理。"))

    def _toggle_oauth_adv(self) -> None:
        """展开 / 收起 OAuth 高级设置（默认收起，常用区只留必要字段）。"""
        show = not self.oauth_adv_body.isVisible()
        self.oauth_adv_body.setVisible(show)
        self.oauth_adv_btn.set_icon("chevron_down" if show else "chevron_right")
        self.oauth_adv_btn.setText("收起高级" if show else "高级设置")

    def _on_oauth_grant(self, _key: str = "") -> None:
        """按授权方式精确条件渲染：只显示该 grant 真正需要的字段。

        常用区只铺「必须填的几行」，PKCE / State / Token 参数名这类低频项
        统一收进默认收起的「高级设置」—— 之前 20 多个字段一次性铺开，
        页面长得像一堵墙，真正要填的反倒找不到。
        """
        grant = self.oauth_grant.current()
        manual = grant in ("implicit", "manual")
        auth_code = grant == "authorization_code"
        password = grant == "password"

        # 换取 token 的模式才有的公共字段
        common = [self.oauth_token_url, self.oauth_row_cred, self.oauth_client_id,
                  self.oauth_client_secret, self.oauth_scope, self.oauth_actions,
                  self.oauth_fetch_btn, self.oauth_discover_btn, self.oauth_clear_btn,
                  self.oauth_issuer, self.oauth_secret_pos_label,
                  self.oauth_token_auth_method, self.oauth_refresh_token]
        for widget in common:
            widget.setVisible(not manual)

        # 仅授权码 + PKCE
        code_only = [self.oauth_auth_url, self.oauth_code, self.oauth_redirect_uri,
                     self.oauth_code_verifier, self.oauth_state,
                     self.oauth_state_returned, self.oauth_pkce_btn,
                     self.oauth_open_btn]
        for widget in code_only:
            widget.setVisible(auth_code)

        # 仅密码模式
        self.oauth_row_userpass.setVisible(password)
        self.oauth_username.setVisible(password)
        self.oauth_password.setVisible(password)

        # 手动 / 隐式：只留粘贴框，以及放在哪里的选择
        self.oauth_access_token.setVisible(manual)
        self.oauth_token_key.setVisible(True)
        self.oauth_placement_label.setVisible(True)
        self.oauth_placement.setVisible(True)
        # 手动模式要自己指定 Token 放哪（高级区里的两项就是全部必填项），
        # 切过来时自动展开，免得用户以为「什么都不能填」。
        if manual and not self._oauth_was_manual:
            self.oauth_adv_body.setVisible(True)
            self.oauth_adv_btn.set_icon("chevron_down")
            self.oauth_adv_btn.setText("收起高级")
            self._oauth_auto_adv = True
        elif not manual and self._oauth_auto_adv:
            # 高级区是刚才为手动模式自动展开的：换回其他 grant 就收起来，
            # 别让「自动打开」变成一直占着半屏的常开区域。
            self.oauth_adv_body.setVisible(False)
            self.oauth_adv_btn.set_icon("chevron_right")
            self.oauth_adv_btn.setText("高级设置")
            self._oauth_auto_adv = False
        self._oauth_was_manual = manual
        self._refresh_oauth_status()
        if not self._loading:
            self.changed.emit()

    def _refresh_oauth_status(self) -> None:
        from .oauth2_auth import cached_entry, cached_token

        auth = self.dump()
        env = self.store.env_vars() if self.store else {}
        entry = cached_token(auth, self.store, env)
        stale = cached_entry(auth, self.store, env)
        if entry:
            self.oauth_status.setText(i18n.tr("已缓存 Token · 发送时自动使用并在过期前刷新"))
            self.oauth_status.setStyleSheet(f"color: {theme().success}; background: transparent;")
        elif stale and stale.get("refresh_token"):
            self.oauth_status.setText(i18n.tr("Token 已过期 · 发送时用 Refresh Token 自动刷新"))
            self.oauth_status.setStyleSheet(f"color: {theme().warning}; background: transparent;")
        else:
            self.oauth_status.setText(i18n.tr("尚未获取 Token · 首次发送时自动换取"))
            self.oauth_status.setStyleSheet("")

    def _on_oauth_pkce(self) -> None:
        from .oauth2_auth import pkce

        verifier, _challenge = pkce()
        self.oauth_code_verifier.setText(verifier)
        self.toast_message(i18n.tr("已生成新的 PKCE Verifier"))

    def _on_oauth_open(self) -> None:
        from .oauth2_auth import authorize_url_with_state

        auth = self.dump()
        url, verifier, state = authorize_url_with_state(
            auth, self.store.env_vars() if self.store else {})
        if not url:
            self.toast_message(i18n.tr("请先填写授权地址"), warn=True)
            return
        self._loading = True
        if verifier:
            self.oauth_code_verifier.setText(verifier)
        if state:
            self.oauth_state.setText(state)
        self._loading = False
        QGuiApplication.clipboard().setText(url)
        QDesktopServices.openUrl(QUrl(url))
        self.toast_message(i18n.tr("已生成 PKCE / State 并打开授权页，地址已复制"))

    def _on_oauth_fetch(self) -> None:
        from .oauth2_auth import fetch_token, save_token

        auth = self.dump()
        env = self.store.env_vars() if self.store else {}
        token, err = fetch_token(auth, env, 15)
        if err:
            self.oauth_status.setText("✕ " + err)
            self.oauth_status.setStyleSheet(f"color: {theme().danger}; background: transparent;")
            return
        save_token(auth, self.store, env, token)
        # save_token 会把轮换后的 refresh_token / access_token 回填到 auth
        self._loading = True
        self.oauth_refresh_token.setText(str(auth.get("oauth_refresh_token") or ""))
        self.oauth_access_token.setText(str(auth.get("oauth_access_token") or ""))
        self._loading = False
        self._refresh_oauth_status()
        self.toast_message(i18n.tr("Token 获取成功"))

    def _on_oauth_discover(self) -> None:
        from .oauth2_auth import discover

        info, err = discover(self.oauth_issuer.text(), 12)
        if err:
            self.toast_message(err, warn=True)
            return
        self._loading = True
        self.oauth_auth_url.setText(info.get("oauth_auth_url", ""))
        self.oauth_token_url.setText(info.get("oauth_token_url", ""))
        self._loading = False
        self.toast_message(i18n.tr("OIDC 地址已自动回填"))

    def _on_oauth_clear(self) -> None:
        from .oauth2_auth import clear_token

        clear_token(self.dump(), self.store, self.store.env_vars() if self.store else {})
        self.toast_message(i18n.tr("本机 Token 缓存已清除"))
        self._refresh_oauth_status()

    def _current_request(self) -> Dict[str, Any]:
        if not self.store or not self._request_id:
            return {}
        try:
            for node in self.store.walk():
                if isinstance(node, dict) and node.get("id") == self._request_id:
                    return node
        except Exception:  # noqa: BLE001
            pass
        return {}

    def _on_aws_infer(self) -> None:
        from .awsv4_auth import infer_service_region

        url = str(self._current_request().get("url") or "")
        if not url:
            self.toast_message(i18n.tr("找不到当前请求地址"), warn=True)
            return
        service, region = infer_service_region(url)
        self._loading = True
        self.aws_region.setText(region)
        self.aws_service.setText(service)
        self._loading = False
        self.aws_detail.setText(i18n.trf("已推断：region={r} · service={s}", r=region, s=service))
        self.toast_message(i18n.tr("AWS 区域与服务已自动推断"))

    def _on_aws_presign(self) -> None:
        from .awsv4_auth import presign

        node = self._current_request()
        url = str(node.get("url") or "")
        if not url:
            self.toast_message(i18n.tr("找不到当前请求地址"), warn=True)
            return
        signed, err = presign(str(node.get("method") or "GET"), url, 3600,
                              self.dump(), self.store.env_vars() if self.store else {})
        if err:
            self.toast_message(err, warn=True)
            return
        QGuiApplication.clipboard().setText(signed)
        self.aws_detail.setText(i18n.trf("预签名 URL（1 小时，已复制）：{url}",
                                         url=signed[:180] + ("…" if len(signed) > 180 else "")))
        self.toast_message(i18n.tr("预签名 URL 已生成并复制"))

    def toast_message(self, text: str, warn: bool = False) -> None:
        """轻量提示：不依赖主窗口的 toast，状态行就地显示即可。"""
        self.oauth_status.setText(("✕ " if warn else "✓ ") + text)
        self.oauth_status.setStyleSheet(
            f"color: {theme().danger if warn else theme().success}; background: transparent;")

    def _on_change(self) -> None:
        if self._loading:
            return
        if self._type == "jwt":
            self._refresh_jwt()
        elif self._type == "oauth2":
            self._refresh_oauth_status()
        self.changed.emit()

    def load(self, auth: Dict[str, Any], request_id: str = "") -> None:
        self._loading = True
        self._request_id = request_id or ""
        self._type = auth.get("type", "none") or "none"
        if self._type not in dict(AUTH_TYPES):
            self._type = "none"
        self.types.set_current(self._type, emit=False)
        self.stack.set_current(self._type, animate=False)
        self.bearer_token.setText(auth.get("token", ""))
        self.basic_user.setText(auth.get("username", ""))
        self.basic_pass.setText(auth.get("password", ""))
        self.api_key.setText(auth.get("key", ""))
        self.api_value.setText(auth.get("value", ""))
        self.api_add.set_current(auth.get("add_to", "header"), emit=False)
        self.jwt_mode.set_current(auth.get("jwt_mode", "auto"), emit=False)
        self.jwt_pages.set_current(auth.get("jwt_mode", "auto"), animate=False)
        self.jwt_alg.set_current(auth.get("jwt_alg", "HS256"), emit=False)
        self.jwt_payload.setText(auth.get("jwt_payload", ""))
        self.jwt_secret.setText(auth.get("jwt_secret", ""))
        self.jwt_token.setText(auth.get("jwt_token", ""))
        self.oauth_grant.set_current(auth.get("oauth_grant", "client_credentials"), emit=False)
        for attr, key in (
            ("oauth_issuer", "oauth_issuer"),
            ("oauth_auth_url", "oauth_auth_url"), ("oauth_token_url", "oauth_token_url"),
            ("oauth_client_id", "oauth_client_id"),
            ("oauth_client_secret", "oauth_client_secret"), ("oauth_scope", "oauth_scope"),
            ("oauth_username", "oauth_username"), ("oauth_password", "oauth_password"),
            ("oauth_code", "oauth_code"), ("oauth_redirect_uri", "oauth_redirect_uri"),
            ("oauth_code_verifier", "oauth_code_verifier"),
            ("oauth_state", "oauth_state"), ("oauth_state_returned", "oauth_state_returned"),
            ("oauth_access_token", "oauth_access_token"),
            ("oauth_refresh_token", "oauth_refresh_token"),
            ("oauth_token_key", "oauth_token_key"),
        ):
            getattr(self, attr).setText(auth.get(key, ""))
        self.oauth_placement.set_current(auth.get("oauth_token_placement", "header"), emit=False)
        self.oauth_token_auth_method.set_current(
            auth.get("oauth_token_auth_method", "client_secret_post"), emit=False)
        self.aws_access.setText(auth.get("aws_access_key_id", ""))
        self.aws_secret.setText(auth.get("aws_secret_access_key", ""))
        self.aws_session.setText(auth.get("aws_session_token", ""))
        self.aws_region.setText(auth.get("aws_region", "us-east-1"))
        self.aws_service.setText(auth.get("aws_service", "execute-api"))
        self.aws_sign_body.set_current("yes" if auth.get("aws_sign_body", True) else "no",
                                        emit=False)
        self.digest_user.setText(auth.get("digest_username", ""))
        self.digest_pass.setText(auth.get("digest_password", ""))
        self.digest_algorithm.set_current(auth.get("digest_algorithm", "MD5"), emit=False)
        self.digest_qop.set_current(auth.get("digest_qop", "auto"), emit=False)
        self.digest_realm.setText(auth.get("digest_realm", ""))
        self.digest_nonce.setText(auth.get("digest_nonce", ""))
        self.digest_opaque.setText(auth.get("digest_opaque", ""))
        self._on_oauth_grant()
        self._loading = False
        if self._type == "inherit":
            self._refresh_inherit()
        elif self._type == "jwt":
            self._refresh_jwt()

    def dump(self) -> Dict[str, Any]:
        return {
            "type": self._type,
            "token": self.bearer_token.text(),
            "username": self.basic_user.text(),
            "password": self.basic_pass.text(),
            "key": self.api_key.text(),
            "value": self.api_value.text(),
            "add_to": self.api_add.current(),
            "jwt_mode": self.jwt_mode.current(),
            "jwt_alg": self.jwt_alg.current(),
            "jwt_payload": self.jwt_payload.text(),
            "jwt_secret": self.jwt_secret.text(),
            "jwt_token": self.jwt_token.text(),
            "oauth_grant": self.oauth_grant.current(),
            "oauth_issuer": self.oauth_issuer.text(),
            "oauth_auth_url": self.oauth_auth_url.text(),
            "oauth_token_url": self.oauth_token_url.text(),
            "oauth_client_id": self.oauth_client_id.text(),
            "oauth_client_secret": self.oauth_client_secret.text(),
            "oauth_scope": self.oauth_scope.text(),
            "oauth_username": self.oauth_username.text(),
            "oauth_password": self.oauth_password.text(),
            "oauth_code": self.oauth_code.text(),
            "oauth_redirect_uri": self.oauth_redirect_uri.text(),
            "oauth_code_verifier": self.oauth_code_verifier.text(),
            "oauth_state": self.oauth_state.text(),
            "oauth_state_returned": self.oauth_state_returned.text(),
            "oauth_access_token": self.oauth_access_token.text(),
            "oauth_refresh_token": self.oauth_refresh_token.text(),
            "oauth_token_placement": self.oauth_placement.current(),
            "oauth_token_key": self.oauth_token_key.text() or "access_token",
            "oauth_token_auth_method": self.oauth_token_auth_method.current(),
            "oauth_use_refresh": True,
            "aws_access_key_id": self.aws_access.text(),
            "aws_secret_access_key": self.aws_secret.text(),
            "aws_session_token": self.aws_session.text(),
            "aws_region": self.aws_region.text(),
            "aws_service": self.aws_service.text(),
            "aws_sign_body": self.aws_sign_body.current() == "yes",
            "digest_username": self.digest_user.text(),
            "digest_password": self.digest_pass.text(),
            "digest_algorithm": self.digest_algorithm.current(),
            "digest_qop": self.digest_qop.current(),
            "digest_realm": self.digest_realm.text(),
            "digest_nonce": self.digest_nonce.text(),
            "digest_opaque": self.digest_opaque.text(),
        }


class ScriptPage(QWidget):
    """脚本编辑器：JavaScript 代码 + 一键插入的代码片段 + API 速查。

    前置 / 后置各用本类的一份独立实例（由 RequestEditor 分别挂到 pre / post 页），
    页内不再做二次切换 —— 顶层「前置脚本 / 后置脚本」标签本身就是切换。
    编辑器用统一高亮的 CodeView，支持括号补全与缩进；右侧说明用可滚动容器，
    内容超出时只滚动右侧，不会挤出或挡住下方按钮。
    """

    changed = pyqtSignal()

    LANGS = [("javascript", "JavaScript"), ("python", "Python")]

    SNIPPETS = {
        "javascript": [
            ("环境变量：设置一个变量", 'pw.env.set("token", "abc123");'),
            ("环境变量：设置时间戳", 'pw.env.set("ts", String(Date.now()));'),
            ("环境变量：设置随机数", 'pw.env.set("id", String(Math.floor(Math.random() * 10000)));'),
            ("请求：添加一个请求头", 'req.setHeader("X-Trace-Id", "123");'),
            ("控制台：打印一条消息", 'console.log("hello", req.method);'),
        ],
        "python": [
            ("环境变量：设置一个变量", 'pw.env.set("token", "abc123")'),
            ("环境变量：设置时间戳", 'pw.env.set("ts", str(int(time.time() * 1000)))'),
            ("请求：添加一个请求头", 'req.set_header("X-Trace-Id", "123")'),
            ("控制台：打印一条消息", 'print("hello", req.method)'),
        ],
    }

    # 后置脚本专属片段：读响应、取字段、做断言
    POST_SNIPPETS = {
        "javascript": [
            ("响应：打印状态与耗时", 'console.log("status", res.status, "time", res.time + "ms");'),
            ("响应：解析 JSON 并取字段", 'var data = res.json();\nif (data) console.log("keys", Object.keys(data).join(", "));'),
            ("响应：把 token 存进环境", 'var d = res.json();\nif (d && d.token) pw.env.set("token", d.token);'),
            ("断言：状态码为 200", 'test("状态码 200", function () {\n  if (res.status !== 200) throw new Error("got " + res.status);\n});'),
            ("断言：响应包含字段", 'var d = res.json();\ntest("包含 token", function () {\n  if (!d || !d.token) throw new Error("missing token");\n});'),
        ],
        "python": [
            ("响应：打印状态与耗时", 'print("status", res.status, "time", res.time)'),
            ("响应：解析 JSON 并取字段", 'data = res.json()\nprint("keys", list(data) if data else [])'),
            ("响应：把 token 存进环境", 'data = res.json()\nif data and data.get("token"):\n    pw.env.set("token", data["token"])'),
            ("断言：状态码为 200",
             'test("状态码 200", lambda: assert_true(res.status == 200, "got %s" % res.status))'),
            ("断言：响应包含字段",
             'data = res.json()\ntest("包含 token", lambda: assert_true(bool(data and data.get("token")), "missing token"))'),
        ],
    }

    DOCS = {
        "pre_javascript": "前置脚本在请求发送前用 JavaScript 运行。\n"
                          "可修改 req.url、req.headers 和 req.params，或用 pw.env.set() 把值存入当前环境。\n"
                          "console.log() 的输出会出现在响应面板的「控制台」页。",
        "post_javascript": "后置脚本在收到响应后用 JavaScript 运行。\n"
                           "可读取 res.status / res.json()，用 test() 写断言，或用 pw.env.set() 把值存回当前环境。\n"
                           "console.log() 与断言结果都会出现在响应面板的「控制台」页。",
        "pre_python": "前置脚本在请求发送前用 Python 运行。\n"
                      "直接改 req.url / req.method，或用 req.set_header()、pw.env.set()；"
                      "json / re / math / random / hashlib 已内置。\n"
                      "print() 与 console.log() 都会出现在响应面板的「控制台」页。",
        "post_python": "后置脚本在收到响应后用 Python 运行。\n"
                       "可读 res.status、用 res.json()['token'] 取字段，用 assert 或 test() 写断言，"
                       "或用 pw.env.set() 存变量。\n"
                       "print() 与 console.log() 都会出现在响应面板的「控制台」页。",
    }

    def __init__(self, store: Store, kind: str = "pre", parent=None):
        super().__init__(parent)
        self.store = store
        self._loading = False
        self._kind = "post" if kind == "post" else "pre"
        self._lang = "javascript"
        self._codes = {"javascript": "", "python": ""}

        self.code = CodeView(read_only=False, highlight=True, show_gutter=True, wrap=True)
        self.code.set_language("javascript")
        self.code.textChanged.connect(self._on_code_changed)

        editor = Card(radius=9)
        el = QVBoxLayout(editor)
        el.setContentsMargins(0, 6, 0, 6)
        # 语言切换贴着编辑器顶部，一行高，不额外占一整块面板
        lang_row = QHBoxLayout()
        lang_row.setContentsMargins(10, 0, 10, 0)
        lang_row.setSpacing(7)
        lang_row.addWidget(Label("语言", 10.4, theme().text_faint))
        self.lang_tabs = SegmentedTabs(
            self.LANGS, style="pill", current="javascript", height=23,
            pad_h=9, font_size=10.6)
        self.lang_tabs.setToolTip("切换脚本语言，两种语言的代码分别保留。")
        self.lang_tabs.changed.connect(self._set_language)
        lang_row.addWidget(self.lang_tabs)
        lang_row.addStretch(1)
        el.addLayout(lang_row)
        el.addWidget(self.code, 1)

        # 右侧：说明 + 一键插入的代码片段（内容多时自己滚动，不挤压下方）
        self.doc = Label(self._doc_text(), 11.2, theme().text_dim)
        self.doc.setWordWrap(True)
        snippets = QWidget()
        self.snippet_layout = QVBoxLayout(snippets)
        self.snippet_layout.setContentsMargins(0, 0, 0, 0)
        self.snippet_layout.setSpacing(6)
        self._fill_snippets()

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 12, 14, 12)
        sl.setSpacing(10)
        sl.addWidget(self.doc)
        sl.addWidget(Divider())
        sl.addWidget(Label("代码片段", 11.4, theme().text_dim,
                           weight=QFont.Weight.DemiBold))
        sl.addWidget(snippets, 1)
        self.side_scroll = SmoothScrollArea()
        self.side_scroll.setWidget(side)

        body = QHBoxLayout()
        body.setContentsMargins(14, 8, 14, 2)
        body.setSpacing(12)
        body.addWidget(editor, 3)
        body.addWidget(self.side_scroll, 2)

        # 底部：运行状态（细体图标 + 文案）与「试运行」按钮。结果走弹窗，这里只留一行。
        # 状态行与上方编辑器左对齐、紧贴其下沿，不再留一大块空白。
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(15, 15)
        self.status_icon.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status = Label("", 10.5, theme().text_faint)
        # 必须保持一行，否则会把下方按钮整行顶得忽高忽低
        self.status.setWordWrap(False)
        self.status_row = HBox(self.status_icon, self.status, 1, spacing=5)
        self._status_text = ""
        self._status_kind = "ok"
        self.run_btn = Button(
            "试运行", "play", kind="ghost", height=26, padding=11, font_size=11.5,
            tooltip="不联网，只在临时请求上执行当前脚本，查看日志与错误。")
        self.run_btn.clicked.connect(self._run_test)
        tools = HBox(self.status_row, 1, self.run_btn, spacing=8,
                     margins=(14, 0, 0, 0))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(2)
        lay.addLayout(body, 1)
        lay.addWidget(tools)

    def _doc_text(self) -> str:
        return self.DOCS[f"{self._kind}_{self._lang}"]

    def _fill_snippets(self) -> None:
        """按当前语言重建右侧片段按钮；语言切换与界面换肤都会走这里。"""
        while self.snippet_layout.count():
            item = self.snippet_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        items = list(self.SNIPPETS[self._lang])
        if self._kind == "post":
            items = list(self.POST_SNIPPETS[self._lang]) + items[-2:]
        for title, snippet in items:
            b = Button(title, "plus", kind="subtle", height=25, padding=8, font_size=11)
            b.clicked.connect(lambda _c=False, s=snippet: self._insert(s))
            self.snippet_layout.addWidget(b)
        self.snippet_layout.addStretch(1)

    def _set_language(self, lang: str) -> None:
        lang = "python" if lang == "python" else "javascript"
        if lang == self._lang:
            return
        # 先存旧语言的代码，再换入新语言的那份，来回切不丢内容
        self._codes[self._lang] = self.code.toPlainText()
        self._lang = lang
        self._loading = True
        self.code.set_language(lang)
        self.code.setPlainText(self._codes[lang])
        self._loading = False
        self.doc.setText(self._doc_text())
        self._fill_snippets()
        self._clear_status()
        self.changed.emit()

    def _on_code_changed(self) -> None:
        if not self._loading:
            self.changed.emit()

    def _insert(self, snippet: str) -> None:
        """把片段插到**新的一行**：当前行有代码就换行再插，插完再留一行空行。

        以前是直接在光标处插入，粘在 `}` 后面或行中间，粘两次就成一行乱码，
        用户还得手工整理。现在每次点都从独立一行开始。
        """
        from PyQt6.QtGui import QTextCursor

        cur = self.code.textCursor()
        cur.beginEditBlock()
        if self.code.document().characterCount() > 1:
            line_before = cur.block().text()[:cur.positionInBlock()]
            if line_before.strip():
                cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                cur.insertText("\n")
        cur.insertText(snippet)
        if not snippet.endswith("\n"):
            cur.insertText("\n")
        cur.endEditBlock()
        self.code.setTextCursor(cur)
        self.code.ensureCursorVisible()
        self.code.setFocus()

    def _set_status(self, text: str, kind: str = "ok", animate: bool = True) -> None:
        """状态行：细体对号/叉号图标 + 文案，颜色用主题成功/危险色，淡入过渡。"""
        self._status_text = text
        self._status_kind = kind
        ok = kind == "ok"
        color = S(theme().success if ok else theme().danger)
        # 图标走矢量绘制、细笔宽 1.3（不加粗），颜色与文案严格一致
        self.status_icon.setPixmap(
            icons.pixmap("check" if ok else "close", color, 12, 1.3)
            if text else QPixmap())
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; background: transparent;")
        if text and animate:
            from .anim import animations_on

            if animations_on():
                fade_in(self.status_row, 200)

    def _clear_status(self) -> None:
        self._status_text = ""
        self._status_kind = "ok"
        self.status_icon.clear()
        self.status.setText("")
        self.status.setStyleSheet("")

    def set_logs(self, lines: List[str]) -> None:
        """真实请求执行完脚本后的日志由主窗口回填；结果走弹窗，这里不再内联展示。"""
        self._last_logs = list(lines or [])

    def _run_test(self) -> None:
        """试跑：不联网，只在临时请求上执行当前脚本，结果用弹窗一次看清。"""
        from .dialogs import ScriptResultDialog
        from .http_client import Response
        from .scripts import run_script

        source = self.code.toPlainText()
        if not source.strip():
            self._clear_status()
            return
        req = {"method": "GET", "url": "https://example.com", "headers": [],
               "params": [], "cookies": [], "body": {"raw": ""}}
        # 后置脚本要能碰到 res，否则一上来就 ReferenceError；给一份示例响应
        res = None
        if self._kind == "post":
            sample = '{"token": "demo-token", "ok": true}'
            res = Response(status=200, reason="OK", elapsed=42,
                           headers=[("Content-Type", "application/json")],
                           body=sample.encode("utf-8"), size=len(sample),
                           url="https://example.com", content_type="application/json")
        result = run_script(source, self.store, req, res=res, language=self._lang)
        lines = list(result.logs)
        if result.error and not any(l == result.error for l in lines):
            lines.append("✕ " + result.error)
        # 成功只显示「运行成功」，失败显示错误；完整日志进弹窗
        # 传中文原文给 Label（它内部按当前语言 tr），切回中文时才能还原
        self._set_status("运行成功" if result.ok else result.error[:180],
                         "ok" if result.ok else "error")
        dlg = ScriptResultDialog(result.ok, lines, "" if result.ok else result.error, self)
        dlg.exec()

    def load(self, scripts: Dict[str, Any]) -> None:
        data = scripts or {}
        lang = str(data.get(f"{self._kind}_lang") or "javascript").lower()
        if lang not in ("javascript", "python"):
            lang = "javascript"
        self._loading = True
        self._lang = lang
        self._codes = {
            "javascript": str(data.get(self._kind) or ""),
            "python": str(data.get(f"{self._kind}_python") or ""),
        }
        self.lang_tabs.set_current(lang)
        self.code.set_language(lang)
        self.code.setPlainText(self._codes[lang])
        self.doc.setText(self._doc_text())
        self._fill_snippets()
        self._clear_status()
        self._last_logs = []
        self._loading = False

    def dump(self) -> Dict[str, str]:
        """只写自己这一半字段，两边 merge 后就是完整的 scripts dict。"""
        self._codes[self._lang] = self.code.toPlainText()
        return {
            self._kind: self._codes["javascript"],
            f"{self._kind}_python": self._codes["python"],
            f"{self._kind}_lang": self._lang,
        }

    def refresh_theme(self) -> None:
        """语言/主题切换后重译说明与片段，并按当前主题刷新状态图标颜色。"""
        self.doc.setText(self._doc_text())
        self._fill_snippets()
        self.run_btn.setToolTip(i18n.tr("不联网，只在临时请求上执行当前脚本，查看日志与错误。"))
        if self._status_text:
            # 文案走 Label 的 i18n_src_text 机制自动重译；这里只刷新图标与语义色
            self._set_status(self._status_text, self._status_kind, animate=False)


# ---------------------------------------------------------------- 主编辑器


class RequestEditor(QWidget):
    changed = pyqtSignal()
    # 脚本属于「辅助编辑」：改脚本不该把上一次真实请求的响应作废。
    # 单独发一个信号，让主窗口只标记 dirty / 落盘，不清空响应区。
    scriptsChanged = pyqtSignal()
    sendRequested = pyqtSignal()
    cancelRequested = pyqtSignal()
    wsSendRequested = pyqtSignal(str, bool)      # WebSocket 消息（内容, 是否二进制）
    sioSendRequested = pyqtSignal(str, str, bool)  # Socket.IO（事件, 载荷, 是否等 ACK）
    saveRequested = pyqtSignal()
    codeRequested = pyqtSignal()
    copyCurlRequested = pyqtSignal()
    deleteRequested = pyqtSignal()
    mockRequested = pyqtSignal()
    mockizeRequested = pyqtSignal()
    duplicateRequested = pyqtSignal()
    notify = pyqtSignal(str)            # 底部浮动提示
    aiSettingsRequested = pyqtSignal()  # 没配 Key：直接打开设置 → AI

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.request: Dict[str, Any] = {}
        self._loading = False
        self._syncing = False

        self.urlbar = UrlBar(store=self.store)
        self.urlbar.sendRequested.connect(self.sendRequested.emit)
        self.urlbar.cancelRequested.connect(self.cancelRequested.emit)
        self.urlbar.saveRequested.connect(self.saveRequested.emit)
        self.urlbar.codeRequested.connect(self.codeRequested.emit)
        self.urlbar.mockRequested.connect(self.mockRequested.emit)
        self.urlbar.mockizeRequested.connect(self.mockizeRequested.emit)
        self.urlbar.duplicateRequested.connect(self.duplicateRequested.emit)
        self.urlbar.moreRequested.connect(self._on_more)
        self.urlbar.methodChanged.connect(self._on_method)
        self.urlbar.urlChanged.connect(self._on_url)
        self.node_btn = self.urlbar.node_btn

        # 请求页签同样自适应：面板窄了把放不下的收进「…」，而不是把最后一个
        # 「后置脚本」硬裁在右边（之前直接消失，用户以为页签没了）。
        self.tabs = SegmentedTabs(
            HTTP_TABS, style="underline", height=32, pad_h=10, font_size=12.2,
            adaptive=True)
        self.tabs.changed.connect(self._on_tab)
        self.tabs.more_clicked.connect(self._on_tabs_more)
        self._tabs_menu: Optional[ChoiceMenu] = None
        self.count_label = Label("", 10.5, theme().text_faint, mono_font=True)
        # 用 (widget, stretch) 形式：addWidget 不带伸缩因子，标签只会拿到
        # sizeHint（160px）就被判定放不下，明明有整行宽度也只剩一个页签。
        tools = HBox((self.tabs, 1), spacing=8)

        self.params = KVEditor("参数名", "值", empty_hint="添加查询参数", with_types=True,
                               allow_file=False)
        self.params.changed.connect(self._on_params)
        self.paste_btn = Button("粘贴", None, kind="ghost", height=24, padding=8, font_size=11.5,
                                tooltip="从剪贴板批量导入：a=1&b=2 / 多行 key: value / JSON")
        self.paste_btn.clicked.connect(self._paste_params)
        self.params_bulk_btn = Button("批量编辑", None, kind="ghost", height=24, padding=8, font_size=11.5,
                                      tooltip="以 key: value 文本一次编辑全部参数")
        self.params_bulk_btn.clicked.connect(self._toggle_params_bulk)
        self.params_tools = HBox(1, self.paste_btn, self.params_bulk_btn, spacing=4)
        self.params_preview = ElideLabel("", 10.5, theme().text_faint, mono_font=True,
                                         mode=Qt.TextElideMode.ElideMiddle)
        self.params_preview.setToolTip("最终发送的完整地址")

        self.headers = KVEditor("Header", "值", suggestions=COMMON_HEADERS, empty_hint="添加请求头")
        self.headers.changed.connect(self._on_headers)
        self.bulk_btn = Button("批量编辑", None, kind="ghost", height=24, padding=8, font_size=11.5)
        self.bulk_btn.clicked.connect(self._toggle_bulk)
        self.quick_ct = Button("Content-Type: JSON", None, kind="ghost", height=24, padding=8, font_size=11.5)
        self.quick_ct.clicked.connect(self._quick_content_type)
        self.headers_tools = HBox(1, self.quick_ct, self.bulk_btn, spacing=4)

        self.body = BodyPage()
        self.body.changed.connect(self._on_body)
        self.body.aiRequested.connect(self._ai_fill_body)
        self.auth = AuthPage(store=self.store)
        self.auth.changed.connect(self._on_auth)
        self.scripts_pre = ScriptPage(store=self.store, kind="pre")
        self.scripts_pre.changed.connect(self._on_scripts)
        self.scripts_post = ScriptPage(store=self.store, kind="post")
        self.scripts_post.changed.connect(self._on_scripts)
        from .ws_panel import WsComposer
        from .sio_panel import SioComposer

        self.ws = WsComposer()
        self.ws.changed.connect(self._on_ws_changed)
        self.ws.sendRequested.connect(self.wsSendRequested.emit)
        self.ws.headersToggled.connect(self._open_ws_headers)
        self.sio = SioComposer()
        self.sio.changed.connect(self._on_sio_changed)
        self.sio.sendRequested.connect(self.sioSendRequested.emit)
        self.sio.headersToggled.connect(self._open_ws_headers)
        from .sse_panel import SseComposer

        self.sse = SseComposer()
        self.sse.changed.connect(self._on_sse_changed)
        self.sse.headersToggled.connect(self._open_ws_headers)
        self._mode = "http"

        # WebSocket 是独立的一套界面：只有「消息 + 握手头」两件事，
        # 不掺 HTTP 的参数 / 请求体 / 认证 / 脚本那些页签。
        # 握手头是低频配置，走弹层编辑（WsHeadersPopup），不占请求区的高度。
        self._ws_headers_popup = None

        # Cookie 单独一栏：发送时拼成 Cookie 头，也能一键把响应里的 Set-Cookie 收进来
        self.cookies = KVEditor("Cookie 名", "值", empty_hint="添加 Cookie")
        self.cookies.changed.connect(self._on_cookies)
        self.cookie_import = Button("从响应导入", "download", kind="ghost", height=24,
                                    padding=8, font_size=11.5,
                                    tooltip="把上一次响应里的 Set-Cookie 收进这张表")
        self.cookie_import.clicked.connect(self._import_cookies)
        self.cookie_import.setEnabled(False)
        self.cookies_hint = Label("发送时合并成 Cookie 请求头", 10.5, theme().text_faint,
                                  mono_font=True)
        self.cookies_tools = HBox(1, self.cookies_hint, self.cookie_import, spacing=8)
        self._last_cookies: List[Dict[str, Any]] = []

        self.pages = FadeStack()
        self.pages.add("params", self._scroll_page(
            self._wrap(self.params, self.params_tools, self.params_preview)))
        self.pages.add("body", self._scroll_page(self.body))
        self.pages.add("headers", self._scroll_page(
            self._wrap(self.headers, self.headers_tools)))
        self.pages.add("cookies", self._scroll_page(
            self._wrap(self.cookies, self.cookies_tools)))
        self.pages.add("auth", self._scroll_page(self.auth))
        self.pages.add("pre", self.scripts_pre)
        self.pages.add("post", self.scripts_post)
        self.pages.set_current("params", animate=False)

        self.ws_page = QWidget()
        wl = QVBoxLayout(self.ws_page)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        wl.addWidget(self.ws, 1)
        self.ws_page.hide()

        self.sio_page = QWidget()
        sl = QVBoxLayout(self.sio_page)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        sl.addWidget(self.sio, 1)
        self.sio_page.hide()

        self.sse_page = QWidget()
        ssl = QVBoxLayout(self.sse_page)
        ssl.setContentsMargins(0, 0, 0, 0)
        ssl.setSpacing(0)
        ssl.addWidget(self.sse, 1)
        self.sse_page.hide()

        self.head = QWidget()
        hl = QHBoxLayout(self.head)
        hl.setContentsMargins(14, 4, 10, 0)
        hl.setSpacing(0)
        hl.addWidget(tools, 1)
        self.head_div = Divider()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.urlbar)
        lay.addSpacing(2)
        lay.addWidget(self.head)
        lay.addWidget(self.head_div)
        lay.addWidget(self.pages, 1)
        lay.addWidget(self.ws_page, 1)
        lay.addWidget(self.sio_page, 1)
        lay.addWidget(self.sse_page, 1)
        self.urlbar.refresh_node()

    def refresh_node(self) -> None:
        self.urlbar.refresh_node()

    def _wrap(self, editor: QWidget, tools: QWidget, footer: Optional[QWidget] = None) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 6, 14, 10)
        lay.setSpacing(4)
        lay.addWidget(tools, 0)
        lay.addWidget(editor, 1)
        if footer is not None:
            lay.addWidget(footer, 0)
        return w

    @staticmethod
    def _scroll_page(widget: QWidget) -> QWidget:
        """统一的可滚动页容器：内容高度超出请求区时自己出滚动条，不再被裁掉。

        KVEditor / CodeView 内部已有自己的滚动区，minimumSizeHint 很小，
        套上这层后不会多出第二根滚动条；Auth 这类固定高度表单超出时会自动出现。
        """
        sc = SmoothScrollArea()
        sc.setWidget(widget)
        return sc

    # -------------------------------------------------- 加载 / 同步
    def load(self, request: Dict[str, Any]) -> None:
        # try/finally：任何一行数据有问题都不能把 _loading 卡在 True，
        # 否则之后所有编辑都不再回写请求、界面看起来「点什么都不动」。
        self._loading = True
        self.request = request
        try:
            self.urlbar.set_method(request.get("method", "GET"))
            self._set_mode(request.get("method", "GET"), animate=False)
            self.urlbar.set_url(request.get("url", ""))
            self.params.set_rows(request.get("params", []))
            self.headers.set_rows(request.get("headers", []))
            self.cookies.set_rows(request.get("cookies", []))
            self.body.load(request.get("body", {}))
            self.auth.load(request.get("auth", {}), request.get("id", ""))
            # 只给对应协议的编辑器补默认值：全都 load 一遍会让普通 HTTP 请求
            # 也长出一份 ws / sio / sse 配置，导出时被误认成实时请求。
            method = (request.get("method") or "").upper()
            if method == WS_METHOD:
                self.ws.load(request)
            elif method == SIO_METHOD:
                self.sio.load(request)
            elif method == SSE_METHOD:
                self.sse.load(request)
            scripts = request.get("scripts", {}) or {}
            self.scripts_pre.load(scripts)
            self.scripts_post.load(scripts)
        finally:
            self._loading = False
        self._refresh_counts()
        self.pages.set_current(self.tabs.current(), animate=False)

    def _set_mode(self, method: str, animate: bool = True) -> None:
        """HTTP / WebSocket / Socket.IO：三套完全独立的界面，只切显示的那一页。

        实时协议没有请求体、查询参数、后置脚本，把 HTTP 那些页签摆在那里只会
        让人以为能用 —— 所以整块换掉，不做「半套」。
        """
        # 地址栏每次 load 都重算，否则新开的实时标签还显示「发送」
        self.urlbar._on_method_mode(method)
        upper = (method or "").upper()
        mode = ("ws" if upper == WS_METHOD else
                "sio" if upper == SIO_METHOD else
                "sse" if upper == SSE_METHOD else "http")
        if mode != self._mode:
            self._mode = mode
            if mode == "http":
                self.tabs.set_items(HTTP_TABS, current="params")
                self.pages.set_current("params", animate=animate)
        realtime = mode != "http"
        self.head.setVisible(not realtime)
        self.head_div.setVisible(not realtime)
        self.pages.setVisible(not realtime)
        self.ws_page.setVisible(mode == "ws")
        self.sio_page.setVisible(mode == "sio")
        self.sse_page.setVisible(mode == "sse")
        if not self._loading:
            self._refresh_counts()

    def is_ws(self) -> bool:
        """是否实时协议页（WebSocket 或 Socket.IO）；保留旧调用名。"""
        return self._mode != "http"

    def is_sio(self) -> bool:
        return self._mode == "sio"

    def is_sse(self) -> bool:
        return self._mode == "sse"

    def set_ws_state(self, state: str) -> None:
        self.urlbar.set_ws_state(state)
        composer = (self.sse if self._mode == "sse"
                    else self.sio if self._mode == "sio" else self.ws)
        composer.set_connected(state == "open")

    def _sync_request(self, *, script_only: bool = False) -> None:
        if self._loading or self._syncing or not self.request:
            return
        self.request["method"] = self.urlbar.method.method()
        self.request["url"] = self.urlbar.url_text()
        if self._mode == "http":
            self.request["params"] = self.params.rows()
            # 实时协议的握手头是弹层直接写进 request 的，这里不要去覆盖它
            self.request["headers"] = self.headers.rows()
        self.request["cookies"] = self.cookies.rows()
        self.request["body"] = self.body.dump()
        self.request["auth"] = self.auth.dump()
        if self._mode == "sio":
            self.sio.dump(self.request)
        elif self._mode == "sse":
            self.sse.dump(self.request)
        elif self._mode == "ws":
            self.ws.dump(self.request)
        scripts = {}
        scripts.update(self.scripts_pre.dump())
        scripts.update(self.scripts_post.dump())
        self.request["scripts"] = scripts
        if not self.request.get("name") or self.request.get("name") == "Untitled Request":
            self._auto_name()
        self._refresh_counts()
        # 脚本改动只更新数据与脏标记，不能让旁边正在看的响应被 show_stale 清掉。
        if script_only:
            self.scriptsChanged.emit()
        else:
            self.changed.emit()

    def _final_url(self, params: Optional[List[Dict]] = None) -> str:
        """把 base URL 与启用的查询参数拼成最终地址（与发送时同一套算法，并解析环境变量）。

        params=None 时用 HTTP 参数表；实时协议传自己的参数表，避免混用两套数据。
        """
        from urllib.parse import urlencode

        env = self.store.env_vars() if self.store else {}
        raw = resolve_vars(self.urlbar.url_text().strip(), env)
        if not raw:
            return ""
        if "://" not in raw:
            raw = "http://" + raw
        rows = self.params.rows() if params is None else params
        pairs = [(resolve_vars(str(r["key"]), env), resolve_vars(str(r.get("value", "")), env))
                 for r in rows if r.get("enabled", True) and r.get("key")]
        if not pairs:
            return raw
        sep = "&" if "?" in raw else "?"
        return raw + sep + urlencode(pairs)

    def _auto_name(self) -> None:
        if not self.store.settings.get("auto_name", True):
            return
        url = self.urlbar.url_text().strip()
        if not url:
            return
        path = url.split("?")[0].split("://")[-1]
        parts = [p for p in path.split("/") if p]
        name = parts[-1] if parts else (parts[0] if parts else "Untitled Request")
        if not self.request.get("name") or self.request.get("name") in ("Untitled Request", ""):
            self.request["name"] = name[:40]

    def _refresh_counts(self) -> None:
        if self._mode in ("ws", "sio"):
            headers = len(self.request.get("headers") or [])
            composer = self.ws if self._mode == "ws" else self.sio
            composer.set_headers_count(headers)
            self.count_label.setText("")
            # 参数页底部的最终地址预览：实时协议与 HTTP 用同一套拼接算法。
            rows = composer.params.rows()
            final = self._final_url(rows)
            preview = final if rows else ""
            self.params_preview.setText(preview)
            self.params_preview.setToolTip(preview or "")
            composer.set_params_preview(preview)
            return
        for key in ("body", "cookies", "post", "auth", "pre"):
            if self.tabs.has(key):
                self.tabs.set_badge(key, 0)
        self.tabs.set_badge("params", len(self.params.rows()))
        self.tabs.set_badge("headers", len(self.headers.rows()))
        cookies = len(self.cookies.rows())
        if self.tabs.has("cookies"):
            self.tabs.set_badge("cookies", cookies)
        # 不再 dump 整段请求体：只问「有没有内容」，避免每次按键复制一遍大正文
        self.tabs.set_badge("body", 1 if self.body.has_content() else 0)
        self.tabs.set_badge("auth", 1 if self.auth.dump().get("type") != "none" else 0)
        pre_scripts = self.scripts_pre.dump() if hasattr(self, "scripts_pre") else {}
        post_scripts = self.scripts_post.dump() if hasattr(self, "scripts_post") else {}
        # 徽标看真正会执行的那份：切到 Python 后，JS 里留的代码不算数
        pre_script = script_parts(pre_scripts, "pre")[0].strip()
        post_script = script_parts(post_scripts, "post")[0].strip()
        self.tabs.set_badge("pre", 1 if pre_script else 0)
        if self.tabs.has("post"):
            self.tabs.set_badge("post", 1 if post_script else 0)
        p = len(self.params.rows())
        h = len(self.headers.rows())
        self.count_label.setText(i18n.trf("{p} 参数 · {h} 请求头", p=p, h=h) if (p or h) else "")
        if cookies:
            self.cookies_hint.setText(i18n.trf("{n} 条 Cookie 会合并成 Cookie 请求头", n=cookies))
        else:
            self.cookies_hint.setText(i18n.tr("发送时合并成 Cookie 请求头"))
        self.cookie_import.setVisible(bool(self._last_cookies))
        final = self._final_url()
        self.params_preview.setText(final if p else "")
        self.params_preview.setToolTip(final or "")

    # -------------------------------------------------- Cookie
    def set_last_cookies(self, cookies: List[Dict[str, Any]]) -> None:
        """主窗口收到响应后把 Set-Cookie 递进来，供「从响应导入」使用。"""
        self._last_cookies = list(cookies or [])
        self.cookie_import.setEnabled(bool(self._last_cookies))
        self.cookie_import.setVisible(bool(self._last_cookies))
        self.cookie_import.setToolTip(
            i18n.trf("把上一次响应的 {n} 条 Set-Cookie 收进这张表", n=len(self._last_cookies))
            if self._last_cookies else i18n.tr("上一次响应没有 Set-Cookie"))

    def _import_cookies(self) -> None:
        if not self._last_cookies:
            return
        rows = self.cookies.rows()
        known = {(r.get("key"), r.get("value")) for r in rows}
        added = 0
        for c in self._last_cookies:
            name = str(c.get("name") or "").strip()
            if not name or (name, c.get("value", "")) in known:
                continue
            rows.append({"key": name, "value": str(c.get("value", "")), "enabled": True})
            known.add((name, c.get("value", "")))
            added += 1
        if not added:
            return
        self._syncing = True
        self.cookies.set_rows(rows)
        self._syncing = False
        self._refresh_counts()
        self._sync_request()

    # -------------------------------------------------- 事件
    def _on_method(self, method: str) -> None:
        if self._loading:
            return
        self._set_mode(method)
        self._sync_request()

    def _open_ws_headers(self) -> None:
        """弹层里编辑握手请求头，改一条写一条，关掉即生效。"""
        from .ws_panel import WsHeadersPopup

        if self._ws_headers_popup is not None:
            try:
                self._ws_headers_popup.close()
            except RuntimeError:
                pass
        popup = WsHeadersPopup(self, self.request.get("headers") or [])
        popup.changed.connect(self._on_ws_headers_rows)
        composer = self.sio if self._mode == "sio" else self.ws
        btn = composer.headers_btn
        popup.popup_at(btn.mapToGlobal(QPoint(btn.width() - popup.width() + 8,
                                             btn.height() + 8)))
        self._ws_headers_popup = popup

    def _on_ws_headers_rows(self, rows) -> None:
        self.request["headers"] = list(rows or [])
        # HTTP 那一侧的请求头表跟着同步：导出、发请求用的是同一份数据
        self.headers.set_rows(self.request["headers"])
        composer = self.sio if self._mode == "sio" else self.ws
        composer.set_headers_count(len(self.request["headers"]))
        if not self._loading:
            self._sync_request()

    def _on_ws_changed(self) -> None:
        self._refresh_counts()
        if not self._loading:
            self._sync_request()

    def _on_sio_changed(self) -> None:
        self._refresh_counts()
        if not self._loading:
            self._sync_request()

    def _on_sse_changed(self) -> None:
        self._refresh_counts()
        if not self._loading:
            self._sync_request()

    def _on_url(self, _text: str) -> None:
        if self._loading or self._syncing:
            return
        # URL 里带了 ?a=1&b=2 时自动拆进参数表，URL 只留 base —— 保证只有一个数据源，
        # 不会再出现「参数表是空的、请求却还带着旧参数」的幽灵参数
        self._absorb_query()
        self._sync_request()

    def _absorb_query(self) -> None:
        text = self.urlbar.url_text()
        if "?" not in text:
            return
        base, _, _qs = text.partition("?")
        query = QUrlQuery(QUrl(text))
        # 实时协议用自己「参数」页的表，HTTP 用 HTTP 的表，互不串数据
        editor = self.params if self._mode == "http" else (
            self.ws.params if self._mode == "ws" else self.sio.params)
        rows = editor.rows()
        known = {(r.get("key"), r.get("value")) for r in rows}
        added = 0
        for key, value in query.queryItems():
            if (key, value) in known:
                continue
            rows.append({"key": key, "value": value, "enabled": True, "type": "auto"})
            known.add((key, value))
            added += 1
        if not added:
            self.urlbar.set_url(base)
            return
        self._syncing = True
        editor.set_rows(rows)
        self._syncing = False
        self.urlbar.set_url(base)
        self._refresh_counts()

    def _paste_params(self) -> None:
        from PyQt6.QtWidgets import QApplication

        text = QApplication.clipboard().text()
        if not text.strip():
            return
        self._syncing = True
        ok = self.params.paste_text(text)
        self._syncing = False
        if ok:
            self._refresh_counts()
            self._sync_request()

    def _on_params(self) -> None:
        self._refresh_counts()
        if not self._loading:
            self._sync_request()

    def _on_headers(self) -> None:
        self._refresh_counts()
        if not self._loading:
            self._sync_request()

    def _on_body(self) -> None:
        self._refresh_counts()
        if not self._loading:
            self._sync_request()

    # -------------------------------------------------- AI 生成请求体
    def _ai_fill_body(self) -> None:
        """按字段名生成 JSON：有字段用字段，没字段就按接口用途自己设计。

        边生成边写进编辑器（打字机效果），生成完自动格式化成缩进 JSON。
        """
        from . import ai as ai_mod

        cfg = ai_mod.config(self.store)
        ok, why = ai_mod.ready(cfg)
        if not ok:
            self.notify.emit(why)
            self.aiSettingsRequested.emit()
            return
        text = self.body.code.toPlainText()
        keys = ai_mod.json_keys(text)
        if not keys:
            keys = [str(r.get("key")) for r in self.params.rows() if r.get("key")]
        msgs = ai_mod.messages_for_json(
            keys, self._current_method(), self.urlbar.url_text(), existing=text)

        self._ai_orig = text
        self._ai_buf = ""
        self._ai_last = 0.0
        self.body.ai_btn.setEnabled(False)
        self.body.ai_btn.setText("生成中…")
        self.body.code.setPlainText("")
        self._ai_chat = ai_mod.start(
            msgs, cfg=cfg, max_tokens=900, temperature=0.5,
            on_chunk=self._ai_on_chunk, on_done=self._ai_on_done,
            on_error=self._ai_on_error,
        )

    def _current_method(self) -> str:
        try:
            return str(self.request.get("method") or "GET")
        except Exception:  # noqa: BLE001
            return "GET"

    def _ai_on_chunk(self, piece: str) -> None:
        self._ai_buf += piece
        # 节流：每 60ms 才刷一次编辑器，避免逐字重排 + 重高亮把界面拖卡
        import time as _time

        now = _time.perf_counter()
        if now - getattr(self, "_ai_last", 0.0) > 0.06:
            self._ai_last = now
            self.body.code.setPlainText(self._ai_buf)

    def _ai_on_done(self, _full: str) -> None:
        from . import ai as ai_mod

        self.body.ai_btn.setEnabled(True)
        self.body.ai_btn.setText("AI 生成")
        raw = ai_mod.clean_json(getattr(self, "_ai_buf", ""))
        pretty = raw
        valid = False
        try:
            pretty = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
            valid = True
        except Exception:  # noqa: BLE001
            pass
        self.body.code.setPlainText(pretty)
        self.body.changed.emit()
        if not pretty.strip():
            self.notify.emit("生成内容为空，再试一次")
        elif not valid:
            # 思考型模型偶尔被 max_tokens 截断：内容照留，但明确告诉用户
            self.notify.emit("生成的 JSON 不完整，再点一次或加个字段描述")
        else:
            self.notify.emit("已生成请求体，可以再改")

    def _ai_on_error(self, message: str) -> None:
        self.body.ai_btn.setEnabled(True)
        self.body.ai_btn.setText("AI 生成")
        # 失败时把原来的内容还回去，别让用户白丢一段请求体
        self.body.code.setPlainText(getattr(self, "_ai_orig", ""))
        self.notify.emit(message)

    def _on_auth(self) -> None:
        self._refresh_counts()
        if not self._loading:
            self._sync_request()

    def _on_cookies(self) -> None:
        self._refresh_counts()
        if not self._loading:
            self._sync_request()

    def _on_scripts(self) -> None:
        if not self._loading:
            self._sync_request(script_only=True)

    def _on_tab(self, key: str) -> None:
        # 模式切换后旧页签可能已经不在当前集合里：只切确实存在的页
        if key in getattr(self.pages, "_pages", {}):
            self.pages.set_current(key)

    def _toggle_bulk(self) -> None:
        self.headers.set_bulk(not self.headers.is_bulk())
        self.bulk_btn.setText("退出批量" if self.headers.is_bulk() else "批量编辑")

    def _toggle_params_bulk(self) -> None:
        self.params.set_bulk(not self.params.is_bulk())
        self.params_bulk_btn.setText("退出批量" if self.params.is_bulk() else "批量编辑")

    def _quick_content_type(self) -> None:
        rows = self.headers.rows()
        for row in rows:
            if row["key"].lower() == "content-type":
                row["value"] = "application/json"
                self.headers.set_rows(rows)
                return
        rows.append({"key": "Content-Type", "value": "application/json", "enabled": True})
        self.headers.set_rows(rows)

    def _on_tabs_more(self, global_pos) -> None:
        popup_hidden_tabs(self, "_tabs_menu", self.tabs, global_pos, width=182)

    def _on_more(self, anchor: QWidget) -> None:
        t = theme()
        menu = Menu(self)
        act_code = menu.addAction(icons.icon("code", t.text, 14), "生成代码片段  ⌘⇧C")
        act_curl = menu.addAction(icons.icon("book", t.text, 14), "复制为 cURL")
        menu.addSeparator()
        # 一键 Mock 和 Mock 服务是一家人，收进这里比在地址栏再占一颗图标清爽。
        # 名字说清楚「会生成一条路由」，比「一键 Mock」这种口号更知道点下去发生什么。
        act_mockize = menu.addAction(icons.icon("layers", t.text, 14),
                                     "生成 Mock 路由")
        act_mock = menu.addAction(icons.icon("grid", t.text, 14), "Mock 服务…")
        menu.addSeparator()
        act_dup = menu.addAction(icons.icon("copy", t.text, 14), "复制请求")
        act_del = menu.addAction(icons.icon("trash", t.danger, 14), "删除请求")
        chosen = menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        if chosen is act_code:
            self.codeRequested.emit()
        elif chosen is act_curl:
            self.copyCurlRequested.emit()
        elif chosen is act_mockize:
            self.mockizeRequested.emit()
        elif chosen is act_mock:
            self.mockRequested.emit()
        elif chosen is act_dup:
            self.duplicateRequested.emit()
        elif chosen is act_del:
            self.deleteRequested.emit()

    def set_busy(self, busy: bool) -> None:
        self.urlbar.set_busy(busy)

    def focus_url(self) -> None:
        self.urlbar.focus_url()
