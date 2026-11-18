"""回收站：删除的集合 / 文件夹 / 请求先落到这里，可原样恢复。

带背景模糊的独立窗口（GlassDialog + BLUR_FIXED）。布局刻意做成
「顶部统计条（搜索内嵌右上）+ 左侧筛选 + 右侧列表 / 详情」三段式——
和数据编辑区分开：顶部一眼看全貌、左边管筛选与时间、右边是条目与完整详情。
全部沿用纯黑简约主题：靠明暗层次和语义色区分，不用渐变和彩色描边。
"""
from __future__ import annotations

import datetime as _dt
import time
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QDate, QEasingCurve, QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QCalendarWidget,
    QDateEdit,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import i18n, icons
from .store import Store
from .theme import C, S, font, method_color, mono, theme
from .widgets import (Button, Card, Divider, HBox, Label, SegmentedTabs, VBox,
                      animate, icon_button)

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
    """和主界面共用一套方法配色：GET绿/POST橙/PUT·WS蓝/DELETE红…

    之前这里单独维护一份字典，漏了 WS/HEAD/OPTIONS 等，导致回收站里
    这些请求一律灰字，和侧栏对不上。现在直接走主题的统一映射。
    """
    return method_color(method or "")


# ---------------------------------------------------------------- 日期控件
def _style_date_edit(w: QDateEdit) -> None:
    """把 QDateEdit + 弹出的日历统一成当前纯黑主题。

    Qt 原生日历是白底、红周末、紫选中，扔进深色窗口里非常突兀。这里同时
    给行编辑器和 calendarWidget 挂 QSS，并显式覆盖周末文字格式——周末的
    红色来自星期格式而非 palette，只写 QSS 是盖不掉的。
    """
    t = theme()
    w.setFixedHeight(30)
    w.setStyleSheet(f"""
        QDateEdit {{ background: {t.card}; color: {t.text};
            border: 1px solid {S(t.border)}; border-radius: 6px; padding: 2px 8px; }}
        QDateEdit:focus {{ border: 1px solid {S(t.border_strong)}; }}
        QDateEdit::drop-down {{ width: 20px; border: none; background: transparent; }}
        QDateEdit QAbstractItemView {{ background: {t.panel}; color: {t.text}; }}
    """)
    cal = w.calendarWidget()
    if cal is None:
        return
    cal.setStyleSheet(f"""
        QCalendarWidget {{ background: {t.panel}; border: 1px solid {S(t.border_strong)};
            border-radius: 8px; }}
        QWidget#qt_calendar_navigationbar {{ background: {t.panel_alt};
            border: none; border-top-left-radius: 8px; border-top-right-radius: 8px; }}
        QToolButton {{ color: {t.text_dim}; background: transparent; border: none;
            padding: 5px 7px; }}
        QToolButton:hover {{ background: {S(t.hover)}; border-radius: 5px; }}
        QSpinBox {{ background: {t.card}; color: {t.text}; border: 1px solid {S(t.border)};
            border-radius: 5px; padding: 2px 6px; }}
        QTableView {{ background: {t.panel}; gridline-color: transparent;
            selection-background-color: {S(t.selected)}; }}
        QAbstractItemView {{ color: {t.text}; selection-color: {t.text};
            selection-background-color: {S(t.selected)}; }}
        QAbstractItemView::item:hover {{ background: {S(t.hover)}; }}
        QHeaderView::section {{ background: {t.panel_alt}; color: {t.text_dim};
            border: none; border-bottom: 1px solid {S(t.border)}; padding: 4px 0px; }}
    """)
    # 星期表头（周日~周六）那一行：QSS 的 palette 未必盖得住各平台的原生底，
    # 直接对水平表头逐段上色，彻底压成暗色。
    try:
        header = cal.horizontalHeader() if hasattr(cal, "horizontalHeader") else None
        if header is not None:
            header.setStyleSheet(
                f"QHeaderView::section {{ background: {t.panel_alt}; "
                f"color: {t.text_dim}; border: none; "
                f"border-bottom: 1px solid {S(t.border)}; padding: 4px 0px; }}")
    except Exception:
        pass
    # 周末 / 表头文字：默认红字，显式改成主题前景
    fmt = QColor(t.text)
    from PyQt6.QtGui import QTextCharFormat
    normal = QTextCharFormat()
    normal.setForeground(fmt)
    header = QTextCharFormat()
    header.setForeground(QColor(t.text_dim))
    header.setFont(font(10.5, weight=QFont.Weight.DemiBold))
    for dow in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
        cal.setWeekdayTextFormat(dow, normal)
    cal.setHeaderTextFormat(header)


# ---------------------------------------------------------------- 回收站条目列表
def _group_key(ts: float) -> str:
    """按删除时间归入 1小时内 / 今天 / 昨天 / 7天内 / 30天内 / 更早。"""
    try:
        dt = _dt.datetime.fromtimestamp(ts)
    except (ValueError, OSError, OverflowError):
        return "older"
    now = time.time()
    age = now - ts
    today = _dt.date.today()
    if 0 <= age < 3600:
        return "hour"
    if dt.date() == today:
        return "today"
    if dt.date() == today - _dt.timedelta(days=1):
        return "yesterday"
    if age < 7 * 86400:
        return "week"
    if age < 30 * 86400:
        return "month"
    return "older"


GROUP_DEFS = [
    ("hour",      "1小时内"),
    ("today",     "今天"),
    ("yesterday", "昨天"),
    ("week",      "7天内"),
    ("month",     "30天内"),
    ("older",     "更早"),
]
GROUP_LABELS = {k: lab for k, lab in GROUP_DEFS}


class TrashList(QWidget):
    """自绘条目列表：按删除时间分组、组头可折叠（带动画），支持多选与 hover。"""

    picked = pyqtSignal()                 # 选中变化（按钮态刷新）
    activated = pyqtSignal(str)           # 双击：查看该条详情
    detailRequested = pyqtSignal(str)     # hover 的「详情」小按钮：弹出详情浮层
    ROW_H = 62
    HEADER_H = 32                         # 分组头高度
    DETAIL_W = 46                         # 详情小按钮宽度
    DETAIL_H = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: List[Dict[str, Any]] = []
        self.groups: List[Dict[str, Any]] = []   # {key,label,recs,expanded,factor,anim,top}
        self.selected: set = set()
        self._anchor = -1
        self._hover = -1
        self._hover_group: Optional[str] = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    # -------------------------------------------------- 分组 / 布局
    def set_items(self, items: List[Dict[str, Any]]) -> None:
        self.items = list(items or [])
        ids = {r.get("id") for r in self.items}
        self.selected.intersection_update(ids)
        # 记住哪些组是折叠的，筛选/刷新后保持一致
        collapsed = {g["key"] for g in self.groups if not g["expanded"]}
        buckets: Dict[str, List[Dict[str, Any]]] = {k: [] for k, _ in GROUP_DEFS}
        # 用对象 id 记录原始行号：内容相同的两条记录也不会串位
        row_index = {id(rec): i for i, rec in enumerate(self.items)}
        for rec in self.items:
            buckets.setdefault(_group_key(rec.get("deleted_at", 0)), []).append(rec)
        self.groups = []
        for key, label in GROUP_DEFS:
            recs = buckets.get(key) or []
            if not recs:
                continue
            # 每条记录记住自己的行号，供命中/详情按钮定位（浅拷贝，不写回 store）
            for rec in recs:
                rec["_row_index"] = row_index.get(id(rec), 0)
            self.groups.append({
                # 存中文原文，绘制时再 tr()：切语言后重绘即更新标题
                "key": key, "label": label, "recs": recs,
                "expanded": key not in collapsed,
                "factor": 0.0 if key in collapsed else 1.0, "anim": None, "top": 0.0,
            })
        self._relayout()
        self.picked.emit()

    def _relayout(self) -> None:
        """按各组展开因子重算总高度。折叠动画每帧调用，O(分组数)。"""
        y = 0.0
        for g in self.groups:
            g["top"] = y
            y += self.HEADER_H
            y += len(g["recs"]) * self.ROW_H * g["factor"]
        self.setFixedHeight(max(self.HEADER_H, int(y) + 6))
        self.update()

    def _row_y(self, i: int) -> float:
        """第 i 条记录当前的 y 坐标；被折叠时返回 -1。"""
        for g in self.groups:
            for k, rec in enumerate(g["recs"]):
                if rec.get("_row_index") == i:
                    if g["factor"] < 0.999:
                        return -1.0
                    return g["top"] + self.HEADER_H + k * self.ROW_H
        return -1.0

    def _hit(self, y: float):
        """返回 ('header', group) / ('item', rec) / (None, None)。"""
        for g in self.groups:
            top = g["top"]
            if top <= y < top + self.HEADER_H:
                return "header", g
            body_h = len(g["recs"]) * self.ROW_H * g["factor"]
            if top + self.HEADER_H <= y < top + self.HEADER_H + body_h:
                k = int((y - top - self.HEADER_H) // self.ROW_H)
                if 0 <= k < len(g["recs"]):
                    return "item", g["recs"][k]
        return None, None

    def _row_at(self, y: float) -> int:
        kind, val = self._hit(y)
        return int(val.get("_row_index", -1)) if kind == "item" else -1

    @staticmethod
    def _descendant_node_ids(node: Dict[str, Any]) -> set:
        """文件夹快照里所有子项的 node id（级联勾选 / 去重恢复用）。"""
        out: set = set()
        stack = list(node.get("children") or [])
        while stack:
            cur = stack.pop()
            if cur.get("id"):
                out.add(cur.get("id"))
            stack.extend(cur.get("children") or [])
        return out

    def _cascade(self, tid: str, selected: set) -> None:
        """勾选文件夹时连带勾选它在回收站里独立的子项（若有）。"""
        rec = next((r for r in self.items if r.get("id") == tid), None)
        if not rec or rec.get("node", {}).get("type") != "folder":
            return
        child_ids = self._descendant_node_ids(rec.get("node", {}))
        for r in self.items:
            if r.get("node", {}).get("id") in child_ids:
                selected.add(r.get("id"))

    def _detail_rect(self, i: int) -> QRectF:
        """第 i 条记录「详情」小按钮的命中区域（贴在行右侧、删除时间左边）。"""
        y = self._row_y(i)
        if y < 0:
            return QRectF(-100, -100, 1, 1)
        r = QRectF(3, y + 3, self.width() - 6, self.ROW_H - 6)
        return QRectF(r.right() - 146 - self.DETAIL_W, r.center().y() - self.DETAIL_H / 2,
                      self.DETAIL_W, self.DETAIL_H)

    def _toggle_group(self, g: Dict[str, Any]) -> None:
        """折叠 / 展开一组，factor 0↔1 用动画平滑过渡。"""
        from .anim import stop as _stop
        target = 0.0 if g["expanded"] else 1.0
        g["expanded"] = not g["expanded"]
        start = g["factor"]
        _stop(g.get("anim"))

        def _set(v):
            g["factor"] = float(v)
            self._relayout()

        def _done():
            g["factor"] = target
            self._relayout()

        g["anim"] = animate(self, start, target, 240, _set,
                            QEasingCurve.Type.OutCubic, on_done=_done)

    def mouseMoveEvent(self, e):  # noqa: N802
        kind, val = self._hit(e.position().y())
        i = int(val.get("_row_index", -1)) if kind == "item" else -1
        hg = val.get("key") if kind == "header" else None
        if i != self._hover or hg != self._hover_group:
            self._hover = i
            self._hover_group = hg
            self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = -1
        self._hover_group = None
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        kind, val = self._hit(e.position().y())
        if kind == "header":
            self._toggle_group(val)
            return
        if kind != "item":
            return
        i = int(val.get("_row_index", -1))
        if i < 0:
            return
        # hover 时右侧「详情」小按钮：只弹详情，不改变选中
        if i == self._hover and self._detail_rect(i).contains(e.position()):
            self.detailRequested.emit(self.items[i].get("id"))
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
            self._cascade(tid, self.selected)
        else:
            self.selected = {tid}
            self._anchor = i
            self._cascade(tid, self.selected)
        self.update()
        self.picked.emit()

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        kind, val = self._hit(e.position().y())
        if kind == "item":
            self.activated.emit(val.get("id"))

    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(self.rect(), C(t.panel))
        for g in self.groups:
            top = g["top"]
            # ---- 分组头：chevron + 名称 + 数量（hover 时轻微底色）----
            hr = QRectF(3, top + 2, self.width() - 6, self.HEADER_H - 4)
            if g["key"] == self._hover_group:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.hover))
                p.drawRoundedRect(hr, 7, 7)
            col = QColor(t.text_dim)
            col.setAlphaF(0.55 + 0.45 * g["factor"])
            p.setPen(col)
            p.setFont(font(11, weight=QFont.Weight.DemiBold))
            # 与集合树 / 历史分组完全同款：chevron_right 图标，收起朝右、展开朝下
            icon_col = QColor(t.text_faint)
            icon_col.setAlphaF(0.55 + 0.45 * g["factor"])
            pm = icons.pixmap("chevron_right",
                              icon_col.name(QColor.NameFormat.HexArgb), 11, 2.0)
            p.save()
            p.translate(hr.left() + 12, hr.center().y())
            if g["expanded"]:
                p.rotate(90)
            p.drawPixmap(QPointF(-5.5, -5.5), pm)
            p.restore()
            p.setPen(col)
            # 标题靠左，数量和历史一样贴最右边
            p.drawText(QRectF(hr.left() + 26, hr.top(), hr.width() - 70, hr.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       i18n.tr(g["label"]))
            p.setFont(mono(10))
            p.setPen(C(t.text_faint))
            p.drawText(QRectF(hr.right() - 38, hr.top(), 30, hr.height()),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       str(len(g["recs"])))

            # ---- 组内记录：按 factor 裁剪高度，动画展开时逐行揭示 ----
            body_h = len(g["recs"]) * self.ROW_H * g["factor"]
            if body_h <= 0.5:
                continue
            p.save()
            p.setClipRect(QRectF(0, top + self.HEADER_H, self.width(), body_h))
            for k, rec in enumerate(g["recs"]):
                y = top + self.HEADER_H + k * self.ROW_H
                i = int(rec.get("_row_index", 0))
                r = QRectF(3, y + 3, self.width() - 6, self.ROW_H - 6)
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
                p.setPen(C(t.text))
                p.setFont(font(12.2, weight=QFont.Weight.DemiBold))
                name = node.get("name") or i18n.tr("未命名")
                p.drawText(QRectF(tx, r.top() + 9, r.right() - tx - 146, 18),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                           p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight,
                                                      int(r.right() - tx - 146)))
                detail = rec.get("_detail", "")
                p.setPen(C(t.text_faint))
                p.setFont(mono(10.3))
                p.drawText(QRectF(tx, r.top() + 28, r.right() - tx - 146, 16),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                           p.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight,
                                                      int(r.right() - tx - 146)))
                p.setPen(C(t.text_faint))
                p.setFont(mono(10))
                p.drawText(QRectF(r.right() - 138, r.top() + 12, 130, 18),
                           int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                           _fmt_deleted(rec.get("deleted_at", 0)))
                if i == self._hover:
                    dr = self._detail_rect(i)
                    p.setPen(QPen(C(t.border_strong), 1))
                    p.setBrush(C(t.card))
                    p.drawRoundedRect(dr, dr.height() / 2, dr.height() / 2)
                    p.setPen(C(t.text_dim))
                    p.setFont(font(9.5))
                    p.drawText(dr, int(Qt.AlignmentFlag.AlignCenter), i18n.tr("详情"))
            p.restore()
        p.end()


# ---------------------------------------------------------------- 详情面板
class TrashDetail(QWidget):
    """选中条目的完整详情：身份 / 请求配置 / 环境变量 / 原位置 / 时间。"""

    def __init__(self, store: Optional[Store] = None, parent=None):
        super().__init__(parent)
        self.store = store
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 12, 14, 12)
        self._lay.setSpacing(6)
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

    def _pill_row(self, pills: List) -> None:
        row = HBox(*pills, 1, spacing=6)
        row.layout().setContentsMargins(0, 1, 0, 1)
        self._lay.addWidget(row)

    def _title_row(self, title: str, pills: List) -> None:
        """标题和胶囊同一行：一眼看到名称 + 类型/方法，不再占两行。"""
        lab = Label(title, 13, theme().text, weight=QFont.Weight.DemiBold)
        lab.setWordWrap(True)
        row = HBox(lab, *pills, 1, spacing=8)
        row.layout().setContentsMargins(0, 0, 0, 2)
        self._lay.addWidget(row)

    def _parent_name(self, rec: Dict[str, Any]) -> str:
        pid = rec.get("parent_id")
        if not pid:
            return i18n.tr("顶层")
        if self.store is not None:
            parent = self.store.find(str(pid))
            if parent is not None:
                return str(parent.get("name") or pid)
            # 父文件夹也一起被删了：从回收站快照里找名字
            for other in self.store.trash:
                node = other.get("node", {})
                for cid in TrashList._descendant_node_ids(node) | {node.get("id")}:
                    if cid == pid:
                        return f"{node.get('name') or pid}（{i18n.tr('已删除')}）"
        return i18n.trf("原文件夹 {id}", id=str(pid)[:6])

    def show_record(self, rec: Dict[str, Any]) -> None:
        self._clear()
        t = theme()
        node = rec.get("node", {})
        is_folder = node.get("type") == "folder"
        method = str(node.get("method") or "GET")

        # 标题 + 类型/方法胶囊同一行；详情回到「简单列出」：不重复类型/方法，
        # 只保留 URL、包含、删除时间、原位置几项，干净利落。
        from .widgets import Pill
        if is_folder:
            pills = [Pill(i18n.tr("文件夹"), t.warning, font_size=9.6, height=18)]
        else:
            pills = [Pill(method, _method_color(method), font_size=9.6, height=18),
                     Pill(i18n.tr("请求"), t.text_dim, font_size=9.6, height=18)]
        self._title_row(node.get("name") or i18n.tr("未命名"), pills)
        self._lay.addWidget(Divider())

        if not is_folder:
            self._row("URL", str(node.get("url") or "-"), t.info, mono_value=True)
            # 请求配置：把参数 / 请求头 / 正文 / Cookie / 认证都列出来，填满浮层，
            # 恢复前不用切回主界面就能看清这条请求到底带了什么。
            n_params = len(node.get("params") or [])
            n_headers = len(node.get("headers") or [])
            n_cookies = len(node.get("cookies") or [])
            body = node.get("body") or {}
            if isinstance(body, dict):
                mode = str(body.get("mode") or "-")
                content = body.get("content")
                if isinstance(content, str) and content.strip():
                    mode += i18n.trf(" · {n} 字", n=len(content))
            else:
                mode = i18n.tr("有内容")
            self._row(i18n.tr("参数"), i18n.trf("{n} 项", n=n_params), t.text_dim)
            self._row(i18n.tr("请求头"), i18n.trf("{n} 项", n=n_headers), t.text_dim)
            self._row(i18n.tr("正文"), mode, t.text_dim)
            if n_cookies:
                self._row("Cookie", i18n.trf("{n} 项", n=n_cookies), t.text_dim)
            auth = node.get("auth") or {}
            if isinstance(auth, dict) and auth.get("type") and auth.get("type") != "none":
                self._row(i18n.tr("认证"), str(auth.get("type")), t.text_dim)
            # 环境变量：列出引用到的变量名，缺失的用警告色提示
            if self.store is not None:
                refs = self.store.env_refs(node)
                if refs:
                    missing = set(self.store.missing_env_refs(node))
                    txt = ", ".join("{{" + r + "}}" +
                                    (i18n.tr("（未定义）") if r in missing else "")
                                    for r in refs)
                    self._row(i18n.tr("环境变量"), txt,
                              t.warning if missing else t.text_dim, mono_value=True)
        else:
            kids = self._collect_requests(node.get("children") or [])
            self._row(i18n.tr("包含"), i18n.trf("{n} 个请求", n=len(kids)))
            if kids:
                names = "、".join(str(k.get("name") or "?") for k in kids[:6])
                if len(kids) > 6:
                    names += i18n.trf(" 等 {n} 项", n=len(kids))
                self._row(i18n.tr("子请求"), names, t.text_dim)
        self._row(i18n.tr("删除时间"), _fmt_full(rec.get("deleted_at", 0)),
                  t.text_dim, mono_value=True)
        where = self._parent_name(rec)
        self._row(i18n.tr("原位置"), f"{where} · #{int(rec.get('index', 0)) + 1}",
                  t.text_dim)

    @staticmethod
    def _collect_requests(children: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for c in children:
            if c.get("type") == "request":
                out.append(c)
            out.extend(TrashDetail._collect_requests(c.get("children") or []))
        return out


# ---------------------------------------------------------------- 详情浮层
class DetailPopup(QWidget):
    """点「详情」小按钮弹出的轻量浮层：无模糊、点外部即关，不占常驻空间。"""

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._card = Card(radius=11, parent=self)
        lay = QVBoxLayout(self._card)
        lay.setContentsMargins(2, 2, 2, 2)
        # 内容变多：加滚动区，最多显示到 MAX_H，超出的字段可滚，不再撑爆窗口
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail = TrashDetail(store, self._card)
        self.detail_scroll.setWidget(self.detail)
        self.detail_scroll.viewport().setStyleSheet(
            f"QWidget {{ background: {theme().card}; }}")
        lay.addWidget(self.detail_scroll)
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.addWidget(self._card)
        self.MAX_H = 430
        self.setFixedSize(500, 300)

    def show_record(self, rec: Dict[str, Any], anchor: QPoint) -> None:
        self.detail.show_record(rec)
        # 按内容实际高度调整浮层：至少 220，最多 MAX_H，超出用滚动区
        hint = self.detail.sizeHint().height()
        h = max(220, min(self.MAX_H, hint + 20))
        self.setFixedSize(500, h)
        # 贴在锚点下方，超出屏幕则翻到上方；水平居中于锚点
        pos = QPoint(anchor.x() - self.width() // 2, anchor.y() + 12)
        screen = self.screen()
        if screen is not None:
            geo = screen.availableGeometry()
            if pos.x() < geo.left() + 8:
                pos.setX(geo.left() + 8)
            if pos.x() + self.width() > geo.right() - 8:
                pos.setX(geo.right() - self.width() - 8)
            if pos.y() + self.height() > geo.bottom() - 8:
                pos.setY(max(geo.top() + 8, anchor.y() - self.height() - 12))
        self.move(pos)
        self.show()
        self.raise_()


# ---------------------------------------------------------------- 操作动画
class ActionFlash(QWidget):
    """清空 / 恢复 / 彻底删除后的 lightweight 艺术反馈。

    单个透明覆盖层：一圈扩散的细环 + 中心图标淡入上浮 + 一行文案。
    全程一个 QVariantAnimation 驱动 paintEvent，不建额外窗口、不起线程，
    动画结束自动隐藏，资源占用极低；关动效时会由调用方直接跳过。
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._p = 0.0
        self._icon = "trash"
        self._text = ""
        self._color = None
        self._anim = None
        self.hide()

    def play(self, icon: str, text: str, color: str) -> None:
        """在父控件中央播放一次动画。"""
        host = self.parentWidget()
        if host is None:
            return
        self._icon, self._text, self._color = icon, text, color
        self.setGeometry(host.rect())
        self.raise_()
        self.show()

        def _set(v):
            self._p = float(v)
            self.update()

        def _done():
            self.hide()

        from .anim import stop as _stop
        _stop(self._anim)
        # 1220ms：比原来多约 0.5 秒，扩散环与图标上浮更从容、更耐看
        self._anim = animate(self, 0.0, 1.0, 1220, _set,
                             QEasingCurve.Type.OutCubic, on_done=_done)

    def paintEvent(self, _e):  # noqa: N802
        if not (0.0 < self._p < 1.0) or not self._text:
            return
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        c = QColor(self._color or t.accent)
        cx, cy = self.width() / 2, self.height() / 2

        # 半透明底：淡入再淡出，避免闪一下硬块
        env = min(1.0, self._p * 6, (1.0 - self._p) * 6)
        veil = QColor(t.window)
        veil.setAlpha(int(150 * env))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(veil)
        p.drawRect(self.rect())

        # 扩散细环：半径随进度增大、透明度递减
        ring = c
        ring.setAlpha(int(150 * (1.0 - self._p)))
        pen = QPen(ring, 1.6)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        radius = 26 + 74 * self._p
        p.drawEllipse(QRectF(cx - radius, cy - radius - 16, radius * 2, radius * 2))

        # 中心图标：淡入 + 轻微上浮
        alpha = env
        pm = icons.pixmap(self._icon, c.name(QColor.NameFormat.HexArgb), 30, 1.7)
        p.setOpacity(alpha)
        p.drawPixmap(QPointF(cx - 15, cy - 15 - 16 - 5 * (1.0 - self._p)), pm)
        # 文案
        p.setPen(QColor(c.red(), c.green(), c.blue(), int(235 * alpha)))
        p.setFont(font(12.5, weight=QFont.Weight.DemiBold))
        p.drawText(QRectF(cx - 160, cy + 4, 320, 22),
                   int(Qt.AlignmentFlag.AlignCenter), self._text)
        p.setOpacity(1.0)
        p.end()


# ---------------------------------------------------------------- 主窗口
class TrashDialog(GlassDialog):
    """回收站窗口：恢复 / 彻底删除 / 详情 / 搜索 / 日期范围 / 自动清理。"""

    BLUR_FIXED = True
    changed = pyqtSignal()               # 数据变动，主窗口刷新集合树
    restored = pyqtSignal(list)          # 恢复完成，携带 node_id 列表（侧边栏定位）

    def __init__(self, store: Store, parent=None):
        super().__init__(parent, 1030, 620, i18n.tr("回收站"))
        self.store = store
        self._type = "all"
        self._range = "all"
        self._query = ""
        self._flash = ActionFlash(self.body)
        self._build()

    # -------------------------------------------------- 构建
    def _build(self) -> None:
        t = theme()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(16, 10, 16, 14)
        body.setSpacing(10)

        # 顶部统计条：左侧数字 + 右侧搜索框（搜索内嵌在这里，不占左栏位置）
        body.addWidget(self._stat_bar())

        # 主体：左筛选 / 极细分隔线 / 右删除记录
        main = QWidget()
        ml = QHBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(11)
        ml.addWidget(self._left_panel(), 0)
        # 1px 分隔线：只在视觉上分栏，不用重色块
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setObjectName("TrashSep")
        sep.setStyleSheet(f"QWidget#TrashSep {{ background: {S(t.border)}; }}")
        ml.addWidget(sep, 0)
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
        hl.setSpacing(8)

        def cell(num: Label, caption: str, color: Optional[str] = None) -> QWidget:
            w = QWidget()
            vl = QVBoxLayout(w)
            vl.setContentsMargins(14, 8, 14, 8)
            vl.setSpacing(2)
            vl.addWidget(num)
            cap = Label(caption, 10, color or t.text_faint)
            vl.addWidget(cap)
            return w

        self.stat_total = Label("0", 19, t.text, mono_font=True,
                                weight=QFont.Weight.DemiBold)
        self.stat_req = Label("0", 19, t.info, mono_font=True,
                              weight=QFont.Weight.DemiBold)
        self.stat_folder = Label("0", 19, t.warning, mono_font=True,
                                 weight=QFont.Weight.DemiBold)
        # 三项统计紧凑靠左，其余空间留给搜索框
        for w, cap, col in (
            (self.stat_total, i18n.tr("全部条目"), None),
            (self.stat_req, i18n.tr("请求"), t.info),
            (self.stat_folder, i18n.tr("文件夹"), t.warning),
        ):
            hl.addWidget(cell(w, cap, col))
        hl.addStretch(1)

        # 搜索框放右上，和统计条同一行；显式描边，避免和深色背景糊在一起
        self.search = QLineEdit()
        self.search.setPlaceholderText(i18n.tr("搜索名称 / URL / 方法"))
        self.search.setFixedSize(268, 30)
        self.search.setStyleSheet(f"""
            QLineEdit {{ background: {t.card}; color: {t.text};
                border: 1px solid {S(t.border_strong)}; border-radius: 6px;
                padding: 0 10px; }}
            QLineEdit:focus {{ border: 1px solid {S(t.accent)}; }}
        """)
        self.search.textChanged.connect(self._on_search)
        hl.addWidget(self.search, 0, Qt.AlignmentFlag.AlignVCenter)
        return bar

    def _left_panel(self) -> QWidget:
        t = theme()
        panel = QWidget()
        # 加宽侧栏：英文下 Any time / Today / 7 days / 30 days / Custom
        # 五个 pill 实际宽度约 322，284 时 Custom 仍会被切，这里给到 334。
        panel.setFixedWidth(334)
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(9)

        vl.addWidget(Label(i18n.tr("类型"), 10, t.text_faint))
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
        dr.setSpacing(5)
        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        for w in (self.date_from, self.date_to):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
            w.setDate(QDate.currentDate())
            _style_date_edit(w)
        self.date_from.setDate(QDate.currentDate().addDays(-30))
        self.date_from.dateChanged.connect(self._on_dates)
        self.date_to.dateChanged.connect(self._on_dates)
        dr.addWidget(self.date_from, 1)
        dr.addWidget(Label("→", 11, t.text_faint))
        dr.addWidget(self.date_to, 1)
        self.date_row.setVisible(False)
        vl.addWidget(self.date_row)

        # 自动清理提示：设置里开关，这里只说明当前策略
        days = self.store.trash_keep_days()
        on = bool(self.store.settings.get("trash_enabled", True))
        tip = (i18n.trf("自动清理已开启：超过 {n} 天的条目在启动时清除。", n=days)
               if on else i18n.tr("自动清理已关闭"))
        hint = Label(tip, 10, t.text_faint)
        hint.setWordWrap(True)
        vl.addSpacing(4)
        vl.addWidget(hint)
        vl.addStretch(1)
        return panel

    def _right_panel(self) -> QWidget:
        """右侧整块给删除记录；详情改成 hover 行内的小按钮弹出浮层。"""
        wrap = QWidget()
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(2)

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
        self.list.detailRequested.connect(self._show_detail)
        vl.addWidget(self.list_scroll, 1)

        # 详情浮层：点行内「详情」小按钮时弹出，用完即走
        self._detail_popup = DetailPopup(self.store, self)
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
        self.refresh_btn.clicked.connect(self._refresh)
        # 点击先转一圈，再读盘，交互有明确反馈
        self.refresh_btn.clicked.connect(self.refresh_btn.spin_once)
        for w in (self.refresh_btn, self.clear_btn, self.purge_btn, self.restore_btn):
            hl.addWidget(w, 0)
        return bar

    # -------------------------------------------------- 数据
    def reload(self) -> None:
        """从 store 重新读回收站，应用当前筛选后刷新视图。"""
        recs = list(self.store.trash)
        n_req = sum(1 for r in recs if r.get("node", {}).get("type") != "folder")
        n_folder = len(recs) - n_req
        self.stat_total.setText(str(len(recs)))
        self.stat_req.setText(str(n_req))
        self.stat_folder.setText(str(n_folder))

        shown = [r for r in recs if self._match(r)]
        shown.sort(key=lambda r: r.get("deleted_at", 0), reverse=True)
        # 用浅拷贝附带 _detail，避免把展示字段写回 store 数据落盘
        view = [dict(r, _detail=self.store._trash_detail(r.get("node", {})))
                for r in shown]
        self.list.set_items(view)
        self.count_label.setText(i18n.trf("显示 {shown} / {total} 项",
                                          shown=len(shown), total=len(recs)))
        self._on_picked()

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
                self.store._trash_detail(node))).lower()
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
        """详情不再常驻，这里只维护底部按钮状态。"""
        has = bool(self.list.selected)
        self.restore_btn.setEnabled(has)
        self.purge_btn.setEnabled(has)
        self.clear_btn.setEnabled(bool(self.store.trash))

    def _on_activate(self, tid: str) -> None:
        # 双击等价于点详情
        self._show_detail(tid)

    def _show_detail(self, tid: str) -> None:
        """行内「详情」按钮 / 双击：在鼠标附近弹出轻量详情浮层。"""
        rec = next((r for r in self.list.items if r.get("id") == tid), None)
        if rec is None:
            return
        popup = self._detail_popup
        # 锚点：该行右侧按钮的屏幕坐标；拿不到就用鼠标当前位置
        row = next((i for i, r in enumerate(self.list.items) if r.get("id") == tid), -1)
        if row >= 0:
            anchor = self.list.mapToGlobal(
                self.list._detail_rect(row).center().toPoint())
        else:
            from PyQt6.QtGui import QCursor
            anchor = QCursor.pos()
        popup.show_record(rec, anchor)

    def _selected_ids(self) -> List[str]:
        return list(self.list.selected)

    def _persist(self) -> None:
        self.store.save()
        self.changed.emit()
        self.reload()

    def _flash_action(self, icon: str, text: str, key: str) -> None:
        """操作完成后的轻量艺术动画；关动效时 animate 会直接跳到终态。"""
        try:
            self._flash.play(icon, text, getattr(theme(), key, theme().accent))
        except Exception:
            pass  # 动画是锦上添花，绝不因为反馈影响真正的删除/恢复

    def _refresh(self) -> None:
        """刷新按钮：重新读盘，让其它窗口 / 外部改动的删除能立即反映出来。"""
        try:
            from .store import Store as _Store
            disk = _Store.load(self.store.path)
            self.store.data.clear()
            self.store.data.update(disk.data)
        except Exception:
            pass
        self.reload()
        self.notify(i18n.tr("回收站已刷新"))

    def _restore_notes(self, recs: List[Dict[str, Any]]) -> List[str]:
        """恢复前的级联 / 环境变量提示（文件夹含几个请求、变量是否缺失）。"""
        notes: List[str] = []
        for rec in recs:
            node = rec.get("node", {})
            name = node.get("name") or i18n.tr("未命名")
            if node.get("type") == "folder":
                n = self.store.trash_request_count(node)
                if n:
                    notes.append(i18n.trf("{name} 里还有 {n} 个请求，会一起恢复。",
                                          name=f"「{name}」", n=n))
            if self.store is not None:
                missing = self.store.missing_env_refs(node)
                if missing:
                    vars_txt = "、".join("{{" + m + "}}" for m in missing)
                    notes.append(i18n.trf("{name} 引用了环境变量 {vars}，当前环境未定义，"
                                          "恢复后请检查。", name=f"「{name}」", vars=vars_txt))
        return notes

    def _restore(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        recs = [r for r in self.list.items if r.get("id") in ids]
        # 级联提示：文件夹连带子请求 + 环境变量缺失
        notes = self._restore_notes(recs)
        if notes:
            from .dialogs import ConfirmDialog
            msg = "\n".join(notes) + "\n\n" + i18n.tr("确认恢复吗？")
            if not ConfirmDialog.ask(self, i18n.tr("恢复前请确认"), msg,
                                     i18n.tr("继续恢复")):
                return
        # 去重：文件夹已含某请求快照时，不再单独恢复那条独立记录
        nested: set = set()
        for rec in recs:
            if rec.get("node", {}).get("type") == "folder":
                nested |= TrashList._descendant_node_ids(rec.get("node", {}))
        restorable = [tid for tid in ids
                      if next((r.get("node", {}).get("id") for r in recs
                               if r.get("id") == tid), None) not in nested]
        done_ids: List[str] = []
        for tid in restorable:
            node = self.store.restore_from_trash(tid)
            if node is not None and node.get("id"):
                done_ids.append(node["id"])
        self._persist()
        self.restored.emit(done_ids)
        self._flash_action("undo", i18n.trf("已恢复 {n} 项", n=len(done_ids)), "success")
        self.notify(i18n.trf("已恢复 {n} 项", n=len(done_ids)))

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
        self._flash_action("close", i18n.trf("已彻底删除 {n} 项", n=done), "danger")
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
        self._flash_action("trash", i18n.trf("已清空回收站（{n} 项）", n=n), "danger")
        self.notify(i18n.trf("已清空回收站（{n} 项）", n=n))

    def notify(self, text: str) -> None:
        """借用主窗口的 toast 提示；找不到时静默。

        对话框本身是顶层窗口，self.window() 拿到的就是它、没有 toast；
        所以显式沿 parent 链找主窗口，刷新 / 恢复的反馈用户才看得见。
        """
        node = self.parentWidget()
        while node is not None:
            toast = getattr(node, "toast", None)
            if toast is not None and hasattr(toast, "show_message"):
                toast.show_message(text, "success")
                return
            node = node.parentWidget()


# ---------------------------------------------------------------- 打开入口
def open_trash(store: Store, parent=None) -> TrashDialog:
    dlg = TrashDialog(store, parent)
    dlg.exec()
    return dlg
