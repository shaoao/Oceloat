"""自绘 UI 组件库：按钮、分段标签、淡入堆栈、Toast、开关、骨架屏等。

所有控件均直接 QPainter 绘制，颜色实时读取主题令牌，因此切换浅色/深色
主题时只需 update()，无需重建界面。交互动效统一使用 120~220ms 的
OutCubic / OutQuart 缓动，保持 macOS 的轻盈手感。
"""
from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import brand as brand_mod, i18n, icons
from .anim import animations_on as _animations_on, running as _anim_running, stop as _anim_stop
from .i18n import tr as _tr
from .theme import C, S, font, mono, px, theme


def _mix_colors(a: QColor, b: QColor, t: float) -> QColor:
    """按 t 在两种颜色之间插值，用于选中态淡入淡出。"""
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class Menu(QMenu):
    """圆角菜单。

    原生 QMenu 的窗口是不透明的矩形，QSS 的 border-radius 只在中间画出圆角，
    四个角会残留窗口底色的小方块（截图里菜单角落的「方块」就是这么来的）。
    加上透明底之后圆角才真正生效；其余样式仍由全局 QSS 提供。
    """

    def __init__(self, parent=None, title: str = ""):
        super().__init__(title, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        # WA_TranslucentBackground 下，macOS 常常不绘制样式表里的 QMenu 背景，
        # 结果整个菜单透明、能看见后面的文字（用户截图）。这里把背景交给
        # paintEvent 自绘：先铺不透明圆角底，菜单项仍由 Qt 正常绘制。
        self.setStyleSheet(
            "QMenu { background: transparent; border: none; }")

    def paintEvent(self, e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.elevated))
        p.drawRoundedRect(r, 10, 10)
        p.end()
        super().paintEvent(e)

    # -------------------------------------------------- 语言
    def localize(self) -> None:
        """弹出前把条目文案过一遍 tr()。

        菜单都是一次性构建的（右键菜单、标题栏菜单），不走 apply_language，
        所以在显示这一刻统一翻译最省事：原文记在 action 属性上，来回切换不失真。
        """
        for act in self.actions():
            text = act.text()
            if not text:
                continue
            src = act.property("i18n_src")
            if src is None:
                act.setProperty("i18n_src", text)
                src = text
            act.setText(i18n.tr(src))
            sub = act.menu()
            if sub is not None:
                localize = getattr(sub, "localize", None)
                if callable(localize):
                    localize()

    def exec(self, *args, **kwargs):  # noqa: A003
        self.localize()
        return super().exec(*args, **kwargs)

    def popup(self, *args, **kwargs):
        self.localize()
        return super().popup(*args, **kwargs)


class Quote(QWidget):
    """引用块：一条强调色竖线 + 极淡底，用于文档里的提示/说明。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._label = QLabel(text, self)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(True)
        self._label.setFont(font(12))
        self._label.setContentsMargins(14, 9, 12, 9)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._label)

    def setText(self, text: str) -> None:  # noqa: N802
        self._label.setText(text)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        bg = QColor(C(t.text))
        bg.setAlpha(10 if t.is_dark else 8)
        p.setBrush(bg)
        p.drawRoundedRect(r, 7, 7)
        bar = C(t.accent_dim)
        p.setBrush(bar)
        p.drawRoundedRect(QRectF(r.left() + 6, r.top() + 8, 2.2, r.height() - 16), 1.1, 1.1)
        p.end()


class SuggestPopup(QWidget):
    """地址栏 / 搜索框的历史候选浮层。

    不用 QCompleter 自带的下拉：它在首次显示时会重建自己的视图，之前设的
    delegate 与样式全部被丢掉，弹出来永远是系统白底列表。这里直接做一个浮在
    窗口里的子控件（不是独立窗口），既不抢输入框焦点，也不用跟 Qt 内部较劲。
    """

    ROW_H = 28
    PAD = 5
    MAX_ROWS = 8

    picked = pyqtSignal(str)

    def __init__(self, parent=None, icon_name: str = "clock"):
        super().__init__(parent)
        self.icon_name = icon_name
        self.items: List[str] = []
        self._seen: List[str] = []
        self._hover = -1
        self._width = 460
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.hide()

    # -------------------------------------------------- 数据
    def set_items(self, items: Sequence[str]) -> None:
        self.items = list(items)[: self.MAX_ROWS]
        self._hover = 0 if self.items else -1
        h = self.PAD * 2 + self.ROW_H * len(self.items)
        self.setFixedHeight(max(h, 0))
        self.update()

    def has_items(self) -> bool:
        return bool(self.items)

    def current(self) -> Optional[str]:
        if 0 <= self._hover < len(self.items):
            return self.items[self._hover]
        return None

    def step(self, delta: int) -> None:
        if not self.items:
            return
        self._hover = max(0, min(len(self.items) - 1, self._hover + delta))
        self.update()

    # -------------------------------------------------- 位置
    def popup_below(self, anchor: QWidget, width: Optional[int] = None) -> None:
        """贴在 anchor 下沿弹出；空间不够时向上翻。"""
        win = anchor.window()
        if win is None:
            return
        self.setParent(win)
        self._width = int(width or max(anchor.width(), 320))
        self.setFixedWidth(self._width)
        top_left = anchor.mapTo(win, QPoint(0, anchor.height() + 4))
        max_y = win.height() - self.height() - 8
        if top_left.y() > max_y:                       # 下方放不下：翻到上方
            top_left = anchor.mapTo(win, QPoint(0, -self.height() - 4))
            top_left.setY(max(8, top_left.y()))
        top_left.setX(max(8, min(top_left.x(), win.width() - self._width - 8)))
        self.move(top_left)
        self.show()
        self.raise_()

    # -------------------------------------------------- 交互
    def mouseMoveEvent(self, e):
        idx = int((e.position().y() - self.PAD) // self.ROW_H)
        if 0 <= idx < len(self.items) and idx != self._hover:
            self._hover = idx
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            text = self.current()
            self.hide()
            if text:
                self.picked.emit(text)
        super().mouseReleaseEvent(e)

    # -------------------------------------------------- 绘制
    def paintEvent(self, _e):
        if not self.items:
            return
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.elevated))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(Qt.PenStyle.NoPen)
        f = mono(11.5)
        p.setFont(f)
        fm = QFontMetricsF(f)
        for i, text in enumerate(self.items):
            row = QRectF(4, self.PAD + i * self.ROW_H, self.width() - 8, self.ROW_H)
            if i == self._hover:
                p.setBrush(C(t.selected))
                p.drawRoundedRect(row.adjusted(0, 1.5, 0, -1.5), 6, 6)
                p.setBrush(Qt.BrushStyle.NoBrush)
            pm = icons.pixmap(self.icon_name, t.text_dim if i == self._hover else t.text_faint,
                              11, 1.6)
            p.drawPixmap(QPointF(row.left() + 8, row.center().y() - pm.height() / 2), pm)
            p.setPen(C(t.text if i == self._hover else t.text_dim))
            p.drawText(QPointF(row.left() + 27,
                               row.center().y() + (fm.ascent() - fm.descent()) / 2),
                       fm.elidedText(text, Qt.TextElideMode.ElideMiddle, row.width() - 34))
        p.end()


# ---------------------------------------------------------------- 布局助手


def _add(layout, items: Sequence) -> None:
    for item in items:
        if item is None:
            continue
        if isinstance(item, int):
            layout.addStretch(item)
        elif isinstance(item, QWidget):
            layout.addWidget(item)
        elif isinstance(item, tuple):
            if len(item) == 2 and isinstance(item[1], int) and isinstance(item[0], QWidget):
                layout.addWidget(item[0], item[1])
            else:
                layout.addLayout(item)


def HBox(*items, spacing: int = 8, margins=(0, 0, 0, 0), parent=None) -> QWidget:
    w = QWidget(parent)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    _add(lay, items)
    return w


def VBox(*items, spacing: int = 8, margins=(0, 0, 0, 0), parent=None) -> QWidget:
    w = QWidget(parent)
    lay = QVBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    _add(lay, items)
    return w



def _scroll_host(widget) -> object:
    """找到承载自己的滚动区。

    setWidget 之后 QWidget 的 parent 是 viewport，不是滚动区本身，
    所以要往上找几层；找不到就当作没有滚动（整块可见）。
    """
    w = widget.parentWidget() if widget is not None else None
    for _ in range(4):
        if w is None:
            return None
        if hasattr(w, "verticalScrollBar"):
            return w
        w = w.parentWidget()
    return None

# ---------------------------------------------------------------- 动画助手


def animate(widget: QWidget, start, end, dur: int = 180,
            on_value: Optional[Callable] = None,
            easing: QEasingCurve.Type = QEasingCurve.Type.OutCubic,
            on_done: Optional[Callable] = None) -> QVariantAnimation:

    anim = QVariantAnimation(widget)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(easing)
    if on_value is not None:
        anim.valueChanged.connect(on_value)
    if on_done is not None:
        anim.finished.connect(on_done)
    if not _animations_on():
        # 关闭动效：直接落到终值
        anim.setDuration(0)
        if on_value is not None:
            on_value(end)
        if on_done is not None:
            on_done()
        return anim
    anim.setDuration(dur)
    anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


def _has_native_child(widget: QWidget) -> bool:
    """子树里是否存在带原生窗口句柄的控件（QVideoWidget / QOpenGLWidget 等）。"""
    try:
        for child in widget.findChildren(QWidget):
            if child.testAttribute(Qt.WidgetAttribute.WA_NativeWindow):
                return True
    except RuntimeError:
        return False
    return False


def fade_window(widget: QWidget, dur: int = 160, start: float = 0.0,
                on_done: Optional[Callable] = None) -> None:
    """顶层窗口的淡入：走窗口原生透明度，绝不使用 QGraphicsOpacityEffect。

    macOS 上给「无边框 + WA_TranslucentBackground」的顶层窗口挂图形特效，
    会在 Qt 渲染线程触发 SIGBUS 硬崩（崩溃日志里 <no Python frame>，抓不到
    Python 栈）。窗口透明度由窗口服务器合成，是唯一安全的方式。
    """

    _anim_stop(getattr(widget, "_fade_anim", None))
    if not _animations_on():
        widget.setWindowOpacity(1.0)
        if on_done is not None:
            on_done()
        return
    widget.setWindowOpacity(max(0.0, min(1.0, start)))

    def step(v):
        try:
            widget.setWindowOpacity(max(0.0, min(1.0, float(v))))
        except RuntimeError:
            pass

    def done():
        try:
            widget.setWindowOpacity(1.0)
        except RuntimeError:
            pass
        if on_done:
            on_done()

    widget._fade_anim = animate(widget, start, 1.0, dur, step, on_done=done)


def fade_in(widget: QWidget, dur: int = 160, start: float = 0.0,
            on_done: Optional[Callable] = None) -> None:
    """给控件做一次淡入，结束后移除 effect 避免影响子控件渲染质量。

    同一控件重复触发时会先停止上一次动画，避免访问已销毁的 effect。
    顶层窗口自动改走 fade_window（原生透明度），规避 macOS 的 SIGBUS。
    """

    if widget.isWindow():
        fade_window(widget, dur, start, on_done)
        return
    if not _animations_on():
        if on_done is not None:
            on_done()
        return
    # 子树里若有原生窗口（音视频预览的 QVideoWidget 等），QGraphicsOpacityEffect
    # 会在 macOS 上令渲染层 SIGBUS；这种页面只淡入普通控件，含原生的直接跳过。
    if _has_native_child(widget):
        if on_done is not None:
            on_done()
        return
    _anim_stop(getattr(widget, "_fade_anim", None))
    eff = QGraphicsOpacityEffect(widget)
    eff.setOpacity(start)
    widget.setGraphicsEffect(eff)

    def step(v):
        try:
            if widget.graphicsEffect() is eff:
                eff.setOpacity(float(v))
        except RuntimeError:
            pass

    def done():
        try:
            if widget.graphicsEffect() is eff:
                widget.setGraphicsEffect(None)
        except RuntimeError:
            pass
        if on_done:
            on_done()

    widget._fade_anim = animate(widget, start, 1.0, dur, step, on_done=done)


# ---------------------------------------------------------------- 按钮基类


class Button(QWidget):
    """自绘按钮。kind: ghost(默认) / primary(反色实心) / subtle / danger / plain。"""

    clicked = pyqtSignal()

    def __init__(self, text: str = "", icon_name: Optional[str] = None,
                 kind: str = "ghost", icon_size: int = 15, height: int = 28,
                 padding: int = 9, radius: int = 7, font_size: float = 12.5,
                 mono_font: bool = False, tooltip: Optional[str] = None,
                 parent=None, min_width: int = 0, gap: int = 6):
        super().__init__(parent)
        self._text = text
        self._icon_name = icon_name
        self._kind = kind
        self._icon_size = icon_size
        self._height = height
        self._padding = padding
        self._radius = radius
        self._font = mono(font_size) if mono_font else font(font_size)
        self._min_width = min_width
        self._gap = gap
        self._hover = 0.0
        self._pressed = False
        self._busy = False
        self._angle = 0.0
        self._icon_rotation = 0.0
        self._spin_anim: Optional[QVariantAnimation] = None
        self._enabled = True
        self._checked = False
        self._tip = tooltip or ""
        if tooltip:
            self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._anim: Optional[QVariantAnimation] = None
        self._spin = QTimer(self)
        self._spin.setInterval(16)
        self._spin.timeout.connect(self._tick)

    # -------------------------------------------------- 属性
    def setText(self, text: str) -> None:
        self._text = text
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def set_icon(self, name: Optional[str]) -> None:
        self._icon_name = name
        self.updateGeometry()
        self.update()

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self.update()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self._spin.start()
        else:
            self._spin.stop()
            self._angle = 0.0
        self.updateGeometry()
        self.update()

    def set_checked(self, checked: bool) -> None:
        self._checked = checked
        self.update()

    def spin_once(self, duration: int = 560) -> None:
        """图标原地转一圈：刷新按钮点击后给一次明确的「我干活了」反馈。

        和 _busy 的连续转圈不同，这里只转 360° 后归零；图标旋转靠
        paintEvent 里的 translate/rotate，不另起定时器，复用统一动画。
        """
        if self._icon_name is None:
            return
        _anim_stop(self._spin_anim)
        self._icon_rotation = 0.0

        def _done():
            self._icon_rotation = 0.0
            self.update()

        self._spin_anim = animate(
            self, 0.0, 360.0, duration,
            lambda v: (setattr(self, "_icon_rotation", float(v)), self.update()),
            QEasingCurve.Type.InOutCubic, on_done=_done)

    def set_icon_rotation(self, deg: float) -> None:
        """直接摆到位（不做动画）：启动恢复分栏方向时用。"""
        _anim_stop(self._spin_anim)
        self._icon_rotation = float(deg)
        self.update()

    def rotate_icon(self, to_deg: float, duration: int = 240) -> None:
        """图标从当前角度转到 to_deg：用于「分栏方向」这类状态型图标。"""
        _anim_stop(self._spin_anim)
        start = float(getattr(self, "_icon_rotation", 0.0))
        if abs(start - to_deg) < 0.5:
            self._icon_rotation = to_deg
            self.update()
            return
        self._spin_anim = animate(
            self, start, float(to_deg), duration,
            lambda v: (setattr(self, "_icon_rotation", float(v)), self.update()),
            QEasingCurve.Type.OutCubic)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        self._enabled = enabled
        super().setEnabled(enabled)
        self.update()

    def _tick(self) -> None:
        self._angle = (self._angle + 9) % 360
        self.update()

    def _colors(self) -> Tuple[QColor, QColor, QColor]:
        t = theme()
        if self._kind == "primary":
            bg = C(t.accent)
            fg = C(t.accent_text)
            if self._hover > 0:
                bg = bg.lighter(100 + int(6 * self._hover)) if t.is_dark else bg.lighter(112)
            if self._pressed:
                bg = bg.darker(108) if t.is_dark else bg.darker(112)
            return bg, fg, bg
        if self._kind == "danger":
            base = C(t.danger)
            bg = QColor(base)
            bg.setAlpha(int(28 + 40 * self._hover))
            return bg, base, base
        if self._kind == "subtle":
            bg = C(t.panel_alt)
            if self._hover:
                bg = QColor(bg)
                bg = bg.lighter(100 + int(10 * self._hover)) if t.is_dark else bg
            fg = C(t.text) if self._checked else C(t.text_dim)
            return bg, fg, C(t.border)
        # ghost
        bg = C(t.hover)
        bg.setAlpha(int(C(t.hover).alpha() * self._hover))
        fg = C(t.text) if (self._hover > 0.3 or self._checked) else C(t.text_dim)
        return bg, fg, bg

    def _title(self) -> str:
        return _tr(self._text)

    # -------------------------------------------------- 绘制
    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetricsF(self._font)
        w = self._padding * 2
        if self._busy:
            w += 13
            if self._text:
                w += self._gap
        elif self._icon_name:
            w += self._icon_size
            if self._text:
                w += self._gap
        if self._text:
            w += fm.horizontalAdvance(self._title()) + 1
        return QSize(max(int(w), self._min_width), self._height)

    def enterEvent(self, e):  # noqa: N802
        self._start_hover(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._start_hover(0.0)
        self._pressed = False
        self.update()
        super().leaveEvent(e)

    def _start_hover(self, target: float) -> None:
        _anim_stop(self._anim)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(target)
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_hover)
        self._anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_hover(self, v) -> None:
        self._hover = float(v)
        self.update()

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self._enabled:
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self._pressed and e.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self.update()
            if self.rect().contains(e.position().toPoint()):
                self.clicked.emit()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(e)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        if not self._enabled:
            p.setOpacity(0.38)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg, fg, border = self._colors()
        if self._kind == "subtle":
            p.setPen(QPen(QColor(border), 1))
        else:
            p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg if bg.alpha() > 0 else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, self._radius, self._radius)

        x = self._padding
        cy = r.center().y() + (0.5 if self._pressed else 0)
        if self._busy:
            self._draw_spinner(p, QRectF(x, cy - 6.5, 13, 13), fg)
            x += 13 + (self._gap if self._text else 0)
        elif self._icon_name:
            pm = icons.pixmap(self._icon_name, fg.name(QColor.NameFormat.HexArgb),
                              self._icon_size, 1.55)
            rot = getattr(self, "_icon_rotation", 0.0)
            if rot:
                p.save()
                p.translate(x + self._icon_size / 2, cy)
                p.rotate(rot)
                p.drawPixmap(QPointF(-self._icon_size / 2, -self._icon_size / 2), pm)
                p.restore()
            else:
                p.drawPixmap(QPointF(x, cy - self._icon_size / 2), pm)
            x += self._icon_size + (self._gap if self._text else 0)
        if self._text:
            p.setFont(self._font)
            p.setPen(fg)
            rect = QRectF(x, r.top(), r.width() - x - self._padding, r.height())
            p.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._title())
        p.end()

    def _draw_spinner(self, p: QPainter, rect: QRectF, color: QColor) -> None:
        pen = QPen(color, 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect, int(-self._angle * 16), int(260 * 16))


def icon_button(icon_name: str, tooltip: str = "", size: int = 26,
                icon_size: int = 15, kind: str = "ghost", parent=None) -> Button:
    b = Button("", icon_name, kind=kind, icon_size=icon_size, height=size,
               padding=(size - icon_size) // 2, radius=6, tooltip=tooltip, parent=parent)
    b.setFixedWidth(size)
    b._min_width = size
    return b


# ---------------------------------------------------------------- 自绘选择菜单


class ChoiceMenu(QWidget):
    """轻量自绘下拉：语义色文字 + 图标对号 + 悬停灰层。

    原生 QMenu 的 checkmark 在 macOS 深色主题下会画成乱码小图标（用户截图里
    格式菜单 JSON 前的牙签），且样式不受控；这里统一用自绘 Popup 解决。
    items: [(key, label, color_or_none, hint_or_none)]
    """

    ROW_H = 30
    PAD = 5
    picked = pyqtSignal(str)

    def __init__(self, items: Sequence[Tuple[str, str, Optional[str], Optional[str]]],
                 current: str, parent=None, width: int = 178):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._items = [list(it) for it in items]
        self._current = current
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.resize(width, self.PAD * 2 + len(self._items) * self.ROW_H + 4)

    def set_current(self, key: str) -> None:
        self._current = key
        self._hover = -1
        self.update()

    def popup(self, global_pos) -> None:
        from PyQt6.QtGui import QGuiApplication

        self.localize()
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = min(global_pos.x(), geo.right() - self.width() - 6)
        y = global_pos.y()
        if y + self.height() > geo.bottom():
            y = max(geo.top() + 6, geo.bottom() - self.height() - 6)
        self.move(int(x), int(y))
        self._hover = -1
        self.update()
        self.show()
        self.raise_()

    def _row_rect(self, i: int) -> QRectF:
        return QRectF(self.PAD, self.PAD + i * self.ROW_H,
                      self.width() - self.PAD * 2, self.ROW_H - 2)

    def _row_at(self, y: float) -> int:
        i = int((y - self.PAD) // self.ROW_H)
        return i if 0 <= i < len(self._items) else -1

    def localize(self) -> None:
        """把菜单项文案按当前语言翻一遍。

        菜单是自绘的，走不了 i18n.apply_language（那套只管 QLabel / QAbstractButton），
        所以这里在弹出前自己翻一次；hint（右侧的补充说明）同样要翻。
        原文记在 _src_items 里，来回切语言不会把英文当成原文再翻一遍。
        """

        src = getattr(self, "_src_items", None)
        if src is None:
            src = [tuple(it) for it in self._items]
            self._src_items = src
        for orig, item in zip(src, self._items):
            if len(orig) >= 2 and isinstance(orig[1], str):
                item[1] = _tr(orig[1])
            if len(orig) >= 4 and isinstance(orig[3], str):
                item[3] = _tr(orig[3])
        self.update()

    def items(self) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
        return [tuple(it) for it in self._items]

    def mouseMoveEvent(self, e):
        if not self.rect().contains(e.position().toPoint()):
            if self._hover != -1:
                self._hover = -1
                self.update()
            return
        idx = self._row_at(e.position().y())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def mouseReleaseEvent(self, e):
        idx = self._row_at(e.position().y())
        if 0 <= idx < len(self._items):
            self.picked.emit(self._items[idx][0])
            self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.elevated))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        for i, item in enumerate(self._items):
            key, label, color, hint = (list(item) + [None, None])[:4]
            rr = self._row_rect(i)
            if i == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected))
                p.drawRoundedRect(rr, 7, 7)
            p.setFont(font(12.5, QFont.Weight.Medium))
            p.setPen(C(color) if color else C(t.text))
            p.drawText(QRectF(rr.left() + 12, rr.top(), rr.width() - 36, rr.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
            if hint:
                p.setFont(font(10.5))
                p.setPen(C(t.text_faint))
                p.drawText(QRectF(rr.left() + 12 + QFontMetricsF(font(12.5, QFont.Weight.Medium))
                                  .horizontalAdvance(label) + 8, rr.top(), 60, rr.height()),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), hint)
            if key == self._current:
                pm = icons.pixmap("check", t.text, 12, 1.9)
                p.drawPixmap(QPointF(rr.right() - 18, rr.center().y() - 6), pm)
        p.end()


# ---------------------------------------------------------------- 分段标签


class SegmentedTabs(QWidget):
    """macOS 风格分段控件 / 下划线标签。items: [(key, label, badge)]"""

    changed = pyqtSignal(str)

    def __init__(self, items: Sequence[Tuple[str, str]], style: str = "underline",
                 current: Optional[str] = None, parent=None, font_size: float = 12.5,
                 spacing: int = 2, pad_h: int = 11, height: int = 30,
                 show_badges: bool = True):
        super().__init__(parent)
        self._items: List[Dict] = []
        self._style = style
        self._pad_h = pad_h
        self._spacing = spacing
        self._fsize = font_size
        self._font = font(font_size, QFont.Weight.Medium)
        self._badge_font = mono(9.5)
        self._hover = -1
        self._hover_v = 0.0
        self._show_badges = show_badges
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._indicator = 0.0
        self._indicator_w = 0.0
        self._pill = QRectF()
        self._prev_key = ""
        self._fade_t = 1.0
        self._fade_anim: Optional[QVariantAnimation] = None
        self._anim: Optional[QVariantAnimation] = None
        self._badge_anims: Dict[str, float] = {}
        for key, label in items:
            self._items.append({"key": key, "label": label, "badge": 0})
        self._current = current or (self._items[0]["key"] if self._items else "")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _label(self, item: Dict) -> str:
        return _tr(item["label"])

    def refresh_scale(self) -> None:
        """界面文字大小变了：内部字体是按构造时的系数算死的，重算一遍。"""
        self._font = font(self._fsize, QFont.Weight.Medium)
        self._badge_font = mono(9.5)
        self.sync_size()

    def sync_size(self) -> None:
        """按当前语言重新量宽度。

        控件是 Fixed 策略，宽度取 sizeHint；语言一换（「集合 / 历史」变成
        Collections / History）文字长度就变了，父布局不会自己重排，
        结果第二个标签被裁掉半截 —— 所以这里主动把尺寸钉到新的 sizeHint。
        """
        self.updateGeometry()
        want = self.sizeHint().width()
        if want and (self.minimumWidth() != want or self.maximumWidth() != want):
            self.setFixedWidth(want)
        self._snap_indicator()

    # -------------------------------------------------- API
    def set_label(self, key: str, label: str) -> None:
        for item in self._items:
            if item["key"] == key and item["label"] != label:
                item["label"] = label
                self.sync_size()
                self.update()
                return

    def set_badge(self, key: str, count: int) -> None:
        for item in self._items:
            if item["key"] == key:
                if item["badge"] != count:
                    item["badge"] = count
                    self.sync_size()
                    self.update()
                return

    def set_items(self, items: Sequence[Tuple[str, str]], current: Optional[str] = None) -> None:
        """整组换标签：HTTP 请求与 WebSocket 请求用的是两套页签。"""
        keys = [k for k, _l in items]
        if keys == [i["key"] for i in self._items] and current is None:
            return
        self._items = [{"key": k, "label": label, "badge": 0} for k, label in items]
        if current not in keys:
            current = keys[0] if keys else ""
        self._current = current or ""
        self._hover = -1
        self._prev_key = ""
        self._anim_stop_all()
        self.sync_size()
        self._snap_indicator()
        self.update()

    def _anim_stop_all(self) -> None:
        _anim_stop(self._anim)
        _anim_stop(self._fade_anim)

    def has(self, key: str) -> bool:
        return any(i["key"] == key for i in self._items)

    def current(self) -> str:
        return self._current

    def set_current(self, key: str, emit: bool = False) -> None:
        for item in self._items:
            if item["key"] == key:
                if self._current == key:
                    if not _anim_running(self._anim):
                        self._snap_indicator()
                    return
                self._prev_key = self._current
                self._current = key
                self._animate_indicator()
                self._animate_fade()
                self.update()
                if emit:
                    self.changed.emit(key)
                return

    def _rects(self) -> List[QRectF]:
        fm = QFontMetricsF(self._font)
        rects = []
        x = 0.0
        for item in self._items:
            w = fm.horizontalAdvance(self._label(item)) + self._pad_h * 2
            if self._show_badges and item["badge"]:
                w += QFontMetricsF(self._badge_font).horizontalAdvance(str(item["badge"])) + 8
            rects.append(QRectF(x, 0, w, self.height()))
            x += w + self._spacing * 2
        return rects

    def sizeHint(self) -> QSize:  # noqa: N802
        rects = self._rects()
        return QSize(int(rects[-1].right()) + 2 if rects else 0, self.height())

    def _snap_indicator(self) -> None:
        rects = self._rects()
        _anim_stop(self._fade_anim)
        self._fade_t = 1.0
        self._prev_key = ""
        for i, item in enumerate(self._items):
            if item["key"] == self._current and i < len(rects):
                self._indicator = rects[i].left()
                self._indicator_w = rects[i].width()
                self._pill = rects[i].adjusted(0, 2, 0, -2)
        self.update()

    def _animate_fade(self) -> None:
        _anim_stop(self._fade_anim)
        self._fade_t = 0.0
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(220)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _on(value):
            self._fade_t = float(value)
            self.update()

        anim.valueChanged.connect(_on)
        self._fade_anim = anim
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _animate_indicator(self) -> None:
        rects = self._rects()
        target = None
        for i, item in enumerate(self._items):
            if item["key"] == self._current and i < len(rects):
                target = rects[i]
        if target is None:
            return
        _anim_stop(self._anim)
        self._anim = QVariantAnimation(self)
        start = QRectF(self._pill) if not self._pill.isNull() else QRectF(target)
        end = QRectF(target.adjusted(0, 2, 0, -2))
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuint)
        self._anim.valueChanged.connect(self._on_indicator)
        self._anim.finished.connect(lambda: self._snap_pill_only(end))
        self._anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _snap_pill_only(self, rect: QRectF) -> None:
        self._pill = QRectF(rect)
        self._indicator = rect.left()
        self._indicator_w = rect.width()
        self.update()

    def _on_indicator(self, v) -> None:
        r = v
        self._indicator = r.left()
        self._indicator_w = r.width()
        self._pill = QRectF(r)
        self.update()

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self.sync_size()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if not _anim_running(self._anim):
            self._snap_indicator()

    # -------------------------------------------------- 交互
    def mouseMoveEvent(self, e):  # noqa: N802
        idx = -1
        for i, r in enumerate(self._rects()):
            if r.contains(e.position()):
                idx = i
                break
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        for i, r in enumerate(self._rects()):
            if r.contains(e.position()):
                self.set_current(self._items[i]["key"], emit=True)
                return

    # -------------------------------------------------- 绘制
    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        rects = self._rects()
        moving = _anim_running(self._anim) or self._fade_t < 0.999
        for i, (item, r) in enumerate(zip(self._items, rects)):
            active = item["key"] == self._current
            if active:
                hot = self._fade_t if self._prev_key else 1.0
            elif self._prev_key == item["key"] and self._fade_t < 1.0:
                hot = 1.0 - self._fade_t
            else:
                hot = 0.0
            if self._style == "pill":
                # 选中的胶囊用动画中的实时矩形，跟手滑过去，而不是整块瞬移
                if moving and not self._pill.isNull() and active:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(C(t.accent_soft))
                    p.drawRoundedRect(self._pill, 7, 7)
                elif active:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(C(t.accent_soft))
                    p.drawRoundedRect(r.adjusted(0, 2, 0, -2), 7, 7)
                elif i == self._hover:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(C(t.hover))
                    p.drawRoundedRect(r.adjusted(0, 2, 0, -2), 7, 7)
            elif i == self._hover and not active:
                p.setPen(Qt.PenStyle.NoPen)
                c = C(t.hover)
                c.setAlpha(int(c.alpha() * 0.7))
                p.setBrush(c)
                p.drawRoundedRect(r.adjusted(0, 3, 0, -3), 6, 6)

            p.setFont(self._font)
            # 选中项跟着主题色走：自动 = 原来的文字色，彩色 = 该强调色
            base = C(t.text_dim if i == self._hover else t.text_faint)
            col = _mix_colors(base, C(t.accent), hot) if hot > 0.001 else base
            x = r.left() + self._pad_h
            text_rect = QRectF(x, r.top(), r.width() - self._pad_h * 2, r.height())
            p.setPen(col)
            p.drawText(text_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       self._label(item))
            if self._show_badges and item["badge"]:
                tw = QFontMetricsF(self._font).horizontalAdvance(self._label(item))
                btext = str(item["badge"])
                bw = QFontMetricsF(self._badge_font).horizontalAdvance(btext) + 10
                br = QRectF(x + tw + 6, r.center().y() - 7.5, bw, 15)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected) if active else C(t.hover))
                p.drawRoundedRect(br, 7.5, 7.5)
                p.setFont(self._badge_font)
                p.setPen(C(t.accent) if active else C(t.text_dim))
                p.drawText(br, int(Qt.AlignmentFlag.AlignCenter), btext)

        if self._style == "underline" and self._indicator_w > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.accent))
            bar = QRectF(self._indicator + 7, self.height() - 3.0, max(self._indicator_w - 14, 8), 2.0)
            p.drawRoundedRect(bar, 1, 1)
        p.end()


# ---------------------------------------------------------------- 淡入堆栈


class FadeStack(QWidget):
    """轻量堆栈容器，切换页面时 140ms 淡入 + 4px 上浮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages: Dict[str, QWidget] = {}
        self._current: Optional[str] = None
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)

    def add(self, key: str, widget: QWidget, alias: bool = False) -> None:
        """加入一页。alias=True 时只为另一个 key 复用同一控件，不再塞进布局。"""
        self._pages[key] = widget
        if alias:
            return
        widget.setParent(self)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        widget.hide()
        self._lay.addWidget(widget, 1)

    def current(self) -> Optional[str]:
        return self._current

    def set_current(self, key: str, animate: bool = True) -> None:
        """切换页面；同一控件被多个 key 复用时，切到别名页也只更新内部状态。"""
        widget = self._pages.get(key)
        if widget is None:
            return
        if key == self._current:
            return
        old = self._pages.get(self._current) if self._current else None
        self._current = key
        if old is not widget:
            if old is not None:
                old.hide()
            widget.show()
            if animate:
                fade_in(widget, 150)


# ---------------------------------------------------------------- 其它原子控件


class Spinner(QWidget):
    def __init__(self, size: int = 16, color: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._size = size
        self._color = color
        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start()
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._angle = (self._angle + 9) % 360
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(C(self._color or t.text_dim), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = QRectF(1.6, 1.6, self._size - 3.2, self._size - 3.2)
        p.drawArc(r, int(-self._angle * 16), int(250 * 16))
        p.end()


class Switch(QWidget):
    """macOS 开关，38x22，knob 位移带弹性缓动。"""

    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._pos = 1.0 if checked else 0.0
        self.setFixedSize(38, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim: Optional[QVariantAnimation] = None

    def isChecked(self) -> bool:  # noqa: N802
        return self._checked

    def setChecked(self, value: bool, emit: bool = False) -> None:  # noqa: N802
        if value == self._checked:
            return
        self._checked = value
        _anim_stop(self._anim)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if value else 0.0)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._anim.valueChanged.connect(self._on_pos)
        self._anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
        if emit:
            self.toggled.emit(value)

    def _on_pos(self, v):
        self._pos = max(0.0, min(1.08, float(v)))
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.setChecked(not self._checked, emit=True)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        off = QColor(0, 0, 0, 40) if not t.is_dark else QColor(255, 255, 255, 46)
        on = C(t.accent)
        pos = max(0.0, min(1.0, self._pos))
        bg = QColor(
            int(off.red() + (on.red() - off.red()) * pos),
            int(off.green() + (on.green() - off.green()) * pos),
            int(off.blue() + (on.blue() - off.blue()) * pos),
            int(off.alpha() + (on.alpha() - off.alpha()) * pos),
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = self.height() - 4
        x = 2 + pos * (self.width() - d - 4)
        knob = C(t.accent_text) if pos > 0.5 else (QColor("#FFFFFF") if t.is_dark else QColor("#FFFFFF"))
        p.setPen(QPen(QColor(0, 0, 0, 34), 0.8))
        p.setBrush(knob)
        p.drawEllipse(QRectF(x, 2, d, d))
        p.end()


class Divider(QWidget):
    def __init__(self, vertical: bool = False, parent=None):
        super().__init__(parent)
        self._vertical = vertical
        if vertical:
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setPen(QPen(C(t.border), 1))
        if self._vertical:
            p.drawLine(0, 0, 0, self.height())
        else:
            p.drawLine(0, 0, self.width(), 0)
        p.end()


class Card(QFrame):
    def __init__(self, radius: int = 10, parent=None, fill: Optional[str] = None,
                 border: bool = True):
        super().__init__(parent)
        self._radius = radius
        self._fill = fill
        self._border = border

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(C(t.border), 1) if self._border else Qt.PenStyle.NoPen)
        p.setBrush(C(self._fill or t.card))
        p.drawRoundedRect(r, self._radius, self._radius)
        p.end()


def infer_token(color) -> Optional[str]:
    """把具体的颜色值反查为主题令牌名，便于切换主题时重新着色。"""
    if color is None:
        return None
    t = theme()
    for name in ("text", "text_dim", "text_faint", "success", "warning", "danger",
                 "info", "accent", "accent_text", "window", "panel", "elevated"):
        if getattr(t, name, None) == color:
            return name
    return None


class Label(QLabel):
    def __init__(self, text: str = "", size: float = 12.5, color=None,
                 weight: QFont.Weight = QFont.Weight.Normal, mono_font: bool = False,
                 parent=None, spacing: float = 0.0):
        super().__init__("", parent)
        self.setFont(mono(size, weight, spacing) if mono_font else font(size, weight, spacing))
        self._token = infer_token(color)
        self._raw = color
        self.setText(text)
        self.refresh_theme()

    def setText(self, text: str) -> None:  # noqa: N802
        """写入时就把中文原文记下来并显示译文。

        页面里的文案大多在控件构造那一刻写进来 —— 如果界面已经是英文，
        apply_language 那次遍历早就跑完了，晚造出来的这一批就永远停在中英混排。
        在 setText 这一步翻译，创建顺序就无所谓了。
        """
        if not isinstance(text, str):
            return super().setText(text)
        src = self.property("i18n_src_text")
        # apply_language 回写的是译文，别把它当成新原文存下来
        if not (src and text == i18n.tr(src)):
            self.setProperty("i18n_src_text", text)
            src = text
        super().setText(i18n.tr(src or text))

    def refresh_theme(self) -> None:
        col = getattr(theme(), self._token) if self._token else self._raw
        if col:
            self.setStyleSheet(f"color: {col}; background: transparent;")
        else:
            self.setStyleSheet("background: transparent;")

    # -------------------------------------------------- 数字过渡
    def animate_number(self, value, fmt: Callable[..., str], duration: int = 280) -> None:
        """数字变化时做一次短补间（一条动画，不额外起定时器）。

        value 可以是数字，也可以是一组数字；fmt 收到补间后的当前值并返回文案。
        连续调用会从当前显示值接着走，不会突然跳回起点。
        """
        values = tuple(float(v) for v in value) if isinstance(value, (tuple, list)) \
            else (float(value),)
        anim = getattr(self, "_num_anim", None)
        if anim is None:
            anim = QVariantAnimation(self)
            anim.setDuration(duration)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._num_value = values
            self._num_from = values
            self._num_to = values
            self._num_fmt = fmt
            anim.valueChanged.connect(self._apply_number)
            self._num_anim = anim
        anim.stop()
        self._num_from = self._num_value
        self._num_to = values
        self._num_fmt = fmt
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()

    def _apply_number(self, progress) -> None:
        t = float(progress)
        vals = tuple(a + (b - a) * t for a, b in zip(self._num_from, self._num_to))
        self._num_value = vals
        # 直接走 QLabel：数字不是文案，不该每次补间都过一遍 i18n 字典
        QLabel.setText(self, self._num_fmt(*vals))


class Pill(QWidget):
    """状态胶囊：文本 + 语义色，带轻微底色。"""

    def __init__(self, text: str = "", color: Optional[str] = None, parent=None,
                 font_size: float = 10.5, mono_font: bool = True, pad: int = 8,
                 height: int = 19, radius: int = 6):
        super().__init__(parent)
        self._text = text
        self._color = color
        self._token = infer_token(color)
        self._font = mono(font_size, QFont.Weight.DemiBold) if mono_font else font(font_size, QFont.Weight.DemiBold)
        self._pad = pad
        self._radius = radius
        self._alpha = 34
        self._min_height = height
        self.setFixedHeight(height)
        self._sync_size()

    def _sync_size(self) -> None:
        """按真实字形量宽度并钉死尺寸。

        英文译文比中文长（「失败」→ failed），而 QWidget 的 minimumSizeHint
        近乎为 0，水平布局在空间紧张时会把它压到比文字还窄，文字直接溢出胶囊底
        —— 所以这里自己算死宽高，布局再也压不动它。
        """
        fm = QFontMetricsF(self._font)
        text = self._title()
        w = int(fm.horizontalAdvance(text) + self._pad * 2 + 6)
        self.setFixedWidth(max(w, self._pad * 2 + 12))
        h = max(self._min_height, int(fm.height() + 7))
        if self.height() != h:
            self.setFixedHeight(h)

    def set_text(self, text: str) -> None:
        self._text = text
        self._sync_size()
        self.updateGeometry()
        self.update()

    def set_color(self, color: Optional[str]) -> None:
        self._color = color
        self._token = infer_token(color)
        self.update()

    def refresh_theme(self) -> None:
        if self._token:
            self._color = getattr(theme(), self._token)
        # 语言切换后 self._title() 变了，尺寸也要跟着重量一遍
        self._sync_size()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetricsF(self._font)
        return QSize(int(fm.horizontalAdvance(self._title()) + self._pad * 2), self.height())

    def _title(self) -> str:
        return i18n.tr(self._text) if isinstance(self._text, str) else str(self._text)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        col = C(self._color or t.text_dim)
        bg = QColor(col)
        bg.setAlpha(self._alpha)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        r = QRectF(self.rect())
        p.drawRoundedRect(r, self._radius, self._radius)
        p.setFont(self._font)
        p.setPen(col)
        p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), self._title())
        p.end()


class EmptyState(QWidget):
    """空状态：环形图标 + 标题 + 副标题 + 快捷键提示。"""

    def __init__(self, icon_name: str = "send", title: str = "", subtitle: str = "",
                 hint: str = "", parent=None, brand_mark: bool = False):
        super().__init__(parent)
        self._icon = icon_name
        self._title = title
        self._subtitle = subtitle
        self._hint = hint
        # 品牌位：用线条标识代替「圆环 + 图标」，进页面时自己描一遍
        self._brand = brand_mark
        self.mark = None
        if brand_mark:
            self.mark = brand_mod.BrandMark(px(56), self, autoplay=True,
                                            token="text_faint", hover_token="text")
            self.setMouseTracking(True)

    def set_text(self, title: str, subtitle: str = "", hint: str = "") -> None:
        self._title, self._subtitle, self._hint = title, subtitle, hint
        self.update()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if self.mark is not None:
            cx, cy = self.width() / 2, self.height() / 2 - px(14)
            side = self.mark.width()
            self.mark.move(int(cx - side / 2), int(cy - px(58) - side / 2 + px(27)))

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self.width() / 2, self.height() / 2 - px(14)
        if not self._brand:
            # 圆环（尺寸都跟着界面字号走，150% 时不会和下面的文字叠在一起）
            ring = QRectF(cx - px(27), cy - px(62), px(54), px(54))
            p.setPen(QPen(C(t.border_strong), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(ring)
            pm = icons.pixmap(self._icon, t.text_faint, px(22), 1.5)
            p.drawPixmap(QPointF(cx - px(11), cy - px(62) + px(16)), pm)
        p.setFont(font(13.5, QFont.Weight.DemiBold))
        p.setPen(C(t.text_dim))
        p.drawText(QRectF(cx - px(200), cy + px(2), px(400), px(22)),
                   int(Qt.AlignmentFlag.AlignCenter), i18n.tr(self._title))
        p.setFont(font(11.5))
        p.setPen(C(t.text_faint))
        p.drawText(QRectF(cx - px(220), cy + px(24), px(440), px(40)),
                   int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                   i18n.tr(self._subtitle))
        if self._hint:
            fm = QFontMetricsF(mono(10.5))
            hint = i18n.tr(self._hint)
            w = fm.horizontalAdvance(hint) + px(20)
            hr = QRectF(cx - w / 2, cy + px(70), w, px(21))
            p.setPen(QPen(C(t.border), 1))
            p.setBrush(C(t.panel_alt))
            p.drawRoundedRect(hr, 5, 5)
            p.setFont(mono(10.5))
            p.setPen(C(t.text_faint))
            p.drawText(hr, int(Qt.AlignmentFlag.AlignCenter), hint)
        p.end()


class Shimmer(QWidget):
    """骨架屏：多条圆角占位条，带扫光动画。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _tick(self):
        self._phase = (self._phase + 0.011) % 1.4
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        base = C(t.panel_alt)
        w = self.width()
        widths = [0.86, 0.62, 0.74, 0.45, 0.7, 0.55, 0.3]
        y = 6.0
        for i, frac in enumerate(widths):
            h = 11 if i % 3 else 9
            bar = QRectF(2, y, max(40, (w - 20) * frac), h)
            grad = QLinearGradient(bar.left(), 0, bar.right(), 0)
            hi = QColor(base)
            hi.setAlpha(120)
            c1 = QColor(base)
            c1.setAlpha(70)
            pos = self._phase
            grad.setColorAt(max(0.0, min(1.0, pos - 0.25)), c1)
            grad.setColorAt(max(0.0, min(1.0, pos)), hi)
            grad.setColorAt(max(0.0, min(1.0, pos + 0.25)), c1)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(bar, 4, 4)
            y += h + 9
        p.end()


class FindBar(QWidget):
    """响应内容查找条：⌘F 唤出，高亮/计数/上下跳转。"""

    closed = pyqtSignal()
    search = pyqtSignal(str, bool)  # text, backwards
    textChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self._edit = QLineEdit()
        i18n.placeholder(self._edit, "在响应中查找…")
        self._edit.setFont(font(12))
        self._edit.setFixedHeight(24)
        self._edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; padding-left: 2px; "
            f"color: {theme().text}; }}")
        self._count = Label("", 10.5, theme().text_faint, mono_font=True)
        prev = icon_button("chevron_up", "上一个", 22, 13)
        nxt = icon_button("chevron_down", "下一个", 22, 13)
        close = icon_button("close", "关闭", 22, 13)
        prev.clicked.connect(lambda: self._go(False))
        nxt.clicked.connect(lambda: self._go(True))
        close.clicked.connect(self._close)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 6, 0)
        lay.setSpacing(4)
        lay.addWidget(Label("查找", 10.5, theme().text_faint))
        lay.addWidget(self._edit, 1)
        lay.addWidget(self._count)
        lay.addWidget(prev)
        lay.addWidget(nxt)
        lay.addWidget(close)
        self._edit.textChanged.connect(self.textChanged.emit)
        self._edit.returnPressed.connect(lambda: self._go(False))
        self.setStyleSheet(
            f"FindBar {{ background: {theme().panel_alt}; border-top: 1px solid {S(theme().border)}; }}")

    def refresh_theme(self) -> None:
        t = theme()
        self._edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; padding-left: 2px; color: {t.text}; }}")
        self.setStyleSheet(
            f"FindBar {{ background: {t.panel_alt}; border-top: 1px solid {S(t.border)}; }}")

    def set_count(self, current: int, total: int) -> None:
        self._count.setText(f"{current}/{total}" if total else "无结果")

    def _go(self, backwards: bool) -> None:
        self.search.emit(self._edit.text(), backwards)

    def _close(self) -> None:
        self.hide()
        self.closed.emit()

    def focus(self) -> None:
        self._edit.setFocus()
        self._edit.selectAll()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._close()
            return
        super().keyPressEvent(e)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(C(t.border), 1))
        p.drawLine(0, 0, self.width(), 0)
        p.end()


class AvatarDot(QWidget):
    """环境指示小圆点（带呼吸动效）。"""

    def __init__(self, color: str, size: int = 6, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(self._color))
        p.drawEllipse(QRectF(0, 0, self.width(), self.height()))
        p.end()


class ElideLabel(QLabel):
    """会自己省略的标签。

    QLabel 不会省略长文本，写死 elidedText 又会在窗口变化时错位。
    这里保留完整文本，每次绘制按当前宽度重新省略 —— 列表里的地址、
    文件路径用它，行与行之间才能严格对齐。
    """

    def __init__(self, text: str = "", size: float = 12.2, color=None,
                 weight: QFont.Weight = QFont.Weight.Normal, mono_font: bool = False,
                 mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle, parent=None):
        super().__init__("", parent)
        self._full = text or ""
        self.setFont(mono(size, weight) if mono_font else font(size, weight))
        self._token = infer_token(color)
        self._raw = color
        self._mode = mode
        self._ink = QColor("#EDEDF1")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.refresh_theme()
        self.setToolTip("")

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text or ""
        self.setToolTip(self._full if len(self._full) > 26 else "")
        self.update()

    def _shown(self) -> str:
        """显示用文本：完整原文过一遍 tr()，路由名 / 说明这类数据也在里面。"""
        return i18n.tr(self._full) if self._full else ""

    def text(self) -> str:  # noqa: N802
        return self._full

    def refresh_theme(self) -> None:
        col = getattr(theme(), self._token) if self._token else self._raw
        if col:
            self._ink = C(col)
        self.setStyleSheet("background: transparent;")

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(24, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetricsF(self.font())
        return QSize(int(fm.horizontalAdvance(self._shown())) + 2, int(fm.height()) + 2)

    def paintEvent(self, _e):
        shown = self._shown()
        if not shown:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setFont(self.font())
        p.setPen(self._ink)
        fm = QFontMetricsF(self.font())
        text = fm.elidedText(shown, self._mode, max(self.width(), 10))
        y = (self.height() + fm.ascent() - fm.descent()) / 2
        p.drawText(QPointF(0, y), text)
        p.end()


class SmoothScrollArea(QScrollArea):
    """滚轮带缓动的滚动区。

    鼠标滚轮一格是 120，直接跳过去很生硬；这里每格只走 78px 并做 170ms 缓动，
    触控板的高精度滚动（pixelDelta）也照原样跟手。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._apply)

    def _apply(self, value) -> None:
        bar = self.verticalScrollBar()
        if bar is not None:
            bar.setValue(int(value))

    def wheelEvent(self, e):  # noqa: N802
        bar = self.verticalScrollBar()
        if bar is None or bar.maximum() <= 0:
            return
        pixel = e.pixelDelta().y()
        if pixel:
            bar.setValue(bar.value() - pixel)
            return
        delta = e.angleDelta().y()
        if not delta:
            return
        step = -delta / 120 * 78
        target = int(max(bar.minimum(), min(bar.value() + step, bar.maximum())))
        # 动画在部分环境（safemode / 某些平台）不会发出 valueChanged，滚轮会
        # 彻底失灵。先直接落到目标值保证一定能滚，再用动画只是锦上添花的缓动
        # ——真要缓动时从原位置插到目标；不能把「能滚」押在动画回调上。
        if os.environ.get("OCELOT_NO_ANIM"):
            bar.setValue(target)
            return
        _anim_stop(self._anim)
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()
        if self._anim.state() == QVariantAnimation.State.Stopped:
            bar.setValue(target)


class KeyCap(QWidget):
    """键帽：显示一个快捷键，可点击（设置页用来录制）。"""

    clicked = pyqtSignal()

    def __init__(self, text: str = "", parent=None, recording: bool = False,
                 width: int = 0, height: int = 22):
        super().__init__(parent)
        self._text = text
        self._recording = recording
        self._hover = False
        self._font = mono(10.6, QFont.Weight.Medium, 0.3)
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._fixed_w = width
        if width:
            self.setFixedWidth(width)

    def set_text(self, text: str, recording: bool = False) -> None:
        self._text = text or ""
        self._recording = recording
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def sizeHint(self) -> QSize:  # noqa: N802
        if self._fixed_w:
            return QSize(self._fixed_w, self.height())
        fm = QFontMetricsF(self._font)
        return QSize(int(fm.horizontalAdvance(self._text) + 20), self.height())

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._recording:
            fill, edge, ink = C(t.accent_soft), C(t.accent_dim), t.text
        elif self._hover:
            fill, edge, ink = C(t.hover), C(t.border_strong), t.text
        else:
            fill, edge, ink = C(t.panel_alt), C(t.border), t.text_dim
        p.setPen(QPen(edge, 1))
        p.setBrush(fill)
        p.drawRoundedRect(r, 5, 5)
        p.setFont(self._font)
        p.setPen(C(ink))
        p.drawText(r, int(Qt.AlignmentFlag.AlignCenter),
                   self._text or "未设置")
        p.end()
