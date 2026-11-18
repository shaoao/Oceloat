"""请求编辑器：URL 栏 + 参数 / 请求头 / 请求体 / 认证 四个编辑面板。"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import (QPoint, QPointF, QRectF, QSize, Qt, QTimer,
                          QUrl, QUrlQuery, pyqtSignal)
from PyQt6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QPainter,
                         QPen, QPixmap)
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
from .store import BODY_CONTENT_TYPES, Store, kv, resolve_vars
from .anim import running as _anim_running, stop as _anim_stop
from .theme import C, S, method_color, font, mono, theme
from .widgets import (
    Button,
    Card,
    Divider,
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
REALTIME_METHODS = (WS_METHOD, SIO_METHOD)

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
              ("basic", "Basic"), ("apikey", "API Key"), ("jwt", "JWT")]


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
        """WebSocket 请求的方法是固定的：不弹下拉、不画箭头，看起来就是个标识。"""
        self._locked = bool(locked)
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
        self._ws_mode = realtime
        i18n.placeholder(
            self.url,
            ("ws:// 或 wss:// 地址，例如 ws://localhost:3000/socket.io" if sio
             else "ws:// 或 wss:// 地址，例如 wss://echo.websocket.org")
            if realtime else "输入请求地址，例如 https://httpbin.org/get")
        self.url.setToolTip("" if not realtime else i18n.tr(
            "支持 ws:// wss://；直接粘 http(s) 地址会自动补全 Socket.IO 路径")
            if sio else i18n.tr("支持 ws:// wss://；直接粘 http(s) 地址会自动改写"))
        self.method.set_locked(realtime)
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
            self.send_btn.setText("断开")
            self.send_btn.set_icon("stop")
            self.send_btn.set_kind("subtle")
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
                               self.format_btn, self.minify_btn, spacing=4)

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

        self.types = SegmentedTabs([(k, l) for k, l in AUTH_TYPES], style="pill", height=28,
                                   font_size=12, pad_h=11)
        self.types.changed.connect(self._on_type)

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

        self.stack = FadeStack()
        self.stack.add("none", self.none_box)
        self.stack.add("inherit", self.inherit_box)
        self.stack.add("bearer", self.bearer_box)
        self.stack.add("basic", self.basic_box)
        self.stack.add("apikey", self.api_box)
        self.stack.add("jwt", self.jwt_box)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(10)
        lay.addWidget(self.types)
        lay.addWidget(self.stack, 1)

    def _field(self, placeholder: str, ph: str = "", password: bool = False) -> QLineEdit:
        e = QLineEdit()
        e.setObjectName("Field")
        e.setPlaceholderText(ph or placeholder)
        e.setFont(mono(11.8))
        e.setFixedHeight(30)
        e.setMinimumWidth(260)
        if password:
            e.setEchoMode(QLineEdit.EchoMode.Password)
        e.textChanged.connect(self._on_change)
        return e

    def _group(self, title: str, desc: str, *widgets) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(9)
        head = VBox(Label(title, 12.5, theme().text, weight=QFont.Weight.DemiBold),
                    Label(desc, 11.5, theme().text_faint), spacing=3)
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
        if not self._loading:
            self.changed.emit()

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

    def _on_change(self) -> None:
        if self._loading:
            return
        if self._type == "jwt":
            self._refresh_jwt()
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
        }


class ScriptPage(QWidget):
    """脚本编辑器：JavaScript 代码 + 一键插入的代码片段 + API 速查。

    前置 / 后置各用本类的一份独立实例（由 RequestEditor 分别挂到 pre / post 页），
    页内不再做二次切换 —— 顶层「前置脚本 / 后置脚本」标签本身就是切换。
    编辑器用统一高亮的 CodeView，支持括号补全与缩进；右侧说明用可滚动容器，
    内容超出时只滚动右侧，不会挤出或挡住下方按钮。
    """

    changed = pyqtSignal()

    SNIPPETS = [
        ("环境变量：设置一个变量", 'pw.env.set("token", "abc123");'),
        ("环境变量：设置时间戳", 'pw.env.set("ts", String(Date.now()));'),
        ("环境变量：设置随机数", 'pw.env.set("id", String(Math.floor(Math.random() * 10000)));'),
        ("请求：添加一个请求头", 'req.setHeader("X-Trace-Id", "123");'),
        ("控制台：打印一条消息", 'console.log("hello", req.method);'),
    ]

    # 后置脚本专属片段：读响应、取字段、做断言
    POST_SNIPPETS = [
        ("响应：打印状态与耗时", 'console.log("status", res.status, "time", res.time + "ms");'),
        ("响应：解析 JSON 并取字段", 'var data = res.json();\nif (data) console.log("keys", Object.keys(data).join(", "));'),
        ("响应：把 token 存进环境", 'var d = res.json();\nif (d && d.token) pw.env.set("token", d.token);'),
        ("断言：状态码为 200", 'test("状态码 200", function () {\n  if (res.status !== 200) throw new Error("got " + res.status);\n});'),
        ("断言：响应包含字段", 'var d = res.json();\ntest("包含 token", function () {\n  if (!d || !d.token) throw new Error("missing token");\n});'),
    ]

    DOCS = {
        "pre": "前置脚本在请求发送前用 JavaScript 运行。\n"
               "可修改 req.url、req.headers 和 req.params，或用 pw.env.set() 把值存入当前环境。\n"
               "console.log() 的输出会出现在响应面板的「控制台」页。",
        "post": "后置脚本在收到响应后用 JavaScript 运行。\n"
                "可读取 res.status / res.json()，用 test() 写断言，或用 pw.env.set() 把值存回当前环境。\n"
                "console.log() 与断言结果都会出现在响应面板的「控制台」页。",
    }

    def __init__(self, store: Store, kind: str = "pre", parent=None):
        super().__init__(parent)
        self.store = store
        self._loading = False
        self._kind = "post" if kind == "post" else "pre"

        self.code = CodeView(read_only=False, highlight=True, show_gutter=True, wrap=True)
        self.code.set_language("javascript")
        self.code.textChanged.connect(self._on_code_changed)

        editor = Card(radius=9)
        el = QVBoxLayout(editor)
        el.setContentsMargins(0, 6, 0, 6)
        el.addWidget(self.code, 1)

        # 右侧：说明 + 一键插入的代码片段（内容多时自己滚动，不挤压下方）
        self.doc = Label(self.DOCS[self._kind], 11.2, theme().text_dim)
        self.doc.setWordWrap(True)
        snippets = QWidget()
        sh = QVBoxLayout(snippets)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(6)
        items = list(self.SNIPPETS)
        if self._kind == "post":
            items = list(self.POST_SNIPPETS) + items[-2:]
        for title, snippet in items:
            b = Button(title, "plus", kind="subtle", height=25, padding=8, font_size=11)
            b.clicked.connect(lambda _c=False, s=snippet: self._insert(s))
            sh.addWidget(b)
        sh.addStretch(1)

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
        result = run_script(source, self.store, req, res=res)
        lines = list(result.logs)
        if result.error and not any(l == result.error for l in lines):
            lines.append("✕ " + result.error)
        # 成功只显示「运行成功」，失败显示错误；完整日志进弹窗
        # 传中文原文给 Label（它内部按当前语言 tr），切回中文时才能还原
        self._set_status("运行成功" if result.ok else result.error[:180],
                         "ok" if result.ok else "error")
        dlg = ScriptResultDialog(result.ok, lines, "" if result.ok else result.error, self)
        dlg.exec()

    @property
    def _drafts(self) -> Dict[str, str]:
        if not hasattr(self, "_script_drafts"):
            self._script_drafts: Dict[str, str] = {"pre": "", "post": ""}
        return self._script_drafts

    def load(self, scripts: Dict[str, Any]) -> None:
        self._loading = True
        self._script_drafts = {
            "pre": str((scripts or {}).get("pre") or ""),
            "post": str((scripts or {}).get("post") or ""),
        }
        self.code.setPlainText(self._script_drafts[self._kind])
        self._clear_status()
        self._last_logs = []
        self._loading = False

    def dump(self) -> Dict[str, str]:
        drafts = dict(self._drafts)
        drafts[self._kind] = self.code.toPlainText()
        return drafts

    def refresh_theme(self) -> None:
        """语言/主题切换后重译 tooltip，并按当前主题刷新状态图标颜色。"""
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
    duplicateRequested = pyqtSignal()

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
        self.urlbar.duplicateRequested.connect(self.duplicateRequested.emit)
        self.urlbar.moreRequested.connect(self._on_more)
        self.urlbar.methodChanged.connect(self._on_method)
        self.urlbar.urlChanged.connect(self._on_url)
        self.node_btn = self.urlbar.node_btn

        self.tabs = SegmentedTabs(
            HTTP_TABS, style="underline", height=32, pad_h=10, font_size=12.2)
        self.tabs.changed.connect(self._on_tab)
        self.count_label = Label("", 10.5, theme().text_faint, mono_font=True)
        tools = HBox(self.tabs, 1, spacing=8)

        self.params = KVEditor("参数名", "值", empty_hint="添加查询参数", with_types=True,
                               file_tooltip="URL 查询参数无法携带文件；文件上传请在「请求体 → Form 表单」里添加")
        self.params.changed.connect(self._on_params)
        self.paste_btn = Button("粘贴", None, kind="ghost", height=24, padding=8, font_size=11.5,
                                tooltip="从剪贴板批量导入：a=1&b=2 / 多行 key: value / JSON")
        self.paste_btn.clicked.connect(self._paste_params)
        self.params_bulk_btn = Button("批量编辑", None, kind="ghost", height=24, padding=8, font_size=11.5,
                                      tooltip="以 key: value 文本一次编辑全部参数")
        self.params_bulk_btn.clicked.connect(self._toggle_params_bulk)
        self.params_tools = HBox(1, self.paste_btn, self.params_bulk_btn, spacing=4)
        self.params_preview = Label("", 10.5, theme().text_faint, mono_font=True)
        self.params_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
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
            self.ws.load(request)
            self.sio.load(request)
            scripts = request.get("scripts", {}) or {}
            self.scripts_pre.load({"pre": scripts.get("pre", "")})
            self.scripts_post.load({"post": scripts.get("post", "")})
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
                "sio" if upper == SIO_METHOD else "http")
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
        if not self._loading:
            self._refresh_counts()

    def is_ws(self) -> bool:
        """是否实时协议页（WebSocket 或 Socket.IO）；保留旧调用名。"""
        return self._mode != "http"

    def is_sio(self) -> bool:
        return self._mode == "sio"

    def set_ws_state(self, state: str) -> None:
        self.urlbar.set_ws_state(state)
        composer = self.sio if self._mode == "sio" else self.ws
        composer.set_connected(state == "open")

    def _sync_request(self, *, script_only: bool = False) -> None:
        if self._loading or self._syncing or not self.request:
            return
        self.request["method"] = self.urlbar.method.method()
        self.request["url"] = self.urlbar.url_text()
        self.request["params"] = self.params.rows()
        if self._mode == "http":
            # 实时协议的握手头是弹层直接写进 request 的，这里不要去覆盖它
            self.request["headers"] = self.headers.rows()
        self.request["cookies"] = self.cookies.rows()
        self.request["body"] = self.body.dump()
        self.request["auth"] = self.auth.dump()
        if self._mode == "sio":
            self.sio.dump(self.request)
        elif self._mode == "ws":
            self.ws.dump(self.request)
        self.request["scripts"] = {
            "pre": self.scripts_pre.dump().get("pre", ""),
            "post": self.scripts_post.dump().get("post", ""),
        }
        if not self.request.get("name") or self.request.get("name") == "Untitled Request":
            self._auto_name()
        self._refresh_counts()
        # 脚本改动只更新数据与脏标记，不能让旁边正在看的响应被 show_stale 清掉。
        if script_only:
            self.scriptsChanged.emit()
        else:
            self.changed.emit()

    def _final_url(self) -> str:
        """把 base URL 与启用的查询参数拼成最终地址（与发送时同一套算法，并解析环境变量）。"""
        from urllib.parse import urlencode

        env = self.store.env_vars() if self.store else {}
        raw = resolve_vars(self.urlbar.url_text().strip(), env)
        if not raw:
            return ""
        if "://" not in raw:
            raw = "http://" + raw
        pairs = [(resolve_vars(str(r["key"]), env), resolve_vars(str(r.get("value", "")), env))
                 for r in self.params.rows() if r.get("enabled", True) and r.get("key")]
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
            key, composer = (("ws", self.ws) if self._mode == "ws"
                             else ("sio", self.sio))
            messages = len((self.request.get(key) or {}).get("messages") or [])
            composer.set_headers_count(headers)
            composer.set_messages_count(messages)
            self.count_label.setText("")
            self.params_preview.setText("")
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
        pre_script = self.scripts_pre.dump().get("pre", "").strip() if hasattr(self, "scripts_pre") else ""
        post_script = self.scripts_post.dump().get("post", "").strip() if hasattr(self, "scripts_post") else ""
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
        rows = self.params.rows()
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
        self.params.set_rows(rows)
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

    def _on_more(self, anchor: QWidget) -> None:
        t = theme()
        menu = Menu(self)
        act_code = menu.addAction(icons.icon("code", t.text, 14), "生成代码片段  ⌘⇧C")
        act_curl = menu.addAction(icons.icon("terminal" if False else "book", t.text, 14), "复制为 cURL")
        menu.addSeparator()
        act_mock = menu.addAction(icons.icon("grid", t.text, 14), "Mock 数据…")
        menu.addSeparator()
        act_dup = menu.addAction(icons.icon("copy", t.text, 14), "复制请求")
        act_del = menu.addAction(icons.icon("trash", t.danger, 14), "删除请求")
        chosen = menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        if chosen is act_code:
            self.codeRequested.emit()
        elif chosen is act_curl:
            self.copyCurlRequested.emit()
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
