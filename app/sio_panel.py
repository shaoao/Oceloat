"""Socket.IO 的界面部分：事件发送器 + 事件日志。

沿用 WebSocket 面板的纯黑简约视觉和视口绘制列表；协议特有部分是命名空间 /
认证 JSON / 事件名 / ACK，以及「发现的事件」一键筛选。所有已修过的日志布局、
滚轮、输入法、草稿和空态问题都继承同一套实现，不重复造轮子。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QStackedWidget, QVBoxLayout, QWidget

from . import i18n
from .code_editor import CodeView
from .kv_editor import KVEditor
from .store import uid
from .theme import theme
from .widgets import Button, Divider, HBox, Label, SegmentedTabs, SmoothScrollArea, Switch
from .ws_panel import KIND_LABEL, MsgChip, WsLogView

# 日志行上的技术标签保持大写短词，不需要翻译
KIND_LABEL.update({"event": "EVENT", "ack": "ACK"})

# 载荷输入区支持 JSON / 文本两种模式（只影响高亮与格式化，不改变协议内容）
PAYLOAD_KINDS = [("text", "文本"), ("json", "JSON")]


def default_sio() -> Dict[str, Any]:
    return {
        "messages": [], "namespace": "/", "auth": "", "ack": False,
        "auto_reconnect": True, "clear_after_send": False,
        "event": "message", "draft": "", "kind": "json",
    }


def ensure_sio(req: Dict[str, Any]) -> Dict[str, Any]:
    sio = req.get("sio")
    if not isinstance(sio, dict):
        sio = default_sio()
        req["sio"] = sio
    for key, value in default_sio().items():
        sio.setdefault(key, value)
    if not isinstance(sio.get("messages"), list):
        sio["messages"] = []
    return sio


# ---------------------------------------------------------------- 请求侧
class SioComposer(QWidget):
    """Socket.IO「事件」页：命名空间、认证、事件名、载荷、ACK 和常用事件。"""

    sendRequested = pyqtSignal(str, str, bool)   # 事件名, 载荷, 是否等 ACK
    changed = pyqtSignal()
    headersToggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sio: Dict[str, Any] = default_sio()
        self._connected = False
        self._loading = False
        self._chips: List[MsgChip] = []

        t = theme()
        # --- 「通讯」页：事件名称单独一行、stretch 填满；下面是载荷工具行。
        # 命名空间是连接级参数，移到「认证」页，通讯页只留日常收发需要的字段，
        # 这样每一行左边缘都落在同一条竖线上。
        self.event_name = QLineEdit()
        self.event_name.setObjectName("Field")
        self.event_name.setFixedHeight(28)
        i18n.placeholder(self.event_name, "事件名，例如 chat message")
        self.event_name.setToolTip(i18n.tr("要发送的事件名称，例如 chat message"))
        self.event_name.textChanged.connect(self._on_option)
        ev_row = QHBoxLayout()
        ev_row.setSpacing(10)
        ev_row.addWidget(Label("事件名称", 11, t.text_faint))
        ev_row.addWidget(self.event_name, 1)

        # 载荷模式：JSON / 文本切换，只影响高亮与格式化
        self.kind = SegmentedTabs(PAYLOAD_KINDS, style="pill", height=26,
                                  font_size=11.4, pad_h=11)
        self.kind.changed.connect(self._on_kind)

        self.fmt_btn = Button("格式化", "code", kind="ghost", height=24, padding=8,
                              font_size=11, icon_size=11)
        self.fmt_btn.setToolTip(i18n.tr("把 JSON 载荷排版成易读的缩进格式"))
        self.fmt_btn.clicked.connect(self._format)
        self.save_btn = Button("保存事件", "plus", kind="ghost", height=24, padding=8,
                               font_size=11, icon_size=11)
        self.save_btn.setToolTip(i18n.tr("存进常用事件，下次一点就填"))
        self.save_btn.clicked.connect(self._save_current)
        self.send_btn = Button("发送事件", "send", kind="primary", height=26, padding=12,
                               font_size=11.6, icon_size=12)
        self.send_btn.clicked.connect(self._send)
        tools = HBox(self.kind, 1, self.fmt_btn, self.save_btn, self.send_btn,
                     spacing=8, margins=(0, 0, 0, 0))

        self.editor = CodeView(read_only=False, highlight=True, show_gutter=False)
        self.editor.setMinimumHeight(68)
        i18n.placeholder(self.editor,
                         "输入事件载荷。JSON 会高亮；留空表示事件不带数据。")
        self.editor.textChanged.connect(self._on_draft_changed)

        self.saved_note = Label("", 10.4, t.text_faint)
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
        cl.setContentsMargins(22, 10, 14, 12)
        cl.setSpacing(8)
        cl.addLayout(ev_row)
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

        # --- 「认证」页：握手期认证与连接行为，单独成页
        self.auth = QLineEdit()
        self.auth.setObjectName("Field")
        self.auth.setFixedHeight(28)
        i18n.placeholder(self.auth, '{"token": "..."}')
        self.auth.setToolTip(i18n.tr("连接时随 40 包发送的认证对象，必须是合法 JSON"))
        self.auth.textChanged.connect(self._on_option)

        self.ack_sw = Switch(False)
        self.ack_sw.setToolTip(i18n.tr("开启后这次事件会带 ack id，收到回执会在日志里显示"))
        self.ack_sw.toggled.connect(lambda _v: self._on_option())
        self.clear_sw = Switch(False)
        self.clear_sw.toggled.connect(lambda _v: self._on_option())
        self.reconnect_sw = Switch(True)
        self.reconnect_sw.toggled.connect(lambda _v: self._on_option())

        # 认证页去掉整块灰色底：与协议页一样直接铺在页面底色上，
        # 分组标题 + 细分隔线足够分层，输入框左边缘与其他页保持同一条线。
        self.namespace = QLineEdit()
        self.namespace.setObjectName("Field")
        self.namespace.setFixedHeight(28)
        i18n.placeholder(self.namespace, "/")
        self.namespace.setToolTip(i18n.tr("默认命名空间填 /，自定义填 /admin"))
        self.namespace.textChanged.connect(self._on_option)

        auth_card = QWidget()
        av = QVBoxLayout(auth_card)
        av.setContentsMargins(10, 10, 14, 14)
        av.setSpacing(12)
        av.addWidget(Label(i18n.tr("连接参数"), 11, t.text_dim))
        a_ns = QHBoxLayout()
        a_ns.setSpacing(10)
        a_ns.addWidget(Label("命名空间", 11, t.text_faint))
        a_ns.addWidget(self.namespace, 1)
        av.addLayout(a_ns)
        av.addWidget(Divider())
        av.addWidget(Label(i18n.tr("握手认证"), 11, t.text_dim))
        a1 = QHBoxLayout()
        a1.setSpacing(10)
        a1.addWidget(Label("认证 JSON", 11, t.text_faint))
        a1.addWidget(self.auth, 1)
        av.addLayout(a1)
        av.addWidget(Divider())
        av.addWidget(Label(i18n.tr("连接行为"), 11, t.text_dim))
        a2 = QHBoxLayout()
        a2.setSpacing(10)
        a2.addWidget(Label("等 ACK", 11, t.text_dim))
        a2.addWidget(self.ack_sw)
        a2.addSpacing(10)
        a2.addWidget(Label("重连", 11, t.text_dim))
        a2.addWidget(self.reconnect_sw)
        a2.addSpacing(10)
        a2.addWidget(Label("发送后清空", 11, t.text_dim))
        a2.addWidget(self.clear_sw)
        a2.addStretch(1)
        self.headers_btn = Button("握手头", "list", kind="ghost", height=26, padding=10,
                                  font_size=11, icon_size=12)
        self.headers_btn.setToolTip(i18n.tr("连接时一起发送的请求头，例如 Authorization"))
        self.headers_btn.clicked.connect(self.headersToggled.emit)
        a2.addWidget(self.headers_btn)
        av.addLayout(a2)
        hint = Label(i18n.tr("认证对象在连接时随握手发送；连接行为在断开重连后重新应用。"),
                     10.4, t.text_faint)
        hint.setWordWrap(True)
        av.addWidget(hint)
        av.addStretch(1)

        auth_page = QWidget()
        al = QVBoxLayout(auth_page)
        al.setContentsMargins(14, 10, 14, 12)
        al.setSpacing(0)
        al.addWidget(auth_card, 1)

        # 与 HTTP 请求页同款 underline 页签：通讯 / 参数 / 认证 三页。
        # 与 UrlBar / HTTP 页签栏同款 14px 缩进，文字落在顶部徽标那条竖线上。
        self.tabs = SegmentedTabs([("chat", "通讯"), ("params", "参数"),
                                   ("auth", "认证")],
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
        self.stack.addWidget(auth_page)

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
            self._sio = ensure_sio(req)
            pairs = (
                (self.namespace, self._sio.get("namespace", "/") or "/"),
                (self.auth, self._sio.get("auth", "") or ""),
                (self.event_name, self._sio.get("event", "message") or "message"),
            )
            for w, value in pairs:
                w.blockSignals(True)
                w.setText(str(value))
                w.blockSignals(False)
            for sw, key, default in ((self.ack_sw, "ack", False),
                                     (self.reconnect_sw, "auto_reconnect", True),
                                     (self.clear_sw, "clear_after_send", False)):
                sw.blockSignals(True)
                sw.setChecked(bool(self._sio.get(key, default)))
                sw.blockSignals(False)
            self.editor.blockSignals(True)
            self.editor.setPlainText(str(self._sio.get("draft") or ""))
            self.editor.blockSignals(False)
            kind = str(self._sio.get("kind") or "json")
            self.kind.blockSignals(True)
            self.kind.set_current(kind, emit=False)
            self.kind.blockSignals(False)
            self._apply_kind(kind)
            self.params.blockSignals(True)
            self.params.set_rows(req.get("params") or [])
            self.params.blockSignals(False)
            self._refresh_saved()
        finally:
            self._loading = False

    def dump(self, req: Dict[str, Any]) -> None:
        sio = ensure_sio(req)
        req["params"] = self.params.rows()
        sio["namespace"] = (self.namespace.text().strip() or "/")
        sio["auth"] = self.auth.text().strip()
        sio["event"] = self.event_name.text().strip()
        sio["ack"] = self.ack_sw.isChecked()
        sio["auto_reconnect"] = self.reconnect_sw.isChecked()
        sio["clear_after_send"] = self.clear_sw.isChecked()
        sio["kind"] = self.kind_key()
        sio["draft"] = self.editor.toPlainText()

    def _on_draft_changed(self) -> None:
        if self._loading:
            return
        # 只改内存字典，落盘交给主窗口的 debounce 定时器。
        # 不能在这里 set_language —— CodeView 重设语言会再触发 textChanged，
        # 形成 textChanged→set_language→textChanged 的死循环。
        self._sio["draft"] = self.editor.toPlainText()
        self.changed.emit()

    def _on_option(self) -> None:
        if not self._loading:
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
        """通讯 / 参数 / 认证 三页签。"""
        index = {"chat": 0, "params": 1, "auth": 2}.get(key, 0)
        self.stack.setCurrentIndex(index)

    def _on_kind(self, key: str) -> None:
        """切换载荷高亮模式；不在草稿 textChanged 里 set_language，避免死循环。"""
        if self._loading:
            return
        self._apply_kind(key)
        self.changed.emit()

    def _apply_kind(self, key: str) -> None:
        is_json = key == "json"
        self.editor.set_language("json" if is_json else None)
        self.fmt_btn.setVisible(is_json)

    def kind_key(self) -> str:
        return self.kind.current() or "json"

    def set_headers_count(self, n: int) -> None:
        self.headers_btn.setText(i18n.trf("握手头 · {n}", n=n) if n
                                 else i18n.tr("握手头"))

    def event_value(self) -> str:
        """事件名。不能叫 event()——那是 QWidget 的事件处理器，会被 Qt 用参数调用。"""
        return self.event_name.text().strip()

    def payload(self) -> str:
        return self.editor.toPlainText()

    def ack_enabled(self) -> bool:
        return self.ack_sw.isChecked()

    def set_connected(self, on: bool) -> None:
        self._connected = on
        self.send_btn.setEnabled(on)
        self.send_btn.setToolTip("" if on else i18n.tr("先连接再发送事件"))
        i18n.placeholder(
            self.editor,
            "输入事件载荷。JSON 会高亮；留空表示事件不带数据。" if on
            else "还没连接：点左上角「连接」建立 Socket.IO 连接。")

    def _format(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            return
        try:
            data = json.loads(text)
        except Exception:  # noqa: BLE001
            return
        self.editor.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))

    def _send(self) -> None:
        if not self._connected:
            return
        if not self.event_value():
            self.event_name.setFocus()
            return
        self.sendRequested.emit(self.event_value(), self.payload(), self.ack_enabled())
        if self.clear_sw.isChecked():
            self.editor.setPlainText("")

    # -------------------------------------------------- 常用事件
    def _save_current(self) -> None:
        text = self.payload().strip()
        name = self.event_value()
        if not name:
            return
        messages = self._sio.setdefault("messages", [])
        if any(m.get("event") == name and m.get("payload") == text for m in messages):
            return
        messages.append({"id": uid(), "name": name[:24], "event": name,
                         "payload": text})
        self._refresh_saved()
        self.changed.emit()

    def _delete(self, msg_id: str) -> None:
        self._sio["messages"] = [m for m in self._sio.get("messages", [])
                                 if m.get("id") != msg_id]
        self._refresh_saved()
        self.changed.emit()

    def _load_msg(self, item: Dict[str, Any]) -> None:
        self.event_name.setText(str(item.get("event") or item.get("name") or ""))
        self.editor.setPlainText(str(item.get("payload") or ""))

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
        messages = [m for m in self._sio.get("messages", []) if isinstance(m, dict)]
        for msg in messages:
            chip = MsgChip(msg)
            chip.load.connect(self._load_msg)
            chip.delete.connect(self._delete)
            self.saved_lay.addWidget(chip)
            self._chips.append(chip)
        self.saved_lay.addStretch(1)
        n = len(messages)
        self.saved_note.setText(i18n.trf("常用事件 · {n}", n=n) if n else "")
        self.saved_note.setVisible(bool(n))
        self.saved_scroll.setVisible(bool(n))


# ---------------------------------------------------------------- 响应侧
class SioLogView(WsLogView):
    """Socket.IO 日志：继承 WS 的视口绘制和详情卡，加「发现的事件」快捷筛选。"""

    eventReplay = pyqtSignal(str, str)         # 事件名, 载荷
    replay = pyqtSignal(str)                   # 覆盖基类签名，仍供主窗口按需连接

    def __init__(self, parent=None):
        super().__init__(parent)
        self._log_name = "socketio-log.json"
        self._events: Dict[str, int] = {}
        i18n.placeholder(self.search, "过滤事件或内容")
        self.filter.set_items([("all", "全部"), ("in", "接收"), ("out", "发出"),
                               ("event", "事件")])
        self.list.setToolTip(i18n.tr(
            "单击展开详情（可同时展开多条），双击事件填回事件编辑器"))

        self.event_bar = QWidget()
        el = QHBoxLayout(self.event_bar)
        el.setContentsMargins(12, 3, 12, 3)
        el.setSpacing(6)
        self.event_bar.hide()
        lay = self.layout()
        lay.insertWidget(2, self.event_bar)

    # -------------------------------------------------- 发现的事件
    def _record(self, frame) -> bool:
        if getattr(frame, "kind", "") != "event":
            return False
        try:
            arr = json.loads(frame.text())
            name = str(arr[0]) if isinstance(arr, list) and arr else ""
        except Exception:  # noqa: BLE001
            name = ""
        if not name:
            return False
        if self._events.get(name) == 1:
            self._events[name] = 2
            return False
        if name in self._events:
            self._events[name] += 1
            return False
        self._events[name] = 1
        return True

    def _build_events(self) -> None:
        # 立即从布局与父控件摘掉旧项：连续收到多条事件会在同一个事件循环里
        # 反复重建，deleteLater() 要等下一轮才生效，旧的 label / 按钮会短暂
        # 叠在一起（截图里就是「发现的事件」文字被挤成一条）。
        lay = self.event_bar.layout()
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        names = list(self._events)[:8]
        if not names:
            self.event_bar.hide()
            return
        label = Label(i18n.trf("发现的事件 · {n}", n=len(self._events)),
                      10.2, theme().text_faint)
        self.event_bar.layout().addWidget(label, 0)
        for name in names:
            btn = Button(name[:20], None, kind="ghost", height=22, padding=7,
                         font_size=10, radius=6, parent=self.event_bar)
            btn.setToolTip(i18n.trf("{name} · {n} 次，点击筛选", name=name,
                                    n=self._events[name]))
            btn.clicked.connect(lambda _c=False, n=name: self._pick_event(n))
            self.event_bar.layout().addWidget(btn, 0)
        self.event_bar.layout().addStretch(1)
        self.event_bar.show()

    def _pick_event(self, name: str) -> None:
        self.search.setText("" if (self._query == name.lower()) else name)

    # -------------------------------------------------- 覆盖基类
    def set_frames(self, frames) -> None:
        self._events.clear()
        super().set_frames(frames)
        for f in self._frames:
            self._record(f)
        self._build_events()

    def add_frame(self, frame) -> None:
        super().add_frame(frame)
        if self._record(frame):
            self._build_events()
        elif frame.kind == "event" and self._events:
            # 次数变了，tooltip 更新一下即可，不必重建整排按钮
            self._build_events()

    def clear(self) -> None:
        self._events.clear()
        super().clear()
        self._build_events()

    def _match(self, frame) -> bool:
        if self._filter == "event":
            ok = frame.kind in ("event", "ack")
            return ok and (not self._query or self._query in frame.preview(4000).lower())
        return super()._match(frame)

    def _update_empty(self, has_rows: bool) -> None:
        self.body.setCurrentIndex(1 if has_rows else 0)
        if has_rows:
            return
        self.empty_label.setText(
            i18n.tr("没有符合条件的内容。清空搜索或换个筛选试试。")
            if self._frames else
            i18n.tr("还没有事件。连接后收发、ACK 和心跳都会实时出现在这里。"))

    def _replay(self, index: int) -> None:
        items = self.list.frames
        if not (0 <= index < len(items)):
            return
        frame = items[index]
        if frame.kind == "event":
            try:
                arr = json.loads(frame.text())
            except Exception:  # noqa: BLE001
                return
            if not isinstance(arr, list) or not arr:
                return
            name = str(arr[0])
            args = arr[1:]
            payload = json.dumps(args[0] if len(args) == 1 else args,
                                 ensure_ascii=False) if args else ""
            self.eventReplay.emit(name, payload)
            return
        super()._replay(index)
