"""左侧边栏：集合树（文件夹/请求）+ 请求历史。

自绘委托实现 iOS/macOS 风格的圆角悬停与选中态，鼠标移入有淡入动效；
集合树支持拖拽排序、右键菜单、搜索过滤与内联折叠。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set

from PyQt6.QtCore import (
    QEasingCurve,
    QModelIndex,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
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
from .anim import running as _anim_running, stop as _anim_stop
from .theme import C, method_color, status_color, font, mono, theme
from .widgets import Button, Divider, HBox, Label, Menu, VBox, icon_button

ROLE_ID = Qt.ItemDataRole.UserRole
ROLE_TYPE = Qt.ItemDataRole.UserRole + 1
ROLE_DATA = Qt.ItemDataRole.UserRole + 2


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
        return QSize(0, 29)

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
            avail = rect.width() - (x - rect.left()) - (18 if count_text else 6)
            name = QFontMetricsF(p.font()).elidedText(node.get("name", ""), Qt.TextElideMode.ElideRight, avail)
            p.setPen(text_color)
            p.drawText(QRectF(x, rect.top(), avail, rect.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)
            if count_text:
                p.setFont(mono(9.5))
                p.setPen(C(t.text_faint))
                p.drawText(QRectF(rect.right() - 18, rect.top(), 14, rect.height()),
                           int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), count_text)
        else:
            method = (node.get("method") or "GET").upper()
            mcol = C(method_color(method, t))
            if not selected and hover < 0.5:
                mcol = QColor(mcol)
                mcol.setAlpha(200)
            p.setFont(mono(9, QFont.Weight.DemiBold))
            p.setPen(mcol)
            p.drawText(QRectF(x, rect.top(), 36, rect.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), method)
            x += 38
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIndentation(13)
        self.setRootIsDecorated(False)
        # 隐藏 Qt 自带的展开三角（委托里已经画了一个，否则会出现两个箭头）
        self.setStyleSheet(
            "QTreeView::branch { background: transparent; image: none; border-image: none; }")
        self.setRootIsDecorated(False)
        self.setItemDelegate(TreeDelegate(self))
        self.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setExpandsOnDoubleClick(False)
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
        super().mouseMoveEvent(e)

    def _on_hover(self, v):
        self._hover_v = float(v)
        self.viewport().update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover_item = None
        self._hover_v = 0.0
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
        mcol = C(method_color(e.get("method", "GET"), t))
        p.setFont(mono(9, QFont.Weight.DemiBold))
        p.setPen(mcol)
        p.drawText(QRectF(r.left() + 8, r.top() + 5, 36, 14),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   (e.get("method") or "GET").upper())
        # URL
        p.setFont(mono(11.2))
        p.setPen(C(t.text) if self._hover_v > 0.4 else C(t.text_dim))
        url = e.get("url", "")
        avail = r.width() - 54 - 22
        text = QFontMetricsF(p.font()).elidedText(url, Qt.TextElideMode.ElideMiddle, avail)
        p.drawText(QRectF(r.left() + 48, r.top() + 3, avail, 17),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        # 元信息
        p.setFont(mono(9.5))
        sc = C(status_color(status, t)) if status else C(t.text_faint)
        p.setPen(sc)
        meta = f"{status}" if status else "ERR"
        p.drawText(QRectF(r.left() + 48, r.top() + 20, 42, 16),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), meta)
        p.setPen(C(t.text_faint))
        rel = time.strftime("%H:%M", time.localtime(e.get("ts", 0)))
        p.drawText(QRectF(r.left() + 88, r.top() + 20, max(r.width() - 118, 40), 16),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   f"{rel}  ·  {human_elapsed(int(e.get('elapsed') or 0))}")
        if self._hover_v > 0.25:
            p.setOpacity(min(1.0, self._hover_v))
            pm = icons.pixmap("close", t.text_dim, 10, 1.9)
            p.drawPixmap(QPointF(r.right() - 17, r.center().y() - 5), pm)
            p.setOpacity(1.0)
        p.end()


# ---------------------------------------------------------------- 侧边栏


class Sidebar(QWidget):
    openRequest = pyqtSignal(dict)          # 双击：固定打开
    previewRequest = pyqtSignal(dict)       # 单击：预览
    requestDeleted = pyqtSignal(str)
    runFolder = pyqtSignal(str)             # 右键「运行集合」：folder node id
    changed = pyqtSignal()
    notify = pyqtSignal(str)

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self._mode = "collections"
        self.open_ids: Set[str] = set()
        self._build()
        self.refresh()

    # -------------------------------------------------- 构建
    def _build(self) -> None:
        t = theme()
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
        root.addWidget(self.search)

        # 集合树
        self.tree = CollectionsTree()
        self.tree.openRequest.connect(self.openRequest.emit)
        self.tree.previewRequest.connect(self.previewRequest.emit)
        self.tree.structureChanged.connect(self._on_structure_changed)
        self.tree.requestContext.connect(self._show_context)
        self.tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # QTreeView 的列头边界会给出 SplitHCursor；集合树没有可调列宽，统一回普通箭头
        for w in (self.tree, self.tree.viewport(), self.tree.header()):
            w.setCursor(Qt.CursorShape.ArrowCursor)
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
        self.history_scroll.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        root.addWidget(self.history_scroll, 1)

        # 底部操作条
        self.new_btn = Button("新建请求", "plus", kind="subtle", height=28, padding=10,
                              radius=7, font_size=12, parent=self)
        self.new_btn.clicked.connect(self._new_request)
        self.folder_btn = icon_button("folder", "新建文件夹", 28, 14)
        self.folder_btn.clicked.connect(self._new_folder)
        self.clear_btn = icon_button("trash", "清空历史", 28, 14)
        self.clear_btn.clicked.connect(self._clear_history)
        self.clear_btn.hide()
        bottom = HBox(self.new_btn, 1, self.clear_btn, self.folder_btn, spacing=4,
                      margins=(0, 2, 0, 0))
        root.addWidget(bottom)

    # -------------------------------------------------- 模式
    def _on_mode(self, key: str) -> None:
        self._mode = key
        is_col = key == "collections"
        self.tree.setVisible(is_col)
        self.history_scroll.setVisible(not is_col)
        self.folder_btn.setVisible(is_col)
        self.clear_btn.setVisible(not is_col)
        self.new_btn.setText("新建请求" if is_col else "清空历史")
        self.new_btn.set_icon("plus" if is_col else "trash")
        self.search.clear()
        if is_col:
            self.refresh()
        else:
            self.refresh_history()

    # -------------------------------------------------- 集合树
    def refresh(self) -> None:
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
            flags |= Qt.ItemFlag.ItemIsDropEnabled
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

    def _apply_filter(self, text: str) -> None:
        text = (text or "").strip().lower()

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

    # -------------------------------------------------- 增删改
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

    def _new_folder(self) -> None:
        node = new_folder("New Folder")
        self.store.add_node(self._selected_folder(), node)
        self.store.save()
        self.refresh()
        self.changed.emit()

    def create_request_in(self, parent_id: Optional[str], method: str = "GET", url: str = "") -> Dict:
        node = new_request("Untitled Request", method, url)
        self.store.add_node(parent_id, node)
        self.store.save()
        self.refresh()
        self.openRequest.emit(node)
        self.changed.emit()
        return node

    def _clear_history(self) -> None:
        self.store.clear_history()
        self.store.save()
        self.refresh_history()
        self.notify.emit("历史已清空")

    def rename_node(self, node_id: str, name: str) -> None:
        node = self.store.find(node_id)
        if node is None or not name.strip():
            return
        node["name"] = name.strip()
        self.store.save()
        self.refresh()
        self.changed.emit()

    def delete_node(self, node_id: str) -> None:
        node = self.store.find(node_id)
        self.store.remove_node(node_id)
        self.store.save()
        self.refresh()
        if node:
            self.requestDeleted.emit(node_id)
        self.notify.emit(i18n.trf("已删除「{name}」", name=node.get("name", ""))
                         if node else i18n.tr("已删除"))
        self.changed.emit()

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
        act_new = menu.addAction(icons.icon("plus", t.text, 14), "新建请求")
        act_folder = menu.addAction(icons.icon("folder", t.text, 14), "新建文件夹") if is_folder else None
        menu.addSeparator()
        act_run = menu.addAction(icons.icon("play", t.text, 14), "运行集合") if is_folder else None
        if act_run is not None:
            menu.addSeparator()
        act_rename = menu.addAction(icons.icon("pencil", t.text, 14), "重命名…")
        act_dup = menu.addAction(icons.icon("copy", t.text, 14), "创建副本")
        if not is_folder:
            act_curl = menu.addAction(icons.icon("code", t.text, 14), "复制为 cURL")
        else:
            act_curl = None
        menu.addSeparator()
        act_del = menu.addAction(icons.icon("trash", t.danger, 14), "删除")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is act_new:
            parent = node_id if is_folder else (self._parent_of(node_id) or None)
            self.create_request_in(parent)
        elif act_folder and chosen is act_folder:
            self.store.add_node(node_id, new_folder("New Folder"))
            self.store.save()
            self.refresh()
            self.changed.emit()
        elif act_run is not None and chosen is act_run:
            self.runFolder.emit(node_id)
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

    # -------------------------------------------------- 历史
    def refresh_history(self) -> None:
        entries = self.store.history
        rows = list(getattr(self, "_hist_rows", []))

        # 快速路径：每发一次请求只会在头部多一条、尾部裁一条。
        # 以前不管三七二十一整列表重建，240 条历史就是 240 个新控件 —— 每发一次请求都卡一下。
        if entries and rows:
            incoming = [e.get("id") for e in entries]
            existing = [r.entry.get("id") for r in rows]
            if incoming[0] not in existing and (incoming[1:] == existing
                                               or incoming[1:] == existing[:-1]):
                row = HistoryRow(entries[0])
                row.clicked.connect(self._restore_history)
                row.removeRequested.connect(self._remove_history)
                self.history_lay.insertWidget(0, row)
                rows.insert(0, row)
                while len(rows) > len(entries):
                    old = rows.pop()
                    self.history_lay.removeWidget(old)
                    old.setParent(None)
                    old.deleteLater()
                self._hist_rows = rows
                return

        while self.history_lay.count() > 1:
            item = self.history_lay.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._hist_rows = []
        if not entries:
            from .widgets import EmptyState

            empty = EmptyState("clock", "暂无历史记录", "发送请求后会自动记录在这里", "⌘↵ 发送")
            self.history_lay.insertWidget(0, empty)
            return
        for entry in entries:
            row = HistoryRow(entry)
            row.clicked.connect(self._restore_history)
            row.removeRequested.connect(self._remove_history)
            self.history_lay.insertWidget(self.history_lay.count() - 1, row)
            self._hist_rows.append(row)

    def _restore_history(self, entry: Dict[str, Any]) -> None:
        req = dict(entry.get("request") or {})
        req["id"] = req.get("id") or ""
        self.openRequest.emit(req)

    def _remove_history(self, entry_id: str) -> None:
        self.store.data["history"] = [h for h in self.store.history if h.get("id") != entry_id]
        self.store.save()
        self.refresh_history()
