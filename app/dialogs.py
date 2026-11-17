"""对话框与浮层：设置、环境变量、代码生成、重命名、更新内容、命令面板。"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QStyledItemDelegate,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import i18n, icons
from .anim import stop as _anim_stop
from .code_editor import CodeView
from .codegen import LANGUAGES
from .kv_editor import KVEditor
from .store import CHANGELOG, STATE_FILE, VERSION, Store, new_folder
from .theme import C, S, font, mono, theme
from .widgets import (
    Button,
    Card,
    Divider,
    SmoothScrollArea,
    HBox,
    KeyCap,
    Label,
    Pill,
    SegmentedTabs,
    Switch,
    VBox,
    animate,
    fade_in,
    icon_button,
)


# ---------------------------------------------------------------- 基类


class GlassDialog(QDialog):
    """无边框圆角对话框，与主窗口同一套视觉语言。"""

    def __init__(self, parent=None, width: int = 520, height: int = 320, title: str = ""):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self._radius = 13
        self.resize(width, height)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._drag_pos: Optional[QPoint] = None

        self.title = title
        self.header = QWidget()
        self.header.setFixedHeight(46)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(18, 0, 10, 0)
        hl.setSpacing(8)
        self._title_label = Label(title, 13, theme().text, weight=font(13).weight())
        hl.addWidget(self._title_label)
        hl.addStretch(1)
        self.close_btn = icon_button("close", "关闭  esc", 24, 12)
        self.close_btn.clicked.connect(self.reject)
        hl.addWidget(self.close_btn)
        self._root.addWidget(self.header)
        self._root.addWidget(Divider())

        self.body = QWidget()
        self._root.addWidget(self.body, 1)

    # -------------------------------------------------- 绘制 / 拖动
    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.panel))
        p.drawRoundedRect(r, self._radius, self._radius)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 46:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        # 对话框多半是在语言切完以后才建的，这里补一次翻译，否则英文界面里会混着中文
        if i18n.current() == "en":
            i18n.apply_language(self)
            nav = getattr(self, "nav", None)
            if nav is not None:
                nav.sync_width()
        fade_in(self, 140)


# ---------------------------------------------------------------- 输入框对话框


class PromptDialog(GlassDialog):
    def __init__(self, title: str, label: str, value: str = "", parent=None):
        super().__init__(parent, 420, 172, title)
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(18, 12, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(Label(label, 11.5, theme().text_faint))
        self.edit = QLineEdit(value)
        self.edit.setObjectName("Field")
        self.edit.setFixedHeight(31)
        self.edit.selectAll()
        lay.addWidget(self.edit)
        lay.addStretch(1)
        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        ok = Button("确定", None, kind="primary", height=28, padding=16, font_size=12)
        ok.clicked.connect(self.accept)
        lay.addWidget(HBox(1, cancel, ok, spacing=6))
        self.edit.returnPressed.connect(self.accept)

    def value(self) -> str:
        return self.edit.text()

    def showEvent(self, e):
        super().showEvent(e)
        self.edit.setFocus()


# ---------------------------------------------------------------- 设置


class NavList(QWidget):
    """设置左侧竖向导航：图标 + 文字，圆角选中态，悬停淡入。"""

    changed = pyqtSignal(str)

    ROW_H = 33

    def __init__(self, items: List[tuple], parent=None):
        super().__init__(parent)
        self.items = items            # [(key, label, icon)]
        self.index = 0
        self._hover = -1
        self.setFixedWidth(166)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.width(), 12 + len(self.items) * self.ROW_H)

    def sync_width(self) -> None:
        """按当前语言量一遍：英文条目（Environment Variables）比中文长，166px 放不下。"""
        fm = QFontMetricsF(font(12.5, QFont.Weight.Medium))
        longest = max((fm.horizontalAdvance(i18n.tr(label)) for _k, label, _i in self.items),
                      default=0)
        self.setFixedWidth(max(166, int(longest) + 52))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def current_key(self) -> str:
        return self.items[self.index][0] if self.items else ""

    def set_key(self, key: str) -> None:
        for i, (k, _l, _i) in enumerate(self.items):
            if k == key:
                self.index = i
                self.update()
                return

    def _row_at(self, y: float) -> int:
        i = int((y - 6) // self.ROW_H)
        return i if 0 <= i < len(self.items) else -1

    def mouseMoveEvent(self, e):
        idx = self._row_at(e.position().y())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        idx = self._row_at(e.position().y())
        if idx >= 0 and idx != self.index:
            self.index = idx
            self.update()
            self.changed.emit(self.current_key())

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(t.panel_alt))
        p.drawRoundedRect(QRectF(0, 0, self.width() - 6, self.height()), 10, 10)
        for i, (_key, label, icon_name) in enumerate(self.items):
            r = QRectF(5, 6 + i * self.ROW_H, self.width() - 16, self.ROW_H - 2)
            selected = i == self.index
            hovered = i == self._hover
            if selected:
                p.setPen(QPen(C(t.border), 1))
                p.setBrush(C(t.elevated))
                p.drawRoundedRect(r, 7, 7)
            elif hovered:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.hover))
                p.drawRoundedRect(r, 7, 7)
            col = t.accent if selected else t.text_dim
            pm = icons.pixmap(icon_name, col, 14, 1.7)
            p.drawPixmap(QPointF(r.left() + 11, r.center().y() - 7), pm)
            p.setFont(font(12.5, QFont.Weight.Medium if selected else QFont.Weight.Normal))
            p.setPen(C(t.accent if selected else t.text_dim))
            p.drawText(QRectF(r.left() + 34, r.top(), r.width() - 40, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       i18n.tr(label))
        p.end()


class SchemePicker(QWidget):
    """配色方案选择器：每套方案一个「迷你窗口」缩略块，选中有对号。"""

    picked = pyqtSignal(str)

    TILE_W = 116
    TILE_H = 60
    GAP = 10

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        from .theme import SCHEMES

        self.schemes = list(SCHEMES)
        self.current = "graphite" if current in ("dark", "") else current
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        cols = 3
        rows = (len(self.schemes) + cols - 1) // cols
        self.setMinimumHeight(rows * self.TILE_H + (rows - 1) * self.GAP)
        self.setMinimumWidth(cols * 96 + (cols - 1) * self.GAP)

    def resizeEvent(self, e):
        cols = 3
        self.TILE_W = max(96, int((self.width() - (cols - 1) * self.GAP) / cols))
        super().resizeEvent(e)

    def _rects(self):
        from PyQt6.QtCore import QRectF

        out = []
        cols = 3
        for i in range(len(self.schemes)):
            r, c = divmod(i, cols)
            out.append(QRectF(c * (self.TILE_W + self.GAP), r * (self.TILE_H + self.GAP),
                              self.TILE_W, self.TILE_H))
        return out

    def _at(self, pos):
        for i, r in enumerate(self._rects()):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e):
        idx = self._at(e.position())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        idx = self._at(e.position())
        if idx >= 0:
            self.current = self.schemes[idx][0]
            self.update()
            self.picked.emit(self.current)

    def paintEvent(self, _e):
        from PyQt6.QtCore import QRectF

        from .theme import theme_by_name

        active = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        for i, (key, label) in enumerate(self.schemes):
            r = self._rects()[i]
            sch = theme_by_name(key)
            selected = key == self.current
            p.setPen(QPen(C(active.border_strong if (selected or i == self._hover)
                            else active.border), 2 if selected else 1))
            p.setBrush(C(sch.window))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
            # 迷你内容块
            card = QRectF(r.left() + 9, r.top() + 11, r.width() - 18, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(sch.card))
            p.drawRoundedRect(card, 5, 5)
            p.setBrush(C(sch.text))
            p.drawRoundedRect(QRectF(card.left() + 7, card.top() + 7, 30, 4), 2, 2)
            p.setBrush(C(sch.text_faint))
            p.drawRoundedRect(QRectF(card.left() + 42, card.top() + 7, 16, 4), 2, 2)
            p.setFont(font(11))
            p.setPen(C(sch.text if sch.is_dark else sch.text))
            p.drawText(QRectF(r.left() + 10, r.bottom() - 22, r.width() - 30, 18),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       i18n.tr(label))
            if selected:
                pm = icons.pixmap("check", sch.text, 12, 1.9)
                p.drawPixmap(QPointF(r.right() - 20, r.bottom() - 21), pm)
        p.end()


class AccentPicker(QWidget):
    """主题色选择器：一排色点，选中的外面套一圈，旁边显示名字。"""

    picked = pyqtSignal(str)

    DOT = 20
    GAP = 8
    RING = 4          # 选中时描边比色点多出多少（左右要留够，否则第一颗会被卡片边缘切掉）

    def __init__(self, current: str = "auto", parent=None):
        super().__init__(parent)
        from .theme import ACCENT_ORDER

        self.keys = list(ACCENT_ORDER)
        self.current = current if current in self.keys else "auto"
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 上下各留出描边的余量，避免描边被垂直裁切
        self.setFixedHeight(self.DOT + (self.RING + 2) * 2)
        self.setMinimumWidth(int(self._x0() * 2 + (len(self.keys) - 1) * (self.DOT + self.GAP)
                                 + self.DOT))

    def _x0(self) -> float:
        # 第一颗色点的圆心位置：必须 ≥ 半径 + 描边，否则左边被切
        return self.DOT / 2 + self.RING + 2

    def _centers(self):
        y = self.height() / 2
        x0 = self._x0()
        return [QPointF(x0 + i * (self.DOT + self.GAP), y) for i in range(len(self.keys))]

    def _at(self, pos):
        for i, c in enumerate(self._centers()):
            if (pos.x() - c.x()) ** 2 + (pos.y() - c.y()) ** 2 <= (self.DOT / 2 + 5) ** 2:
                return i
        return -1

    def mouseMoveEvent(self, e):
        idx = self._at(e.position())
        if idx != self._hover:
            self._hover = idx
            self.setToolTip("")
            if idx >= 0:
                from .theme import ACCENTS

                self.setToolTip(ACCENTS[self.keys[idx]][0])
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        idx = self._at(e.position())
        if idx >= 0 and self.keys[idx] != self.current:
            self.current = self.keys[idx]
            self.update()
            self.picked.emit(self.current)

    def paintEvent(self, _e):
        from PyQt6.QtCore import QRectF

        from .theme import ACCENTS, theme as _theme

        t = _theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for i, key in enumerate(self.keys):
            c = self._centers()[i]
            bg, fg = _accent_preview(key, t)
            selected = key == self.current
            # 选中：先画一圈底色描边，再画实心点；悬停给一点点亮
            if selected:
                ring = QColor(t.text)
                ring.setAlpha(90 if t.is_dark else 70)
                p.setPen(QPen(ring, 1.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                r = self.DOT / 2 + 4
                p.drawEllipse(QRectF(c.x() - r, c.y() - r, r * 2, r * 2))
            p.setPen(Qt.PenStyle.NoPen)
            fill = QColor(bg)
            if i == self._hover and not selected:
                fill = fill.lighter(112) if t.is_dark else fill.darker(106)
            p.setBrush(fill)
            d = self.DOT
            p.drawEllipse(QRectF(c.x() - d / 2, c.y() - d / 2, d, d))
            if selected:
                pm = icons.pixmap("check", fg, 11, 2.0)
                p.drawPixmap(QPointF(c.x() - 5.5, c.y() - 5.5), pm)
        p.end()


def _accent_preview(key: str, t) -> tuple[str, str]:
    """设置面板里的色点取色：auto 用当前主题的反色，其余按主题明暗取。"""
    from .theme import ACCENTS

    _label, d, lt = ACCENTS.get(key, ACCENTS["auto"])
    if key == "auto":
        return (t.text, t.window) if t.is_dark else (t.text, "#FFFFFF")
    return d if t.is_dark else lt


# ---------------------------------------------------------------- 快捷键录制


class ShortcutRecorder(GlassDialog):
    """录制一个组合键：按下什么就记什么，esc 放弃。"""

    def __init__(self, name: str, current: str = "", parent=None):
        super().__init__(parent, 430, 226, i18n.trf("录制快捷键 · {name}", name=name))
        from . import shortcuts as sc

        t = theme()
        self.value = ""
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(24, 6, 24, 18)
        lay.setSpacing(12)

        self.cap = KeyCap(sc.display(current) if current else "按下组合键",
                          width=0, height=46)
        self.cap.setFont(font(15))
        lay.addWidget(HBox(1, self.cap, 1, spacing=0))

        self.hint = Label("直接按下新的组合键。支持 ⌘ / ⌃ / ⌥ / ⇧ 与字母、数字、"
                          "方向键、回车等。", 10.8, t.text_faint)
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.hint)
        lay.addStretch(1)
        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        lay.addWidget(HBox(1, cancel, 1, spacing=6))

    def keyPressEvent(self, e):
        from . import shortcuts as sc

        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        seq = sc.from_event(e)
        if not seq:
            return
        self.value = seq
        self.cap.set_text(sc.display(seq), recording=True)
        self.accept()


class ShortcutRow(QWidget):
    """一行快捷键：名称 + 默认键位提示 + 键帽 + 清除。"""

    changed = pyqtSignal(str, str)      # (action, seq)

    def __init__(self, action: str, name: str, seq: str, shown: str, parent=None):
        super().__init__(parent)
        from . import shortcuts as sc

        t = theme()
        self.action = action
        self._seq = seq
        self._name = name
        h = QHBoxLayout(self)
        h.setContentsMargins(2, 9, 2, 9)
        h.setSpacing(10)

        default = sc.defaults().get(action, "")
        sub = (i18n.trf("默认 {keys}", keys=sc.display(default))
               if default != seq else i18n.tr("默认键位"))
        text = VBox(Label(name, 12.4, t.text), Label(sub, 10.4, t.text_faint), spacing=2)
        h.addWidget(text, 1)

        self.cap = KeyCap(shown, width=118, height=24)
        self.cap.clicked.connect(self._record)
        h.addWidget(self.cap, 0, Qt.AlignmentFlag.AlignVCenter)

        self.clear_btn = Button("清除", None, kind="ghost", height=24, padding=9,
                                font_size=11)
        self.clear_btn.clicked.connect(lambda: self.changed.emit(self.action, ""))
        self.clear_btn.setEnabled(bool(seq))
        h.addWidget(self.clear_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._record()
        super().mouseReleaseEvent(e)

    def _record(self) -> None:
        dlg = ShortcutRecorder(self._name, self._seq, self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.value:
            self.changed.emit(self.action, dlg.value)

    def set_key(self, seq: str) -> None:
        from . import shortcuts as sc

        self._seq = seq
        self.cap.set_text(sc.display(seq))
        self.clear_btn.setEnabled(bool(seq))


class SettingsDialog(GlassDialog):
    """统一的设置面板：通用 / 外观 / 快捷键 / 网络 / 环境变量 / 数据 / 更新内容 都在这一页。"""

    themeChanged = pyqtSignal(str)
    accentChanged = pyqtSignal(str)
    settingsChanged = pyqtSignal()
    shortcutsChanged = pyqtSignal()
    dataReloaded = pyqtSignal()

    NAV = [
        ("general", "通用", "sliders"),
        ("appearance", "外观", "moon"),
        ("shortcuts", "快捷键", "keyboard"),
        ("network", "网络", "globe"),
        ("cloud", "云同步", "cloud"),
        ("env", "环境变量", "layers"),
        ("data", "数据", "folder"),
        ("about_app", "关于 Ocelot", "book"),
    ]

    def __init__(self, store: Store, parent=None, page: str = "general"):
        super().__init__(parent, 940, 700, "设置")
        self.store = store
        s = store.settings
        self._page = page

        root = QHBoxLayout(self.body)
        root.setContentsMargins(16, 12, 18, 14)
        root.setSpacing(18)

        self.nav = NavList(self.NAV)
        self.nav.changed.connect(self._on_nav)
        root.addWidget(self.nav, 0, Qt.AlignmentFlag.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(10)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_general(s))
        self.stack.addWidget(self._page_appearance(s))
        self.stack.addWidget(self._page_shortcuts())
        self.stack.addWidget(self._page_network(s))
        self.stack.addWidget(self._page_cloud(s))
        self.stack.addWidget(self._page_env())
        self.stack.addWidget(self._page_data())
        self.stack.addWidget(self._page_about_app())
        right.addWidget(self.stack, 1)

        done = Button("完成", None, kind="primary", height=28, padding=18, font_size=12)
        done.clicked.connect(self._done)
        foot = HBox(1, done, spacing=8)
        foot.layout().setContentsMargins(0, 0, 4, 0)
        right.addWidget(foot)
        root.addLayout(right, 1)

        keys = [k for k, _l, _i in self.NAV]
        # 显式映射，别靠 stack 下标：加页或调序时最容易造成「每页看起来都一样」
        self._page_widgets = {k: self.stack.widget(i) for i, k in enumerate(keys)}
        self.nav.set_key(page if page in keys else "general")
        self.stack.setCurrentWidget(self._page_widgets.get(self.nav.current_key())
                                    or self.stack.widget(0))
        self._apply_page_title()

    # -------------------------------------------------- 页面
    def _page_shell(self, title: str, desc: str, *blocks) -> QWidget:
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(2, 0, 10, 14)
        lay.setSpacing(16)
        # 标题与说明都要能换行：英文比中文长不少，不换行就会被裁掉半截
        head_title = Label(title, 17, theme().text, weight=QFont.Weight.DemiBold, spacing=0.2)
        head_desc = Label(desc, 11.6, theme().text_faint)
        head_desc.setWordWrap(True)
        head = VBox(head_title, head_desc, spacing=4)
        lay.addWidget(head)
        lay.addWidget(Divider())
        for b in blocks:
            if isinstance(b, QLabel):
                b.setWordWrap(True)
            lay.addWidget(b)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _card(self, *rows) -> QWidget:
        card = Card(radius=10)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 6, 12, 6)
        lay.setSpacing(0)
        for i, r in enumerate(rows):
            if i:
                lay.addWidget(Divider())
            lay.addWidget(r)
        return card

    def _page_general(self, s: Dict[str, Any]) -> QWidget:
        from . import i18n

        self.lang_seg = SegmentedTabs([("zh", "简体中文"), ("en", "English")],
                                      style="pill", height=26, font_size=11.5, pad_h=12)
        self.lang_seg.set_current(i18n.current(), emit=False)
        self.lang_seg.changed.connect(self._on_language)
        self.auto_name = Switch(s.get("auto_name", True))
        self.auto_name.toggled.connect(lambda _v: self._save())
        self.restore_session = Switch(bool(s.get("restore_session", True)))
        self.restore_session.toggled.connect(lambda _v: self._save())
        block = self._card(
            self._row("语言", "界面显示语言，切换后立即生效。", self.lang_seg),
            self._row("自动命名请求", "按 URL 末段自动给请求命名，重命名后不再覆盖。", self.auto_name),
            self._row("记住窗口与分栏", "下次启动恢复打开的标签、侧栏与上下分栏比例。",
                      self.restore_session),
        )
        # 快捷键独立成页，这里只留一个入口 —— 键位表太长，塞在通用页里只会被挤扁
        jump = Button("去设置", "keyboard", kind="subtle", height=27, padding=11,
                      font_size=11.6, icon_size=12)
        jump.clicked.connect(self._goto_shortcuts)
        keys_card = self._card(
            self._row("快捷键", "发送、搜索、切换标签等键位都可以改，也能整组恢复默认。",
                      jump),
        )
        return self._page_shell("通用", "启动行为与编辑习惯。", block, keys_card)

    def _goto_shortcuts(self) -> None:
        self.nav.set_key("shortcuts")
        self._on_nav("shortcuts")

    def _section(self, title: str, *widgets) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lab = Label(title, 10, theme().text_faint, weight=QFont.Weight.DemiBold, spacing=0.8)
        lay.addWidget(lab)
        for x in widgets:
            lay.addWidget(x)
        return w

    def _page_appearance(self, s: Dict[str, Any]) -> QWidget:
        self.scheme_picker = SchemePicker(s.get("theme", "graphite"))
        self.scheme_picker.picked.connect(self._on_scheme)
        scheme_card = Card(radius=12)
        sl = QVBoxLayout(scheme_card)
        sl.setContentsMargins(16, 14, 16, 16)
        sl.setSpacing(10)
        sl.addWidget(self.scheme_picker)

        self.accent_picker = AccentPicker(s.get("accent", "auto"))
        self.accent_picker.picked.connect(self._on_accent)
        accent_card = self._card(
            self._row("主题色", "主按钮、开关、勾选框、选中态与强调文字一起换色；「自动」为黑白反色。",
                      self.accent_picker),
        )

        self.anim_switch = Switch(bool(s.get("animations", True)))
        self.anim_switch.toggled.connect(self._on_anim)
        self.font_seg = SegmentedTabs([("10.5", "小"), ("11.8", "标准"), ("13", "大")],
                                      style="pill", height=26, font_size=11.5, pad_h=12)
        cur_size = str(s.get("code_font_size", 11.8))
        self.font_seg.set_current(cur_size if cur_size in ("10.5", "11.8", "13") else "11.8",
                                  emit=False)
        self.font_seg.changed.connect(self._on_font_size)
        options = self._card(
            self._row("界面动效", "关闭后页面切换、悬停与响应到达不再播放动画。", self.anim_switch),
            self._row("代码字号", "响应体、请求体与代码片段的等宽字体大小。", self.font_seg),
        )

        preview = Card(radius=12)
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(16, 12, 16, 14)
        pl.setSpacing(10)
        pl.addWidget(Label("预览", 10, theme().text_faint, weight=QFont.Weight.DemiBold,
                           spacing=0.8))
        pl.addWidget(HBox(Button("发送", "send", kind="primary", height=28, padding=14, font_size=12),
                          Button("次按钮", None, kind="subtle", height=28, padding=14, font_size=12),
                          Button("文字按钮", None, kind="ghost", height=28, padding=10, font_size=12),
                          1, spacing=8))
        return self._page_shell(
            "外观", "配色、主题色、动效与字号，改动立即生效。",
            self._section("配色方案", scheme_card), accent_card, options, preview)

    # -------------------------------------------------- 快捷键
    def _page_shortcuts(self) -> QWidget:
        """所有快捷键集中一页：点键帽重录，右键/按钮清除，冲突会自动接管。"""
        from . import shortcuts as sc

        t = theme()
        self._key_rows: List[Tuple[str, "ShortcutRow"]] = []

        tip = Card(radius=10)
        tl = QHBoxLayout(tip)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(10)
        ic = Label("", 12)
        ic.setFixedSize(15, 15)
        ic.setPixmap(icons.pixmap("keyboard", t.text_faint, 15, 1.6))
        tl.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        tip_text = Label("点键帽开始录制，按下新的组合键即可替换；按 esc 取消。"
                         "清除后该动作只在菜单里可用。同一个键位被两个动作占用时，"
                         "旧的那个会自动让位。", 11, t.text_faint)
        tip_text.setWordWrap(True)
        tl.addWidget(tip_text, 1)

        blocks: List[QWidget] = [tip]
        mapping = sc.mapping(self.store)
        for group, rows in sc.by_group(mapping):
            card = Card(radius=10)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 12, 10)
            cl.setSpacing(0)
            cl.addWidget(Label(group, 9.6, t.text_faint,
                               weight=QFont.Weight.DemiBold, spacing=0.8))
            cl.addSpacing(2)
            for i, (action, name, seq) in enumerate(rows):
                if i:
                    cl.addWidget(Divider())
                row = ShortcutRow(action, name, seq, sc.display(seq), self)
                row.changed.connect(self._on_shortcut)
                self._key_rows.append((action, row))
                cl.addWidget(row)
            blocks.append(card)

        self.shortcut_note = Label("", 10.6, t.text_faint)
        reset = Button("恢复默认", "refresh", kind="ghost", height=26, padding=10,
                       font_size=11.4, icon_size=12)
        reset.clicked.connect(self._reset_shortcuts)
        foot = HBox(self.shortcut_note, 1, reset, spacing=8)
        blocks.append(foot)
        return self._page_shell("快捷键", "想怎么按就怎么按 —— 所有键位都可以改、可以清空。",
                                *blocks)

    def _on_shortcut(self, action: str, seq: str) -> None:
        from . import shortcuts as sc

        if seq:
            other = sc.conflict(sc.mapping(self.store), seq, exclude=action)
            if other:
                for key, value in sc.mapping(self.store).items():
                    if key != action and value and sc.display(value) == sc.display(seq):
                        sc.set_key(self.store, key, "")
                        self._refresh_shortcut_row(key)
                self.shortcut_note.setText(i18n.trf("{keys} 原来是「{action}」的，已让位",
                                                   keys=sc.display(seq), action=other))
            else:
                self.shortcut_note.setText(i18n.trf("已改为 {keys}", keys=sc.display(seq)))
        else:
            self.shortcut_note.setText(i18n.trf("已清除 {name} 的快捷键", name=sc.label_of(action)))
        sc.set_key(self.store, action, seq)
        self._refresh_shortcut_row(action)
        self.shortcutsChanged.emit()

    def _refresh_shortcut_row(self, action: str) -> None:
        from . import shortcuts as sc

        value = sc.mapping(self.store).get(action, "")
        for key, row in self._key_rows:
            if key == action:
                row.set_key(value)
                break

    def _reset_shortcuts(self) -> None:
        from . import shortcuts as sc

        sc.reset(self.store)
        for action, row in self._key_rows:
            row.set_key(sc.mapping(self.store).get(action, ""))
        self.shortcut_note.setText("已恢复默认键位")
        self.shortcutsChanged.emit()

    def _page_network(self, s: Dict[str, Any]) -> QWidget:
        self.timeout = QLineEdit(str(s.get("timeout", 30)))
        self.timeout.setObjectName("Field")
        self.timeout.setFixedHeight(28)
        self.timeout.setFixedWidth(64)
        self.timeout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timeout.setFont(mono(11.5))
        self.timeout.editingFinished.connect(self._save)
        self.redirect = Switch(s.get("follow_redirects", True))
        self.redirect.toggled.connect(lambda _v: self._save())
        self.verify = Switch(s.get("verify_ssl", True))
        self.verify.toggled.connect(lambda _v: self._save())
        self.proxy_seg = SegmentedTabs([("auto", "自动"), ("system", "系统"), ("off", "直连")],
                                       style="pill", height=26, font_size=11.5, pad_h=12)
        self.proxy_seg.set_current(s.get("proxy_mode", "auto"), emit=False)
        self.proxy_seg.changed.connect(self._on_proxy)
        self.ua = QLineEdit(str(s.get("user_agent") or "Ocelot/1.0 (macOS)"))
        self.ua.setObjectName("Field")
        self.ua.setFixedHeight(28)
        self.ua.setFont(mono(11.5))
        self.ua.setFixedWidth(232)
        self.ua.editingFinished.connect(self._on_ua)
        block = self._card(
            self._row("请求超时", "单位秒，0 表示不限制。",
                      HBox(self.timeout, Label("秒", 11, theme().text_faint), spacing=6)),
            self._row("跟随重定向", "自动跟随 3xx 跳转到最终地址。", self.redirect),
            self._row("校验 SSL 证书", "关闭后可用于自签名证书的调试环境。", self.verify),
            self._row("网络代理", "自动：优先读环境变量代理，其次系统代理；本地地址始终直连。",
                      self.proxy_seg),
            self._row("默认 User-Agent", "请求没带 UA 时使用（部分接口会按 UA 限流）。", self.ua),
        )
        return self._page_shell("网络", "超时、跳转、证书与代理。", block)

    # -------------------------------------------------- 云同步
    def _page_cloud(self, s: Dict[str, Any]) -> QWidget:
        self.cloud_enabled = Switch(bool(s.get("cloud_enabled", False)))
        self.cloud_enabled.toggled.connect(lambda _v: self._save_cloud())

        self.cloud_url = QLineEdit(str(s.get("turso_url", "")))
        self.cloud_url.setObjectName("Field")
        self.cloud_url.setFixedHeight(28)
        self.cloud_url.setMinimumWidth(320)
        self.cloud_url.setFont(mono(11))
        self.cloud_url.setPlaceholderText("https://ocelot-you.turso.io")
        self.cloud_url.editingFinished.connect(self._save_cloud)

        self.cloud_token = QLineEdit(str(s.get("turso_token", "")))
        self.cloud_token.setObjectName("Field")
        self.cloud_token.setFixedHeight(28)
        self.cloud_token.setMinimumWidth(320)
        self.cloud_token.setFont(mono(11))
        self.cloud_token.setEchoMode(QLineEdit.EchoMode.Password)
        i18n.placeholder(self.cloud_token, "粘贴 Turso 的 Auth Token")
        self.cloud_token.editingFinished.connect(self._save_cloud)

        test = Button("测试连接", "cloud", kind="subtle", height=26, padding=10, font_size=11.5)
        test.clicked.connect(self._test_cloud)
        self.cloud_status = Label("尚未测试", 10.5, theme().text_faint, mono_font=True)
        self.cloud_status.setMinimumWidth(150)

        up = Button("上传到云端", "download", kind="subtle", height=26, padding=10, font_size=11.5)
        up.clicked.connect(self._cloud_push)
        down = Button("从云端恢复", "refresh", kind="subtle", height=26, padding=10, font_size=11.5)
        down.clicked.connect(self._cloud_pull)

        self.cloud_auto = Switch(bool(s.get("cloud_auto", False)))
        self.cloud_auto.toggled.connect(lambda _v: self._save_cloud())

        block = self._card(
            self._row("启用云同步", "把集合、环境变量与设置存到 Turso，多台机器共用同一份数据。",
                      self.cloud_enabled),
            self._row_stack("数据库地址", "Turso 控制台里的 URL（libsql:// 开头也可以，会自动换成 https）。",
                            self.cloud_url, mono_desc=True),
            self._row_stack("Auth Token", "数据库的访问令牌，只保存在本机，上传时作为 Bearer 头。",
                            self.cloud_token, mono_desc=True),
            self._row("连通性", "先测一下再上传：只跑一条 SELECT 1，不写入任何数据。",
                      HBox(test, 4, self.cloud_status, spacing=8)),
            self._row_stack("手动同步", "上传会覆盖云端快照；恢复会先用云端覆盖本机（自动备份为 state.json.bak）。",
                            HBox(up, down, 1, spacing=6)),
            self._row("退出时自动上传", "关闭窗口时把最新数据推上去，适合固定一台机器当主库。",
                      self.cloud_auto),
        )
        tip = Label("数据表：ocelot_sync（k / v / updated_at）。同一个 Token 可见范围内只有一行快照。",
                    10.5, theme().text_faint)
        tip.setWordWrap(True)
        return self._page_shell("云同步", "用 Turso 做一份你自己的云备份 —— 不需要注册第三方账号体系。",
                                block, tip)

    def _save_cloud(self) -> None:
        from .cloud import normalize_url

        s = self.store.settings
        s["turso_url"] = normalize_url(self.cloud_url.text())
        if self.cloud_url.text().strip() and s["turso_url"] != self.cloud_url.text().strip():
            self.cloud_url.setText(s["turso_url"])
        s["turso_token"] = self.cloud_token.text().strip()
        s["cloud_enabled"] = self.cloud_enabled.isChecked()
        s["cloud_auto"] = self.cloud_auto.isChecked()
        self.store.save()

    def _cloud_busy(self, text: str) -> None:
        self.cloud_status.setText(text)
        self.cloud_status.setStyleSheet(f"color: {theme().text_dim}; background: transparent;")

    def _cloud_say(self, ok: bool, text: str) -> None:
        self.cloud_status.setText(text)
        self.cloud_status.setStyleSheet(
            f"color: {theme().success if ok else theme().danger}; background: transparent;")

    def _spawn(self, fn, cb) -> None:
        """把动作丢到后台线程，避免测试连接时整页卡住。"""
        from .cloud import CloudWorker

        worker = CloudWorker(fn, self)
        workers = getattr(self, "_workers", None)
        if workers is None:
            workers = self._workers = []
        workers.append(worker)

        def done(ok, msg, data):
            if worker in workers:
                workers.remove(worker)
            cb(ok, msg, data)

        worker.done.connect(done)
        worker.start()

    def _test_cloud(self) -> None:
        from .cloud import client_for

        self._save_cloud()
        client = client_for(self.store.settings)
        self._cloud_busy("连接中…")

        def run():
            ok, msg, _ms = client.test()
            return ok, msg, None

        def done(ok, msg, _data):
            if ok:
                self.store.settings["cloud_verified"] = True
                self.store.save()
            self._cloud_say(ok, msg)

        self._spawn(run, done)

    def _cloud_push(self) -> None:
        from .cloud import client_for

        self._save_cloud()
        client = client_for(self.store.settings)
        text = json.dumps(self.store.data, ensure_ascii=False)
        self._cloud_busy("上传中…")

        def run():
            return client.push(text)

        def done(ok, msg, _data):
            self._cloud_say(ok, msg if ok else i18n.trf("上传失败：{err}", err=msg))

        self._spawn(run, done)

    def _cloud_pull(self) -> None:
        from .cloud import client_for

        self._save_cloud()
        client = client_for(self.store.settings)
        self._cloud_busy("读取中…")

        def run():
            text, _stamp = client.pull()
            return bool(text), "云端还没有数据" if not text else "已获取快照", text

        def done(ok, msg, text):
            if not ok:
                self._cloud_say(False, i18n.trf("恢复失败：{err}", err=msg))
                return
            try:
                data = json.loads(text)
                if not isinstance(data, dict) or "collections" not in data:
                    raise ValueError("云端数据不是 Ocelot 快照")
            except Exception as exc:  # noqa: BLE001
                self._cloud_say(False, i18n.trf("数据格式不对：{err}", err=exc))
                return
            # 先备份本机快照，再整份替换；云端没带的字段（比如 token）保留本机值
            try:
                from .store import STATE_FILE

                if STATE_FILE.exists():
                    STATE_FILE.with_suffix(".json.bak").write_text(
                        STATE_FILE.read_text("utf-8"), "utf-8")
            except Exception:  # noqa: BLE001
                pass
            keep = {k: self.store.settings.get(k) for k in
                    ("turso_url", "turso_token", "cloud_enabled", "cloud_auto", "theme", "accent")}
            self.store.data.clear()
            self.store.data.update(data)
            self.store.data.setdefault("settings", {})
            self.store.settings.update({k: v for k, v in keep.items() if v is not None})
            self.store.save()
            self._cloud_say(True, "已用云端数据覆盖本机")
            self.dataReloaded.emit()

    def _page_env(self) -> QWidget:
        self.env_editor = EnvEditor(self.store)
        return self._page_shell("环境变量", "{{变量}} 会按当前激活的环境替换。", self.env_editor)

    def _page_data(self) -> QWidget:
        path = str(STATE_FILE.parent).replace(str(os.path.expanduser("~")), "~")
        open_dir = Button("打开数据目录", "folder", kind="ghost", height=26, padding=10, font_size=11.5)
        open_dir.clicked.connect(self._open_dir)
        clear_hist = Button("清空历史", "trash", kind="ghost", height=26, padding=10, font_size=11.5)
        clear_hist.clicked.connect(self._clear_history)
        limit = int(self.store.settings.get("history_limit", 240))
        self.limit_seg = SegmentedTabs([("100", "100 条"), ("240", "240 条"), ("500", "500 条")],
                                       style="pill", height=26, font_size=11.5, pad_h=12)
        self.limit_seg.set_current(str(limit) if str(limit) in ("100", "240", "500") else "240",
                                   emit=False)
        self.limit_seg.changed.connect(self._on_history_limit)
        block = self._card(
            self._row("本地数据", path, open_dir, mono_desc=True),
            self._row("历史记录上限",
                  i18n.tr("当前 {n} 条，超出后自动丢弃最旧的。").format(
                      n=len(self.store.history or [])),
                      self.limit_seg),
            self._row("清空历史", "只删历史记录，集合与环境变量不受影响。", clear_hist),
        )
        return self._page_shell("数据", "所有数据都是本地纯 JSON，可直接备份或版本管理。", block)

    def _page_about_app(self) -> QWidget:
        """关于页：品牌区 + 运行环境 + 常用入口，做得像一张「应用名片」。"""
        import platform as _platform

        from .store import APP_DIR

        t = theme()
        word = Label("Ocelot", 30, t.text, weight=QFont.Weight.DemiBold, spacing=-0.4)
        tag = Label("把请求调试做得干净、安静的桌面工具。没有账号体系，没有遥测，数据只留在你的机器上。",
                    11.8, t.text_dim)
        tag.setWordWrap(True)
        pills = HBox(Pill(f"v{VERSION}", t.text_dim, font_size=10.2),
                     Pill("纯本地", t.text_faint, font_size=10.2),
                     1, spacing=6)
        hero = Card(radius=12)
        hv = QVBoxLayout(hero)
        hv.setContentsMargins(22, 20, 22, 18)
        hv.setSpacing(7)
        hv.addWidget(word)
        hv.addWidget(tag)
        hv.addSpacing(6)
        hv.addWidget(pills)

        # ---------- 运行环境：三列，中间一条细竖线
        def metric(caption: str, value: str) -> QWidget:
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            v.addWidget(Label(caption, 9.6, t.text_faint,
                              weight=QFont.Weight.DemiBold, spacing=0.7))
            val = Label(value, 11.4, t.text_dim, mono_font=True)
            val.setWordWrap(True)
            v.addWidget(val)
            return box

        env_card = Card(radius=10)
        eh = QHBoxLayout(env_card)
        eh.setContentsMargins(18, 14, 18, 14)
        eh.setSpacing(18)
        eh.addWidget(metric("版本", f"Ocelot {VERSION}"), 2)
        line2 = QWidget()
        line2.setFixedWidth(1)
        line2.setStyleSheet(f"background: {t.border};")
        eh.addWidget(line2)
        mac_ver, _cpu, _arch = _platform.mac_ver()
        sys_text = (f"macOS {mac_ver or _platform.release()} · {_platform.machine()}")
        eh.addWidget(metric("系统", sys_text), 3)

        # ---------- 入口
        notes = Button("查看更新内容", "book", kind="subtle", height=30, padding=12, font_size=12)
        notes.clicked.connect(lambda: WhatsNewDialog(self).exec())
        folder = Button("打开数据目录", "folder", kind="subtle", height=30, padding=12, font_size=12)
        folder.clicked.connect(self._open_dir)
        copy_btn = Button("复制版本信息", "copy", kind="ghost", height=30, padding=12, font_size=12)
        copy_btn.clicked.connect(lambda: self._copy_version_info(copy_btn))
        actions = QWidget()
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        al.addWidget(notes)
        al.addWidget(folder)
        al.addWidget(copy_btn)
        al.addStretch(1)

        # ---------- 为什么是 Ocelot：四条能验证的优势，不写空话
        def perk(icon_name: str, title: str, desc: str) -> QWidget:
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 12, 0)
            v.setSpacing(5)
            ic = Label("", 12)
            ic.setFixedSize(16, 16)
            ic.setPixmap(icons.pixmap(icon_name, t.text_dim, 16, 1.6))
            v.addWidget(ic)
            v.addWidget(Label(title, 12.2, t.text, weight=QFont.Weight.DemiBold))
            d = Label(desc, 10.8, t.text_faint)
            d.setWordWrap(True)
            v.addWidget(d)
            return w

        grid = Card(radius=12)
        gl = QVBoxLayout(grid)
        gl.setContentsMargins(18, 16, 18, 16)
        gl.setSpacing(16)
        gl.addWidget(Label("为什么是 Ocelot", 10, t.text_faint,
                           weight=QFont.Weight.DemiBold, spacing=0.8))
        row1 = HBox(perk("lock", "数据只在你的机器上",
                         "集合、历史、环境变量都是本地 JSON。没有账号体系，没有遥测，"
                         "断网也能整理接口。"),
                    perk("send", "一条链路做完四件事",
                         "发请求 → 看响应 → 出接口文档 → 复制十种语言代码，都在一个窗口里，"
                         "不用再开浏览器和编辑器。"),
                    1, spacing=18)
        row2 = HBox(perk("layers", "原生绘制，不是套壳浏览器",
                         "界面全部由 QPainter 自绘，单进程、无 Electron，冷启动一秒内，"
                         "大响应也不会把内存吃满。"),
                    perk("code", "可以 diff 的配置",
                         "状态文件是纯文本，能进 Git、能手改、能脚本生成；"
                         "出了问题用编辑器就能查清。"),
                    1, spacing=18)
        gl.addWidget(row1)
        gl.addWidget(row2)

        # ---------- 能力清单：只说「你能用它做什么」，不摆文件名与类名
        abilities = [
            ("发请求", "参数、请求头、Cookies、表单与 JSON 请求体分开填，"
                      "改动即时生效；地址栏支持历史补全与变量替换。"),
            ("看响应", "JSON 树、格式化原文、图片 / 音视频预览、响应时间线四种视角；"
                      "几百 KB 的响应也是秒开，不卡滚动。"),
            ("出文档", "一次点击把请求与响应变成完整接口文档：概览、参数表、"
                      "状态码语义、响应示例，再加上十种语言的调用代码。"),
            ("造假数据", "在自己电脑上起一个真服务，路由、状态码、延迟、动态字段、"
                        "条件规则都能改；前端联调不用等后端排期。"),
            ("多环境", "测试 / 预发 / 线上各存一套变量，{{base_url}} 写在请求里，"
                      "切换环境整组地址一起变。"),
            ("可复用", "每次响应都进历史，能对比、能重放、能直接生成代码；"
                      "集合与配置都是纯文本，可以进 Git、可以脚本生成。"),
        ]
        grid2 = Card(radius=12)
        g2 = QVBoxLayout(grid2)
        g2.setContentsMargins(18, 16, 18, 16)
        g2.setSpacing(14)
        g2.addWidget(Label("它能做什么", 10, t.text_faint,
                           weight=QFont.Weight.DemiBold, spacing=0.8))
        for i in range(0, len(abilities), 2):
            pair = abilities[i:i + 2]
            row = HBox(*[self._ability(*a) for a in pair], 1, spacing=20)
            g2.addWidget(row)

        arch = Card(radius=12)
        al = QVBoxLayout(arch)
        al.setContentsMargins(18, 16, 18, 16)
        al.setSpacing(0)
        al.addWidget(Label("一次请求走完的流程", 10, t.text_faint,
                           weight=QFont.Weight.DemiBold, spacing=0.8))
        al.addSpacing(10)
        steps = [
            ("1", "写好请求", "填地址与参数，变量自动换成当前环境的值"),
            ("2", "发出去", "请求在后台跑，界面不冻结，随时可以取消"),
            ("3", "看结果", "状态、耗时、体积、响应头、响应体一处看完"),
            ("4", "留下来", "进历史、出文档、生代码，下次直接复用"),
        ]
        for i, (num, title, desc) in enumerate(steps):
            if i:
                al.addWidget(Divider())
            al.addWidget(HBox(
                Label(num, 10.2, t.text_faint, mono_font=True), 0,
                Label(title, 11.4, t.text, weight=QFont.Weight.Medium), 0,
                Label(desc, 10.8, t.text_faint), 1,
                spacing=12, margins=(0, 8, 0, 8)))
        al.addWidget(Divider())
        flow = Label("整个过程不离开一个窗口，也不用把参数、响应在各处复制粘贴。",
                     10.8, t.text_faint)
        flow.setWordWrap(True)
        al.addWidget(HBox(flow, 1, margins=(0, 10, 0, 0)))

        foot = Label(f"{i18n.tr('数据目录')} · {APP_DIR}", 10.4, t.text_faint, mono_font=True)
        return self._page_shell("关于 Ocelot", "它是什么、能做什么、为什么这么做。",
                                hero, env_card, grid, grid2, arch, actions, foot)

    def _ability(self, title: str, desc: str) -> QWidget:
        """关于页的能力条目：一行标题 + 两行说明，宽度自适应两列。"""
        t = theme()
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(Label(title, 12.2, t.text, weight=QFont.Weight.DemiBold))
        d = Label(desc, 10.8, t.text_faint)
        d.setWordWrap(True)
        v.addWidget(d)
        return w

    def _copy_version_info(self, button: Button) -> None:
        import platform as _platform
        import sys as _sys

        from PyQt6.QtCore import QT_VERSION_STR
        from PyQt6.QtGui import QGuiApplication

        from .store import APP_DIR

        text = (f"Ocelot {VERSION}\n"
                f"Python {_sys.version.split()[0]} · PyQt6 {QT_VERSION_STR}\n"
                f"{_platform.platform()}\n"
                f"数据目录 {APP_DIR}")
        QGuiApplication.clipboard().setText(text)
        button.setText("已复制")

    # -------------------------------------------------- 行
    def _row(self, title: str, desc: str, control: QWidget, mono_desc: bool = False) -> QWidget:
        """左右一行：左边标题+说明，右边控件。

        说明文字必须可换行 —— 窄窗口下不许把控件挤出卡片边界（云同步页的输入框
        之前就是被顶出右边界的）。
        """
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 11, 2, 11)
        h.setSpacing(16)
        d = Label(desc, 11, theme().text_faint, mono_font=mono_desc)
        d.setWordWrap(True)
        text = VBox(Label(title, 12.5, theme().text), d, spacing=3)
        text.setMaximumWidth(330)
        h.addWidget(text, 1)
        h.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return w

    def _row_stack(self, title: str, desc: str, control: QWidget,
                   mono_desc: bool = False) -> QWidget:
        """上下排：控件独占一整行。输入框 / 多按钮这类「宽控件」用这个，永远不吃边。"""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(2, 11, 2, 13)
        v.setSpacing(8)
        d = Label(desc, 11, theme().text_faint, mono_font=mono_desc)
        d.setWordWrap(True)
        v.addWidget(VBox(Label(title, 12.5, theme().text), d, spacing=3))
        v.addWidget(control)
        return w

    def _apply_page_title(self) -> None:
        label = dict((k, l) for k, l, _i in self.NAV).get(self.nav.current_key(), "设置")
        self._title_label.setText(i18n.trf("设置 · {name}", name=label))

    # -------------------------------------------------- 事件
    def _on_nav(self, key: str) -> None:
        widget = getattr(self, "_page_widgets", {}).get(key)
        if widget is not None and widget is not self.stack.currentWidget():
            self.stack.setCurrentWidget(widget)
        self._apply_page_title()

    def _on_theme(self, name: str) -> None:
        self.store.settings["theme"] = name
        self.store.save()
        self.themeChanged.emit(name)

    def _on_scheme(self, name: str) -> None:
        self._on_theme(name)

    def _on_accent(self, key: str) -> None:
        self.store.settings["accent"] = key
        self.store.save()
        self.accentChanged.emit(key)

    def _on_language(self, value: str) -> None:
        from . import i18n

        self.store.settings["language"] = "en" if value == "en" else "zh"
        self.store.save()
        i18n.set_language(self.store.settings["language"])   # 立即刷新主界面
        self.settingsChanged.emit()

    def _on_anim(self, on: bool) -> None:
        self.store.settings["animations"] = bool(on)
        self.store.save()
        self.settingsChanged.emit()

    def _on_font_size(self, value: str) -> None:
        from .code_editor import CodeView

        try:
            size = float(value)
        except (TypeError, ValueError):
            return
        self.store.settings["code_font_size"] = size
        self.store.save()
        CodeView.set_global_size(size)

    def _on_proxy(self, mode: str) -> None:
        self.store.settings["proxy_mode"] = mode
        self.store.save()

    def _on_ua(self) -> None:
        ua = self.ua.text().strip() or "Ocelot/1.0 (macOS)"
        self.ua.setText(ua)
        self.store.settings["user_agent"] = ua
        self.store.save()

    def _on_history_limit(self, value: str) -> None:
        try:
            limit = int(value)
        except (TypeError, ValueError):
            return
        self.store.settings["history_limit"] = limit
        del self.store.history[limit:]
        self.store.save()

    def _save(self) -> None:
        s = self.store.settings
        try:
            s["timeout"] = max(0, int(self.timeout.text() or 30))
        except (ValueError, AttributeError):
            try:
                self.timeout.setText(str(s.get("timeout", 30)))
            except AttributeError:
                pass
        for attr, key in (("redirect", "follow_redirects"), ("verify", "verify_ssl"),
                          ("auto_name", "auto_name"), ("restore_session", "restore_session")):
            wdg = getattr(self, attr, None)
            if wdg is not None:
                s[key] = wdg.isChecked()
        self.store.save()
        self.settingsChanged.emit()

    def _done(self) -> None:
        self._save()
        if getattr(self, "env_editor", None) is not None:
            self.env_editor.save()
        self.accept()

    def _open_dir(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(STATE_FILE.parent)))

    def _clear_history(self) -> None:
        self.store.clear_history()
        self.store.save()
        self.settingsChanged.emit()

    def showEvent(self, e):
        super().showEvent(e)
        if self._page == "env" and getattr(self, "env_editor", None) is not None:
            self.env_editor._fill_list()


class EnvDelegate(QStyledItemDelegate):
    """环境列表：自绘圆角选中态 + 当前环境圆点。"""

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(0, 33)

    def paint(self, p, option, index):
        t = theme()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        item = index.model().itemData(index)
        name = str(item.get(Qt.ItemDataRole.DisplayRole) or "")
        active = bool(item.get(Qt.ItemDataRole.UserRole))
        rect = QRectF(option.rect).adjusted(4, 2, -4, -2)
        selected = bool(option.state & __import__("PyQt6.QtWidgets", fromlist=["QStyle"]).QStyle.StateFlag.State_Selected)
        if selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.selected))
            p.drawRoundedRect(rect, 6, 6)
        p.setFont(font(12.5, weight=QFont.Weight.Medium if selected else QFont.Weight.Normal))
        p.setPen(C(t.text) if selected else C(t.text_dim))
        p.drawText(QRectF(rect.left() + 10, rect.top(), rect.width() - 30, rect.height()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   QFontMetricsF(p.font()).elidedText(name, Qt.TextElideMode.ElideRight,
                                                      int(rect.width()) - 30))
        if active:
            pm = icons.pixmap("check", t.success, 11, 2.0)
            p.drawPixmap(QPointF(rect.right() - 19, rect.center().y() - 5.5), pm)
        p.restore()


# ---------------------------------------------------------------- 环境变量


class EnvEditor(QWidget):
    """环境变量编辑面板（可内嵌在设置里，不再单独弹窗）。"""

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.envs = copy.deepcopy(store.environments or [])
        self.current = store.data.get("active_env")
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        head = HBox(Label("激活的环境会用于替换 {{变量}}", 10.5, theme().text_faint, mono_font=True),
                    1, spacing=8)
        lay.addWidget(head)

        content = QHBoxLayout()
        content.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(6)
        self.list = QListWidget()
        self.list.setFixedWidth(184)
        self.list.setFont(font(12.5))
        self.list.setItemDelegate(EnvDelegate(self.list))
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setStyleSheet(
            f"QListWidget {{ background: {theme().panel_alt}; border: 1px solid {S(theme().border)};"
            f" border-radius: 9px; padding: 4px; }}")
        self.list.currentRowChanged.connect(self._on_select)
        self.list.itemDoubleClicked.connect(lambda _i: self._rename_env())
        left.addWidget(self.list, 1)
        row = HBox()
        add = icon_button("plus", "新建环境", 28, 15)
        add.clicked.connect(self._add_env)
        rename = icon_button("pencil", "重命名", 28, 15)
        rename.clicked.connect(self._rename_env)
        dele = icon_button("trash", "删除环境", 28, 15)
        dele.clicked.connect(self._delete_env)
        activate = Button("设为当前", None, kind="subtle", height=26, padding=9, font_size=11.5)
        activate.clicked.connect(self._activate)
        row.layout().addWidget(activate)
        row.layout().addSpacing(6)
        row.layout().addWidget(add)
        row.layout().addWidget(rename)
        row.layout().addWidget(dele)
        row.layout().addStretch(1)
        left.addWidget(row)
        content.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.right_label = Label("变量", 11, theme().text_faint)
        right.addWidget(self.right_label)
        self.vars = KVEditor("变量名", "值", empty_hint="添加变量")
        self.vars.changed.connect(self._on_vars_changed)
        right.addWidget(self.vars, 1)
        content.addLayout(right, 1)
        lay.addLayout(content, 1)

        hint = Label("变量名区分大小写；动态变量如 {{$timestamp}} 无需定义。", 10.5,
                     theme().text_faint)
        lay.addWidget(hint)
        self._fill_list()

    def _fill_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for env in self.envs:
            item = QListWidgetItem(env.get("name", "环境"))
            item.setData(Qt.ItemDataRole.UserRole, env.get("id") == self.current)
            self.list.addItem(item)
        self.list.blockSignals(False)
        index = next((i for i, e in enumerate(self.envs) if e.get("id") == self.current), 0)
        if self.envs:
            self.list.setCurrentRow(max(0, min(index, len(self.envs) - 1)))

    def _current_env(self) -> Optional[Dict[str, Any]]:
        row = self.list.currentRow()
        if 0 <= row < len(self.envs):
            return self.envs[row]
        return None

    def _on_select(self, _row: int) -> None:
        env = self._current_env()
        self._loading = True
        if env:
            self.vars.set_rows(env.get("vars", []))
            self.right_label.setText(i18n.trf("变量 · {name}", name=env.get("name", "")))
        else:
            self.vars.set_rows([])
        self._loading = False

    def _on_vars_changed(self) -> None:
        if self._loading:
            return
        env = self._current_env()
        if env:
            env["vars"] = self.vars.rows()

    def _add_env(self) -> None:
        env = {"id": f"env_{len(self.envs)}_{os.urandom(2).hex()}",
               "name": i18n.trf("环境 {n}", n=len(self.envs) + 1), "vars": []}
        self.envs.append(env)
        self._fill_list()
        self.list.setCurrentRow(len(self.envs) - 1)

    def _rename_env(self) -> None:
        env = self._current_env()
        if not env:
            return
        dlg = PromptDialog("重命名环境", "名称", env.get("name", ""), self)
        if dlg.exec() and dlg.value().strip():
            env["name"] = dlg.value().strip()
            self._fill_list()

    def _delete_env(self) -> None:
        env = self._current_env()
        if not env:
            return
        self.envs = [e for e in self.envs if e is not env]
        if self.current == env.get("id"):
            self.current = self.envs[0]["id"] if self.envs else None
        self._fill_list()

    def _activate(self) -> None:
        env = self._current_env()
        if env:
            self.current = env.get("id")
            self._fill_list()

    def save(self) -> None:
        self.store.data["environments"] = self.envs
        self.store.set_active_env(self.current)
        self.store.save()


class EnvDialog:
    """兼容旧入口：直接打开设置的「环境变量」页。"""

    def __init__(self, store: Store, parent=None):
        self.store = store
        self.parent_widget = parent

    def exec(self) -> int:  # noqa: N802
        return SettingsDialog(self.store, self.parent_widget, page="env").exec()


# ---------------------------------------------------------------- 代码片段


class CodeDialog(GlassDialog):
    def __init__(self, request: Dict[str, Any], env: Dict[str, str],
                 settings: Dict[str, Any], parent=None):
        super().__init__(parent, 720, 500, "代码片段")
        self.request = request
        self.env = env
        self.settings = settings

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(16, 8, 16, 14)
        lay.setSpacing(8)

        self.tabs = SegmentedTabs([(key, label) for key, label, _fn, _lang in LANGUAGES],
                                  style="pill", height=28, font_size=11, pad_h=9, spacing=1)
        self.tabs.changed.connect(self._render)
        copy = Button("复制", "copy", kind="subtle", height=28, padding=10, font_size=12)
        copy.clicked.connect(self._copy)
        lay.addWidget(HBox(self.tabs, 1, copy, spacing=8))

        self.code = CodeView(read_only=True, highlight=True, show_gutter=True, wrap=True)
        self.code.set_language("python")
        frame = Card(radius=9)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 4, 0, 4)
        fl.addWidget(self.code)
        lay.addWidget(frame, 1)
        lay.addWidget(Label("已使用当前环境变量解析值，可直接粘贴到终端运行。", 10.5, theme().text_faint))
        self._render(self.tabs.current())

    def _render(self, key: str) -> None:
        for lang_key, _label, gen, language in LANGUAGES:
            if lang_key == key:
                self.code.set_language(language)
                self.code.setPlainText(gen(self.request, self.env, self.settings))
                return
        # 兜底：保持对话框永远有内容
        self.code.set_language("shell")
        self.code.setPlainText(LANGUAGES[0][2](self.request, self.env, self.settings))

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.code.toPlainText())


# ---------------------------------------------------------------- 导入 cURL


class ImportCurlDialog(GlassDialog):
    """粘贴 cURL 命令 → 解析预览 → 新开标签。

    解析用 app/curl_import.parse_curl：方法、URL、查询参数、请求头、
    -d/--data-raw 请求体、-F multipart（含 @file）、-u Basic 认证都能还原。
    """

    def __init__(self, parent=None):
        super().__init__(parent, 640, 460, "导入 cURL")
        self.request = None
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(18, 10, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(Label("粘贴浏览器「Copy as cURL」或任意 cURL 命令，自动解析方法、请求头、请求体与认证。",
                            11, theme().text_faint))
        self.edit = QPlainTextEdit()
        self.edit.setFont(mono(11.5))
        self.edit.setPlaceholderText(
            "curl 'https://api.example.com/v1/users' \\\n"
            "  -X POST \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            "  -H 'Authorization: Bearer token' \\\n"
            "  --data-raw '{\"name\": \"Ocelot\"}'")
        self.edit.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme().code_bg}; border: 1px solid {S(theme().border)};"
            f" border-radius: 9px; padding: 10px; color: {theme().text}; }}")
        self.edit.textChanged.connect(self._preview)
        lay.addWidget(self.edit, 3)

        paste = Button("从剪贴板粘贴", "paste", kind="ghost", height=26, padding=10, font_size=11.5)
        paste.clicked.connect(self._paste_clip)
        lay.addWidget(HBox(1, paste, spacing=6))

        self.preview = Label("", 11, theme().text_dim, mono_font=True)
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(46)
        lay.addWidget(self.preview)
        self.error = Label("", 10.5, theme().danger, mono_font=True)
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        ok = Button("解析并打开", None, kind="primary", height=28, padding=16, font_size=12)
        ok.clicked.connect(self._parse)
        lay.addWidget(HBox(1, cancel, ok, spacing=6))
        self._preview()

    def _paste_clip(self) -> None:
        text = QGuiApplication.clipboard().text()
        if text:
            self.edit.setPlainText(text)

    def _summarize(self, req) -> str:
        bits = [f"{req['method']}  {req['url']}"]
        if req.get("params"):
            bits.append(i18n.trf("查询参数 {n} 个", n=len(req["params"])))
        if req.get("headers"):
            bits.append(i18n.trf("请求头 {n} 个", n=len(req["headers"])))
        body = req.get("body") or {}
        mode = body.get("mode", "none")
        if mode == "json":
            bits.append(i18n.trf("JSON 请求体 {n} 字符", n=len(body.get("raw") or "")))
        elif mode == "text":
            bits.append(i18n.trf("文本请求体 {n} 字符", n=len(body.get("raw") or "")))
        elif mode == "form":
            files = sum(1 for f in body.get("form", []) if f.get("type") == "file")
            bits.append(i18n.trf("multipart {n} 字段", n=len(body.get("form", [])))
                        + (i18n.trf("（含 {n} 个文件）", n=files) if files else ""))
        elif mode == "urlencoded":
            bits.append(i18n.trf("urlencoded {n} 字段", n=len(body.get("form", []))))
        if (req.get("auth") or {}).get("type") == "basic":
            bits.append(i18n.tr("Basic 认证"))
        return " · ".join(bits)

    def _preview(self) -> None:
        from .curl_import import CurlParseError, parse_curl, strip_hints

        text = self.edit.toPlainText()
        if not text.strip():
            self.preview.setText("")
            self.error.setText("")
            self.request = None
            return
        try:
            self.request = strip_hints(parse_curl(text))
        except CurlParseError as exc:
            self.request = None
            self.error.setText(str(exc))
            self.preview.setText("")
            return
        self.error.setText("")
        self.preview.setText(self._summarize(self.request))

    def _parse(self) -> None:
        self._preview()
        if self.request is None:
            if not self.error.text():
                self.error.setText("请先粘贴 cURL 命令")
            return
        self.accept()


# ---------------------------------------------------------------- 更新内容


def _group_items(items: List[str]) -> List[tuple]:
    """按条目内容分组：修复 / 改进 / 新功能，便于阅读。"""
    groups: Dict[str, List[str]] = {"新功能": [], "改进": [], "修复": []}
    for raw in items:
        text = raw.strip()
        if text.startswith("修复"):
            key = "修复"
        elif text.startswith(("新功能", "新增", "增加", "支持", "加入")):
            key = "新功能"
        else:
            key = "改进"
        groups[key].append(text)
    return [(k, v) for k, v in groups.items() if v]


class WhatsNewPanel(QWidget):
    """更新内容面板：版本分组 + 分类小标题 + 自动换行，可滚动。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        host = QWidget()
        host_lay = QVBoxLayout(host)
        host_lay.setContentsMargins(4, 2, 12, 18)
        host_lay.setSpacing(18)
        for i, entry in enumerate(CHANGELOG):
            host_lay.addWidget(self._entry(entry, latest=(i == 0)))
        host_lay.addStretch(1)
        self.scroll.setWidget(host)
        lay.addWidget(self.scroll)

    def _entry(self, entry: Dict[str, Any], latest: bool = False) -> QWidget:
        t = theme()
        card = QWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        ver = Label(f"v{entry.get('version', '')}", 13.5, t.text, mono_font=True,
                    weight=QFont.Weight.DemiBold)
        date = Label(entry.get("date", ""), 10.5, t.text_faint, mono_font=True)
        head = HBox(ver, date, spacing=10)
        if latest:
            tag = Label(i18n.trf("当前版本 {v}", v=VERSION), 9.5, t.text_dim, mono_font=True)
            tag.setStyleSheet(
                f"color: {t.text_dim}; background: {S(t.hover)}; border-radius: 4px;"
                f" padding: 2px 6px;")
            head.layout().addStretch(1)
            head.layout().addWidget(tag)
        lay.addWidget(head)

        group_colors = {"新功能": t.success, "改进": t.info, "修复": t.warning}
        for name, items in _group_items(entry.get("items", [])):
            color = group_colors.get(name, t.text_faint)
            section = Label(f"{name} {len(items)}", 10, color,
                            weight=QFont.Weight.DemiBold, spacing=0.6)
            lay.addWidget(section)
            for text in items:
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(8)
                dot = Label("•", 12, color)
                dot.setFixedWidth(7)
                dot.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
                rl.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
                # 分组标题已标明类别，去掉条目里重复的前缀，读起来更干净
                shown = text
                for prefix in ("新功能：", "修复：", "改进：", "新功能:", "修复:", "改进:"):
                    if shown.startswith(prefix):
                        shown = shown[len(prefix):]
                        break
                body = Label(shown, 12, t.text_dim)
                body.setWordWrap(True)
                rl.addWidget(body, 1)
                lay.addWidget(row)
        return card


class WhatsNewDialog(GlassDialog):
    def __init__(self, parent=None):
        super().__init__(parent, 620, 560, "更新内容")
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(20, 8, 14, 16)
        lay.setSpacing(10)
        lay.addWidget(WhatsNewPanel(), 1)
        ok = Button("关闭", None, kind="primary", height=28, padding=20, font_size=12)
        ok.clicked.connect(self.accept)
        foot = HBox(1, ok, spacing=8)
        foot.layout().setContentsMargins(4, 0, 6, 0)
        lay.addWidget(foot)


# ---------------------------------------------------------------- 命令面板


class PaletteList(QWidget):
    activated = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: List[Dict[str, Any]] = []
        self.index = 0
        self._hover = -1
        self._hover_v = 0.0
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.row_h = 40

    def set_items(self, items: List[Dict[str, Any]]) -> None:
        self.items = items
        self.index = 0
        self._hover = -1
        self._hover_v = 0.0
        self.setFixedHeight(max(1, len(items)) * self.row_h + 8)
        self.update()

    def _row_at(self, y: int) -> int:
        return int((y - 4) // self.row_h)

    def mouseMoveEvent(self, e):
        if not self.rect().contains(e.position().toPoint()):
            if self._hover != -1:
                self._hover = -1
                self._hover_v = 0.0
                self.update()
            return
        idx = self._row_at(int(e.position().y()))
        if not (0 <= idx < len(self.items)):
            idx = -1
        if idx != self._hover:
            # 悬停必须零延迟跟手：不加补间动画，鼠标到哪灰层就在哪
            self._hover = idx
            self._hover_v = 1.0 if idx >= 0 else 0.0
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        if self._hover != -1:
            self._hover = -1
            self._hover_v = 0.0
            self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        idx = self._row_at(int(e.position().y()))
        if 0 <= idx < len(self.items):
            self.activated.emit(idx)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        if not self.items:
            p.setFont(font(12))
            p.setPen(C(t.text_faint))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter),
                       i18n.tr("没有匹配的结果"))
            p.end()
            return
        for i, item in enumerate(self.items):
            r = QRectF(6, 4 + i * self.row_h, self.width() - 12, self.row_h - 2)
            active = i == self.index
            hovered = i == self._hover
            if hovered:
                # 鼠标所在行永远优先，且无延迟
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected))
                p.drawRoundedRect(r, 8, 8)
            elif active:
                # 键盘选中行：只留一圈细边，避免和鼠标灰层抢视觉
                p.setPen(QPen(C(t.border_strong), 1))
                p.setBrush(C(t.hover))
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            ic = item.get("icon", "dot")
            col = t.text if (active or hovered) else t.text_dim
            pm = icons.pixmap(ic, col, 14, 1.6)
            p.drawPixmap(QPointF(r.left() + 12, r.center().y() - 7), pm)
            p.setFont(font(12.5, weight=font(12.5).weight()))
            p.setPen(C(t.text) if (active or hovered) else C(t.text_dim))
            hint = item.get("hint", "")
            hint_w = 52 if hint else 8
            tw = QFontMetricsF(p.font()).horizontalAdvance(item["title"]) + 6
            title_w = min(tw, r.width() * 0.46)
            p.drawText(QRectF(r.left() + 38, r.top(), title_w, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       QFontMetricsF(p.font()).elidedText(item["title"], Qt.TextElideMode.ElideRight,
                                                          max(title_w, 40)))
            sub = item.get("subtitle", "")
            if sub:
                p.setFont(mono(10))
                p.setPen(C(t.text_faint))
                sub_rect = QRectF(r.left() + 38 + title_w + 12, r.top(),
                                  max(r.width() - 60 - title_w - hint_w, 30), r.height())
                p.drawText(sub_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                           QFontMetricsF(p.font()).elidedText(sub, Qt.TextElideMode.ElideMiddle,
                                                              int(sub_rect.width())))
            if hint:
                p.setFont(mono(10))
                p.setPen(C(t.text_faint))
                p.drawText(QRectF(r.right() - hint_w - 6, r.top(), hint_w, r.height()),
                           int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), hint)
        p.end()


class CommandPalette(QWidget):
    """⌘K 命令面板：覆盖主窗口的浮层，可搜索请求与执行动作。"""

    execute = pyqtSignal(str, object)

    ACTIONS = [
        ("new_request", "新建请求", "plus", "⌘N"),
        ("new_folder", "新建文件夹", "folder", ""),
        ("send", "发送当前请求", "send", "⌘↵"),
        ("save", "保存到集合", "download", "⌘S"),
        ("env", "环境变量…", "globe", ""),
        ("settings", "设置…", "sliders", "⌘,"),
        ("appearance", "外观与主题色…", "moon", ""),
        ("cloud", "云同步…", "cloud", ""),
        ("toggle_sidebar", "显示 / 隐藏侧边栏", "layers", "⌘B"),
        ("import_curl", "导入 cURL…", "code", ""),
        ("import_collection", "导入集合…", "download", ""),
        ("export_collection", "导出集合…", "file", ""),
        ("doc", "查看接口文档…", "file", ""),
        ("mock", "Mock 服务…", "grid", ""),
        ("shortcuts", "快捷键设置…", "keyboard", ""),
        ("duplicate", "复制当前请求", "copy", ""),
        ("close_tab", "关闭当前标签", "close", "⌘W"),
    ]

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.hide()
        self._opacity = 0.0

        self.card = Card(radius=13, parent=self)
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(10, 10, 10, 6)
        cl.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setObjectName("Bare")
        i18n.placeholder(self.edit, "搜索请求，或执行命令…")
        self.edit.setFont(font(15))
        self.edit.setFixedHeight(34)
        self.edit.textChanged.connect(self._filter)
        self.edit.installEventFilter(self)
        ic = Label("", 12)
        ic.setFixedSize(15, 15)
        ic.setPixmap(icons.pixmap("search", theme().text_faint, 15, 1.7))
        row = HBox(ic, self.edit, spacing=8, margins=(10, 2, 10, 2))
        cl.addWidget(row)
        cl.addWidget(Divider())
        # 命令越多越长，超出卡片高度就滚动 —— 之前直接按条目数定死高度，
        # 结果最后几条被卡片裁掉，既看不见也滚不到。
        self.scroll = SmoothScrollArea()
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list = PaletteList()
        self.scroll.setWidget(self.list)
        cl.addWidget(self.scroll, 1)
        self.list.activated.connect(self._activate)
        self._results: List[Dict[str, Any]] = []

    # -------------------------------------------------- 打开 / 关闭
    def open(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        self.card.setFixedWidth(min(620, parent.width() - 80))
        self._layout_card()
        self.edit.clear()
        self._filter("")
        bar = self.scroll.verticalScrollBar()
        if bar is not None:
            bar.setValue(0)
        self.edit.setFocus()
        animate(self, 0.0, 1.0, 130, self._set_opacity)

    def _set_opacity(self, v):
        self._opacity = float(v)
        self.update()

    # 搜索框 + 分隔线 + 内外边距固定占掉的高度（写死一个常量，卡片高度才能
    # 正好落在整行上 —— 否则最下面一行会被卡片边缘切掉半截）
    CARD_CHROME = 67

    def _layout_card(self) -> None:
        row_h = self.list.row_h
        total = max(1, len(self._results))
        x = (self.width() - self.card.width()) // 2
        y = int(self.height() * 0.16)
        # 卡片最高到窗口 4/5，超出的行交给滚动区；能放几行就只显示几行，
        # 保证底边永远落在行与行之间
        max_h = max(180, self.height() - 2 * y)
        fits = max(1, (max_h - self.CARD_CHROME - 8) // row_h)
        shown = min(total, fits)
        self.list.setFixedHeight(total * row_h + 8)
        # 视口高度直接按「整行」给足，卡片高度再让布局自己算 —— 差几个像素
        # 就会把最后一行切掉半截，手工累加边距永远对不准
        self.scroll.setFixedHeight(shown * row_h + 8)
        self.card.setFixedHeight(self.card.sizeHint().height())
        self.card.move(x, y)
        self._scroll_to(self.list.index)

    def _scroll_to(self, index: int) -> None:
        if not self._results:
            return
        bar = self.scroll.verticalScrollBar()
        if bar is None:
            return
        row_h = self.list.row_h
        top = 4 + max(0, index) * row_h
        bottom = top + row_h
        view = self.scroll.viewport().height()
        if top < bar.value():
            bar.setValue(top)
        elif bottom > bar.value() + view:
            bar.setValue(bottom - view)

    def close(self) -> None:
        animate(self, 1.0, 0.0, 100, self._set_opacity, on_done=self.hide)

    def hideEvent(self, e):
        self._opacity = 0.0
        super().hideEvent(e)

    def mousePressEvent(self, e):
        if not self.card.geometry().contains(e.position().toPoint()):
            self.close()
        super().mousePressEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        elif e.key() in (Qt.Key.Key_Down,):
            self.list.index = min(self.list.index + 1, len(self._results) - 1)
            self.list.update()
            self._scroll_to(self.list.index)
        elif e.key() in (Qt.Key.Key_Up,):
            self.list.index = max(self.list.index - 1, 0)
            self.list.update()
            self._scroll_to(self.list.index)
        else:
            super().keyPressEvent(e)

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Escape):
                self.keyPressEvent(event)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._activate(self.list.index)
                return True
        return super().eventFilter(obj, event)

    # -------------------------------------------------- 数据
    def _collect(self) -> List[Dict[str, Any]]:
        items = []
        for key, title, icon_name, hint in self.ACTIONS:
            items.append({"kind": "action", "key": key, "title": i18n.tr(title),
                          "icon": icon_name, "hint": hint, "subtitle": ""})
        for env in self.store.environments:
            active = env.get("id") == self.store.data.get("active_env")
            items.append({
                "kind": "env", "key": env.get("id"),
                "title": i18n.trf("切换到环境 · {name}", name=env.get("name", "")),
                "icon": "globe", "hint": i18n.tr("当前") if active else "",
                "subtitle": i18n.trf("{n} 个变量", n=len(env.get("vars") or [])),
            })
        for node, _ in self.store.walk():
            if node.get("type") != "request":
                continue
            items.append({
                "kind": "request", "key": node.get("id"), "node": node,
                "title": node.get("name") or i18n.tr("请求"), "icon": "send",
                "subtitle": f"{node.get('method', 'GET')}  {node.get('url', '')}",
                "hint": "",
            })
        return items

    def _filter(self, text: str) -> None:
        query = (text or "").strip().lower()
        all_items = self._collect()
        if query:
            self._results = [i for i in all_items
                             if query in i["title"].lower() or query in i["subtitle"].lower()]
        else:
            self._results = all_items      # 不再截到 11 条：装不下就滚动
        self.list.set_items(self._results)
        self._layout_card()
        self.update()

    def _activate(self, index: int) -> None:
        if not (0 <= index < len(self._results)):
            return
        item = self._results[index]
        self.close()
        self.execute.emit(item["kind"], item.get("node") or item["key"])

    # -------------------------------------------------- 绘制
    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setOpacity(max(0.0, min(1.0, self._opacity)))
        dim = QColor(0, 0, 0, 130 if t.is_dark else 70)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 12, 12)
        p.fillPath(path, dim)
        p.end()
