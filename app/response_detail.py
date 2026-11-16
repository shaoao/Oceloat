"""响应指标悬浮详情卡：响应时间分段、响应大小分解。

设计要点：
- 悬停触发，位置固定在被绑定控件下方，不跟随鼠标。
- 自绘、纯色、白灰层次；图标统一用 24×24 线性图标缓存。
- 所有元素按「顺序累加」排版：标题 → 分割线 → 占比条 → 指标行 → 脚注，
  不再用「距底部 N 像素」定位脚注，避免脚注压住最后一行（用户截图 bug）。
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from PyQt6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QVariantAnimation,
    QEasingCurve,
)
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from . import icons
from .theme import C, font, theme

Row = Tuple[str, str, float]

# 每行图标：沿用线性图标语言，不用彩色 emoji。
ROW_ICONS = {
    "准备": "refresh",
    "Socket 初始化": "globe",
    "DNS 查询": "globe",
    "TCP 握手": "node",
    "SSL 握手": "lock",
    "等待中 (TTFB)": "send",
    "下载内容": "download",
    "处理": "gear",
    "Header": "file",
    "Body": "code",
}


class DetailCard(QWidget):
    """自绘详情卡：标题行 + 图标行 + 可选条形 + 脚注。"""

    _ready = False          # 布局算完才置 True，空壳包装实例直接跳过绘制

    PAD = 15
    ICON_BOX = 22          # 标题与指标行共用一个方块尺寸，确保左边缘严格对齐
    HEAD_H = 44
    ROW_H = 28
    ROW_ICON = 18

    def __init__(self, title: str, total: str, rows: List[Row],
                 bars: bool = False, parent=None,
                 head_icon: str = "clock", note: str = "",
                 split: bool = False):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowTransparentForInput
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._title = title
        self._total = total
        self._rows = rows
        self._bars = bars
        self._split = split
        self._head_icon = head_icon
        self._note = note

        fm = QFontMetricsF(font(11.5))
        label_w = max([fm.horizontalAdvance(r[0]) for r in rows] + [64])
        self._label_w = int(min(max(label_w + 4, 96), 132))
        self._value_w = 58
        # 时间卡要给条形留位置；大小卡只展示两段占比，整体更窄。
        self._w = 356 if bars else 300

        # ---- 顺序布局：每一段的 y 只依赖上一段的结束位置 ----
        y = self.PAD
        self._head_y = y
        y += self.HEAD_H
        self._sep_y = y
        y += 10                                   # 分割线下方留白
        self._split_y = None
        if self._split and self._rows:
            self._split_y = y
            y += 18
        self._rows_y = y
        y += len(rows) * self.ROW_H
        self._note_y = y + 4 if note else None
        if note:
            y += 20
        self._h = y + self.PAD
        self.setFixedSize(self._w, self._h)

        # 条形的 x：跟随标签列结束位置，右端给数值列留出固定间隔。
        label_x = self.PAD + self.ICON_BOX + 10
        bar_x = label_x + self._label_w + 12
        self._bar_x = bar_x
        self._bar_w = max(60, self._w - self.PAD - self._value_w - 14 - bar_x) if bars else 0

        self._opacity = QVariantAnimation(self)
        self._opacity.setDuration(130)
        self._opacity.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._opacity.valueChanged.connect(self.setWindowOpacity)
        self._ready = True

    def paintEvent(self, _e):  # noqa: N802
        # 主题刷新会遍历所有子控件并 update()。Qt 有时会为「Python 包装对象已回收、
        # C++ 对象还挂在父控件上」的卡片重新包一层空壳实例，此时 __dict__ 是空的，
        # 直接画会 AttributeError（PyQt6 里等于直接 abort）。这种空壳本来也不该显示。
        if not getattr(self, "_ready", False):
            return
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.elevated))
        p.drawRoundedRect(r, 12, 12)

        x = self.PAD
        # 标题区：图标方块与下方指标行图标方块同宽同 x
        head = QRectF(x, self._head_y, self.ICON_BOX, self.ICON_BOX)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(t.hover))
        p.drawRoundedRect(head, 6, 6)
        pm = icons.pixmap(self._head_icon, t.text_dim, 14, 1.65)
        icons.draw_centered(p, pm, head.center().x(), head.center().y())

        tx = head.right() + 10
        p.setFont(font(13.5, QFont.Weight.DemiBold))
        p.setPen(C(t.text))
        p.drawText(QRectF(tx, self._head_y + 1, 160, 22),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._title)
        p.setFont(font(9.5, QFont.Weight.Medium))
        p.setPen(C(t.text_faint))
        p.drawText(QRectF(tx, self._head_y + 21, 180, 16),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   "DETAILED METRICS")

        p.setFont(font(14, QFont.Weight.DemiBold))
        p.setPen(C(t.text))
        p.drawText(QRectF(self._w - self.PAD - 118, self._head_y + 3, 118, 26),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), self._total)

        p.setPen(QPen(C(t.border), 1))
        p.drawLine(QPointF(x, self._sep_y), QPointF(self._w - x, self._sep_y))

        # 大小卡：一条两段的分配条，直观区分 Header / Body。
        if self._split_y is not None and self._rows:
            total = sum(max(0.0, row[2]) for row in self._rows) or 1.0
            sw = self._w - 2 * x
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.hover))
            p.drawRoundedRect(QRectF(x, self._split_y, sw, 5), 2.5, 2.5)
            cx = x
            for i, (_label, _value, ratio) in enumerate(self._rows):
                seg = sw * max(0.0, ratio) / total
                if seg <= 0:
                    continue
                col = QColor(C(t.success) if i == 1 else C(t.text_dim))
                if t.is_dark and i == 0:
                    col.setAlpha(210)
                p.setBrush(col)
                p.drawRoundedRect(QRectF(cx, self._split_y, max(3.0, seg), 5), 2.5, 2.5)
                cx += seg

        icon_x = x
        label_x = icon_x + self.ICON_BOX + 10
        for i, (label, value, ratio) in enumerate(self._rows):
            y = self._rows_y + i * self.ROW_H
            faded = not value or value in ("—", "0ms", "0B")
            icon_name = ROW_ICONS.get(label, "dot")
            icon_col = t.text_faint if faded else (t.success if self._bars and ratio > 0.35 else t.text_dim)

            # 图标方块垂直居中于整行，图标再居中于方块——两层居中保证不错位。
            box = QRectF(icon_x, y + (self.ROW_H - self.ROW_ICON) / 2,
                         self.ROW_ICON, self.ROW_ICON)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.hover))
            p.drawRoundedRect(box, 5, 5)
            pm = icons.pixmap(icon_name, icon_col, 11, 1.7)
            icons.draw_centered(p, pm, box.center().x(), box.center().y())

            p.setFont(font(11.5))
            p.setPen(C(t.text_faint if faded else t.text_dim))
            p.drawText(QRectF(label_x, y, self._label_w, self.ROW_H),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)

            if self._bars:
                track = QRectF(self._bar_x, y + self.ROW_H / 2 - 3, self._bar_w, 6)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(C(t.hover).red(), C(t.hover).green(), C(t.hover).blue(), 110))
                p.drawRoundedRect(track, 3, 3)
                if ratio > 0:
                    bw = max(4.0, self._bar_w * max(0.02, min(1.0, ratio)))
                    fill = QColor(C(t.success))
                    if faded:
                        fill.setAlpha(60)
                    p.setBrush(fill)
                    p.drawRoundedRect(QRectF(track.x(), track.y(), bw, 6), 3, 3)

            p.setFont(font(11.5, QFont.Weight.Medium))
            p.setPen(C(t.text_faint if faded else t.text))
            p.drawText(QRectF(self._w - self.PAD - self._value_w, y,
                              self._value_w, self.ROW_H),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), value)

        if self._note_y is not None:
            p.setFont(font(9.5))
            p.setPen(C(t.text_faint))
            p.drawText(QRectF(x, self._note_y, self._w - 2 * x, 18),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._note)
        p.end()

    def show_below(self, widget: QWidget, gap: int = 8) -> None:
        """锚定到控件下方；空间不够则在其上方。全程不使用鼠标坐标。"""
        screen = QApplication.primaryScreen().availableGeometry()
        below = widget.mapToGlobal(QPoint(0, widget.height()))
        above = widget.mapToGlobal(QPoint(0, 0))
        x = below.x() - 10
        x = min(max(6, x), screen.right() - self.width() - 6)
        y = below.y() + gap
        if y + self.height() > screen.bottom() - 6:
            y = above.y() - self.height() - gap
        y = min(max(screen.top() + 6, y), screen.bottom() - self.height() - 6)
        self.move(int(x), int(y))
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._opacity.setStartValue(0.0)
        self._opacity.setEndValue(1.0)
        self._opacity.start()

    def show_at(self, pos: QPoint) -> None:  # 兼容旧调用：不再跟随鼠标
        screen = QApplication.primaryScreen().availableGeometry()
        x = min(max(6, pos.x() - 10), screen.right() - self.width() - 6)
        y = min(max(6, pos.y() + 8), screen.bottom() - self.height() - 6)
        self.move(int(x), int(y))
        self.show()
        self.raise_()


class DetailController(QObject):
    """把 builder(widget) -> DetailCard 绑定到控件，悬浮时弹出固定卡片。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._card: Optional[DetailCard] = None
        self._binds: dict = {}
        self._shown_for = None
        QApplication.instance().installEventFilter(self)

    def bind(self, widget: QWidget, builder: Callable[[], DetailCard]) -> None:
        self._binds[widget] = builder
        widget.setAttribute(Qt.WidgetAttribute.WA_Hover, False)

    def _alive(self, w) -> bool:
        try:
            w.isVisible()
            return True
        except RuntimeError:
            return False

    def hide(self) -> None:
        if self._card is not None and self._alive(self._card):
            self._card.hide()
        self._shown_for = None

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        et = ev.type()
        if obj in self._binds:
            if et in (QEvent.Type.Enter, QEvent.Type.ToolTip):
                if self._shown_for is obj and self._card is not None:
                    return True
                builder = self._binds[obj]
                try:
                    card = builder()
                except Exception:  # noqa: BLE001
                    return False
                if card is None:
                    return False
                self.hide()
                self._card = card
                self._shown_for = obj
                card.show_below(obj)
                return True
            if et == QEvent.Type.Leave:
                self.hide()
        if et in (QEvent.Type.MouseButtonPress, QEvent.Type.Wheel, QEvent.Type.KeyPress):
            self.hide()
        return False
