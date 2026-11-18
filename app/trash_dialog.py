"""回收站：删除的集合 / 文件夹 / 请求先落到这里，可原样恢复。

一个带背景模糊的独立窗口（继承 GlassDialog + BLUR_FIXED），布局刻意做成
「左侧控制 + 右侧列表 + 底部详情」的三段式，和数据编辑区分开：左边管筛选
与时间、右边是条目、底部看详情，操作记录单独一列时间线。全部沿用纯黑简约
主题——靠明暗层次和语义色区分，不用渐变和彩色描边。
"""
from __future__ import annotations

import datetime as _dt
import time
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import i18n
from .store import Store
from .theme import C, S, font, mono, theme
from .widgets import Button, Divider, HBox, Label, SegmentedTabs, VBox, icon_button

from .dialogs import GlassDialog


# ---------------------------------------------------------------- 时间工具
def _fmt_deleted(ts: float) -> str:
    """具体删除时间：今天显示「今天 HH:MM」，否则「YYYY-MM-DD HH:MM」。"""
    try:
        d = _dt.datetime.fromtimestamp(ts)
    except (ValueError, OSError, OverflowError):
        return "-"
    now = _dt.datetime.now()
    if d.date() == now.date():
        return i18n.trf("今天 {t}", t=d.strftime("%H:%M"))
    if d.date() == (now - _dt.timedelta(days=1)).date():
        return i18n.trf("昨天 {t}", t=d.strftime("%H:%M"))
    return d.strftime("%Y-%m-%d %H:%M")


def _fmt_full(ts: float) -> str:
    try:
        return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return "-"


def _method_color(method: str) -> str:
    t = theme()
    return {
        "GET": t.success,
        "POST": t.info,
        "PUT": t.warning,
        "PATCH": t.warning,
        "DELETE": t.danger,
    }.get((method or "").upper(), t.text_dim)


# ---------------------------------------------------------------- 回收站条目列表
class TrashList(QWidget):
    """自绘条目列表：卡片式行、支持 Ctrl / Shift 多选与 hover。"""

    picked = pyqtSignal()                 # 选中变化（详情 / 按钮态刷新）
    activated = pyqtSignal(str)           # 双击：查看该条详情
    ROW_H = 62

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: List[Dict[str, Any]] = []
        self.selected: set = set()
        self._anchor = -1
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def set_items(self, items: List[Dict[str, Any]]) -> None:
        self.items = list(items or [])
        # 清掉已不在列表里的选中项
        ids = {r.get("id") for r in self.items}
        self.selected.intersection_update(ids)
        self.setFixedHeight(max(2, len(self.items)) * self.ROW_H + 6)
        self.update()
        self.picked.emit()

    def _row_at(self, y: float) -> int:
        i = int(y // self.ROW_H)
        return i if 0 <= i < len(self.items) else -1

    def mouseMoveEvent(self, e):  # noqa: N802
        i = self._row_at(e.position().y())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        i = self._row_at(e.position().y())
        if i < 0:
            return
        tid = self.items[i].get("id")
        mods = e.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier or mods & Qt.KeyboardModifier.ShiftModifier:
            if mods & Qt.KeyboardModifier.ShiftModifier and self._anchor >= 0:
                a, b = sorted((self._anchor, i))
                for k in range(a, b + 1):
                    self.selected.add(self.items[k].get("id"))
            else:
                if tid in self.selected:
                    self.selected.discard(tid)
                else:
                    self.selected.add(tid)
                self._anchor = i
        else:
            self.selected = {tid}
            self._anchor = i
        self.update()
        self.picked.emit()

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        i = self._row_at(e.position().y())
        if i >= 0:
            self.activated.emit(self.items[i].get("id"))

    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        # 自绘控件必须自己铺满底色：QScrollArea 的 viewport 默认拿 palette
        # 的浅色 base，不铺就会出现「右边一块白」的割裂。
        p.fillRect(self.rect(), C(t.panel))
        for i, rec in enumerate(self.items):
            r = QRectF(3, i * self.ROW_H + 3, self.width() - 6, self.ROW_H - 6)
            sel = rec.get("id") in self.selected
            if sel:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected))
                p.drawRoundedRect(r, 8, 8)
            elif i == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.hover))
                p.drawRoundedRect(r, 8, 8)

            node = rec.get("node", {})
            is_folder = node.get("type") == "folder"
            # 左侧图标底色块
            bx = r.left() + 9
            by = r.center().y() - 13
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.panel_alt))
            p.drawRoundedRect(QRectF(bx, by, 26, 26), 7, 7)
            p.setPen(C(t.warning if is_folder else _method_color(node.get("method", ""))))
            p.setFont(font(12, weight=QFont.Weight.DemiBold))
            glyph = "▣" if is_folder else str(node.get("method", "?") or "?")[:2]
            p.drawText(QRectF(bx, by, 26, 26),
                       int(Qt.AlignmentFlag.AlignCenter), glyph)

            tx = bx + 36
            # 名称
            p.setPen(C(t.text))
            p.setFont(font(12.2, weight=QFont.Weight.DemiBold))
            name = node.get("name") or i18n.tr("未命名")
            p.drawText(QRectF(tx, r.top() + 9, r.right() - tx - 92, 18),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight,
                                                  int(r.right() - tx - 92)))
            # 副行：方法+URL / 子请求数
            detail = rec.get("_detail", "")
            p.setPen(C(t.text_faint))
            p.setFont(mono(10.3))
            p.drawText(QRectF(tx, r.top() + 28, r.right() - tx - 92, 16),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       p.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight,
                                                  int(r.right() - tx - 92)))
            # 右侧：删除时间
            p.setPen(C(t.text_faint))
            p.setFont(mono(10))
            p.drawText(QRectF(r.right() - 88, r.top() + 12, 80, 18),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       _fmt_deleted(rec.get("deleted_at", 0)))
        p.end()


# ---------------------------------------------------------------- 详情面板
class TrashDetail(QWidget):
    """选中条目的详情：名称 / 类型 / 方法 / URL / 删除时间 / 子项清单。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 12, 14, 12)
        self._lay.setSpacing(7)
        self.show_empty()

    def show_empty(self) -> None:
        self._clear()
        t = theme()
        hint = Label(i18n.tr("选中一条，查看完整详情"), 11, t.text_faint)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lay.addStretch(1)
        self._lay.addWidget(hint)
        self._lay.addStretch(1)

    def _clear(self) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                # setParent(None) 立即从界面摘掉；deleteLater 要等事件循环，
                # 快速切换选中时会看到上一项的文字残留。
                w.setParent(None)
                w.deleteLater()

    def _row(self, label: str, value: str, color: Optional[str] = None,
             mono_value: bool = False) -> None:
        t = theme()
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        lab = Label(label, 10.5, t.text_faint)
        lab.setFixedWidth(72)
        val = Label(value, 11.2, color or t.text, mono_font=mono_value)
        val.setWordWrap(True)
        hl.addWidget(lab, 0, Qt.AlignmentFlag.AlignTop)
        hl.addWidget(val, 1)
        self._lay.addWidget(row)

    def show_record(self, rec: Dict[str, Any]) -> None:
        self._clear()
        t = theme()
        node = rec.get("node", {})
        is_folder = node.get("type") == "folder"
        title = Label(node.get("name") or i18n.tr("未命名"), 13, t.text,
                      weight=QFont.Weight.DemiBold)
        title.setWordWrap(True)
        self._lay.addWidget(title)
        self._lay.addWidget(Divider())

        self._row(i18n.tr("类型"), i18n.tr("文件夹") if is_folder else i18n.tr("请求"))
        if not is_folder:
            method = str(node.get("method") or "GET")
            self._row(i18n.tr("方法"), method, _method_color(method), mono_value=True)
            url = str(node.get("url") or "-")
            self._row("URL", url, t.info, mono_value=True)
        else:
            kids = self._collect_requests(node.get("children") or [])
            self._row(i18n.tr("包含"), i18n.trf("{n} 个请求", n=len(kids)))
        self._row(i18n.tr("删除时间"), _fmt_full(rec.get("deleted_at", 0)),
                  t.text_dim, mono_value=True)
        where = i18n.tr("顶层") if not rec.get("parent_id") else \
            i18n.trf("原文件夹 {id}", id=str(rec.get("parent_id"))[:6])
        self._row(i18n.tr("原位置"), f"{where} · #{int(rec.get('index', 0)) + 1}",
                  t.text_dim)
        self._lay.addStretch(1)

    @staticmethod
    def _collect_requests(children: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for c in children:
            if c.get("type") == "request":
                out.append(c)
            out.extend(TrashDetail._collect_requests(c.get("children") or []))
        return out


# ---------------------------------------------------------------- 操作记录时间线
class TrashOps(QWidget):
    """回收站操作记录：一条一条时间线，带动作色点与具体时间。"""

    OP_TEXT = {
        "delete": ("移入回收站", "warning"),
        "restore": ("已恢复", "success"),
        "purge": ("彻底删除", "danger"),
        "clear": ("清空回收站", "danger"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self.setOps([])

    def setOps(self, ops: List[Dict[str, Any]]) -> None:  # noqa: N802
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        t = theme()
        if not ops:
            hint = Label(i18n.tr("暂无操作记录"), 10.5, t.text_faint)
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._lay.addWidget(hint)
            return
        for op in ops[:60]:
            kind = op.get("op", "delete")
            text, color_key = self.OP_TEXT.get(kind, (kind, "text_dim"))
            color = getattr(t, color_key, t.text_dim)
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 5, 2, 5)
            rl.setSpacing(8)
            dot = Label("●", 9, color)
            dot.setFixedWidth(12)
            dot.setAlignment(Qt.AlignmentFlag.AlignTop)
            rl.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            body = QWidget()
            bl = QVBoxLayout(body)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(1)
            name = op.get("name") or (op.get("detail") or text)
            head = Label(f"{text} · {name}", 10.5, t.text_dim)
            head.setWordWrap(True)
            bl.addWidget(head)
            detail_bits = [x for x in (op.get("detail", ""), _fmt_deleted(op.get("at", 0)))
                           if x and x != name]
            if detail_bits:
                sub = Label("  ·  ".join(detail_bits), 9.5, t.text_faint, mono_font=True)
                sub.setWordWrap(True)
                bl.addWidget(sub)
            rl.addWidget(body, 1)
            self._lay.addWidget(row)
        self._lay.addStretch(1)


# ---------------------------------------------------------------- 主窗口
class TrashDialog(GlassDialog):
    """回收站窗口：恢复 / 彻底删除 / 详情 / 搜索 / 日期范围 / 操作记录。"""

    BLUR_FIXED = True
    changed = pyqtSignal()               # 数据变动，主窗口刷新集合树

    def __init__(self, store: Store, parent=None):
        super().__init__(parent, 940, 620, i18n.tr("回收站"))
        self.store = store
        self._type = "all"
        self._range = "all"
        self._query = ""
        self._build()

    # -------------------------------------------------- 构建
    def _build(self) -> None:
        t = theme()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(16, 10, 16, 14)
        body.setSpacing(10)

        # 顶部统计条
        self.stat_total = Label("0", 19, t.text, mono_font=True,
                                weight=QFont.Weight.DemiBold)
        self.stat_req = Label("0", 19, t.info, mono_font=True,
                              weight=QFont.Weight.DemiBold)
        self.stat_folder = Label("0", 19, t.warning, mono_font=True,
                                 weight=QFont.Weight.DemiBold)
        self.stat_oldest = Label("-", 12, t.text_dim, mono_font=True)
        body.addWidget(self._stat_bar())

        # 主体：左控制 / 右列表+详情
        main = QWidget()
        ml = QHBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(12)
        ml.addWidget(self._left_panel(), 0)
        ml.addWidget(self._right_panel(), 1)
        body.addWidget(main, 1)

        # 底部操作条
        body.addWidget(Divider())
        body.addWidget(self._footer())

        self.reload()

    def _stat_bar(self) -> QWidget:
        t = theme()
        bar = QWidget()
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(2, 0, 2, 0)
        hl.setSpacing(10)

        def cell(num: Label, caption: str, color: Optional[str] = None) -> QWidget:
            w = QWidget()
            vl = QVBoxLayout(w)
            vl.setContentsMargins(14, 8, 14, 8)
            vl.setSpacing(2)
            vl.addWidget(num)
            cap = Label(caption, 10, color or t.text_faint)
            vl.addWidget(cap)
            return w

        hl.addWidget(cell(self.stat_total, i18n.tr("全部条目")))
        hl.addWidget(cell(self.stat_req, i18n.tr("请求")))
        hl.addWidget(cell(self.stat_folder, i18n.tr("文件夹")))
        oldest = QWidget()
        ol = QVBoxLayout(oldest)
        ol.setContentsMargins(14, 8, 14, 8)
        ol.setSpacing(2)
        ol.addWidget(self.stat_oldest)
        ol.addWidget(Label(i18n.tr("最早删除"), 10, t.text_faint))
        hl.addWidget(oldest, 1)
        return bar

    def _left_panel(self) -> QWidget:
        t = theme()
        panel = QWidget()
        panel.setFixedWidth(238)
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(9)

        self.search = QLineEdit()
        self.search.setPlaceholderText(i18n.tr("搜索名称 / URL / 方法"))
        self.search.setFixedHeight(30)
        self.search.textChanged.connect(self._on_search)
        vl.addWidget(self.search)

        self.type_seg = SegmentedTabs(
            [("all", i18n.tr("全部")), ("request", i18n.tr("请求")),
             ("folder", i18n.tr("文件夹"))],
            style="pill", height=26, font_size=11, pad_h=10)
        self.type_seg.changed.connect(self._on_type)
        vl.addWidget(self.type_seg)

        vl.addWidget(Label(i18n.tr("删除时间"), 10, t.text_faint))
        self.range_seg = SegmentedTabs(
            [("all", i18n.tr("不限")), ("today", i18n.tr("今天")),
             ("7d", i18n.tr("7天")), ("30d", i18n.tr("30天")),
             ("custom", i18n.tr("自定义"))],
            style="pill", height=24, font_size=10, pad_h=7)
        self.range_seg.changed.connect(self._on_range)
        vl.addWidget(self.range_seg)

        self.date_row = QWidget()
        dr = QHBoxLayout(self.date_row)
        dr.setContentsMargins(0, 0, 0, 0)
        dr.setSpacing(6)
        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        for w in (self.date_from, self.date_to):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
            w.setDate(_dt.date.today())
        self.date_from.setDate(_dt.date.today() - _dt.timedelta(days=30))
        self.date_from.dateChanged.connect(self._on_dates)
        self.date_to.dateChanged.connect(self._on_dates)
        dr.addWidget(self.date_from, 1)
        dr.addWidget(Label("→", 11, t.text_faint))
        dr.addWidget(self.date_to, 1)
        self.date_row.setVisible(False)
        vl.addWidget(self.date_row)

        vl.addWidget(Label(i18n.tr("操作记录"), 10, t.text_faint))
        self.ops_scroll = QScrollArea()
        self.ops_scroll.setWidgetResizable(True)
        self.ops_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.ops_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.ops = TrashOps()
        self.ops_scroll.setWidget(self.ops)
        self.ops_scroll.viewport().setStyleSheet(
            f"QWidget {{ background: {theme().panel}; }}")
        vl.addWidget(self.ops_scroll, 1)
        return panel

    def _right_panel(self) -> QWidget:
        wrap = QWidget()
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(8)

        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list = TrashList()
        self.list_scroll.setWidget(self.list)
        self.list_scroll.viewport().setStyleSheet(
            f"QWidget {{ background: {theme().panel}; }}")
        self.list.picked.connect(self._on_picked)
        self.list.activated.connect(self._on_activate)
        vl.addWidget(self.list_scroll, 1)

        self.detail = TrashDetail()
        self.detail.setMinimumHeight(140)
        self.detail.setMaximumHeight(176)
        vl.addWidget(self.detail, 0)
        return wrap

    def _footer(self) -> QWidget:
        t = theme()
        bar = QWidget()
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(2, 0, 2, 0)
        hl.setSpacing(8)
        self.count_label = Label("", 10.5, t.text_faint)
        hl.addWidget(self.count_label, 1)

        self.restore_btn = Button(i18n.tr("恢复选中"), "undo", kind="primary",
                                  height=30, padding=14, font_size=11.5)
        self.restore_btn.clicked.connect(self._restore)
        self.purge_btn = Button(i18n.tr("彻底删除"), "close", kind="ghost",
                                height=30, padding=12, font_size=11.5)
        self.purge_btn.clicked.connect(self._purge)
        self.clear_btn = Button(i18n.tr("清空回收站"), "trash", kind="ghost",
                                height=30, padding=12, font_size=11.5)
        self.clear_btn.clicked.connect(self._clear_all)
        self.refresh_btn = icon_button("refresh", i18n.tr("刷新"), 30, 15)
        self.refresh_btn.clicked.connect(self.reload)
        for w in (self.refresh_btn, self.clear_btn, self.purge_btn, self.restore_btn):
            hl.addWidget(w, 0)
        return bar

    # -------------------------------------------------- 数据
    def reload(self) -> None:
        """从 store 重新读回收站 + 操作记录，应用当前筛选后刷新视图。"""
        recs = list(self.store.trash)
        n_req = sum(1 for r in recs if r.get("node", {}).get("type") != "folder")
        n_folder = len(recs) - n_req
        self.stat_total.setText(str(len(recs)))
        self.stat_req.setText(str(n_req))
        self.stat_folder.setText(str(n_folder))
        stamps = [r.get("deleted_at", 0) for r in recs if r.get("deleted_at")]
        self.stat_oldest.setText(_fmt_deleted(min(stamps)) if stamps else "-")

        shown = [r for r in recs if self._match(r)]
        shown.sort(key=lambda r: r.get("deleted_at", 0), reverse=True)
        # 用浅拷贝附带 _detail，避免把展示字段写回 store 数据落盘
        view = [dict(r, _detail=self.store._trash_detail(r.get("node", {})))
                for r in shown]
        self.list.set_items(view)
        self.ops.setOps(list(self.store.trash_ops))
        self.count_label.setText(i18n.trf("显示 {shown} / {total} 项",
                                          shown=len(shown), total=len(recs)))

    def _match(self, rec: Dict[str, Any]) -> bool:
        node = rec.get("node", {})
        is_folder = node.get("type") == "folder"
        if self._type == "request" and is_folder:
            return False
        if self._type == "folder" and not is_folder:
            return False
        ts = rec.get("deleted_at", 0)
        today = _dt.date.today()
        if self._range == "today":
            try:
                if _dt.datetime.fromtimestamp(ts).date() != today:
                    return False
            except (ValueError, OSError, OverflowError):
                return False
        elif self._range in ("7d", "30d"):
            days = 7 if self._range == "7d" else 30
            if ts < time.time() - days * 86400:
                return False
        elif self._range == "custom":
            try:
                d = _dt.datetime.fromtimestamp(ts).date()
            except (ValueError, OSError, OverflowError):
                return False
            if not (self.date_from.date().toPyDate() <= d <= self.date_to.date().toPyDate()):
                return False
        if self._query:
            hay = " ".join(str(x) for x in (
                node.get("name", ""), node.get("method", ""), node.get("url", ""),
                rec.get("_detail", ""))).lower()
            if self._query not in hay:
                return False
        return True

    # -------------------------------------------------- 交互
    def _on_search(self, text: str) -> None:
        self._query = (text or "").strip().lower()
        self.reload()

    def _on_type(self, key: str) -> None:
        self._type = key
        self.reload()

    def _on_range(self, key: str) -> None:
        self._range = key
        self.date_row.setVisible(key == "custom")
        self.reload()

    def _on_dates(self, *_a) -> None:
        if self._range == "custom":
            self.reload()

    def _on_picked(self) -> None:
        ids = set(self.list.selected)
        recs = [r for r in self.list.items if r.get("id") in ids]
        if len(recs) == 1:
            self.detail.show_record(recs[0])
        elif len(recs) > 1:
            t = theme()
            self.detail._clear()
            self.detail._lay.addStretch(1)
            lab = Label(i18n.trf("已选中 {n} 项，可批量恢复或彻底删除", n=len(recs)),
                        11.5, t.info)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.detail._lay.addWidget(lab)
            self.detail._lay.addStretch(1)
        else:
            self.detail.show_empty()
        has = bool(recs)
        self.restore_btn.setEnabled(has)
        self.purge_btn.setEnabled(has)
        self.clear_btn.setEnabled(bool(self.store.trash))

    def _on_activate(self, tid: str) -> None:
        rec = next((r for r in self.list.items if r.get("id") == tid), None)
        if rec is not None:
            self.detail.show_record(rec)

    def _selected_ids(self) -> List[str]:
        return list(self.list.selected)

    def _persist(self) -> None:
        self.store.save()
        self.changed.emit()
        self.reload()

    def _restore(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        done = sum(1 for tid in ids if self.store.restore_from_trash(tid) is not None)
        self._persist()
        self.notify(i18n.trf("已恢复 {n} 项", n=done))

    def _purge(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        from .dialogs import ConfirmDialog
        if not ConfirmDialog.ask(self, i18n.tr("彻底删除"),
                                 i18n.trf("彻底删除选中的 {n} 项？此操作无法恢复。", n=len(ids)),
                                 i18n.tr("彻底删除")):
            return
        done = sum(1 for tid in ids if self.store.purge_from_trash(tid))
        self._persist()
        self.notify(i18n.trf("已彻底删除 {n} 项", n=done))

    def _clear_all(self) -> None:
        n = len(self.store.trash)
        if not n:
            return
        from .dialogs import ConfirmDialog
        if not ConfirmDialog.ask(self, i18n.tr("清空回收站"),
                                 i18n.trf("清空回收站里的全部 {n} 项？此操作无法恢复。", n=n),
                                 i18n.tr("清空")):
            return
        self.store.clear_trash()
        self._persist()
        self.notify(i18n.trf("已清空回收站（{n} 项）", n=n))

    def notify(self, text: str) -> None:
        """借用主窗口的 toast 提示；找不到时静默。"""
        win = self.window()
        toast = getattr(win, "toast", None)
        if toast is not None and hasattr(toast, "show_message"):
            toast.show_message(text, "success")


# ---------------------------------------------------------------- 打开入口
def open_trash(store: Store, parent=None) -> TrashDialog:
    dlg = TrashDialog(store, parent)
    dlg.exec()
    return dlg
