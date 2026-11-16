"""节点选择面板：IPv4 / IPv6 分栏、搜索、测速结果与自定义代理节点。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .nodes import LOCAL_ID, NodeBook, probe_node
from .theme import C, font, mono, theme
from .widgets import Button, HBox, Label, SegmentedTabs, fade_in, icon_button

ROW_H = 32


def latency_color(ms: Optional[float]) -> str:
    t = theme()
    if ms is None:
        return t.text_faint
    if ms < 60:
        return t.success
    if ms < 160:
        return t.warning
    return t.danger


class NodeList(QWidget):
    picked = pyqtSignal(str)
    removed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodes: List[Dict[str, Any]] = []
        self.current = LOCAL_ID
        self.ping: Dict[str, Optional[float]] = {}
        self.pending: set = set()
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_nodes(self, nodes: List[Dict[str, Any]], current: str) -> None:
        self.nodes = nodes
        self.current = current
        self._hover = -1
        self.setFixedHeight(max(1, len(nodes)) * ROW_H + 4)
        self.update()

    def set_ping(self, node_id: str, ms: Optional[float]) -> None:
        self.pending.discard(node_id)
        self.ping[node_id] = ms
        self.update()

    def _at(self, y: float) -> int:
        i = int((y - 2) // ROW_H)
        return i if 0 <= i < len(self.nodes) else -1

    def mouseMoveEvent(self, e):
        i = self._at(e.position().y())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        i = self._at(e.position().y())
        if i < 0:
            return
        node = self.nodes[i]
        # 右侧叉：删除自定义节点
        if node.get("kind") == "proxy" and e.position().x() > self.width() - 28:
            self.removed.emit(node["id"])
            return
        self.picked.emit(node["id"])

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        # 几百个节点时只画视口附近的行，否则每次 ping 回来都重画 351 行会卡
        top, bottom = 0, self.height()
        viewport = self.parentWidget()
        sa = viewport.parentWidget() if viewport is not None else None
        if isinstance(sa, QScrollArea):
            v = sa.verticalScrollBar().value()
            top = max(0, v - ROW_H * 2)
            bottom = min(self.height(), v + viewport.height() + ROW_H * 2)
        first = max(0, int((top - 2) // ROW_H))
        last = min(len(self.nodes), int((bottom - 2) // ROW_H) + 1)
        for i in range(first, last):
            node = self.nodes[i]
            r = QRectF(2, 2 + i * ROW_H, self.width() - 4, ROW_H - 2)
            hovered = i == self._hover
            selected = node["id"] == self.current
            if hovered:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.hover))
                p.drawRoundedRect(r, 6, 6)
            elif selected:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected))
                p.drawRoundedRect(r, 6, 6)
            kind = node.get("kind")
            if kind == "local":
                pm = icons.pixmap("panel_left", t.text, 13, 1.7)
            elif kind == "proxy":
                pm = icons.pixmap("lock", t.text_dim, 13, 1.7)
            else:
                pm = icons.pixmap("node", t.text_faint, 13, 1.7)
            p.drawPixmap(QRectF(r.left() + 9, r.center().y() - 7, 13, 13), pm, QRectF(pm.rect()))
            p.setFont(font(12, QFont.Weight.Medium if selected else QFont.Weight.Normal))
            p.setPen(C(t.text if selected else t.text_dim))
            ms = self.ping.get(node["id"])
            right_w = 62
            avail = r.width() - right_w - 42
            p.drawText(QRectF(r.left() + 29, r.top(), avail, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       QFontMetricsF(p.font()).elidedText(node.get("name", ""),
                                                          Qt.TextElideMode.ElideRight, int(avail)))
            # 延迟
            p.setFont(mono(9.5))
            if node["id"] in self.pending:
                p.setPen(C(t.text_faint))
                p.drawText(QRectF(r.right() - 66, r.top(), 54, r.height()),
                           int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), "····")
            elif node["id"] in self.ping:
                text = "超时" if ms is None else f"{ms:.0f} ms"
                p.setPen(C(latency_color(ms)))
                p.drawText(QRectF(r.right() - 66, r.top(), 54, r.height()),
                           int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), text)
            if node.get("kind") == "proxy" and hovered:
                pm = icons.pixmap("close", t.text_faint, 10, 1.8)
                p.drawPixmap(QRectF(r.right() - 20, r.center().y() - 5, 10, 10), pm,
                             QRectF(pm.rect()))
            elif node["id"] == self.current:
                pm = icons.pixmap("check", t.text, 11, 1.9)
                p.drawPixmap(QRectF(r.right() - 21, r.center().y() - 5.5, 11, 11), pm,
                             QRectF(pm.rect()))
        p.end()


class NodePicker(QWidget):
    """弹出式节点面板（自绘圆角卡片）。"""

    picked = pyqtSignal(str)
    pinged = pyqtSignal(str, object)
    fetched = pyqtSignal(object)
    speedProgress = pyqtSignal(int, int)   # (已完成, 总数)

    W = 336
    H = 452

    def __init__(self, book: NodeBook, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.book = book
        self.resize(self.W, self.H)
        self._pool = ThreadPoolExecutor(max_workers=12)
        self._fetching = False
        self._speed_done = 0
        self._speed_total = 0
        self.fetched.connect(self._on_fetched)
        self.speedProgress.connect(self._on_speed_progress)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self.seg = SegmentedTabs([("v4", "IPv4 节点"), ("v6", "IPv6 节点")], style="pill",
                                 height=26, font_size=11.5, pad_h=12)
        self.seg.changed.connect(lambda _k: self._fill())
        self.speed_btn = Button("测速", None, kind="ghost", height=26, padding=8,
                                font_size=11, tooltip="测试当前分栏全部节点的延迟（速度仅供参考，不代表可用性与整体请求速度）")
        self.speed_btn.clicked.connect(self.measure)
        self.reload_btn = Button("刷新节点", "refresh", kind="ghost", height=26, padding=8,
                                 font_size=11, tooltip="从 tcping.cn 重新拉取完整节点列表")
        self.reload_btn.clicked.connect(self.refresh_nodes)
        lay.addWidget(HBox(self.seg, 1, self.speed_btn, self.reload_btn, spacing=6))

        self.search = QLineEdit()
        self.search.setObjectName("Field")
        self.search.setFixedHeight(27)
        self.search.setFont(font(11.5))
        self.search.setPlaceholderText("搜索地区 / 运营商，如 上海、电信")
        self.search.textChanged.connect(lambda _t: self._fill())
        lay.addWidget(self.search)

        self.list = NodeList()
        self.list.picked.connect(self._on_pick)
        self.list.removed.connect(self._on_remove)
        self.pinged.connect(self.list.set_ping)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.list)
        lay.addWidget(self.scroll, 1)

        self.add_btn = Button("添加代理节点", "plus", kind="ghost", height=26, padding=8,
                              font_size=11.5)
        self.add_btn.clicked.connect(self._add_proxy)
        self.hint = Label("", 10, theme().text_faint, mono_font=True)
        lay.addWidget(HBox(self.add_btn, 1, self.hint, spacing=6))
        self._fill()

    # -------------------------------------------------- 数据
    def _current_v6(self) -> bool:
        return self.seg.current() == "v6"

    def _fill(self) -> None:
        kw = self.search.text().strip()
        v6 = self._current_v6()
        nodes = []
        all_nodes = self.book.all_nodes()
        for n in all_nodes:
            if n.get("kind") != "local" and bool(n.get("v6")) != v6:
                continue
            if kw and kw not in n.get("name", "") and kw not in n.get("carrier", ""):
                continue
            nodes.append(n)
        self.seg.set_label("v4", f"IPv4 节点 {sum(1 for n in all_nodes if n.get('v4') and n.get('kind') == 'relay')}")
        self.seg.set_label("v6", f"IPv6 节点 {sum(1 for n in all_nodes if n.get('v6') and n.get('kind') == 'relay')}")
        self.list.set_nodes(nodes, self.book.current_id)
        self._update_hint(self.book.current())

    def _update_hint(self, node: Dict[str, Any]) -> None:
        if node.get("kind") == "relay":
            self.hint.setText("在线节点转发")
        elif node.get("kind") == "proxy":
            self.hint.setText(f"{node.get('scheme', 'http')} 代理")
        elif node.get("kind") == "offline":
            self.hint.setText("离线 · 点刷新节点")
        else:
            self.hint.setText("从本机发出")

    # -------------------------------------------------- 在线节点缓存
    def refresh_nodes(self) -> None:
        if self._fetching:
            return
        self._fetching = True
        self.reload_btn.setText("拉取中…")
        self.reload_btn.setEnabled(False)

        def job():
            from .relay import fetch_nodes

            try:
                self.fetched.emit(fetch_nodes())
            except Exception as exc:  # noqa: BLE001
                self.fetched.emit({"error": str(exc)})

        self._pool.submit(job)

    def _on_fetched(self, result) -> None:
        self._fetching = False
        self.reload_btn.setText("刷新节点")
        self.reload_btn.setEnabled(True)
        if isinstance(result, dict):
            self.hint.setText("拉取失败 · 用缓存")
            return
        self.book.set_remote(result)
        self._fill()
        self.hint.setText(f"已载入 {len(result)} 个节点")

    def refresh_current(self) -> None:
        self.list.current = self.book.current_id
        self._update_hint(self.book.current())
        self.list.update()

    # -------------------------------------------------- 交互
    def popup(self, global_pos: QPoint) -> None:
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x, y = global_pos.x(), global_pos.y()
        if y + self.height() > geo.bottom():
            y = max(geo.top() + 8, geo.bottom() - self.height() - 8)
        if x + self.width() > geo.right():
            x = geo.right() - self.width() - 8
        self.move(x, y)
        self.show()
        self.raise_()
        fade_in(self, 90)
        self.search.setFocus()
        if self.book.remote_stale() and not self._fetching:
            self.refresh_nodes()

    def _on_pick(self, node_id: str) -> None:
        self.book.set_current(node_id)
        self.list.current = node_id
        self.list.update()
        self.picked.emit(node_id)
        self.close()

    def _on_remove(self, node_id: str) -> None:
        self.book.remove_proxy(node_id)
        self._fill()
        self.picked.emit(self.book.current_id)

    def _add_proxy(self) -> None:
        from .dialogs import PromptDialog

        dlg = PromptDialog("添加代理节点", "地址，例如 socks5://127.0.0.1:1080", "", self)
        if dlg.exec():
            node = self.book.add_proxy("", dlg.value())
            if node is not None:
                self.seg.set_current("v6" if node.get("v6") else "v4", emit=True)
                self._fill()
                self.picked.emit(self.book.current_id)

    # -------------------------------------------------- 测速
    def measure(self) -> None:
        """代理节点测 TCP 握手；在线节点全部测一遍（并发受控，不漏节点）。"""
        proxies = [n for n in self.list.nodes if n.get("kind") == "proxy" and n.get("host")]
        relays = [n for n in self.list.nodes if n.get("kind") == "relay"]
        if not proxies and not relays:
            self.hint.setText("无可测速节点")
            return
        for n in proxies + relays:
            self.list.ping.pop(n["id"], None)
            self.list.pending.add(n["id"])
        self.list.update()
        self._speed_total = len(proxies) + len(relays)
        self._speed_done = 0

        def finish_one(nid, ms):
            self._speed_done += 1
            self.pinged.emit(nid, ms)
            self.speedProgress.emit(self._speed_done, self._speed_total)

        def proxy_job(node):
            # 必须用信号回主线程：worker 线程里 QTimer 不会触发
            ms = probe_node(node)
            finish_one(node["id"], ms)

        def relay_job(node):
            from .relay import measure_relay

            try:
                ms = measure_relay(node)
            except Exception:  # noqa: BLE001
                ms = None
            finish_one(node["id"], ms)

        for n in proxies:
            self._pool.submit(proxy_job, n)
        for n in relays:
            self._pool.submit(relay_job, n)

    def _on_speed_progress(self, done: int, total: int) -> None:
        if done >= total:
            self.hint.setText(f"已测 {total} 个节点 · 速度仅供参考，不代表可用性")
        else:
            self.hint.setText(f"测速中 {done}/{total} · 速度不代表可用性")

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.elevated))
        p.drawRoundedRect(r, 11, 11)
        p.end()


class NodeButton(Button):
    """URL 栏上的节点按钮：显示当前节点简称。"""

    def __init__(self, parent=None):
        super().__init__("本地", "node", kind="ghost", height=30, padding=8, font_size=11.5,
                         radius=7, tooltip="选择请求节点（默认从本地发出）", parent=parent)
        self.setMinimumWidth(84)

    def set_node(self, node: Dict[str, Any]) -> None:
        if (node or {}).get("kind") == "local":
            self.setText("本地")
            return
        name = node.get("name") or "本地"
        self.setText(name if len(name) <= 5 else name[:5] + "…")
