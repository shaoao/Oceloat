"""SSE 请求页：只收不发的事件流。

界面刻意跟 WebSocket 页同一套骨架（选项 / 参数两页 + 底部连接按钮在地址栏），
只是把「写消息」整块去掉 —— SSE 是服务器单向推送，给一个输入框反而让人
以为能发东西。日志区直接复用帧列表：每条事件一行，点开看完整 data。
"""
from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List

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
    HBox,
    Label,
    SegmentedTabs,
    Switch,
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


class SseLogView(WsLogView):
    """SSE 的事件日志：复用帧列表，筛选项换成「事件 / 心跳」。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter.set_items([("all", "全部"), ("event", "事件"), ("ping", "心跳")],
                              current="all")
        self.empty_label.setText(i18n.tr("还没有事件。连接后服务器推送的事件会实时出现在这里。"))
        self.search.setFixedWidth(150)
        i18n.placeholder(self.search, "过滤事件内容")
        self.list.setToolTip(i18n.tr("单击展开这条事件（可同时展开多条）"))

    def _match(self, frame) -> bool:      # noqa: D401 — 覆盖父类的方向筛选
        if self._filter == "event" and frame.dir != "in":
            return False
        if self._filter == "ping" and frame.kind != "ping":
            return False
        if self._filter == "all" and frame.kind == "ping":
            return True
        if self._query:
            return self._query in frame.preview(4000).lower()
        return True

    def _update_stats(self) -> None:
        from .code_editor import human_size

        self.stats.setText(i18n.trf("{n} 条事件 · {size}", n=self._n_in,
                                    size=human_size(self._size_in)))

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
