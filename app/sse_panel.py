"""SSE 请求页：只收不发的事件流。

界面刻意跟 WebSocket 页同一套骨架（选项 / 参数两页 + 底部连接按钮在地址栏），
只是把「写消息」整块去掉 —— SSE 是服务器单向推送，给一个输入框反而让人
以为能发东西。日志区直接复用帧列表：每条事件一行，点开看完整 data。
"""
from __future__ import annotations

import datetime
import json
import time
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import i18n
from .kv_editor import KVEditor
from .theme import mono, theme
from .widgets import (
    Button,
    Divider,
    ElideLabel,
    HBox,
    Label,
    SegmentedTabs,
    Switch,
    icon_button,
)
from .ws_panel import WsLogView


def default_sse() -> Dict[str, Any]:
    return {"auto_reconnect": True, "last_event_id": "", "retry_ms": 1500}


def ensure_sse(req: Dict[str, Any]) -> Dict[str, Any]:
    sse = req.get("sse")
    if not isinstance(sse, dict):
        sse = default_sse()
        req["sse"] = sse
    for key, value in default_sse().items():
        sse.setdefault(key, value)
    return sse


class SseComposer(QWidget):
    """SSE 的「选项 / 参数」：都是连接级配置，改了下次连接生效。"""

    changed = pyqtSignal()
    headersToggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sse: Dict[str, Any] = default_sse()
        self._loading = False
        t = theme()

        # ---- 选项页
        self.reconnect_sw = Switch(True)
        self.reconnect_sw.toggled.connect(lambda _v: self._on_change())
        self.last_id = QLineEdit()
        self.last_id.setObjectName("Field")
        self.last_id.setFixedHeight(28)
        self.last_id.setFont(mono(11.5))
        i18n.placeholder(self.last_id, "可留空，断线重连时作为 Last-Event-ID 发回")
        self.last_id.textChanged.connect(lambda _v: self._on_change())
        self.retry_edit = QLineEdit("1500")
        self.retry_edit.setObjectName("Field")
        self.retry_edit.setFixedHeight(28)
        self.retry_edit.setFixedWidth(72)
        self.retry_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.retry_edit.setFont(mono(11.5))
        self.retry_edit.textChanged.connect(lambda _v: self._on_change())
        self.headers_btn = Button("请求头", "list", kind="ghost", height=26, padding=10,
                                  font_size=11, icon_size=12)
        self.headers_btn.setToolTip(i18n.tr("连接时一起发送的请求头，例如 Authorization"))
        self.headers_btn.clicked.connect(self.headersToggled.emit)

        card = QWidget()
        cv = QVBoxLayout(card)
        cv.setContentsMargins(10, 10, 14, 14)
        cv.setSpacing(12)
        cv.addWidget(Label(i18n.tr("连接参数"), 11, t.text_dim))
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(Label("自动重连", 11, t.text_dim))
        row.addWidget(self.reconnect_sw)
        row.addSpacing(12)
        row.addWidget(Label("重试间隔", 11, t.text_dim))
        row.addWidget(self.retry_edit)
        row.addWidget(Label("毫秒", 10.4, t.text_faint))
        row.addStretch(1)
        row.addWidget(self.headers_btn)
        cv.addLayout(row)
        cv.addWidget(Divider())
        cv.addWidget(Label(i18n.tr("续传"), 11, t.text_dim))
        cv.addWidget(self.last_id)
        hint = Label(i18n.tr(
            "SSE 只接收服务器推送的事件；连上后每来一条事件就会实时出现在右侧日志里。"
            "服务端断开时会按上面的间隔自动重连，并从最后一条事件的 id 继续。"),
            10.4, t.text_faint)
        hint.setWordWrap(True)
        cv.addWidget(hint)
        cv.addStretch(1)

        options_page = QWidget()
        ol = QVBoxLayout(options_page)
        ol.setContentsMargins(14, 10, 14, 12)
        ol.setSpacing(0)
        ol.addWidget(card, 1)

        # ---- 参数页
        self.params = KVEditor("参数名", "值", empty_hint="添加查询参数", with_types=True,
                               allow_file=False)
        self.params.changed.connect(lambda: self._on_change())
        self.paste_btn = Button("粘贴", None, kind="ghost", height=24, padding=8, font_size=11.5,
                                tooltip="从剪贴板批量导入：a=1&b=2 / 多行 key: value / JSON")
        self.paste_btn.clicked.connect(self._paste_params)
        self.params_preview = Label("", 10.5, t.text_faint, mono_font=True)
        self.params_preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.params_preview.setToolTip(i18n.tr("连接时使用的完整地址"))
        params_page = QWidget()
        pl = QVBoxLayout(params_page)
        pl.setContentsMargins(14, 10, 14, 12)
        pl.setSpacing(6)
        pl.addWidget(Label(i18n.tr("查询参数会在连接时拼到地址后面"), 11, t.text_dim))
        pl.addWidget(self.params, 1)
        pl.addWidget(HBox(1, self.paste_btn, spacing=4))
        pl.addWidget(self.params_preview)

        self.tabs = SegmentedTabs([("options", "选项"), ("params", "参数")],
                                  style="underline", height=32, pad_h=10, font_size=12.2)
        self.tabs.changed.connect(self._on_tab)
        host = QWidget()
        hl = QHBoxLayout(host)
        hl.setContentsMargins(14, 0, 0, 0)
        hl.setSpacing(0)
        hl.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignLeft)
        self.stack = QStackedWidget()
        self.stack.addWidget(options_page)
        self.stack.addWidget(params_page)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(host)
        lay.addWidget(self.stack, 1)

    # -------------------------------------------------- 数据
    def load(self, req: Dict[str, Any]) -> None:
        self._loading = True
        try:
            self._sse = ensure_sse(req)
            self.reconnect_sw.blockSignals(True)
            self.reconnect_sw.setChecked(bool(self._sse.get("auto_reconnect", True)))
            self.reconnect_sw.blockSignals(False)
            for w, key, default in ((self.last_id, "last_event_id", ""),
                                    (self.retry_edit, "retry_ms", 1500)):
                w.blockSignals(True)
                w.setText(str(self._sse.get(key) if self._sse.get(key) not in (None, "")
                             else default))
                w.blockSignals(False)
            self.params.blockSignals(True)
            self.params.set_rows(req.get("params") or [])
            self.params.blockSignals(False)
            self._refresh_preview()
        finally:
            self._loading = False

    def dump(self, req: Dict[str, Any]) -> None:
        sse = ensure_sse(req)
        req["params"] = self.params.rows()
        sse["auto_reconnect"] = self.reconnect_sw.isChecked()
        sse["last_event_id"] = self.last_id.text().strip()
        try:
            sse["retry_ms"] = max(300, int(self.retry_edit.text().strip() or 1500))
        except ValueError:
            sse["retry_ms"] = 1500

    def set_connected(self, on: bool) -> None:
        """连上以后连接级配置就锁住：改了也不会即时生效，容易让人以为失灵。"""
        for w in (self.reconnect_sw, self.last_id, self.retry_edit, self.params,
                  self.paste_btn, self.headers_btn):
            w.setEnabled(not on)
        self.last_id.setToolTip(i18n.tr("已连接；断开后修改再重新连接") if on else "")

    def params_preview_text(self, text: str) -> None:
        self.params_preview.setText(text)

    def _refresh_preview(self) -> None:
        self.params_preview.setText("")

    def _paste_params(self) -> None:
        from PyQt6.QtWidgets import QApplication

        text = (QApplication.clipboard().text() or "").strip()
        if not text:
            return
        rows: List[Dict[str, Any]] = []
        if text.startswith("{") or text.startswith("["):
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    rows = [{"key": str(k), "value": str(v), "enabled": True}
                            for k, v in data.items()]
            except Exception:      # noqa: BLE001
                rows = []
        if not rows:
            for part in text.replace("\n", "&").split("&"):
                if not part.strip():
                    continue
                key, _, value = part.partition("=")
                rows.append({"key": key.strip(), "value": value.strip(), "enabled": True})
        if rows:
            self.params.set_rows(rows)
            self._on_change()

    def _on_tab(self, key: str) -> None:
        index = 1 if key == "params" else 0
        self.stack.setCurrentIndex(index)

    def _on_change(self) -> None:
        if self._loading:
            return
        self.changed.emit()


class _StatusDot(QWidget):
    """连接状态点：一圈淡色底 + 中间一个实心点，颜色跟着状态走。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token = "text_faint"
        self.setFixedSize(12, 12)

    def set_token(self, token: str) -> None:
        if token != self._token:
            self._token = token
            self.update()

    def paintEvent(self, _e):  # noqa: N802
        # 自绘一律走兜底：paintEvent 里抛异常，PyQt6 会直接 abort 掉整个进程
        from .main_window import _guard

        _guard("SseStatusDot.paintEvent", self._paint_dot)

    def _paint_dot(self) -> None:
        from PyQt6.QtCore import QRectF as _QRectF
        from PyQt6.QtGui import QColor as _QColor
        from PyQt6.QtGui import QPainter as _QPainter
        from PyQt6.QtGui import QPen as _QPen

        t = theme()
        col = _QColor(getattr(t, self._token, t.text_faint))
        p = _QPainter(self)
        p.setRenderHint(_QPainter.RenderHint.Antialiasing, True)
        halo = _QColor(col)
        halo.setAlpha(45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(_QRectF(0, 0, 12, 12))
        p.setBrush(col)
        p.drawEllipse(_QRectF(3.5, 3.5, 5, 5))
        p.setPen(_QPen(col, 1))
        p.end()


class SseLogView(WsLogView):
    """SSE 的事件日志。

    和 WebSocket 页刻意不一样的地方（这些都是 SSE 独有、也最容易踩的坑）：
      · 顶部一条「握手结果」：HTTP 状态码 + Content-Type + 事件速率。
        SSE 就是一条 http 长连接，401 / 404 / 被代理缓冲时一条事件都不来，
        没有这行字就只能看到一个空列表干瞪眼。
      · 事件名是服务端的「频道」（message / update / price…），筛选按钮按
        实际收到过的名字动态生成，而不是写死「接收 / 发出」。
      · 暂停：行情类接口每秒几十条，先冻住列表再看，缓冲的条数写在按钮旁边。
    """

    MAX_CHIPS = 4           # 「全部」之外最多列 4 个事件名，再多就挤了

    def __init__(self, parent=None):
        super().__init__(parent)
        self._kinds: Dict[str, int] = {}
        self._paused = False
        self._pending: List[Any] = []
        self._status = 0
        self._ctype = ""
        self._headers: Dict[str, str] = {}
        self._retry: tuple = (0, 0)
        self._stamps: List[float] = []

        self.filter.set_items([("all", "全部"), ("__ping", "心跳")], current="all")
        self.search.setFixedWidth(150)
        i18n.placeholder(self.search, "过滤事件内容")
        self.list.setToolTip(i18n.tr("单击展开这条事件（可同时展开多条）"))

        self.dot = _StatusDot()
        # 状态行里的协议 / 地址可能很长：用会自己省略的标签，窄了打「…」，
        # 不会把右边的速率和暂停按钮挤出屏幕。
        self.status_label = ElideLabel(i18n.tr("未连接"), 10.8, theme().text_dim,
                                       mono_font=True, mode=Qt.TextElideMode.ElideRight)
        self.rate_label = Label("", 10.2, theme().text_faint, mono_font=True)
        self.pause_btn = icon_button("pause", "", 22, 12)
        self.pause_btn.setToolTip(i18n.tr("暂停：先冻住列表，慢慢看已经收到的事件"))
        self.pause_btn.clicked.connect(self.toggle_pause)

        # 这条控制条已合并到响应面板头部第一行（见 ResponsePanel），
        # 这里保留构造以维持 status_label / pause_btn 的引用与更新逻辑，
        # 但自身不再占一行：mety 容器会把它 take 走。
        strip = QWidget()
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        sl.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        sl.addWidget(self.status_label, 1)
        sl.addWidget(self.rate_label)
        sl.addWidget(self.pause_btn)
        self.strip = strip
        lay = self.layout()
        lay.insertWidget(0, strip)
        self.strip_div = Divider()
        lay.insertWidget(1, self.strip_div)

    # -------------------------------------------------- 握手信息
    def set_stream(self, status: int = 0, ctype: str = "", headers: Optional[Dict[str, str]] = None) -> None:
        self._status = int(status or 0)
        self._ctype = ctype or ""
        if headers is not None:
            self._headers = dict(headers)
        tips = [f"HTTP {self._status}"] if self._status else []
        if self._ctype:
            tips.append(f"Content-Type: {self._ctype}")
        for key, value in list(self._headers.items())[:40]:
            tips.append(f"{key}: {value}")
        self.status_label.setToolTip(
            "\n".join(tips) or i18n.tr("服务端返回的 Content-Type"))
        self._render_status()

    def set_retry(self, attempt: int, delay_ms: int) -> None:
        self._retry = (int(attempt), int(delay_ms))
        self._render_status()

    def set_state(self, state: str) -> None:
        self._state = state
        self._render_status()
        self._update_stats()

    def _render_status(self) -> None:
        state = getattr(self, "_state", "idle")
        if state == "open":
            self.dot.set_token("success")
            # 「已连接」上面那颗胶囊已经写过了，这里只留握手结果，别重复
            code = f"{self._status} · " if self._status else ""
            self.status_label.setText(f"{code}{self._ctype or 'text/event-stream'}")
            self.status_label._token = "success"
        elif state in ("connecting", "closing"):
            self.dot.set_token("warning")
            attempt, delay = self._retry
            if attempt:
                self.status_label.setText(i18n.trf("第 {n} 次重连 · {s}s 后重试",
                                                   n=attempt, s=round(delay / 1000, 1)))
            else:
                self.status_label.setText(i18n.tr("连接中…"))
            self.status_label._token = "warning"
        else:
            self.dot.set_token("text_faint")
            if self._status >= 400:
                self.status_label.setText(i18n.trf("连接失败 · HTTP {code}", code=self._status))
                self.status_label._token = "danger"
                self.dot.set_token("danger")
            else:
                # 顶部胶囊已经写了「未连接」，这里别再重复一遍：
                # 留空只显示状态小圆点，等连上后这里换成握手结果。
                self.status_label.setText("")
                self.status_label._token = "text_faint"
        self.status_label.refresh_theme()

    # -------------------------------------------------- 暂停
    def toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_btn.set_icon("play" if self._paused else "pause")
        self.pause_btn.setToolTip(
            i18n.tr("继续：把暂停期间收到的事件一次性放出来") if self._paused
            else i18n.tr("暂停：先冻住列表，慢慢看已经收到的事件"))
        if self._paused:
            self._update_stats()
            return
        pending, self._pending = self._pending, []
        for frame in pending:
            super().add_frame(frame)
        self._pending = []
        self._rebuild()

    def add_frame(self, frame) -> None:
        now = time.time()
        self._stamps.append(now)
        if len(self._stamps) > 1 and self._stamps[-1] - self._stamps[0] > 60:
            self._stamps = [s for s in self._stamps if now - s <= 60]
        if frame.dir == "in" and frame.kind not in ("ping", "open", "close", "error"):
            if frame.kind not in self._kinds:
                self._kinds[frame.kind] = 0
                self._rebuild_chips()
            self._kinds[frame.kind] += 1
        if self._paused:
            self._pending.append(frame)
            if len(self._pending) > 4000:          # 缓冲别无限涨
                self._pending = self._pending[-4000:]
            self._update_stats()
            return
        super().add_frame(frame)
        self._update_rate()

    def set_frames(self, frames) -> None:
        self._pending = []
        self._kinds = {}
        self._stamps = []
        super().set_frames(frames)
        for frame in self._frames:
            if frame.dir == "in" and frame.kind not in ("ping", "open", "close", "error"):
                self._kinds[frame.kind] = self._kinds.get(frame.kind, 0) + 1
        self._rebuild_chips()
        self._update_rate()

    def clear(self) -> None:
        self._pending = []
        self._kinds = {}
        self._stamps = []
        super().clear()
        self._rebuild_chips()
        self._update_rate()

    # -------------------------------------------------- 事件名筛选
    def _rebuild_chips(self) -> None:
        items = [("all", "全部")]
        for name, _n in sorted(self._kinds.items(), key=lambda kv: (-kv[1], kv[0]))[:self.MAX_CHIPS]:
            items.append((name, name if len(name) <= 7 else name[:6] + "…"))
        items.append(("__ping", "心跳"))
        keys = [k for k, _l in items]
        current = self._filter if self._filter in keys else "all"
        if keys == [i.get("key") for i in getattr(self.filter, "_items", [])]:  # 没变就不重建
            return
        self.filter.set_items(items, current=current)
        self._filter = current

    def _match(self, frame) -> bool:      # noqa: D401 — 覆盖父类的方向筛选
        if self._filter == "__ping":
            return frame.kind == "ping"
        if frame.kind == "ping":
            # 心跳默认不进列表：15 秒一条，混在事件里会把真正的内容顶走
            return False
        if self._filter != "all" and frame.kind != self._filter:
            return False
        if self._query:
            return self._query in frame.preview(4000).lower()
        return True

    def _on_filter(self, key: str) -> None:
        self._filter = key
        self._rebuild()

    def _update_empty(self, has_rows: bool) -> None:
        self.body.setCurrentIndex(1 if has_rows else 0)
        if has_rows:
            return
        if self._frames:
            self.empty_label.setText(i18n.tr("没有符合条件的事件。换个筛选或清空搜索试试。"))
        else:
            self.empty_label.setText(
                i18n.tr("还没有事件。连上之后服务器推送的每一条都会出现在这里。"))

    # -------------------------------------------------- 统计
    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._fit_width()

    def _fit_width(self) -> None:
        w = self.width()
        # 窄了就先让统计和搜索退场，保住「筛选 + 三个图标」，绝不叠字
        self.stats.setVisible(w >= 640)
        self.search.setVisible(w >= 560)
        self.rate_label.setVisible(w >= 420)

    def _update_rate(self) -> None:
        n = len(self._stamps)
        self.rate_label.setText(
            i18n.trf("{n} 条/分", n=n) if n else "")
        self._update_stats()

    def _update_stats(self) -> None:
        from .code_editor import human_size

        buffered = len(self._pending)
        text = i18n.trf("{n} 条事件 · {size}", n=self._n_in, size=human_size(self._size_in))
        if self._kinds:
            text += i18n.trf(" · {k} 种事件", k=len(self._kinds))
        if buffered:
            text += i18n.trf(" · 暂停中，缓冲 {b} 条", b=buffered)
        self.stats.setText(text)

    def _export(self) -> None:
        if not self._frames:
            return
        path, _ = QFileDialog.getSaveFileName(
            self.window(), i18n.tr("导出事件日志"),
            getattr(self, "_log_name", "sse-log.json"),
            i18n.tr("JSON (*.json);;文本 (*.log)"))
        if not path:
            return
        rows = [{
            "time": datetime.datetime.fromtimestamp(f.at).isoformat(timespec="milliseconds"),
            "event": f.kind, "id": getattr(f, "event_id", ""),
            "size": f.size, "data": f.preview(200000),
        } for f in self._frames]
        try:
            with open(path, "w", encoding="utf-8") as fh:
                if path.lower().endswith(".log"):
                    fh.write("\n".join(
                        f"{r['time']} {r['event']} {r['size']}B {r['data']}" for r in rows))
                else:
                    json.dump(rows, fh, ensure_ascii=False, indent=2)
        except Exception:      # noqa: BLE001
            return
