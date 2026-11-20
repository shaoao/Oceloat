"""左侧边栏：集合树（文件夹/请求）+ 请求历史。

自绘委托实现 iOS/macOS 风格的圆角悬停与选中态，鼠标移入有淡入动效；
集合树支持拖拽排序、右键菜单、搜索过滤与内联折叠。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import (
    QEasingCurve,
    QModelIndex,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import i18n, icons
from .code_editor import human_elapsed
from .store import Store, new_folder, new_request
from .anim import stop as _anim_stop
from .theme import (C, method_color, method_short, paint_kind_dot, px,
                    status_color, font, mono, theme)
from .widgets import Button, HBox, Label, Menu, animate, icon_button

ROLE_ID = Qt.ItemDataRole.UserRole
ROLE_TYPE = Qt.ItemDataRole.UserRole + 1
ROLE_DATA = Qt.ItemDataRole.UserRole + 2


# ---------------------------------------------------------------- 删除飞入动画
class TrashFly(QWidget):
    """删除时一个小垃圾图标沿抛物线飞向右上角回收站按钮并淡出。

    单个 QVariantAnimation 驱动 paintEvent，不建窗口、不起线程、不驻留定时器，
    动画结束即隐藏；关动效时 animate 直接跳终态。占用资源极少，也带一点诗意。
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._p = 0.0
        self._start = QPointF()
        self._end = QPointF()
        self.hide()

    def fly(self, start: QPointF, end: QPointF) -> None:
        host = self.parentWidget()
        if host is None:
            return
        self._start, self._end = start, end
        self.setGeometry(host.rect())
        self.raise_()
        self.show()

        def _set(v):
            self._p = float(v)
            self.update()

        def _done():
            self.hide()
            self._p = 0.0

        _anim_stop(getattr(self, "_anim", None))
        self._anim = animate(self, 0.0, 1.0, 520, _set,
                             QEasingCurve.Type.InOutCubic, on_done=_done)

    def paintEvent(self, _e):  # noqa: N802
        if not (0.0 < self._p < 1.0):
            return
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        # 二次贝塞尔：控制点在起终点上方，形成一条轻轻上抛再落下的弧线
        s, e = self._start, self._end
        ctrl = QPointF((s.x() + e.x()) / 2, min(s.y(), e.y()) - 56)
        u = 1.0 - self._p
        x = u * u * s.x() + 2 * u * self._p * ctrl.x() + self._p * self._p * e.x()
        y = u * u * s.y() + 2 * u * self._p * ctrl.y() + self._p * self._p * e.y()
        # 后段淡出 + 缩小：飞到按钮里时几乎消失
        fade = 1.0 if self._p < 0.62 else max(0.0, (1.0 - self._p) / 0.38)
        scale = 1.0 - 0.45 * self._p
        size = 26 * scale
        p.setOpacity(fade)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.panel_alt))
        p.drawRoundedRect(QRectF(x - size / 2, y - size / 2, size, size), size / 3, size / 3)
        pm = icons.pixmap("trash", QColor(t.danger).name(QColor.NameFormat.HexArgb),
                          14 * scale, 1.7)
        p.drawPixmap(QPointF(x - pm.width() / 2, y - pm.height() / 2), pm)
        p.setOpacity(1.0)
        p.end()


# ---------------------------------------------------------------- 新建文件夹聚焦动画
class FocusPulse(QWidget):
    """新建文件夹后，在目标行画一圈扩散的高亮细环，随后淡出。

    单个 QVariantAnimation 驱动，动画结束即隐藏，不占常驻定时器。
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._p = 0.0
        self._rect = QRectF()
        self.hide()

    def play(self, rect: QRectF) -> None:
        host = self.parentWidget()
        if host is None:
            return
        self._rect = rect
        self.setGeometry(host.rect())
        self.raise_()
        self.show()

        def _set(v):
            self._p = float(v)
            self.update()

        def _done():
            self.hide()
            self._p = 0.0

        _anim_stop(getattr(self, "_anim", None))
        self._anim = animate(self, 0.0, 1.0, 520, _set,
                             QEasingCurve.Type.OutCubic, on_done=_done)

    def paintEvent(self, _e):  # noqa: N802
        if not (0.0 < self._p < 1.0) or self._rect.isNull():
            return
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fade = 1.0 - self._p
        grow = 3.0 + self._p * 5.0
        r = self._rect.adjusted(-grow, -grow, grow, grow)
        # QPen 没有 setAlphaF：透明度要放在颜色上，否则新建文件夹时直接崩
        ring = C(t.accent)
        ring.setAlphaF(max(0.0, min(1.0, fade)))
        pen = QPen(ring)
        pen.setWidthF(1.6 * fade + 0.4)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 8, 8)
        p.end()


# ---------------------------------------------------------------- 历史删除动画
class HistoryVanish(QWidget):
    """历史行删除时的轻量消散动画：抓一张快照，细扫线掠过 + 细环扩散 + 淡出收拢。

    整段只有一个 QVariantAnimation，不建窗口、不起线程；清空时使用整块视口快照，
    单条删除只抓那一行，动画结束立刻隐藏并释放快照。
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._p = 0.0
        self._shots: List[Tuple[QPixmap, QRectF]] = []
        self.hide()

    def vanish(self, shots: List[Tuple[QPixmap, QRectF]], duration: int = 720) -> None:
        host = self.parentWidget()
        shots = [(pm, r) for pm, r in shots if not pm.isNull()]
        if host is None or not shots:
            return
        self._shots = shots
        self.setGeometry(host.rect())
        self.raise_()
        self.show()

        def _set(v):
            self._p = float(v)
            self.update()

        def _done():
            self.hide()
            self._p = 0.0
            self._shots = []

        _anim_stop(getattr(self, "_anim", None))
        self._anim = animate(self, 0.0, 1.0, duration, _set,
                             QEasingCurve.Type.Linear, on_done=_done)

    def paintEvent(self, _e):  # noqa: N802
        if not (0.0 < self._p < 1.0) or not self._shots:
            return
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        for idx, (pm, rect) in enumerate(self._shots):
            delay = min(0.18, idx * 0.045)
            span = max(0.3, 1.0 - delay)
            u = min(1.0, max(0.0, (self._p - delay) / span))
            e = u * u * (3.0 - 2.0 * u)          # smoothstep：起步轻、收尾稳
            alpha = 1.0 - 0.85 * e
            dpr = pm.devicePixelRatio() or 1.0
            w, h = pm.width() / dpr, pm.height() / dpr
            # 从右往左把旧行擦掉：原位收缩，不飘到下一行上糊成一团
            visible = max(0.0, 1.0 - e)
            y = rect.top() - 3.0 * e
            target = QRectF(rect.left(), y, w * visible, h)
            source = QRectF(0, 0, pm.width() * visible, pm.height())

            p.save()
            p.setOpacity(alpha)
            p.drawPixmap(target, pm, source)
            p.restore()

            # 一道主题色细扫线：跟着擦除边界从右往左收，像被轻轻抹掉
            sweep = QColor(t.accent)
            sweep.setAlpha(int(150 * alpha))
            p.setPen(QPen(sweep, 1.2))
            sx = rect.left() + w * visible
            p.drawLine(QPointF(sx, y), QPointF(sx, y + h))

            # 行尾一圈极淡的扩散环：给删除一点「噗」的呼吸感
            ring = QColor(t.text_faint)
            ring.setAlpha(int(110 * alpha * (1.0 - u)))
            p.setPen(QPen(ring, 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            rr = 10.0 + 34.0 * u
            p.drawEllipse(QRectF(rect.right() - 18.0 - rr,
                                 rect.center().y() - 3.0 * e - rr * 0.55,
                                 rr * 2, rr * 1.1))
        p.end()


# ---------------------------------------------------------------- 搜索框


class SearchField(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, placeholder: str = "搜索", parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self._edit = QLineEdit()
        self._edit.setObjectName("Bare")
        i18n.placeholder(self._edit, placeholder)
        self._edit.setFont(font(12))
        self._edit.setFixedHeight(24)
        self._edit.textChanged.connect(self.changed.emit)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 0, 8, 0)
        lay.setSpacing(6)
        self._icon = Label("", 12)
        self._icon.setFixedSize(13, 13)
        lay.addWidget(self._icon)
        lay.addWidget(self._edit, 1)
        self._focused = False
        self._edit.installEventFilter(self)
        self._refresh_icon()

    def _refresh_icon(self):
        t = theme()
        col = t.text if self._focused else t.text_faint
        self._icon.setPixmap(icons.pixmap("search", col, 13, 1.7))

    def eventFilter(self, obj, event):
        if obj is self._edit:
            if event.type() == event.Type.FocusIn:
                self._focused = True
                self._refresh_icon()
                self.update()
            elif event.type() == event.Type.FocusOut:
                self._focused = False
                self._refresh_icon()
                self.update()
        return super().eventFilter(obj, event)

    def text(self) -> str:
        return self._edit.text()

    def clear(self):
        self._edit.clear()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._edit.clear()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(C(t.border_strong if self._focused else t.border), 1))
        p.setBrush(C(t.panel_alt if not self._focused else t.elevated))
        p.drawRoundedRect(r, 7, 7)
        p.end()


# ---------------------------------------------------------------- 集合树委托


class TreeDelegate(QStyledItemDelegate):
    def __init__(self, tree: "CollectionsTree"):
        super().__init__(tree)
        self.tree = tree

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        # 行高跟着文字大小走：150% 时 29px 会把两行字挤在一起
        return QSize(0, px(29))

    # -------------------------------------------------- 就地重命名
    def createEditor(self, parent, option, index):  # noqa: N802
        """新建文件夹后直接就地输入名字；样式与列表的纯色卡片一致。"""
        item = self.tree.itemFromIndex(index)
        editor = QLineEdit(parent)
        editor.setObjectName("Bare")
        editor.setFont(font(12.5))
        editor.setText(str((item.data(0, ROLE_DATA) or {}).get("name", "")))
        editor.setFrame(False)
        editor.setStyleSheet(
            f"QLineEdit {{ background: {theme().elevated}; color: {theme().text};"
            f" border: 1px solid {theme().accent}; border-radius: 6px; padding: 0 6px; }}")
        editor.selectAll()
        return editor

    def updateEditorGeometry(self, editor, option, index):  # noqa: N802
        item = self.tree.itemFromIndex(index)
        rect = QRectF(option.rect).adjusted(5, 2, -6, -2)
        # 文件夹的文字起点在缩进箭头之后
        if (item.data(0, ROLE_DATA) or {}).get("type") == "folder":
            rect.adjust(24, 0, 0, 0)
        editor.setGeometry(rect.toRect())

    def setModelData(self, editor, model, index):  # noqa: N802
        text = editor.text().strip()
        if not text:
            return
        item = self.tree.itemFromIndex(index)
        if item is not None:
            self.tree.renameCommitted.emit(str(item.data(0, ROLE_ID)), text)

    def paint(self, p: QPainter, option, index: QModelIndex) -> None:
        t = theme()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        item = self.tree.itemFromIndex(index)
        if item is None:
            p.restore()
            return
        node = item.data(0, ROLE_DATA) or {}
        is_folder = node.get("type") == "folder"
        rect = QRectF(option.rect).adjusted(5, 2, -6, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = self.tree.hover_alpha(item)

        if selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.selected))
            p.drawRoundedRect(rect, 6, 6)
            # 左侧一条 2.5px 的主题色标记：换主题色时整条侧栏的「选中」也跟着变
            bar = QRectF(rect.left() + 2.0, rect.center().y() - 6.5, 2.5, 13)
            p.setBrush(C(t.accent))
            p.drawRoundedRect(bar, 1.25, 1.25)
        elif hover > 0.01:
            c = C(t.hover)
            c.setAlpha(int(c.alpha() * hover))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(rect, 6, 6)

        x = rect.left() + 7
        cy = rect.center().y()
        text_color = C(t.text) if selected else (C(t.text) if hover > 0.5 else C(t.text_dim))

        if is_folder:
            # 展开箭头
            icon_col = C(t.text_dim if selected or hover > 0.4 else t.text_faint)
            pm = icons.pixmap("chevron_right", icon_col.name(QColor.NameFormat.HexArgb), 11, 2.0)
            p.save()
            p.translate(x + 5.5, cy)
            if item.isExpanded():
                p.rotate(90)
            p.drawPixmap(QPointF(-5.5, -5.5), pm)
            p.restore()
            x += 17
            count = len(node.get("children") or [])
            count_text = str(count) if count else ""
            p.setFont(font(12.5, QFont.Weight.DemiBold))
            avail = rect.width() - (x - rect.left()) - (px(18) if count_text else 6)
            name = QFontMetricsF(p.font()).elidedText(node.get("name", ""), Qt.TextElideMode.ElideRight, avail)
            p.setPen(text_color)
            p.drawText(QRectF(x, rect.top(), avail, rect.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)
            if count_text:
                p.setFont(mono(9.5))
                p.setPen(C(t.text_faint))
                p.drawText(QRectF(rect.right() - px(18), rect.top(), px(14), rect.height()),
                           int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), count_text)
        else:
            method = (node.get("method") or "GET").upper()
            mcol = C(method_color(method, t))
            if not selected and hover < 0.5:
                mcol = QColor(mcol)
                mcol.setAlpha(200)
            # 类型灯：HTTP 显示方法色，WS / SIO / SSE 显示协议色，一眼分清请求类型
            paint_kind_dot(p, x + 4, cy, method_color(method, t),
                           radius=px(2.8))
            x += px(14)
            p.setFont(mono(9, QFont.Weight.DemiBold))
            p.setPen(mcol)
            # 方法列宽按字号一起放大，否则 150% 下 POST 会被裁成 POS
            mw = px(36)
            p.drawText(QRectF(x, rect.top(), mw, rect.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       method_short(method))
            x += mw + 2
            is_open = node.get("id") in self.tree.open_ids
            avail = rect.right() - x - (12 if is_open else 4)
            p.setFont(font(12.5))
            name = QFontMetricsF(p.font()).elidedText(node.get("name", ""), Qt.TextElideMode.ElideRight, max(avail, 20))
            p.setPen(text_color)
            p.drawText(QRectF(x, rect.top(), avail, rect.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)
            if is_open:
                # 打开态用小图标代替原来的圆点
                pm = icons.pixmap("external", t.text_faint, 10, 1.7)
                p.drawPixmap(QPointF(rect.right() - 13, cy - 5), pm)
        p.restore()


# ---------------------------------------------------------------- 集合树


class CollectionsTree(QTreeWidget):
    openRequest = pyqtSignal(dict)          # 双击：固定打开
    previewRequest = pyqtSignal(dict)       # 单击：VSCode 式预览（复用预览标签）
    structureChanged = pyqtSignal()
    requestContext = pyqtSignal(str, QPoint)  # node_id, global pos
    renameCommitted = pyqtSignal(str, str)   # 就地重命名：node_id, 新名字

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIndentation(13)
        self.setRootIsDecorated(False)
        # 隐藏 Qt 自带的展开三角（委托里已经画了一个，否则会出现两个箭头）
        self.setStyleSheet(
            "QTreeView::branch { background: transparent; image: none; border-image: none; }")
        self.setItemDelegate(TreeDelegate(self))
        self.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setExpandsOnDoubleClick(False)
        # 编辑只在新建文件夹后由代码显式 editItem 触发；双击仍按原来的
        # 预览 / 折叠语义走，不会因为加了 ItemIsEditable 就误进改名框。
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.open_ids: Set[str] = set()
        self._hover_item: Optional[QTreeWidgetItem] = None
        self._hover_v = 0.0
        # 基类会把「选中行」整行（含缩进区）涂一层 Highlight，缩进区就露出一块方形灰底。
        # 选中态我们自己在委托里画圆角胶囊，所以把 Highlight 置为全透明。
        from PyQt6.QtGui import QPalette

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0, 0))
        self.setPalette(pal)
        # 常驻动画：绝不能用 DeleteWhenStopped（底层对象被删后 Python 包装器仍被引用，
        # 下一次 .stop() 就会 RuntimeError: wrapped C/C++ object has been deleted）
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setStartValue(0.0)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.setDuration(140)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover)
        self.itemClicked.connect(self._on_click)
        self.itemDoubleClicked.connect(self._on_double_click)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)

    # -------------------------------------------------- 悬停动效
    def drawBranches(self, painter, rect, index):  # noqa: N802
        """禁用基类的缩进区绘制。

        基类会把「选中行」的缩进区涂成一块灰色方块（截图里行左侧那个灰框），
        展开箭头我们自己在委托里画，这里什么都不做即可。
        """
        return

    def hover_alpha(self, item: QTreeWidgetItem) -> float:
        if item is self._hover_item:
            return self._hover_v
        return 0.0

    def mouseMoveEvent(self, e):  # noqa: N802
        item = self.itemAt(e.position().toPoint())
        if item is not self._hover_item:
            self._hover_item = item
            _anim_stop(self._hover_anim)
            self._hover_v = 0.0
            self._hover_anim.start()
        # 视口才是真正接收鼠标的控件：悬停条目时给手型，空白区保持箭头
        if e.buttons() == Qt.MouseButton.NoButton:
            self.viewport().setCursor(
                Qt.CursorShape.PointingHandCursor if item is not None
                else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)

    def _on_hover(self, v):
        self._hover_v = float(v)
        self.viewport().update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover_item = None
        self._hover_v = 0.0
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().update()
        super().leaveEvent(e)

    # -------------------------------------------------- 交互
    def _on_click(self, item: QTreeWidgetItem, _col: int) -> None:
        node = item.data(0, ROLE_DATA) or {}
        if node.get("type") == "folder":
            item.setExpanded(not item.isExpanded())
        else:
            self.previewRequest.emit(node)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        node = item.data(0, ROLE_DATA) or {}
        if node.get("type") == "request":
            self.openRequest.emit(node)

    def _on_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        node = item.data(0, ROLE_DATA) or {}
        self.requestContext.emit(node.get("id", ""), self.viewport().mapToGlobal(pos))

    def dropEvent(self, event):  # noqa: N802
        super().dropEvent(event)
        self.structureChanged.emit()


# ---------------------------------------------------------------- 历史行


class HistoryRow(QWidget):
    clicked = pyqtSignal(dict)
    removeRequested = pyqtSignal(str)

    def __init__(self, entry: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hover = False
        self._hover_v = 0.0
        self._anim: Optional[QVariantAnimation] = None

    def enterEvent(self, e):
        self._hover = True
        self._start(1.0)
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self._start(0.0)
        self.update()

    def _start(self, target):
        _anim_stop(self._anim)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(self._hover_v)
        self._anim.setEndValue(target)
        self._anim.setDuration(130)
        self._anim.valueChanged.connect(self._on_v)
        self._anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_v(self, v):
        self._hover_v = float(v)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._hover_v > 0.3 and e.position().x() > self.width() - 32:
            self.removeRequested.emit(self.entry.get("id", ""))
            return
        self.clicked.emit(self.entry)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(6, 2, -6, -2)
        if self._hover_v > 0.01:
            c = C(t.hover)
            c.setAlpha(int(c.alpha() * self._hover_v))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(r, 7, 7)
        e = self.entry
        status = int(e.get("status") or 0)
        method = (e.get("method") or "GET").upper()
        mcol = C(method_color(method, t))
        # 类型灯：和集合树、标签页同一颗，历史里也能按颜色分清 HTTP / WS / SSE
        paint_kind_dot(p, r.left() + 12, r.top() + 12,
                       method_color(method, t), radius=px(2.8))
        p.setFont(mono(9, QFont.Weight.DemiBold))
        p.setPen(mcol)
        p.drawText(QRectF(r.left() + 24, r.top() + 5, 36, 14),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   method_short(method))
        # URL（起点跟着方法列一起右移，给类型灯腾位置）
        p.setFont(mono(11.2))
        p.setPen(C(t.text) if self._hover_v > 0.4 else C(t.text_dim))
        url = e.get("url", "")
        avail = r.width() - 62 - 22
        text = QFontMetricsF(p.font()).elidedText(url, Qt.TextElideMode.ElideMiddle, avail)
        p.drawText(QRectF(r.left() + 56, r.top() + 3, avail, 17),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        # 元信息
        p.setFont(mono(9.5))
        sc = C(status_color(status, t)) if status else C(t.text_faint)
        p.setPen(sc)
        meta = f"{status}" if status else "ERR"
        p.drawText(QRectF(r.left() + 56, r.top() + 20, 42, 16),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), meta)
        p.setPen(C(t.text_faint))
        rel = time.strftime("%H:%M", time.localtime(e.get("ts", 0)))
        p.drawText(QRectF(r.left() + 96, r.top() + 20, max(r.width() - 126, 40), 16),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   f"{rel}  ·  {human_elapsed(int(e.get('elapsed') or 0))}")
        if self._hover_v > 0.25:
            p.setOpacity(min(1.0, self._hover_v))
            pm = icons.pixmap("close", t.text_dim, 10, 1.9)
            p.drawPixmap(QPointF(r.right() - 17, r.center().y() - 5), pm)
            p.setOpacity(1.0)
        p.end()


class HistoryGroupHeader(QWidget):
    """历史分组标题：与集合树同款折叠箭头 + 文案 + 条数，点击可折叠。"""

    clicked = pyqtSignal(str)             # 携带分组 key

    def __init__(self, label: str, count: int, group_key: str = "",
                 collapsed: bool = False, parent=None, label_kwargs=None):
        super().__init__(parent)
        # label 始终存中文原文，绘制时才 tr()，语言切换后立即生效
        self.label = label
        self._label_kwargs = label_kwargs or {}
        self.count = count
        self.group_key = group_key
        self.collapsed = collapsed
        self.setFixedHeight(30)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False
        self._hover_v = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_hover)

    def _on_hover(self, v) -> None:
        self._hover_v = float(v)
        self.update()

    def enterEvent(self, e):  # noqa: N802
        self._hover = True
        _anim_stop(self._anim)
        self._anim.setStartValue(self._hover_v)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False
        _anim_stop(self._anim)
        self._anim.setStartValue(self._hover_v)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(e)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.group_key)
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        # 悬停浅色底色，和历史行 / 集合树同一套 hover 色
        if self._hover_v > 0.01:
            c = C(t.hover)
            c.setAlpha(int(c.alpha() * self._hover_v))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(3, 2, self.width() - 6, self.height() - 4), 7, 7)
        # 与集合树同款 chevron_right：收起朝右，展开旋转 90° 朝下
        icon_col = C(t.text_faint)
        pm = icons.pixmap("chevron_right", icon_col.name(QColor.NameFormat.HexArgb), 11, 2.0)
        p.save()
        p.translate(12, self.height() / 2)
        if not self.collapsed:
            p.rotate(90)
        p.drawPixmap(QPointF(-5.5, -5.5), pm)
        p.restore()
        p.setFont(font(11.2, QFont.Weight.Medium))
        p.setPen(C(t.text_dim))
        # 文案按中文原文存，绘制时才 tr()：这样切语言后立即生效，
        # 不必重建列表（也避免快速路径的 _hist_header 与当前语言失配）。
        p.drawText(QRectF(26, 0, self.width() - 70, self.height()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   self.title())
        p.setFont(mono(10))
        p.setPen(C(t.text_faint))
        p.drawText(QRectF(self.width() - 40, 0, 30, self.height()),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                   str(self.count))
        p.end()

    def title(self) -> str:
        """当前语言的分组标题；self.label 始终是中文原文。"""
        if self._label_kwargs:
            return i18n.trf(self.label, **self._label_kwargs)
        return i18n.tr(self.label)

    def refresh_theme(self) -> None:
        """语言/主题切换后重绘（文案在 paintEvent 里按当前语言实时翻译）。"""
        self.update()


def _within_hour(ts: float) -> bool:
    """最近 1 小时内（允许 60s 时钟误差），用于单独分组。"""
    return ts > 0 and (time.time() - ts) <= 3600 + 60


def _history_group_key(ts: float) -> str:
    """分组的稳定 key，与显示语言无关，用于持久化折叠状态。"""
    if _within_hour(ts):
        return "1h"  # 与「今天」区分，折叠状态互不串扰
    return datetime.fromtimestamp(ts or 0).strftime("%Y-%m-%d")


def _history_group(ts: float) -> str:
    """分组的中文原文（不翻译！绘制时由 HistoryGroupHeader 按当前语言 tr）。

    最近 1 小时单独成组，其余按本地日期归到 今天 / 昨天 / N 天前。
    返回中文原文是关键：切语言后 apply_language 走 refresh_theme 重绘，
    标题立刻变；若这里直接存译文，切语言后分组标题会一直停在旧语言。
    """
    if _within_hour(ts):
        return "1小时内"
    day = datetime.fromtimestamp(ts or 0).date()
    today = datetime.now().date()
    delta = (today - day).days
    if delta <= 0:
        return "今天"
    if delta == 1:
        return "昨天"
    if delta < 7:
        return "{n} 天前"
    return datetime.fromtimestamp(ts or 0).strftime("%Y-%m-%d")


def _history_group_kwargs(ts: float) -> Dict[str, int]:
    """分组文案需要的格式化参数（目前只有「N 天前」用到 n）。"""
    if _within_hour(ts):
        return {}
    day = datetime.fromtimestamp(ts or 0).date()
    delta = (datetime.now().date() - day).days
    return {"n": delta} if 1 < delta < 7 else {}


# ---------------------------------------------------------------- 侧边栏


def _count_requests(node: Dict[str, Any]) -> int:
    """数一个文件夹底下有多少个请求（删除确认里要用）。"""
    total = 1 if node.get("type") == "request" else 0
    for child in node.get("children") or []:
        total += _count_requests(child)
    return total


class Sidebar(QWidget):
    openRequest = pyqtSignal(dict)          # 双击：固定打开
    previewRequest = pyqtSignal(dict)       # 单击：预览
    requestDeleted = pyqtSignal(str)
    runFolder = pyqtSignal(str)             # 右键「运行集合」：folder node id
    transferRequested = pyqtSignal()        # 搜索框右侧的导入 / 导出按钮
    trashRequested = pyqtSignal()           # 打开回收站
    changed = pyqtSignal()
    notify = pyqtSignal(str)

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self._mode = "collections"
        self.open_ids: Set[str] = set()
        self._build()
        # 删除飞入动画：挂在最上层，鼠标事件穿透，不影响集合树交互
        self._trash_fly = TrashFly(self)
        self._history_vanish = HistoryVanish(self)
        self._focus_pulse = FocusPulse(self)
        self.tree.renameCommitted.connect(self.rename_node)
        # 刚建出来的节点（id, 它的父级）：连续新建时用来判断该建兄弟还是建子级
        self._last_created: Optional[Dict[str, Any]] = None
        self.refresh()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        for overlay in (getattr(self, "_trash_fly", None),
                        getattr(self, "_history_vanish", None),
                        getattr(self, "_focus_pulse", None)):
            if overlay is not None and not overlay.isHidden():
                overlay.setGeometry(self.rect())

    # -------------------------------------------------- 构建
    def _build(self) -> None:
        self.setMinimumWidth(200)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 10)
        root.setSpacing(8)

        # 顶部：模式切换
        from .widgets import SegmentedTabs

        self.seg = SegmentedTabs([("collections", "集合"), ("history", "历史")],
                                 style="pill", parent=self, height=26, pad_h=12, font_size=12)
        self.seg.changed.connect(self._on_mode)
        root.addWidget(self.seg)

        self.search = SearchField("搜索请求、URL 或方法")
        self.search.changed.connect(self._apply_filter)
        # 搜索框右侧只留导入 / 导出；回收站移到底部操作条原来「新建文件夹」的位置，
        # 因为「新建请求」下拉里已经包含新建文件夹，两处重复。
        self.transfer_btn = icon_button("transfer", "导入 / 导出集合", 28, 14)
        self.transfer_btn.clicked.connect(self.transferRequested.emit)
        root.addWidget(HBox((self.search, 1), self.transfer_btn, spacing=6))

        # 集合树
        self.tree = CollectionsTree()
        self.tree.openRequest.connect(self.openRequest.emit)
        self.tree.previewRequest.connect(self.previewRequest.emit)
        self.tree.structureChanged.connect(self._on_structure_changed)
        self.tree.requestContext.connect(self._show_context)
        self.tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # QTreeView 的列头边界会给出 SplitHCursor；集合树没有可调列宽，统一回普通箭头。
        # 视口不能钉死箭头：条目上的手型在 CollectionsTree.mouseMoveEvent 里按悬停切换。
        for w in (self.tree, self.tree.header()):
            w.setCursor(Qt.CursorShape.ArrowCursor)
        self.tree.viewport().unsetCursor()
        root.addWidget(self.tree, 1)

        # 历史
        self.history_host = QWidget()
        self.history_lay = QVBoxLayout(self.history_host)
        self.history_lay.setContentsMargins(0, 4, 0, 0)
        self.history_lay.setSpacing(0)
        self.history_lay.addStretch(1)
        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.history_scroll.setWidget(self.history_host)
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_scroll.hide()
        # 子控件自己带 PointingHandCursor；视口不要强制覆盖，否则悬停只剩箭头
        self.history_scroll.viewport().unsetCursor()
        root.addWidget(self.history_scroll, 1)

        # 底部操作条：新建请求（下拉里含新建文件夹）+ 回收站。
        # 回收站入口带一个角标显示条目数（0 时隐藏），删除动画也飞向这里。
        self.new_btn = Button("新建请求", "plus", kind="subtle", height=28, padding=10,
                              radius=7, font_size=12, parent=self)
        self.new_btn.clicked.connect(self._new_menu)
        self.trash_btn = icon_button("trash", i18n.tr("回收站"), 28, 14)
        self.trash_btn.clicked.connect(self.trashRequested.emit)
        bottom = HBox(self.new_btn, 1, self.trash_btn, spacing=4,
                      margins=(0, 2, 0, 0))
        root.addWidget(bottom)

    # -------------------------------------------------- 模式
    def _on_mode(self, key: str) -> None:
        self._mode = key
        is_col = key == "collections"
        self.tree.setVisible(is_col)
        self.history_scroll.setVisible(not is_col)
        self.new_btn.setText("新建请求" if is_col else "清空历史")
        self.new_btn.set_icon("plus" if is_col else "trash")
        # 切换集合 / 历史时保留搜索词，让搜索对两个页面都直接生效
        self._apply_filter(self.search.text())
        if is_col:
            self.refresh()
        else:
            self.refresh_history()

    def _sync_trash_badge(self) -> None:
        n = len(self.store.trash) if hasattr(self.store, "trash") else 0
        self.trash_btn.setToolTip(i18n.trf("回收站 · {n} 项", n=n) if n
                                  else i18n.tr("回收站（空）"))

    # -------------------------------------------------- 集合树
    def refresh(self) -> None:
        self._sync_trash_badge()
        expanded = self._expanded_ids()
        self.tree.blockSignals(True)
        self.tree.clear()
        self.tree.open_ids = self.open_ids
        for node in self.store.collections:
            self._add_item(None, node, expanded)
        self.tree.blockSignals(False)
        self._apply_filter(self.search.text())

    def _expanded_ids(self) -> Set[str]:
        out: Set[str] = set()
        for i in range(self.tree.topLevelItemCount()):
            self._collect_expanded(self.tree.topLevelItem(i), out)
        return out

    def _collect_expanded(self, item: QTreeWidgetItem, out: Set[str]) -> None:
        if item.isExpanded():
            out.add(item.data(0, ROLE_ID))
        for i in range(item.childCount()):
            self._collect_expanded(item.child(i), out)

    def _add_item(self, parent, node: Dict[str, Any], expanded: Set[str]) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent) if parent else QTreeWidgetItem(self.tree)
        item.setData(0, ROLE_ID, node.get("id"))
        item.setData(0, ROLE_TYPE, node.get("type"))
        item.setData(0, ROLE_DATA, node)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        if node.get("type") == "folder":
            flags |= Qt.ItemFlag.ItemIsDropEnabled | Qt.ItemFlag.ItemIsEditable
        item.setFlags(flags)
        if node.get("type") == "folder":
            for child in node.get("children", []):
                self._add_item(item, child, expanded)
            should = node.get("id") in expanded or (not expanded and node.get("open"))
            item.setExpanded(bool(should))
        return item

    def _on_structure_changed(self) -> None:
        self.store.data["collections"] = self._tree_to_nodes()
        self.store.save()
        self.changed.emit()
        self.refresh()

    def _tree_to_nodes(self) -> List[Dict[str, Any]]:
        def walk(item: QTreeWidgetItem) -> Dict[str, Any]:
            node = dict(item.data(0, ROLE_DATA) or {})
            if node.get("type") == "folder":
                node["open"] = item.isExpanded()
                node["children"] = [walk(item.child(i)) for i in range(item.childCount())]
            return node

        return [walk(self.tree.topLevelItem(i)) for i in range(self.tree.topLevelItemCount())]

    def _history_match(self, entry: Dict[str, Any], text: str) -> bool:
        """历史条目是否命中搜索词：方法 / URL / 名称 / 状态码都算。"""
        if not text:
            return True
        req = entry.get("request") or {}
        fields = (str(entry.get("method") or req.get("method") or ""),
                  str(entry.get("url") or req.get("url") or ""),
                  str(req.get("name") or ""),
                  str(entry.get("status") or ""))
        return any(text in f.lower() for f in fields)

    def _apply_filter(self, text: str) -> None:
        text = (text or "").strip().lower()

        # 历史模式：按数据过滤行，空组头一起隐藏，切到「历史」后搜索框直接生效
        if self._mode == "history":
            for row in getattr(self, "_hist_rows", []):
                row.setVisible(self._history_match(row.entry, text))
            for header, rows in getattr(self, "_hist_groups", []):
                header.setVisible(not text or any(r.isVisible() for r in rows))
            return

        def walk(item: QTreeWidgetItem) -> bool:
            node = item.data(0, ROLE_DATA) or {}
            hit = (not text) or text in (node.get("name", "").lower()) \
                or text in (node.get("url", "").lower()) \
                or text == (node.get("method", "").lower())
            child_hit = False
            for i in range(item.childCount()):
                child_hit = walk(item.child(i)) or child_hit
            visible = hit or child_hit
            item.setHidden(not visible)
            if text and child_hit:
                item.setExpanded(True)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def _selected_folder(self) -> Optional[str]:
        item = self.tree.currentItem()
        while item is not None:
            node = item.data(0, ROLE_DATA) or {}
            if node.get("type") == "folder":
                return node.get("id")
            item = item.parent()
        return None

    def set_open_ids(self, ids: Set[str]) -> None:
        self.open_ids = ids
        self.tree.open_ids = ids
        self.tree.viewport().update()

    def refresh_theme(self) -> None:
        """语言 / 主题切换后：重译 tooltip 并重绘（行内文案在 paintEvent 里实时翻译）。"""
        self.transfer_btn.setToolTip(i18n.tr("导入 / 导出集合"))
        self._sync_trash_badge()
        self.tree.viewport().update()
        if self._mode == "history":
            self.refresh_history()

    def _find_item(self, node_id: str) -> Optional[QTreeWidgetItem]:
        """按 node id 在树里找条目（深度优先，命中即返回）。"""
        def walk(parent) -> Optional[QTreeWidgetItem]:
            count = parent.childCount() if parent is not None else self.tree.topLevelItemCount()
            for i in range(count):
                item = parent.child(i) if parent is not None else self.tree.topLevelItem(i)
                if item.data(0, ROLE_ID) == node_id:
                    return item
                hit = walk(item)
                if hit is not None:
                    return hit
            return None

        return walk(None)

    def reveal(self, node_id: Optional[str]) -> None:
        """把左侧列表定位到某条请求：切回集合页、展开父级、滚动到位并高亮。

        点上面的标签页时调用 —— 用户不用再去树里自己找是哪一条。
        """
        if not node_id:
            return
        if self._mode != "collections":
            self.seg.set_current("collections", emit=False)
            self._on_mode("collections")
        # 搜索把目标过滤掉了就先清空过滤，否则 scrollToItem 落在隐藏行上没反应
        item = self._find_item(node_id)
        if item is None:
            return
        if item.isHidden():
            self.search.clear()
            self._apply_filter("")
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)

    def expand_node(self, node_id: Optional[str]) -> None:
        """展开某个节点（导入完展示新集合用）。"""
        item = self._find_item(node_id) if node_id else None
        if item is not None and item.childCount():
            item.setExpanded(True)

    # -------------------------------------------------- 增删改
    def _new_menu(self) -> None:
        """「新建请求」：先选类型（HTTP / WebSocket / Socket.IO）再建。"""
        if self._mode == "history":
            self._clear_history()
            return
        t = theme()
        menu = Menu(self)
        a_http = menu.addAction(icons.icon("send", t.text, 14), i18n.tr("HTTP 请求"))
        a_ws = menu.addAction(icons.icon("link", t.text, 14), i18n.tr("WebSocket 请求"))
        a_sio = menu.addAction(icons.icon("link", method_color("SIO", t), 14),
                               i18n.tr("Socket.IO 请求"))
        a_sse = menu.addAction(icons.icon("send", method_color("SSE", t), 14),
                               i18n.tr("SSE 请求"))
        menu.addSeparator()
        a_folder = menu.addAction(icons.icon("folder", t.text, 14), i18n.tr("新建文件夹"))
        pos = self.new_btn.mapToGlobal(QPoint(0, 0))
        pos.setY(pos.y() - menu.sizeHint().height() - 4)
        chosen = menu.exec(pos)
        if chosen is a_http:
            self._new_request()
        elif chosen is a_ws:
            self.create_request_in(self._selected_folder(), "WS")
        elif chosen is a_sio:
            self.create_request_in(self._selected_folder(), "SIO")
        elif chosen is a_sse:
            self.create_request_in(self._selected_folder(), "SSE")
        elif chosen is a_folder:
            self._new_folder()

    def _new_request(self) -> None:
        if self._mode == "history":
            self._clear_history()
            return
        node = new_request("Untitled Request")
        node["params"] = []
        self.store.add_node(self._selected_folder(), node)
        self.store.save()
        self.refresh()
        self.openRequest.emit(node)
        self.notify.emit("已创建请求")
        self.changed.emit()

    def _new_folder(self, parent_id: Optional[str] = None) -> None:
        """新建文件夹。

        连着点几次「新建文件夹」应该得到一排平级文件夹，而不是一层套一层 ——
        新建后焦点会落在刚建的那一项上，所以只有「焦点还在刚建的这个」时，
        才把落点退回它的父级。手动选了别处，就按选中的位置来。
        """
        if self._mode != "collections":
            # 在历史 / 搜索里点新建，建完必须能看见，而不是悄悄落进树里
            self.seg.set_current("collections", emit=False)
            self._on_mode("collections")
        target = parent_id if parent_id is not None else self._creation_parent()
        node = new_folder(self._unique_name("New Folder", target))
        self.store.add_node(target, node)
        self.store.save()
        self.refresh()
        self.changed.emit()
        self._last_created = {"id": node.get("id"), "parent": target}
        self._focus_new_node(node.get("id"))

    def _creation_parent(self) -> Optional[str]:
        """新节点该落在哪一级。"""
        last = self._last_created or {}
        current = self.tree.currentItem()
        node = (current.data(0, ROLE_DATA) or {}) if current is not None else {}
        if last and node.get("id") == last.get("id"):
            return last.get("parent")
        return self._selected_folder()

    def _unique_name(self, base: str, parent_id: Optional[str]) -> str:
        """同级里重名会让树看着发糊，默认名自动加序号。"""
        parent = self.store.find(parent_id) if parent_id else None
        siblings = (parent.get("children") if parent is not None
                    else self.store.collections) or []
        names = {str(n.get("name") or "") for n in siblings if isinstance(n, dict)}
        if base not in names:
            return base
        n = 2
        while f"{base} {n}" in names:
            n += 1
        return f"{base} {n}"

    def _focus_new_node(self, node_id: Optional[str]) -> None:
        """焦点跳到新建节点：滚动居中 + 高亮脉冲 + 就地改名输入框。

        默认名字已经写进数据；用户直接回车 / 点别处就保留默认，输入则替换。
        """
        if not node_id or self._mode != "collections":
            return
        item = self._find_item(node_id)
        if item is None:
            return
        parents = []
        parent = item.parent()
        while parent is not None:
            parents.append(parent)
            parent = parent.parent()
        for p in reversed(parents):
            p.setExpanded(True)
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
        self.tree.viewport().update()
        rect = self.tree.visualItemRect(item)
        if rect.isValid() and not rect.isEmpty():
            local = self.tree.mapTo(self, QRectF(rect).center().toPoint())
            pulse = getattr(self, "_focus_pulse", None)
            if pulse is not None:
                pulse.play(QRectF(local.x() - rect.width() / 2 + 8,
                                  local.y() - rect.height() / 2,
                                  rect.width() - 16, rect.height()))
        # 就地编辑：编辑框里已选中默认名，输入即替换，不输入保持默认
        self.tree.editItem(item, 0)

    def create_request_in(self, parent_id: Optional[str], method: str = "GET", url: str = "") -> Dict:
        node = new_request("Untitled Request", method, url)
        upper = (method or "").upper()
        if upper == "WS":
            from .ws_panel import default_ws

            node["name"] = "WebSocket Request"
            node["ws"] = default_ws()
        elif upper == "SIO":
            from .sio_panel import default_sio

            node["name"] = "Socket.IO Request"
            node["sio"] = default_sio()
        elif upper == "SSE":
            from .sse_panel import default_sse

            node["name"] = "SSE Request"
            node["sse"] = default_sse()
        self.store.add_node(parent_id, node)
        self.store.save()
        self.refresh()
        self.openRequest.emit(node)
        self.changed.emit()
        return node

    def _clear_history(self) -> None:
        if not self.store.history:
            self.notify.emit(i18n.tr("无历史记录"))
            return
        from .dialogs import ConfirmDialog

        if not ConfirmDialog.ask(self.window(), i18n.tr("清空历史"),
                                 i18n.tr("清空全部历史记录？集合与环境变量不受影响，但历史无法恢复。"),
                                 i18n.tr("清空")):
            return
        # 先抓当前视口快照，再清数据：旧内容以消散动画退出，不生硬闪没
        shots = self._history_snapshots()
        self._history_vanish.vanish(shots, 780)
        self.store.clear_history()
        self.store.save()
        self.refresh_history()
        self.notify.emit(i18n.tr("历史已清空"))

    def rename_node(self, node_id: str, name: str) -> None:
        node = self.store.find(node_id)
        if node is None or not name.strip():
            return
        node["name"] = name.strip()
        self.store.save()
        self.refresh()
        self.changed.emit()

    def set_node_method(self, node_id: str, method: str) -> None:
        """请求方式在编辑器里改了 → 集合树里的徽标同步跟上。

        只动当前这一项的数据并重绘一行，不重建整棵树（重建会丢滚动位置和
        正在进行的拖拽），也不覆盖用户的其它编辑。
        """
        node = self.store.find(node_id)
        if node is None or node.get("type") != "request":
            return
        method = (method or "GET").upper()
        if (node.get("method") or "GET").upper() == method:
            return
        node["method"] = method
        item = self._find_item(node_id)
        if item is not None:
            item.setData(0, ROLE_DATA, node)
        self.tree.viewport().update()
        self.store.save()

    def delete_node(self, node_id: str, confirm: bool = True) -> None:
        node = self.store.find(node_id)
        if node is None:
            return
        if confirm and not self._confirm_delete(node):
            return
        name = node.get("name", "")
        # 删除前先记住这条在树里的位置，作为飞行动画起点（相对 Sidebar）
        start = None
        item = self._find_item(node_id)
        if item is not None:
            rect = self.tree.visualItemRect(item)
            if rect.isValid() and not rect.isEmpty():
                local = self.tree.mapTo(self, rect.center())
                start = QPointF(local.x(), local.y())
        # 删除改为移入回收站：误删可在回收站原样恢复，无需再吓唬用户「无法撤销」。
        self.store.move_to_trash(node_id)
        self.store.save()
        self.refresh()
        # 小垃圾图标沿弧线飞向右上角回收站按钮
        fly = getattr(self, "_trash_fly", None)
        if fly is not None and start is not None:
            c = self.trash_btn.mapTo(self, self.trash_btn.rect().center())
            fly.fly(start, QPointF(c.x(), c.y()))
        self.requestDeleted.emit(node_id)
        self.notify.emit(i18n.trf("已把「{name}」移入回收站", name=name))
        self.changed.emit()

    def _confirm_delete(self, node: Dict[str, Any]) -> bool:
        """删除前确认 —— 现在只是移入回收站，仍可恢复，文案说清楚。"""
        from .dialogs import ConfirmDialog

        name = node.get("name") or i18n.tr("未命名")
        if node.get("type") == "folder":
            count = _count_requests(node)
            title = i18n.tr("移入回收站")
            message = i18n.trf("「{name}」里还有 {n} 个请求，会一起移入回收站，可随时恢复。",
                               name=name, n=count) if count else \
                i18n.trf("把「{name}」移入回收站？可随时恢复。", name=name)
        else:
            title = i18n.tr("移入回收站")
            message = i18n.trf("把「{name}」移入回收站？可随时恢复。", name=name)
        return ConfirmDialog.ask(self.window(), title, message, i18n.tr("移入回收站"))

    def duplicate_node(self, node_id: str) -> None:
        self.store.duplicate_node(node_id)
        self.store.save()
        self.refresh()
        self.notify.emit("已创建副本")
        self.changed.emit()

    # -------------------------------------------------- 右键菜单
    def _show_context(self, node_id: str, global_pos: QPoint) -> None:
        node = self.store.find(node_id)
        if node is None:
            return
        t = theme()
        menu = Menu(self)
        is_folder = node.get("type") == "folder"
        act_new = menu.addAction(icons.icon("plus", t.text, 14), i18n.tr("新建请求"))
        act_folder = (menu.addAction(icons.icon("folder", t.text, 14), i18n.tr("新建文件夹"))
                      if is_folder else None)
        menu.addSeparator()
        act_run = (menu.addAction(icons.icon("play", t.text, 14), i18n.tr("运行集合"))
                   if is_folder else None)
        if act_run is not None:
            menu.addSeparator()
        act_auth = (menu.addAction(icons.icon("lock", t.text, 14), i18n.tr("设置认证…"))
                    if is_folder else None)
        act_export = (menu.addAction(icons.icon("download", t.text, 14),
                                     i18n.tr("导出集合"))
                      if is_folder else None)
        act_rename = menu.addAction(icons.icon("pencil", t.text, 14), i18n.tr("重命名…"))
        act_dup = menu.addAction(icons.icon("copy", t.text, 14), i18n.tr("创建副本"))
        if not is_folder:
            act_curl = menu.addAction(icons.icon("code", t.text, 14), i18n.tr("复制为 cURL"))
        else:
            act_curl = None
        menu.addSeparator()
        act_del = menu.addAction(icons.icon("trash", t.danger, 14), i18n.tr("删除"))

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is act_new:
            parent = node_id if is_folder else (self._parent_of(node_id) or None)
            self.create_request_in(parent)
        elif act_folder and chosen is act_folder:
            self._new_folder(node_id)
        elif act_run is not None and chosen is act_run:
            self.runFolder.emit(node_id)
        elif act_auth is not None and chosen is act_auth:
            self._auth_dialog(node)
        elif act_export is not None and chosen is act_export:
            from .dialogs import export_folder

            path = export_folder(self.store, node, self.window(), global_pos)
            if path:
                self.notify.emit(i18n.trf("已导出到 {name}", name=path.rsplit("/", 1)[-1]))
        elif chosen is act_rename:
            self._rename_dialog(node)
        elif chosen is act_dup:
            self.duplicate_node(node_id)
        elif act_curl and chosen is act_curl:
            from .codegen import to_curl

            text = to_curl(node, self.store.env_vars(), self.store.settings)
            from PyQt6.QtWidgets import QApplication

            QApplication.clipboard().setText(text)
            self.notify.emit("已复制 cURL 命令")
        elif chosen is act_del:
            self.delete_node(node_id)

    def _parent_of(self, node_id: str) -> Optional[str]:
        item = self.tree.currentItem()
        if item is None:
            return None
        # 通过数据反查父节点 id
        def walk(parent_item) -> Optional[str]:
            for i in range(parent_item.childCount() if parent_item else self.tree.topLevelItemCount()):
                child = parent_item.child(i) if parent_item else self.tree.topLevelItem(i)
                if child.data(0, ROLE_ID) == node_id:
                    return parent_item.data(0, ROLE_ID) if parent_item else None
                found = walk(child)
                if found is not None:
                    return found
            return None

        return walk(None)

    def _rename_dialog(self, node: Dict[str, Any]) -> None:
        from .dialogs import PromptDialog

        dlg = PromptDialog("重命名", "名称", node.get("name", ""), self.window())
        if dlg.exec():
            name = dlg.value()
            if name.strip():
                node["name"] = name.strip()
                self.store.save()
                self.refresh()
                self.changed.emit()

    def _auth_dialog(self, node: Dict[str, Any]) -> None:
        """文件夹级认证：子请求选「继承」时从这里取凭据。"""
        from .dialogs import GlassDialog
        from .request_panel import AuthPage

        dlg = GlassDialog(self.window(), 580, 540, i18n.tr("集合认证"))
        lay = QVBoxLayout(dlg.body)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(8)
        lay.addWidget(Label(
            i18n.tr("这里的认证会被子请求通过「继承」使用；留空则以请求自己的认证为准。"),
            11.2, theme().text_faint))
        page = AuthPage(store=self.store, parent=dlg.body)
        page.load(node.get("auth") or {}, "")
        lay.addWidget(page, 1)
        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(dlg.reject)
        ok = Button("确定", None, kind="primary", height=28, padding=16, font_size=12)
        ok.clicked.connect(dlg.accept)
        lay.addWidget(HBox(1, cancel, ok, spacing=6))
        if dlg.exec():
            auth = page.dump()
            if (auth.get("type") or "none") == "none":
                node.pop("auth", None)
            else:
                node["auth"] = auth
            self.store.save()
            self.notify.emit(i18n.tr("集合认证已更新"))

    # -------------------------------------------------- 历史
    def _collapsed_groups(self) -> Set[str]:
        return set(self.store.settings.get("history_collapsed") or [])

    def _toggle_group(self, key: str) -> None:
        collapsed = self._collapsed_groups()
        if key in collapsed:
            collapsed.discard(key)
        else:
            collapsed.add(key)
        self.store.settings["history_collapsed"] = sorted(collapsed)
        self.store.save()
        self.refresh_history()

    def refresh_history(self) -> None:
        entries = self.store.history
        rows = list(getattr(self, "_hist_rows", []))
        collapsed = self._collapsed_groups()

        # 快速路径：每发一次请求只会在头部多一条、尾部裁一条，且分组没变。
        # 以前不管三七归一整列表重建，240 条历史就是 240 个新控件 —— 每发一次请求都卡一下。
        if entries and rows:
            incoming = [e.get("id") for e in entries]
            existing = [r.entry.get("id") for r in rows]
            head_group = _history_group(entries[0].get("ts", 0))
            head_key = _history_group_key(entries[0].get("ts", 0))
            first_header = getattr(self, "_hist_header", None)
            header_widget = getattr(self, "_hist_header_widget", None)
            if (incoming[0] not in existing
                    and (incoming[1:] == existing or incoming[1:] == existing[:-1])
                    and first_header == head_group
                    and head_key not in collapsed):
                row = HistoryRow(entries[0])
                row.clicked.connect(self._restore_history)
                row.removeRequested.connect(self._remove_history)
                # 插到当前分组头之后，而不是列表最前
                at = 0
                for i in range(self.history_lay.count()):
                    w = self.history_lay.itemAt(i).widget()
                    if w is header_widget or w is rows[0]:
                        at = i + 1
                        break
                self.history_lay.insertWidget(at, row)
                rows.insert(0, row)
                while len(rows) > len(entries):
                    old = rows.pop()
                    self.history_lay.removeWidget(old)
                    old.setParent(None)
                    old.deleteLater()
                self._hist_rows = rows
                self._apply_filter(self.search.text())
                return

        while self.history_lay.count() > 1:
            item = self.history_lay.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._hist_rows = []
        self._hist_groups = []
        self._hist_header = ""
        self._hist_header_widget = None
        if not entries:
            from .widgets import EmptyState

            empty = EmptyState("clock", "暂无历史记录", "发送请求后会自动记录在这里", "⌘↵ 发送")
            self.history_lay.insertWidget(0, empty)
            return

        # 按日期分组：先单遍统计每组条数（原来在循环里对每个组全量扫 entries，
        # 是 O(n·组数)；240 条历史切语言/折叠时会重复算上千次），再建标题与行。
        groups: List[Dict[str, Any]] = []
        by_key: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            ts = entry.get("ts", 0)
            key = _history_group_key(ts)
            g = by_key.get(key)
            if g is None:
                g = {"key": key, "label": _history_group(ts),
                     "kwargs": _history_group_kwargs(ts), "entries": []}
                by_key[key] = g
                groups.append(g)
            g["entries"].append(entry)

        for g in groups:
            key = g["key"]
            header = HistoryGroupHeader(
                g["label"], len(g["entries"]), key, key in collapsed,
                label_kwargs=g["kwargs"])
            header.clicked.connect(self._toggle_group)
            self.history_lay.insertWidget(self.history_lay.count() - 1, header)
            if self._hist_header_widget is None:
                self._hist_header = g["label"]   # 存中文原文，语言无关
                self._hist_header_widget = header
            group_rows = []
            self._hist_groups.append((header, group_rows))
            if key in collapsed:
                continue
            for entry in g["entries"]:
                row = HistoryRow(entry)
                row.clicked.connect(self._restore_history)
                row.removeRequested.connect(self._remove_history)
                self.history_lay.insertWidget(self.history_lay.count() - 1, row)
                self._hist_rows.append(row)
                group_rows.append(row)
        self._apply_filter(self.search.text())

    def _restore_history(self, entry: Dict[str, Any]) -> None:
        req = dict(entry.get("request") or {})
        req["id"] = req.get("id") or ""
        self.openRequest.emit(req)

    def _history_snapshots(self, row: Optional[QWidget] = None):
        """抓一行或整个历史视口的快照，坐标换算到 Sidebar 供动画覆盖层使用。"""
        if row is not None:
            if not row.isVisible():
                return []
            pm = row.grab()
            pos = row.mapTo(self, QPoint(0, 0))
            return [(pm, QRectF(pos.x(), pos.y(), row.width(), row.height()))]
        vp = self.history_scroll.viewport()
        if not vp.isVisible():
            return []
        pm = vp.grab()
        pos = vp.mapTo(self, QPoint(0, 0))
        return [(pm, QRectF(pos.x(), pos.y(), vp.width(), vp.height()))]

    def _remove_history(self, entry_id: str) -> None:
        row = next((r for r in getattr(self, "_hist_rows", [])
                    if r.entry.get("id") == entry_id), None)
        shots = self._history_snapshots(row)
        self._history_vanish.vanish(shots, 680)
        self.store.data["history"] = [h for h in self.store.history if h.get("id") != entry_id]
        self.store.save()
        self.refresh_history()
