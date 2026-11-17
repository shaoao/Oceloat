"""自绘提示框。

系统 QToolTip 的尺寸不受样式表控制（在 Retina 上会莫名其妙地又高又大），
这里改成自己画一个：尺寸严格贴合文字，圆角、细边、跟随光标。
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer
from PyQt6.QtGui import QCursor, QFontMetricsF, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from . import i18n
from .theme import C, font, theme

PAD_X = 8
PAD_Y = 4
RADIUS = 6
MAX_W = 320


class TipLabel(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._text = ""
        self._lines: list[str] = []
        self._size = (0, 0)

    def text(self) -> str:
        return self._text

    def _measure(self, text: str) -> None:
        f = font(11)
        fm = QFontMetricsF(f)
        self._text = text
        self._lines = []
        for raw in text.split("\n"):
            self._lines.append(raw if fm.horizontalAdvance(raw) <= MAX_W
                               else fm.elidedText(raw, Qt.TextElideMode.ElideRight, MAX_W))
        w = max((fm.horizontalAdvance(line) for line in self._lines), default=0)
        h = fm.height() * max(1, len(self._lines))
        self._size = (int(w + PAD_X * 2 + 2), int(h + PAD_Y * 2 + 2))
        self.setFixedSize(*self._size)

    def show_at(self, pos: QPoint, text: str) -> None:
        self._measure(text)
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x, y = pos.x(), pos.y()
        if x + self.width() > geo.right():
            x = geo.right() - self.width() - 4
        if y + self.height() > geo.bottom():
            y = pos.y() - self.height() - 16
        self.move(max(geo.left(), x), max(geo.top(), y))
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.elevated))
        p.drawRoundedRect(r, RADIUS, RADIUS)
        p.setFont(font(11))
        p.setPen(C(t.text))
        fm = QFontMetricsF(p.font())
        line_h = fm.height()
        for i, line in enumerate(self._lines):
            p.drawText(QRectF(PAD_X, PAD_Y + i * line_h, r.width() - PAD_X * 2, line_h),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), line)
        p.end()


class TipController(QObject):
    """全局接管 QToolTip：换成自绘的小提示框。"""

    _inst: Optional["TipController"] = None

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app
        self.tip = TipLabel()
        self._origin = QPoint()
        self._guard = QTimer(self)
        self._guard.setSingleShot(True)
        self._guard.setInterval(6000)
        self._guard.timeout.connect(self.hide)
        app.installEventFilter(self)

    @classmethod
    def install(cls, app: Optional[QApplication] = None) -> "TipController":
        if cls._inst is None:
            app = app or QApplication.instance()
            cls._inst = cls(app)
        return cls._inst

    def _alive(self) -> bool:
        try:
            self.tip.isVisible()
            return True
        except RuntimeError:      # C++ 对象已析构，Python 壳还在
            return False

    def hide(self) -> None:
        self._guard.stop()
        if self._alive() and self.tip.isVisible():
            self.tip.hide()

    def _should_skip(self, obj: QObject) -> bool:
        return not isinstance(obj, QWidget) or isinstance(obj, TipLabel)

    def eventFilter(self, obj, ev):  # noqa: N802
        et = ev.type()
        if et == QEvent.Type.ToolTip and not self._should_skip(obj):
            # 提示语在这里翻译：控件可能在语言切完之后才建出来，逐个打补丁容易漏
            text = i18n.tr((obj.toolTip() or "").strip())
            if not text:
                return False
            pos = QCursor.pos() + QPoint(10, 18)
            self._origin = pos
            if not self._alive():
                self.tip = TipLabel()
            self.tip.show_at(pos, text)
            self._guard.start()
            return True
        if et in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress,
                  QEvent.Type.Wheel, QEvent.Type.WindowDeactivate):
            self.hide()
        elif et == QEvent.Type.MouseMove and self._alive() and self.tip.isVisible():
            pos = QCursor.pos()
            if (pos - self._origin).manhattanLength() > 26:
                self.hide()
        elif et == QEvent.Type.Leave and self._alive() and self.tip.isVisible():
            self.hide()
        return False


def install(app: Optional[QApplication] = None) -> TipController:
    return TipController.install(app)
