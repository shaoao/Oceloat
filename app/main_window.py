"""主窗口：无边框圆角窗口、交通灯、侧栏、标签、面板分割与全局快捷键。"""
from __future__ import annotations

import base64
import copy as _copy
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
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
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import i18n, icons
from .brand import BrandMark, app_icon as brand_icon
from .code_editor import CodeView, human_elapsed
from .dialogs import CodeDialog, CommandPalette, EnvDialog, ImportCurlDialog, SettingsDialog
from .http_client import ApiClient, Response
from .ws_client import WsClient
from .sio_client import SocketIoClient
from .request_panel import REALTIME_METHODS, SIO_METHOD, RequestEditor
from .response_panel import ResponsePanel
from .sidebar import Sidebar
from .store import Store, kv, new_request, resolve_vars, uid
from .tabs import TabStrip
from .anim import set_animations, stop as _anim_stop
from .theme import (C, apply_theme, font, mono, px, set_accent, set_ui_scale,
                    theme, theme_by_name)
from .widgets import (Divider, HBox, Label, Menu, VBox, animate, fade_window,
                      icon_button)

APP_NAME = "Ocelot"


# ---------------------------------------------------------------- 交通灯


class TitleBar(QWidget):
    """标题栏：空白区域可拖动窗口，双击缩放。"""

    def __init__(self, window: QWidget, parent=None):
        super().__init__(parent)
        self._window = window
        self.setMouseTracking(True)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._window.isMaximized():
                self._window.showNormal()
            else:
                self._window.showMaximized()


class TrafficLights(QWidget):
    def __init__(self, window: QWidget, parent=None):
        super().__init__(parent)
        self.window = window
        self.setFixedSize(64, 14)
        self._hover = -1
        self._group_hover = False
        self.setMouseTracking(True)

    def _rects(self):
        return [QRectF(0 + i * 20, 1, 12, 12) for i in range(3)]

    def enterEvent(self, e):
        self._group_hover = True
        self.update()

    def leaveEvent(self, e):
        self._group_hover = False
        self._hover = -1
        self.update()

    def mouseMoveEvent(self, e):
        idx = -1
        for i, r in enumerate(self._rects()):
            if r.adjusted(-3, -3, 3, 3).contains(e.position()):
                idx = i
                break
        if idx != self._hover:
            self._hover = idx
            self.update()

    def mouseReleaseEvent(self, e):
        idx = self._hover
        if idx == 0:
            self.window.close()
        elif idx == 1:
            self.window.showMinimized()
        elif idx == 2:
            if self.window.isMaximized():
                self.window.showNormal()
            else:
                self.window.showMaximized()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = ["#FF5F57", "#FEBC2E", "#28C840"]
        glyphs = ["close", "minus", "plus"]
        for i, r in enumerate(self._rects()):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(colors[i]))
            p.drawEllipse(r)
            if self._group_hover:
                if self._hover == i:
                    pm = icons.pixmap(glyphs[i], "#00000099", 7, 2.6)
                else:
                    pm = icons.pixmap(glyphs[i], "#00000044", 7, 2.6)
                p.drawPixmap(QPointF(r.center().x() - 3.5, r.center().y() - 3.5), pm)
        p.end()


# ---------------------------------------------------------------- 环境胶囊


class EnvPill(QWidget):
    clicked = pyqtSignal()
    manageRequested = pyqtSignal()

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self._hover = False
        self._hover_v = 0.0
        self._anim: Optional[QVariantAnimation] = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(26)
        self.setToolTip("切换环境变量")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def _name(self) -> str:
        env = self.store.active_environment()
        return env.get("name", "无环境") if env else "无环境"

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetricsF(font(11.5))
        return QSize(int(fm.horizontalAdvance(self._name())) + 58, 26)

    def enterEvent(self, e):
        self._hover = True
        self._to(1.0)

    def leaveEvent(self, e):
        self._hover = False
        self._to(0.0)

    def _to(self, target):
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
        t = theme()
        menu = Menu(self)
        for env in self.store.environments:
            act = menu.addAction(env.get("name", "环境"))
            if env["id"] == self.store.data.get("active_env"):
                act.setIcon(icons.icon("check", t.text, 13))
            act.triggered.connect(lambda _c=False, eid=env["id"]: self._choose(eid))
        menu.addSeparator()
        manage = menu.addAction(icons.icon("gear", t.text, 13), "管理环境…")
        manage.triggered.connect(self.manageRequested.emit)
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _choose(self, env_id: str):
        self.store.set_active_env(env_id)
        self.store.save()
        self.updateGeometry()
        self.update()
        self.clicked.emit()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = C(t.hover)
        bg.setAlpha(int(bg.alpha() * (0.55 + 0.45 * self._hover_v)))
        p.setPen(QPen(C(t.border), 1))
        p.setBrush(C(t.panel_alt) if self._hover_v < 0.5 else bg)
        p.drawRoundedRect(r, 7, 7)
        pm = icons.pixmap("globe", t.text_dim, 13, 1.6)
        p.drawPixmap(QPointF(9, r.center().y() - 6.5), pm)
        p.setFont(font(11.5, QFont.Weight.Medium))
        p.setPen(C(t.text if self._hover_v > 0.4 else t.text_dim))
        p.drawText(r.adjusted(28, 0, -20, 0),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._name())
        pm2 = icons.pixmap("chevron_down", t.text_faint, 10, 2.0)
        p.drawPixmap(QPointF(r.right() - 16, r.center().y() - 5), pm2)
        p.end()


# ---------------------------------------------------------------- Toast


class Toast(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._kind = "info"
        self._opacity = 0.0
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._hide)
        self._anim: Optional[QVariantAnimation] = None

    def show_message(self, text: str, kind: str = "info") -> None:
        # 提示语统一在这里翻译：调用点几十处，逐个包 tr() 容易漏
        text = i18n.tr(text)
        self._text = text
        self._kind = kind
        self._dy = 10.0
        fm = QFontMetricsF(font(12))
        w = int(fm.horizontalAdvance(text)) + 62
        self.setFixedSize(max(160, min(w, 520)), 34)
        self._place()
        self.show()
        self.raise_()
        self._timer.start(2400)
        self._fade_to(1.0, 150)
        animate(self, 10.0, 0.0, 210, self._slide,
                easing=QEasingCurve.Type.OutBack)

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.move((parent.width() - self.width()) // 2,
                  parent.height() - self.height() - 26 + int(getattr(self, "_dy", 0)))

    def _hide(self) -> None:
        self._fade_to(0.0, 160, self.hide)

    def _fade_to(self, target: float, dur: int, done=None) -> None:
        _anim_stop(self._anim)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(target)
        self._anim.setDuration(dur)
        self._anim.valueChanged.connect(self._set_op)
        if done:
            self._anim.finished.connect(done)
        self._anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _set_op(self, v):
        self._opacity = float(v)
        self.update()

    def _slide(self, v):
        self._dy = float(v)
        self._place()
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setOpacity(max(0.0, min(1.0, self._opacity)))
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.elevated))
        p.drawRoundedRect(r, 9, 9)
        col = {"info": t.text_dim, "success": t.success, "error": t.danger}.get(self._kind, t.text_dim)
        name = {"info": "check", "success": "check", "error": "close"}.get(self._kind, "check")
        pm = icons.pixmap(name, col, 13, 1.8)
        p.drawPixmap(QPointF(13, r.center().y() - 6.5), pm)
        p.setFont(font(12))
        p.setPen(C(t.text))
        p.drawText(r.adjusted(36, 0, -14, 0),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._text)
        p.end()


# ---------------------------------------------------------------- 分割手柄


class SplitHandle(QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._hover = False
        self.setMouseTracking(True)
        self.setToolTip("拖动调整高度 · 双击恢复 50 / 50")

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        sp = self.splitter()
        if sp is not None and hasattr(sp, "resetRequested"):
            sp.resetRequested.emit()
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.hover))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 2, 0, -2), 3, 3)
            p.setPen(QPen(C(t.border_strong), 1))
        else:
            p.setPen(QPen(C(t.border), 1))
        y = self.height() // 2
        p.drawLine(4, y, self.width() - 4, y)
        p.end()


class PanelSplitter(QSplitter):
    resetRequested = pyqtSignal()

    def createHandle(self):  # noqa: N802
        return SplitHandle(self.orientation(), self)


class SideSplitter(QSplitter):
    """侧栏与内容区之间的分隔：拖动改宽度，静置只画一条 1px 线。"""

    def createHandle(self):  # noqa: N802
        return SideHandle(self.orientation(), self)


class SideHandle(QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._hover = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.SplitHCursor)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.fillRect(self.rect(), C(t.window))
        col = C(t.border_strong if self._hover else t.border)
        w = 1 if not self._hover else 2
        p.fillRect(QRect(self.width() // 2 - (w // 2), 0, w, self.height()), col)
        p.end()


class CardRoot(QWidget):
    """内容根容器：尺寸一变就请主窗重裁一次圆角。

    窗口的布局是异步的 —— 窗口 resize 时 root 还没跟上，那时候按旧尺寸裁，
    右边和下边就会留出一条没裁掉的直角。所以把裁剪挂到 root 自己的 resizeEvent 上。
    """

    def resizeEvent(self, e):
        super().resizeEvent(e)
        win = self.window()
        fn = getattr(win, "_round_corners", None)
        if callable(fn):
            fn()


class ContentSurface(QWidget):
    """内容区背景：与侧栏同色（整块统一底色），只留一层薄薄的层次。"""

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.fillRect(self.rect(), C(t.panel))
        p.end()


# ---------------------------------------------------------------- 欢迎页


class ActionRow(QWidget):
    clicked = pyqtSignal()

    def __init__(self, icon_name: str, title: str, subtitle: str, hint: str = "", parent=None):
        super().__init__(parent)
        self._icon = icon_name
        self._title = title
        self._subtitle = subtitle
        self._hint = hint
        self._hover = 0.0
        self._anim: Optional[QVariantAnimation] = None
        self.setFixedHeight(px(50))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def enterEvent(self, e):
        self._to(1.0)

    def leaveEvent(self, e):
        self._to(0.0)

    def _to(self, target):
        _anim_stop(self._anim)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(target)
        self._anim.setDuration(150)
        self._anim.valueChanged.connect(lambda v: (setattr(self, "_hover", float(v)), self.update()))
        self._anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = C(t.hover)
        bg.setAlpha(int(bg.alpha() * (0.35 + 0.65 * self._hover)))
        p.setPen(QPen(C(t.border), 1))
        p.setBrush(C(t.panel_alt) if self._hover < 0.5 else bg)
        p.drawRoundedRect(r, 10, 10)
        pm = icons.pixmap(self._icon, t.text_dim, px(15), 1.6)
        p.drawPixmap(QPointF(px(16), r.center().y() - px(15) / 2), pm)
        p.setFont(font(12.8, QFont.Weight.Medium))
        p.setPen(C(t.text))
        p.drawText(QRectF(px(44), r.top() + px(7), r.width() - px(120), px(18)),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), i18n.tr(self._title))
        p.setFont(font(10.8))
        p.setPen(C(t.text_faint))
        p.drawText(QRectF(px(44), r.top() + px(25), r.width() - px(120), px(16)),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), i18n.tr(self._subtitle))
        if self._hint:
            fm = QFontMetricsF(mono(10))
            w = fm.horizontalAdvance(self._hint) + px(14)
            hr = QRectF(r.right() - w - px(12), r.center().y() - px(9), w, px(18))
            p.setPen(QPen(C(t.border_strong), 1))
            p.setBrush(C(t.card))
            p.drawRoundedRect(hr, 4, 4)
            p.setFont(mono(10))
            p.setPen(C(t.text_faint))
            p.drawText(hr, int(Qt.AlignmentFlag.AlignCenter), self._hint)
        p.end()


class WelcomeView(QWidget):
    newRequest = pyqtSignal()
    palette = pyqtSignal()
    envDialog = pyqtSignal()
    samples = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(40, 40, 40, 40)
        col.setSpacing(0)
        col.addStretch(2)

        # 空状态就是品牌展示位：进软件先演一遍描边动画
        self.mark = BrandMark(78, token="text", hover_token="accent",
                              autoplay=True, tooltip=APP_NAME)
        holder = HBox(1, self.mark, 1)
        col.addWidget(holder)
        col.addSpacing(20)
        title = Label(APP_NAME, 27, theme().text, weight=QFont.Weight.Bold, spacing=-0.4)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(title)
        col.addSpacing(7)
        sub = Label("接口调试、Mock 服务、接口文档，离线可用", 12.5, theme().text_dim)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(sub)
        col.addSpacing(34)

        rows = VBox(spacing=8)
        r1 = ActionRow("plus", "新建请求", "从空白标签页开始", "⌘N")
        r2 = ActionRow("keyboard", "打开命令面板", "搜索请求或快速执行命令", "⌘K")
        r3 = ActionRow("globe", "配置变量", "用 {{变量}} 在环境间切换", "⌘E")
        r1.clicked.connect(self.newRequest.emit)
        r2.clicked.connect(self.palette.emit)
        r3.clicked.connect(self.envDialog.emit)
        for r in (r1, r2, r3):
            r.setFixedWidth(420)
            rows.layout().addWidget(r, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(rows)
        col.addStretch(3)
        hint = Label("⌘↵ 发送   ·   ⌘S 保存   ·   ⌘B 侧边栏", 10.5, theme().text_faint, mono_font=True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(hint)


# ---------------------------------------------------------------- 主窗口


# ---------------------------------------------------------------- 状态栏徽章


class MockBadge(QWidget):
    """底部状态栏的 Mock 胶囊：一个绿点 + 端口，点一下就回到 Mock 中心。

    状态从 MockHub 直接读，不做本地缓存 —— 面板里启停、多实例开关都靠它反映，
    定时器每秒半才 refresh 一次，代价可以忽略。
    """

    clicked = pyqtSignal()

    # 字体度量只算一次：sizeHint 每次布局都会问，重复构造 QFontMetricsF 很浪费
    _fm = None

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self._hover = 0.0
        self._text = ""
        self._on = False
        self.setFixedHeight(22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("打开 Mock 中心 / 请求日志")
        self.refresh()

    def _compute(self) -> None:
        running = self.hub.running()
        if running:
            ports = " / ".join(str(s.port) for s in running)
            self._text = f"Mock: {ports} {i18n.tr('运行中')}"
        else:
            self._text = i18n.tr("Mock 未启动")
        self._on = bool(running)

    def refresh(self) -> None:
        text, on = self._text, self._on
        self._compute()
        if (text, on) != (self._text, self._on):
            # 文字变了才重排，否则只重画
            self.updateGeometry()
            self.update()

    def sizeHint(self):  # noqa: N802
        fm = self._fm
        if fm is None:
            fm = self._fm = QFontMetricsF(mono(10.5))
        return QSize(int(fm.horizontalAdvance(self._text) + 34), 22)

    def enterEvent(self, e):  # noqa: N802
        self._hover = 1.0
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._hover = 0.0
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 1.5, -0.5, -1.5)
        bg = C(t.hover if self._hover else t.panel_alt)
        bg.setAlpha(int(bg.alpha() * (0.9 if self._hover else 0.72)))
        p.setPen(QPen(C(t.border), 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 9, 9)
        # 小圆点：运行中是语义绿，未启动是灰
        dot = QColor(t.success if self._on else t.text_faint)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot)
        p.drawEllipse(QPointF(11, self.height() / 2), 3.0, 3.0)
        p.setFont(mono(10.5))
        p.setPen(C(t.text_dim if self._on else t.text_faint))
        p.drawText(QRectF(19, 0, self.width() - 22, self.height()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   self._text)
        p.end()


class MainWindow(QWidget):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        # 字号缩放必须在建控件之前定下来：所有 font()/mono() 都读这个系数
        set_ui_scale(store.settings.get("ui_scale", 1.0))
        # 运行期「当前 Store」以主窗口为准：别的地方临时 Store.load() 读一份快照做校验时，
        # 不会把弹窗读取设置用的引用换掉（否则设置项在弹窗里不生效）。
        Store._active = store
        self.client = ApiClient(self)
        self.client.set_store(store)
        self.client.started.connect(lambda: None)
        self.client.finished.connect(self._on_response)
        # WebSocket：全局一条连接，日志按标签各存各的（切回来还在）
        self.ws = WsClient(self)
        self.ws.stateChanged.connect(self._on_ws_state)
        self.ws.frame.connect(self._on_ws_frame)
        self.ws.opened.connect(self._on_ws_opened)
        self.ws.closed.connect(self._on_ws_closed)
        self.ws.failed.connect(self._on_ws_failed)
        self.ws.ponged.connect(self._on_ws_pong)
        # Socket.IO：复用同一套日志/状态槽，按当前标签选择 client
        self.sio = SocketIoClient(self)
        self.sio.stateChanged.connect(self._on_ws_state)
        self.sio.frame.connect(self._on_ws_frame)
        self.sio.opened.connect(self._on_ws_opened)
        self.sio.closed.connect(self._on_ws_closed)
        self.sio.failed.connect(self._on_ws_failed)
        self.sio.ponged.connect(self._on_ws_pong)
        self._ws_tab: Optional[str] = None
        self._ws_replay_hook = None
        # 连接时长每秒走一格：不然「已连接 42.60s」会一直停在连上那一刻
        self._ws_tick = QTimer(self)
        self._ws_tick.setInterval(1000)
        self._ws_tick.timeout.connect(self._ws_tick_update)

        self.tabs_data: List[Dict[str, Any]] = []
        self._inflight_tab: Optional[str] = None
        self._active_tab_id: Optional[str] = None
        self._sidebar_target = int(store.settings.get("sidebar_width", 268))
        self._side_anim: Optional[QVariantAnimation] = None
        self._side_animating = False
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(700)
        self._autosave.timeout.connect(self._persist)
        # 本地 Mock：Hub 管多个实例（多端口同时跑），关窗时统一收掉
        from .mock_server import MockHub

        self.mock = MockHub()
        # AI 响应分析结果缓存：同一页签 + 同一响应再看一次直接显示，不再烧 token。
        # LRU 上限 + 8 分钟过期 + 关窗清空，绝不会一直占着内存。
        from . import ai as _ai
        self._analysis_cache = _ai.AnalysisCache()
        self._shortcuts: List[QShortcut] = []

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(brand_icon())
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setMinimumSize(1020, 660)
        self.resize(1320, 840)

        set_animations(bool(store.settings.get("animations", True))
                       and not os.environ.get("OCELOT_NO_ANIM"))
        CodeView.set_global_size(float(store.settings.get("code_font_size", 11.8)))
        QApplication.instance().setAttribute(
            Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
        from .ctxmenu import install as _install_ctx
        from .tooltip import install as _install_tip

        _install_tip(QApplication.instance())
        _install_ctx(QApplication.instance())
        self._build()
        self._install_shortcuts()
        # 定时回收：默认 15 分钟一次，设置里可关或改间隔。放在主窗口里，
        # 跟窗口同寿命，退出即停表，不留后台唤醒。
        from .memtrim import AutoTrim

        self._auto_trim = AutoTrim(self.store, self)
        self._restore_session()
        QTimer.singleShot(400, self._auto_start_mock)
        i18n.set_language(store.settings.get("language", "zh"), notify=False)
        i18n.bus().languageChanged.connect(self._retranslate)
        if i18n.current() == "en":
            # 走完整一遍重翻译：只 apply_language 不会重算自绘控件的尺寸，
            # 英文比中文长的那几处（Collections / History）会被裁掉半截。
            self._retranslate("en")
        # 启动时如果存档坏了被自动救回来，得让人知道发生了什么、原文件在哪
        note = getattr(store, "load_note", None)
        if note:
            QTimer.singleShot(900, lambda: self.toast.show_message(note, "error"))

    def _retranslate(self, _lang: str) -> None:
        # 自绘控件的文案不经过 QLabel：在 apply_language 遍历时顺手刷新，
        # 避免过去 findChildren 两遍（一遍翻译、一遍 refresh_theme）的重复开销。
        from .widgets import Button, SegmentedTabs

        def visit(w):
            if isinstance(w, SegmentedTabs):
                w.sync_size()
            elif isinstance(w, Button):
                w.updateGeometry()
                w.update()
            fn = getattr(w, "refresh_theme", None)
            if callable(fn):
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass

        i18n.apply_language(self, visit=visit)
        # 动态拼接的文案（设置页里的 AI 状态、历史条数等）必须等通用翻译全部跑完
        # 再按模板重设，否则会被各控件记下的中文整句原文覆盖回去。
        def refresh_dynamic(w):
            fn = getattr(w, "refresh_i18n", None)
            if callable(fn):
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass

        refresh_dynamic(self)
        for widget in self.findChildren(QWidget):
            refresh_dynamic(widget)

    # -------------------------------------------------- 构建
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.root = CardRoot()
        self.root.setObjectName("Root")
        self.root.setStyleSheet("#Root { background: transparent; }")
        outer.addWidget(self.root)
        root_lay = QVBoxLayout(self.root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        self.titlebar = self._build_titlebar()
        root_lay.addWidget(self.titlebar)
        root_lay.addWidget(Divider())

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)

        self.sidebar = Sidebar(self.store)
        self.sidebar.setMinimumWidth(200)
        self.sidebar.setMaximumWidth(420)
        self.sidebar.openRequest.connect(self._open_from_sidebar)
        self.sidebar.previewRequest.connect(self._preview_from_sidebar)
        self.sidebar.requestDeleted.connect(self._on_request_deleted)
        self.sidebar.changed.connect(self._on_store_changed)
        self.sidebar.runFolder.connect(self.run_collection)
        self.sidebar.transferRequested.connect(self.open_transfer)
        self.sidebar.trashRequested.connect(self.open_trash)
        self.sidebar.notify.connect(lambda msg: self.toast.show_message(msg, "success"))

        content = ContentSurface()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        self.tabstrip = TabStrip()
        self.tabstrip.currentChanged.connect(self._on_tab_changed)
        self.tabstrip.closeRequested.connect(self.close_tab)
        self.tabstrip.addRequested.connect(self.new_request)
        self.tabstrip.orderChanged.connect(self._on_tabs_reordered)
        self.tabstrip.contextMenuRequested.connect(self._tab_context_menu)
        self.tabstrip.pinRequested.connect(self._pin_tab)
        cl.addWidget(self.tabstrip)
        cl.addWidget(Divider())

        self.workspace = QWidget()
        wl = QVBoxLayout(self.workspace)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        self.splitter = PanelSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(10)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.resetRequested.connect(self._reset_split)
        self.editor = RequestEditor(self.store)
        # 防止拖竖分隔时把请求区压到只剩半行，出现「地址栏消失、描述行上浮」。
        self.editor.setMinimumHeight(180)
        self.editor.changed.connect(self._on_editor_changed)
        self.editor.scriptsChanged.connect(self._on_scripts_changed)
        self.editor.sendRequested.connect(self.send_current)
        self.editor.wsSendRequested.connect(self._ws_send)
        self.editor.sioSendRequested.connect(self._sio_send)
        self.editor.cancelRequested.connect(self._abort)
        self.editor.saveRequested.connect(self.save_current)
        self.editor.codeRequested.connect(self.show_code)
        self.editor.copyCurlRequested.connect(self._copy_curl)
        self.editor.deleteRequested.connect(self._delete_current)
        self.editor.mockRequested.connect(self.open_mock)
        self.editor.mockizeRequested.connect(self._mockize_current)
        self.editor.duplicateRequested.connect(self._duplicate_request)
        self.editor.notify.connect(lambda msg: self.toast.show_message(msg, "info"))
        self.editor.aiSettingsRequested.connect(lambda: self.show_settings("ai"))
        self.response = ResponsePanel()
        self.response.ws_view.replay.connect(self._ws_replay)
        self.response.sio_view.eventReplay.connect(self._sio_replay)
        self.response.wsActionRequested.connect(self._on_ws_action)
        self.response.setMinimumHeight(180)
        self.response.requestSaveBody.connect(lambda body, note: self.toast.show_message(
            {"copied": "响应已复制", "redacted": "已脱敏复制（token / Cookie 已打码）"}.get(note, "响应已保存"),
            "success"))
        self.response.saveVariable.connect(self._save_env_var)
        self.response.pickVariableRequested.connect(self._pick_var_from_response)
        self.response.resendRequested.connect(self.send_current)
        self.response.docRequested.connect(self.open_doc)
        self.response.aiExplainRequested.connect(self._ai_explain_response)
        self.response.stale_bar.never.connect(self._on_stale_never)
        self.response.set_stale_notice(bool(self.store.settings.get("stale_notice", True)))
        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.response)
        self.splitter.setSizes([380, 420])
        wl.addWidget(self.splitter, 1)

        self.welcome = WelcomeView()
        self.welcome.newRequest.connect(self.new_request)
        self.welcome.palette.connect(self.show_palette)
        self.welcome.envDialog.connect(self.show_envs)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.workspace)
        cl.addWidget(self.stack, 1)
        # Mock 状态条只属于右半侧：放内容区底部，侧栏（新建请求那一列）
        # 的高度和位置永远不变。服务停了整条收起，恢复成原来的样子。
        cl.addWidget(self._build_statusbar())

        self.split = SideSplitter(Qt.Orientation.Horizontal)
        self.split.setObjectName("SideSplit")
        self.split.setHandleWidth(7)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self.sidebar)
        self.split.addWidget(content)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([self._sidebar_target, 1200])
        self.split.splitterMoved.connect(self._on_sidebar_dragged)
        body_lay.addWidget(self.split, 1)
        root_lay.addWidget(body, 1)

        self.toast = Toast(self.root)
        # 挂在主窗口本身（不是内容容器）：命令面板要盖在背景模糊遮罩之上，
        # 同层兄弟控件才能靠 raise_() 保证顺序。
        self.palette = CommandPalette(self.store, self)
        self.palette.execute.connect(self._on_palette_action)
        self._update_stack()
        self.response.show_empty()

    def _build_statusbar(self) -> QWidget:
        """Mock 状态条：只在服务运行时出现，且只在右半侧（内容区底部）。

        放在 content 的布局里而不是 root —— 侧栏那半边完全不受影响。
        没有分隔线，视觉上就是「胶囊浮在右下角」。服务停了整条收起，
        内容区立刻恢复原来的高度，不留空条。
        """
        bar = QWidget()
        bar.setFixedHeight(28)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)
        lay.addStretch(1)
        self.mock_badge = MockBadge(self.mock)
        self.mock_badge.clicked.connect(self.open_mock)
        lay.addWidget(self.mock_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.status_wrap = bar
        self._status_on = False
        # 整条初始收起；没在跑时定时器也停着，不白转
        bar.setVisible(False)
        self._status_tick = QTimer(self)
        self._status_tick.setInterval(1800)
        self._status_tick.timeout.connect(self._refresh_mock_badge)
        return bar

    def _refresh_mock_badge(self) -> None:
        badge = getattr(self, "mock_badge", None)
        if badge is None:
            return
        on = bool(self.mock.is_running)
        if on != self._status_on:
            self._status_on = on
            # 整条一起显隐：关掉 Mock 后右半侧立刻恢复原样，不留空条。
            self.status_wrap.setVisible(on)
            if on:
                badge.refresh()
                self._status_tick.start()
            else:
                self._status_tick.stop()
        elif on:
            badge.refresh()

    def _build_titlebar(self) -> QWidget:
        bar = TitleBar(self)
        bar.setFixedHeight(46)
        bar.setMouseTracking(True)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 12, 0)
        lay.setSpacing(10)
        self.lights = TrafficLights(self, bar)
        lay.addWidget(self.lights, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(10)
        # 品牌标识：鼠标悬浮时轮廓会沿着起点到终点重新点亮一遍
        self.brand_mark = BrandMark(21, token="text_dim", hover_token="text",
                                    tooltip=APP_NAME)
        lay.addWidget(self.brand_mark, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(7)
        word = Label(APP_NAME, 12.5, theme().text, weight=QFont.Weight.DemiBold, spacing=0.2)
        lay.addWidget(word)
        # lay.addWidget(Label("API Client", 10.5, theme().text_faint, mono_font=True, spacing=0.4))
        lay.addSpacing(6)
        self.sidebar_btn = icon_button("panel_left", "隐藏侧栏  ⌘B", 26, 15)
        self.sidebar_btn.clicked.connect(self.toggle_sidebar)
        lay.addWidget(self.sidebar_btn)
        lay.addStretch(1)
        self.env_pill = EnvPill(self.store)
        self.env_pill.manageRequested.connect(self.show_envs)
        self.env_pill.clicked.connect(lambda: self.toast.show_message("已切换环境", "success"))
        lay.addWidget(self.env_pill)
        palette_btn = icon_button("keyboard", "命令面板  ⌘K", 26, 14)
        palette_btn.clicked.connect(self.show_palette)
        settings_btn = icon_button("gear", "设置与更多  ⌘,", 26, 15)
        self._settings_btn = settings_btn
        settings_btn.clicked.connect(lambda: self._show_settings_menu(settings_btn))
        lay.addWidget(palette_btn)
        lay.addWidget(settings_btn)
        return bar

    def _settings_menu(self) -> Tuple[Menu, Dict[str, Any]]:
        """构建标题栏的「设置与更多」菜单。拆出来是为了测试能直接检查条目。"""
        t = theme()
        menu = Menu(self)
        acts: Dict[str, Any] = {}
        acts["settings"] = menu.addAction(icons.icon("gear", t.text, 14), "设置…")
        acts["env"] = menu.addAction(icons.icon("globe", t.text, 14), "环境变量…")
        acts["resources"] = menu.addAction(icons.icon("grid", t.text, 14), "资源管理器…")
        acts["cloud"] = menu.addAction(icons.icon("cloud", t.text, 14), "云同步…")
        menu.addSeparator()
        acts["mock"] = menu.addAction(icons.icon("grid", t.text, 14), "Mock 服务…")
        acts["curl"] = menu.addAction(icons.icon("code", t.text, 14), "导入 cURL…")
        acts["import"] = menu.addAction(icons.icon("download", t.text, 14), "导入集合…")
        acts["export"] = menu.addAction(icons.icon("file", t.text, 14), "导出集合…")
        menu.addSeparator()
        acts["quit"] = menu.addAction("退出 Ocelot")
        return menu, acts

    def _show_settings_menu(self, anchor: QWidget) -> None:
        menu, acts = self._settings_menu()
        a_settings = acts["settings"]
        a_env = acts["env"]
        a_resources = acts["resources"]
        a_cloud = acts["cloud"]
        a_mock = acts["mock"]
        a_curl = acts["curl"]
        a_import = acts["import"]
        a_export = acts["export"]
        a_quit = acts["quit"]
        chosen = menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        if chosen is a_settings:
            self.show_settings()
        elif chosen is a_env:
            self.show_envs()
        elif chosen is a_resources:
            self.open_resources()
        elif chosen is a_cloud:
            self.show_settings(page="cloud")
        elif chosen is a_mock:
            self.open_mock()
        elif chosen is a_curl:
            self.import_curl()
        elif chosen is a_import:
            self.import_collection()
        elif chosen is a_export:
            self.export_collection()
        elif chosen is a_quit:
            self.close()

    # -------------------------------------------------- 窗口绘制 / 交互
    CARD_RADIUS = 12
    # 边缘拖拽热区。卡片铺满整窗后没有透明留白了，热区按视觉边距给。
    EDGE_HIT = 5

    def card_margin(self) -> int:
        """卡片四周的留白，固定为 0。

        老版本在窗口外留 8px 画投影，靠窗口透明度把投影合成到桌面上。
        但 macOS 从最大化 / 全屏退回来之后会把这个窗口重新标记成不透明，
        那 8px 立刻变成一圈白底方框 —— 圆角还在、外面多了个方块。
        现在卡片铺满整个窗口，圆角交给窗口遮罩裁，投不投影都不影响观感。
        """
        return 0

    def card_rect(self) -> QRect:
        """卡片在窗口自身坐标里的矩形（卡片铺满，所以就是 rect）。"""
        return self.rect()

    def card_radius(self) -> int:
        return 0 if (self.isMaximized() or self.isFullScreen()) else self.CARD_RADIUS

    def _round_corners(self) -> None:
        """把顶层窗口裁成圆角。

        侧栏、内容区都是矩形，会盖住窗口自己画的圆角，四个角看着就是直角。
        这里给窗口本身加圆角遮罩：子控件收在弧线内，系统那层背景也一起被裁掉，
        窗口即使被系统改成不透明，也不会露出一块方形底板。
        最大化 / 全屏时清掉，铺满整屏。
        """
        if not getattr(self, "root", None):
            return
        if self.isMaximized() or self.isFullScreen():
            # 不讲条件地清一次：最大化时若还挂着圆角遮罩，屏幕四角会被啃掉一块
            self._mask_size = None
            if not self.mask().isEmpty():
                self.clearMask()
            if not self.root.mask().isEmpty():
                self.root.clearMask()
            return
        w, h = self.width(), self.height()
        if w < 32 or h < 32:
            return
        if getattr(self, "_mask_size", None) == (w, h):
            return
        self._mask_size = (w, h)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), self.CARD_RADIUS, self.CARD_RADIUS)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self.root.clearMask()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 先整窗刷成透明，再画卡片：来回切全屏时边缘不会留下上一次的像素。
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        radius = self.card_radius()
        if radius == 0:
            # 最大化 / 全屏：铺满、不画圆角，也不留透明缝。
            p.setPen(Qt.PenStyle.NoPen)
            p.fillRect(self.rect(), C(t.window))
            p.end()
            return
        # 圆心内缩半像素，1px 描边才不会被裁掉一半
        card = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(C(t.border), 1))
        p.setBrush(C(t.window))
        p.drawRoundedRect(card, radius - 0.5, radius - 0.5)
        p.end()

    def _edge(self, pos: QPoint) -> Qt.Edge:
        m = self.EDGE_HIT
        edges = Qt.Edge(0)
        if pos.x() <= m:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= self.width() - m:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= m:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= self.height() - m:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mouseMoveEvent(self, e):
        if self.isMaximized():
            return
        edges = self._edge(e.position().toPoint())
        if edges & Qt.Edge.LeftEdge and edges & Qt.Edge.TopEdge:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges & Qt.Edge.RightEdge and edges & Qt.Edge.BottomEdge:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges & Qt.Edge.RightEdge and edges & Qt.Edge.TopEdge:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges & Qt.Edge.LeftEdge and edges & Qt.Edge.BottomEdge:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            edges = self._edge(e.position().toPoint())
            if edges:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edges)
                    return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.position().y() < 46:
            self.showMaximized() if not self.isMaximized() else self.showNormal()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            # 尺寸缓存清掉，强制按新状态重裁圆角；否则还原后还戴着全屏时清掉的遮罩
            self._mask_size = None
            self._round_corners()
            self.update()
            # 遮罩（命令面板 / 弹窗的模糊底）也要跟着重新对齐，不然会停在旧尺寸
            try:
                from . import backdrop as _backdrop
                _backdrop.resync_all()
            except Exception:       # noqa: BLE001
                pass
        elif e.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            # 从别的窗口回来后自检一次：万一标签栏和编辑器错位，立刻拉回正轨
            QTimer.singleShot(0, self._ensure_tab_sync)

    # -------------------------------------------------- 标签管理
    def current_tab(self) -> Optional[Dict[str, Any]]:
        tid = self.tabstrip.current()
        return self._tab(tid) if tid else None

    def _tab(self, tab_id: str) -> Optional[Dict[str, Any]]:
        for t in self.tabs_data:
            if t["id"] == tab_id:
                return t
        return None

    def _duplicate_request(self) -> None:
        """把当前请求复制成新标签（含参数、请求头、Cookies、请求体）。"""
        tab = self.current_tab()
        if tab is None:
            return
        req = _copy.deepcopy(self.editor.request or tab["request"])
        req["id"] = uid()
        req["name"] = (req.get("name") or "Request") + " 副本"
        self._open_request_obj(req, node_id=None)
        self.toast.show_message("已复制为新标签", "success")

    def open_mock(self) -> None:
        """Mock 中心：独立窗口，开着也能继续用主窗口。"""
        from .mock_panel import MockDialog

        dlg = getattr(self, "_mock_dialog", None)
        if dlg is None:
            dlg = MockDialog(self.store, self.mock, self)
            dlg.chosen.connect(self._use_mock)
            dlg.trialRequested.connect(self._mock_trial)
            dlg.stateChanged.connect(self._refresh_mock_badge)
            self._mock_dialog = dlg
        self._refresh_mock_badge()
        if dlg.isVisible():
            # 已经开着：抬到前面就够，别重建（重建会把正在编辑的路由丢掉）
            dlg.raise_()
            dlg.activateWindow()
            return
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _mock_trial(self, method: str, url: str) -> None:
        """点了某条本地路由的「试用」：建一条指向它的请求，直接发。"""
        req = new_request(f"Mock · {url.rstrip('/').split('/')[-1] or 'root'}", method, url)
        self._open_request_obj(req, node_id=None)
        self.toast.show_message("已连上本地 Mock 路由", "success")
        QTimer.singleShot(80, self.send_current)

    def _mockize_current(self) -> None:
        """一键 Mock：把当前请求的 Method / Path 和真实响应体，直接变成本地路由。

        痛点很具体 —— 手动新建路由、填路径、复制响应体太麻烦。这里点了就落一条，
        服务没开顺手拉起来，然后 toast 告诉用户「已经能请求了」。
        """
        from .mock_import import route_from_request
        from .mock_server import mock_config

        tab = self.current_tab()
        if tab is None:
            self.toast.show_message(i18n.tr("先打开或新建一个请求"), "info")
            return
        req = tab.get("request") or {}
        url = str(req.get("url") or "").strip()
        if not url:
            self.toast.show_message(i18n.tr("这个请求还没有地址，先填一个再 Mock"), "info")
            return
        method = str(req.get("method") or "GET").upper()
        if method in REALTIME_METHODS:
            self.toast.show_message(i18n.tr("WebSocket / Socket.IO 不能做 HTTP Mock"), "info")
            return
        resp = tab.get("response")
        body, ctype, status = "", "application/json", 200
        if resp is not None and getattr(resp, "body", b""):
            try:
                body = resp.body.decode(resp.charset(), "replace")[:200_000]
            except Exception:      # noqa: BLE001
                body = ""
            ctype = (getattr(resp, "content_type", "") or "application/json").split(";")[0]
            status = int(getattr(resp, "status", 200) or 200)
            if not 200 <= status <= 599:
                status = 200
        if not body:
            raw = ""
            b = req.get("body") or {}
            if isinstance(b, dict):
                raw = str(b.get("raw") or "")
            body = raw or json.dumps({"code": 0, "message": "ok", "data": {}},
                                     ensure_ascii=False, indent=2)
            ctype = "application/json"
        item = route_from_request(method, url, body, name=str(req.get("name") or ""),
                                  group=i18n.tr("一键 Mock"), status=status,
                                  content_type=ctype)
        cfg = mock_config(self.store.data)
        inst = (cfg.get("instances") or [{}])[0]
        routes = inst.setdefault("routes", [])
        replaced = False
        for existing in routes:
            if (str(existing.get("method") or "").upper() == item["method"]
                    and str(existing.get("path") or "") == item["path"]):
                existing.update({k: item[k] for k in ("body", "status", "content_type", "name")})
                replaced = True
                break
        if not replaced:
            item["id"] = "m" + uid()[:8]
            routes.append(item)
        self.store.save()
        srv = self.mock.get(inst.get("id") or "main", inst.get("name") or "")
        if not srv.running:
            ok, msg = srv.start(routes, inst.get("port") or 8787,
                                bool(cfg.get("fallback_echo")), bool(inst.get("lan")))
            if ok:
                inst["port"] = srv.port
                self.store.save()
            else:
                self.toast.show_message(msg, "danger")
        self._refresh_mock_badge()
        verb = i18n.tr("已更新") if replaced else i18n.tr("已添加")
        self.toast.show_message(
            i18n.trf("{verb} Mock 路由 {method} {path}", verb=verb, method=item["method"],
                     path=item["path"]), "success")

    def _sync_mock_state(self) -> None:
        """服务在对话框里启动 / 停止后，底部徽章和提示保持同步。"""
        self._refresh_mock_badge()
        running = self.mock.running()
        if running:
            self.toast.show_message(
                i18n.trf("本地 Mock 服务运行在 {url}", url=self.mock.base), "success")

    def _use_mock(self, item: Dict[str, Any]) -> None:
        path = (item.get("u") or "").rstrip("/").split("/")[-1] or "mock"
        req = new_request(f"Mock · {path}", item.get("m", "GET"), item.get("u", ""))
        body = item.get("b")
        if body:
            req["body"] = {"mode": "json", "raw": body, "form": [], "file": ""}
            req["headers"] = [kv("Content-Type", "application/json")]
        if "reqres.in" in (item.get("u") or ""):
            # reqres 现在要求带一个免费 key，不带会 401 —— 直接把头部填好
            req["headers"] = [kv("x-api-key", "reqres-free-v1")] + req["headers"]
        self._open_request_obj(req, node_id=None)
        self.toast.show_message("已填入 Mock 请求，按 ⌘↵ 发送", "success")

    def new_request(self) -> None:
        req = new_request("Untitled Request")
        req["id"] = req["id"]
        self._open_request_obj(req, node_id=None)
        self.editor.focus_url()

    def new_websocket(self) -> None:
        """新建 WebSocket 请求：默认停在「消息」页，直接能连。"""
        from .ws_panel import default_ws

        req = new_request("WebSocket Request", "WS", "")
        req["ws"] = default_ws()
        self._open_request_obj(req, node_id=None)
        self.editor.focus_url()

    def new_socketio(self) -> None:
        """新建 Socket.IO 请求：默认停在「事件」页，命名空间 / 认证就地填。"""
        from .sio_panel import default_sio

        req = new_request("Socket.IO Request", SIO_METHOD, "")
        req["sio"] = default_sio()
        self._open_request_obj(req, node_id=None)
        self.editor.focus_url()

    # -------------------------------------------------- AI 自动起名
    @staticmethod
    def _url_default_name(url: str) -> str:
        path = (url or "").split("?")[0].split("://")[-1]
        parts = [p for p in path.split("/") if p]
        return (parts[-1] if parts else "")[:40]

    def _ai_auto_name(self, tab: Dict[str, Any]) -> None:
        """请求名还是「未命名 / URL 末段」时，让 AI 起一个更像人话的名字。

        只在名字没有被用户改过时动手（改过就绝不覆盖）；同一个 URL 只问一次。
        """
        from . import ai as ai_mod

        if tab.get("ai_named") or not self.store.settings.get("ai_auto_name", True):
            return
        req = tab.get("request") or {}
        url = str(req.get("url") or "").strip()
        if not url:
            return
        name = str(req.get("name") or "").strip()
        if name and name not in ("Untitled Request", "未命名请求", self._url_default_name(url)):
            return
        cfg = ai_mod.config(self.store)
        ok, _why = ai_mod.ready(cfg)
        if not ok:
            return
        cache = getattr(self, "_ai_name_cache", None)
        if cache is None:
            cache = self._ai_name_cache = {}
        if url in cache:
            self._apply_ai_name(tab, cache[url])
            return
        if getattr(self, "_ai_name_busy", False):
            return
        self._ai_name_busy = True
        tab_id = tab["id"]
        body = str((req.get("body") or {}).get("raw") or "")
        self._ai_name_chat = ai_mod.start(
            ai_mod.messages_for_name(str(req.get("method") or "GET"), url, body),
            cfg=cfg, max_tokens=40, temperature=0.3,
            on_done=lambda text: self._on_ai_name(tab_id, url, text),
            on_error=lambda _e: setattr(self, "_ai_name_busy", False))

    def _on_ai_name(self, tab_id: str, url: str, text: str) -> None:
        from . import ai as ai_mod

        self._ai_name_busy = False
        name = ai_mod.clean_line(text, 14)
        if not name:
            return
        cache = getattr(self, "_ai_name_cache", None)
        if cache is None:
            cache = self._ai_name_cache = {}
        cache[url] = name
        tab = self._tab(tab_id)
        if tab is not None:
            self._apply_ai_name(tab, name)

    def _apply_ai_name(self, tab: Dict[str, Any], name: str) -> None:
        req = tab.get("request") or {}
        req["name"] = name
        tab["title"] = name
        tab["ai_named"] = True
        self.tabstrip.update_tab(tab["id"], title=name,
                                 method=req.get("method", "GET"))
        if tab["id"] == self.tabstrip.current():
            self.editor.request["name"] = name
        # 标签是集合节点的快照：名字改了必须同步回 store，否则侧栏还显示旧名字
        node_id = tab.get("node_id")
        if node_id:
            node = self.store.find(node_id)
            if node is not None:
                node["name"] = name
            self.sidebar.refresh()
        url = str(req.get("url") or "")
        old_defaults = ("Untitled Request", "未命名请求", self._url_default_name(url))
        for entry in self.store.history:
            if entry.get("url") == url and entry.get("name") in old_defaults:
                entry["name"] = name
                if isinstance(entry.get("request"), dict):
                    entry["request"]["name"] = name
        self.sidebar.refresh_history()
        self._autosave.start()

    def _preview_from_sidebar(self, request: Dict[str, Any]) -> None:
        """单击集合项：VSCode 式预览——复用同一个预览标签，标题斜体。"""
        node_id = request.get("id")
        # 已固定打开则直接切过去
        for t in self.tabs_data:
            if node_id and t.get("node_id") == node_id and not t.get("preview"):
                self.tabstrip.set_current(t["id"])
                self._on_tab_changed(t["id"])
                return
        # 已有预览标签：就地换内容，不再新建
        for t in self.tabs_data:
            if t.get("preview"):
                t["request"] = _copy.deepcopy(request)
                t["node_id"] = node_id
                t["title"] = request.get("name") or "Untitled Request"
                t["method"] = request.get("method", "GET")
                t["response"] = None
                self.tabstrip.update_tab(t["id"], title=t["title"], method=t["method"])
                self.tabstrip.set_current(t["id"])
                self._on_tab_changed(t["id"])
                self._sync_open_ids()
                return
        self._open_request_obj(request, node_id=node_id, preview=True)

    def _open_from_sidebar(self, request: Dict[str, Any]) -> None:
        """双击集合项：固定打开（把同 id 的预览标签转正，或新建固定标签）。"""
        node_id = request.get("id")
        if node_id:
            for t in self.tabs_data:
                if t.get("node_id") == node_id:
                    if t.get("preview"):
                        t["preview"] = False
                    # 预览标签转正：标题的斜体要一起取消，否则双击了还是斜的
                    self.tabstrip.update_tab(t["id"], title=t.get("title"),
                                             dirty=t.get("dirty"), preview=False)
                    self.tabstrip.set_current(t["id"])
                    self._on_tab_changed(t["id"])
                    return
        self._open_request_obj(request, node_id=node_id)

    def _open_request_obj(self, request: Dict[str, Any], node_id: Optional[str],
                          preview: bool = False, activate: bool = True) -> None:
        tab_id = f"tab_{int(time.time() * 1000)}_{len(self.tabs_data)}"
        # 每个标签持有独立快照：绝不与集合树/store 节点共享同一个 dict，
        # 否则一边编辑另一边跟着变（用户反馈的「两个页面内容一样」）。
        tab = {
            "id": tab_id, "request": _copy.deepcopy(request), "node_id": node_id,
            "title": request.get("name") or "Untitled Request",
            "method": request.get("method", "GET"),
            "dirty": False, "response": None, "preview": preview,
        }
        self.tabs_data.append(tab)
        self.tabstrip.add_tab({"id": tab_id, "title": tab["title"], "method": tab["method"],
                               "preview": preview}, activate=activate,
                              animate=activate)   # 批量恢复会话时不要逐个飞胶囊
        self._sync_open_ids()
        # 恢复会话时先只建标签，最后统一加载一次 —— 否则开 8 个标签要跑 8 遍编辑器装载
        if activate:
            self._on_tab_changed(tab_id)
            self._update_stack()

    def close_tab(self, tab_id: str) -> None:
        tab = self._tab(tab_id)
        if tab is None:
            return
        if self._inflight_tab == tab_id:
            self._abort()
        if self._ws_tab == tab_id:
            # 关掉正在连的实时标签：连接不能留成孤儿
            client = self._realtime_client()
            if client.busy:
                client.disconnect_ws()
            self._ws_tab = None
        self.tabs_data = [t for t in self.tabs_data if t["id"] != tab_id]
        if self._active_tab_id == tab_id:
            self._active_tab_id = None
        self.tabstrip.remove_tab(tab_id)
        self._sync_open_ids()
        current = self.tabstrip.current()
        if current:
            self._on_tab_changed(current)
        else:
            self._update_stack()
            self.response.show_empty()
        self._persist()

    def _on_tabs_reordered(self, ids: List[str]) -> None:
        order = {tid: i for i, tid in enumerate(ids)}
        self.tabs_data.sort(key=lambda t: order.get(t["id"], 99))
        # 换序合并进 autosave（700ms 一次）：拖拽期间逐帧 _persist（同步写
        # state.json + 同步所有标签）会把拖动拖成幻灯片。
        self._autosave.start()

    def _tab_context_menu(self, tab_id: str, global_pos) -> None:
        """标签栏右键：关闭 / 关闭其他 / 关闭全部 / 复制标签 / 复制为 cURL。"""
        t = theme()
        menu = Menu(self)
        if tab_id:
            a_close = menu.addAction(icons.icon("close", t.text, 13), i18n.tr("关闭"))
            a_others = menu.addAction(icons.icon("layers", t.text, 13), i18n.tr("关闭其他"))
            a_rename = menu.addAction(icons.icon("pencil", t.text, 13), i18n.tr("重命名…"))
            a_dup = menu.addAction(icons.icon("copy", t.text, 13), i18n.tr("复制标签"))
            a_curl = menu.addAction(icons.icon("code", t.text, 13), i18n.tr("复制为 cURL"))
            a_doc = menu.addAction(icons.icon("file", t.text, 13), i18n.tr("查看接口文档…"))
            menu.addSeparator()
        else:
            a_close = a_others = a_rename = a_dup = a_curl = a_doc = None
        a_all = menu.addAction(icons.icon("trash", t.danger, 13), i18n.tr("关闭全部"))
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is a_close and tab_id:
            self.close_tab(tab_id)
        elif chosen is a_others and tab_id:
            for other in [x["id"] for x in self.tabs_data if x["id"] != tab_id]:
                self.close_tab(other)
        elif chosen is a_rename and tab_id:
            self._rename_tab(tab_id)
        elif chosen is a_dup and tab_id:
            self._duplicate_tab(tab_id)
        elif chosen is a_curl and tab_id:
            self._copy_tab_as_curl(tab_id)
        elif chosen is a_doc and tab_id:
            self.open_doc(tab_id)
        elif chosen is a_all:
            for other in [x["id"] for x in self.tabs_data]:
                self.close_tab(other)

    def _rename_tab(self, tab_id: str) -> None:
        """重命名当前标签：同时改集合节点、标签标题与请求内容，并同步落盘 / 云端。

        改名只改一处最容易被忽略 —— 集合树里还是旧名字、重开又是旧名字。
        这里统一走 store + tab 双向同步，再把当前编辑器里的标题一并刷新。
        """
        from .dialogs import PromptDialog

        tab = self._tab(tab_id)
        if tab is None:
            return
        dlg = PromptDialog("重命名", "名称", tab.get("title") or "Untitled Request", self)
        if not dlg.exec():
            return
        name = dlg.value().strip()
        if not name:
            return
        tab["title"] = name
        tab["request"]["name"] = name
        node_id = tab.get("node_id")
        if node_id:
            self.sidebar.rename_node(node_id, name)     # 落盘 + 刷新集合树 + 发 changed
        self.tabstrip.update_tab(tab_id, title=name, dirty=tab.get("dirty", False))
        self.store.save()
        if tab_id == self.tabstrip.current():
            self.editor.request["name"] = name
        self._cloud_autosync()
        self.toast.show_message("已重命名", "success")

    def _pin_tab(self, tab_id: str) -> None:
        """双击标签栏里的预览标签 → 固定下来（标题不再斜体）。"""
        tab = self._tab(tab_id)
        if tab is None or not tab.get("preview"):
            return
        tab["preview"] = False
        self.tabstrip.update_tab(tab_id, preview=False)
        self._sync_open_ids()
        self._autosave.start()

    def _duplicate_tab(self, tab_id: str) -> None:
        tab = self._tab(tab_id)
        if tab is None:
            return
        self._open_request_obj(_copy.deepcopy(tab["request"]),
                               tab.get("node_id"), preview=False)
        self.toast.show_message("已复制标签", "success")

    def _copy_tab_as_curl(self, tab_id: str) -> None:
        from .codegen import to_curl

        tab = self._tab(tab_id)
        if tab is None:
            return
        text = to_curl(tab["request"], self.store.env_vars(), self.store.settings)
        QGuiApplication.clipboard().setText(text)
        self.toast.show_message("cURL 命令已复制到剪贴板", "success")

    def _refresh_timeline(self, request: Optional[Dict[str, Any]]) -> None:
        """把同一地址的历史曲线喂给响应面板的「时间线」页。"""
        url = ((request or {}).get("url") or "").strip()
        if not url:
            self.response.set_history([])
            return
        entries = [e for e in self.store.history if (e.get("url") or "").strip() == url]
        entries.reverse()          # history 新的在前，时间线要从旧到新
        self.response.set_history(entries[-60:])

    def open_doc(self, tab_id: Optional[str] = None) -> None:
        """打开接口文档窗口：渲染、大纲、代码示例、复制与保存都在里面。"""
        tab = self._tab(tab_id) if tab_id else self.current_tab()
        if tab is None:
            self.toast.show_message("先打开一条请求", "info")
            return
        current = tab_id is None or tab_id == self.tabstrip.current()
        resp = (self.response.response if current else tab.get("response"))
        if resp is None:
            self.toast.show_message("这条请求还没有响应，文档里只会有请求部分", "info")
        req = (self.editor.request if current else tab["request"]) or tab["request"]
        from .doc_window import DocDialog

        dlg = DocDialog(self.store, req, resp, self)
        dlg.exec()

    def _on_tab_changed(self, tab_id: str) -> None:
        tab = self._tab(tab_id)
        if tab is None:
            # 标签栏与数据不同步（新建 / 恢复会话 / 删除后偶发）：先尝试把数据补回来，
            # 补不回来就把这个幽灵标签摘掉。以前这里直接 return，界面就彻底僵住：
            # 点任何标签都没反应、内容永远停在上一份。
            self._recover_tab(tab_id)
            return
        # 已经就是这个标签、编辑器也挂着同一份请求：说明状态本来就同步，
        # 直接返回即可。否则每点一下当前标签都要重新格式化整段响应（大 JSON 会明显卡一下）。
        if tab_id == self._active_tab_id and self.editor.request is tab.get("request"):
            self.tabstrip.set_current(tab_id)
            self._update_stack()
            return
        # 离开旧标签前把响应页状态（格式 / 编码 / 子页）存回它自己，
        # 否则所有标签共用一套 ResponsePanel，切回来会显示别人的结果。
        old_id = self._active_tab_id
        if old_id and old_id != tab_id:
            old = self._tab(old_id)
            if old is not None:
                # editor.request 就是旧标签的 dict，编辑时已实时写回；
                # 这里绝不能再调用 _sync_request()，否则 current_tab() 已是新标签，
                # 会把旧内容写进新标签并把预览标签误标成已编辑。
                old["view"] = self.response.view_state()
        self._active_tab_id = tab_id

        self.tabstrip.set_current(tab_id)
        # 点标签时让左侧列表跳到对应条目（用户不用再自己翻树找位置）
        self.sidebar.reveal(tab.get("node_id"))
        try:
            self.editor.load(tab["request"])
            if (tab["request"].get("method") or "").upper() in REALTIME_METHODS:
                # 实时标签：连接可能还活着，把日志和状态原样铺回去
                self._ws_show(tab)
            elif tab.get("response") is not None:
                self.response.set_response(tab["response"])
                self._refresh_timeline(tab["request"])
                self.response.restore_state(tab.get("view"))
                self.response.stale_bar.setVisible(
                    bool(tab.get("stale")) and bool(self.store.settings.get("stale_notice", True)))
            else:
                self.response.show_empty()
                self.response.restore_state(tab.get("view"))
            self.response.set_console(tab.get("console"))
        except Exception:          # noqa: BLE001  单条脏数据不应把整个界面卡死
            import traceback
            traceback.print_exc()
        finally:
            self.editor.set_busy(self._inflight_tab == tab_id)
            self._update_stack()
            self._autosave.start()      # 切标签不再同步写磁盘

    def _recover_tab(self, tab_id: str) -> None:
        """把标签栏与 tabs_data 的错位修好，修不好就摘掉幽灵标签。"""
        meta = self.tabstrip.tab(tab_id) or {}
        node = self.store.find(meta.get("node_id") or tab_id)
        if node is not None and node.get("type") == "request":
            tab = {
                "id": tab_id, "request": _copy.deepcopy(node), "node_id": node.get("id"),
                "title": node.get("name") or "Untitled Request",
                "method": node.get("method", "GET"),
                "dirty": False, "response": None, "preview": meta.get("preview", False),
            }
            self.tabs_data.append(tab)
            self.tabstrip.update_tab(tab_id, title=tab["title"], method=tab["method"])
            self._on_tab_changed(tab_id)
            return
        self.tabs_data = [t for t in self.tabs_data if t["id"] != tab_id]
        self.tabstrip.remove_tab(tab_id)
        fallback = self.tabs_data[-1]["id"] if self.tabs_data else None
        if fallback:
            self.tabstrip.set_current(fallback)
            self._on_tab_changed(fallback)
        else:
            self._active_tab_id = None
            self._update_stack()
            self.response.show_empty()

    def _ensure_tab_sync(self) -> None:
        """兜底自检：编辑器里挂的请求必须就是当前标签的请求。"""
        tid = self.tabstrip.current()
        tab = self._tab(tid) if tid else None
        if tab is None:
            return
        if self.editor.request is not tab.get("request"):
            self._on_tab_changed(tid)

    def _on_editor_changed(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        req = tab["request"]
        tab["title"] = req.get("name") or "Untitled Request"
        tab["method"] = req.get("method", "GET")
        tab["dirty"] = True
        # 请求方式改了，集合树里的徽标也要跟着变（不然一边 POST 一边显示 GET）
        if tab.get("node_id"):
            self.sidebar.set_node_method(tab["node_id"], tab["method"])
        # 请求改了不销毁上一次的响应：很多人只是把 POST 改成 GET 想对照结果，
        # 一改结果就全没了。保留内容 + 顶部一条「上一次的结果」提示，明确不误导。
        # WebSocket 标签不参与这套：连接还在，日志不该被一条 stale 提示盖掉。
        realtime = (req.get("method") or "").upper() in REALTIME_METHODS
        if not realtime and self.response.is_ws_view():
            # 从实时协议改回 HTTP：日志页不再成立，回到空态等新响应
            self.response.show_empty()
        if not realtime and (
                tab.get("response") is not None or self.response.response is not None):
            tab["stale"] = True
            self.response.mark_stale()
        # 用户一旦编辑预览标签就把它固定下来（VSCode 行为）
        if tab.get("preview"):
            tab["preview"] = False
        self.tabstrip.update_tab(tab["id"], title=tab["title"], method=tab["method"],
                                 dirty=True, preview=tab.get("preview", False))
        self._autosave.start()

    def _on_scripts_changed(self) -> None:
        """只改了脚本：照常标记脏并落盘，但保留上一次响应，避免脚本一改动
        响应区就变成「请求已修改」、内容全没了。"""
        tab = self.current_tab()
        if tab is None:
            return
        tab["dirty"] = True
        if tab.get("preview"):
            tab["preview"] = False
        self.tabstrip.update_tab(tab["id"], title=tab["title"], method=tab["method"],
                                 dirty=True, preview=tab.get("preview", False))
        self._autosave.start()

    def _on_store_changed(self) -> None:
        # 集合树变动时只同步「标题 / 方法」这类元数据；绝不能用 store 节点覆盖
        # tab["request"]——那会把用户在标签里的独立编辑全部抹掉，也是「两个页面
        # 内容变得一样」的根因。每个标签的 request 都是自己的快照。
        for tab in self.tabs_data:
            node_id = tab.get("node_id")
            if node_id:
                node = self.store.find(node_id)
                if node:
                    tab["title"] = node.get("name", tab["title"])
                    # 集合里改了名，标签里的请求内容也要跟着改 —— 否则保存时又写回旧名
                    if isinstance(tab.get("request"), dict) and node.get("type") == "request":
                        tab["request"]["name"] = tab["title"]
                    self.tabstrip.update_tab(tab["id"], title=tab["title"],
                                             method=node.get("method", "GET"))
        self.env_pill.updateGeometry()
        self.env_pill.update()
        self._cloud_autosync()

    def _on_request_deleted(self, node_id: str) -> None:
        for tab in list(self.tabs_data):
            if tab.get("node_id") == node_id:
                self.close_tab(tab["id"])

    def _sync_open_ids(self) -> None:
        self.sidebar.set_open_ids({t["node_id"] for t in self.tabs_data if t.get("node_id")})

    def _update_stack(self) -> None:
        has_tab = bool(self.tabs_data)
        self.stack.setCurrentWidget(self.workspace if has_tab else self.welcome)
        self.tabstrip.setVisible(has_tab)

    # -------------------------------------------------- 发送
    def send_current(self) -> None:
        tab = self.current_tab()
        if tab is not None and (tab["request"].get("method") or "").upper() in REALTIME_METHODS:
            # 已连上时 ⌘↵ 就是「发这条消息 / 事件」；没连上就是「建立连接」
            client = self.sio if (tab["request"].get("method") or "").upper() == SIO_METHOD else self.ws
            if client.is_open and self._ws_tab == tab["id"]:
                self._ws_send_from_composer()
            else:
                self.ws_toggle(tab)
            return
        if self.client.busy:
            self._abort()
            return
        if tab is None:
            return
        req = tab["request"]
        if not (req.get("url") or "").strip():
            self.toast.show_message("请先填写请求地址", "error")
            self.editor.focus_url()
            return
        self._inflight_tab = tab["id"]
        # 一旦真的发了请求，这个标签就不再是「临时预览」了：斜体转正
        if tab.get("preview"):
            tab["preview"] = False
            self.tabstrip.update_tab(tab["id"], title=tab.get("title"), preview=False)
        self.editor.set_busy(True)
        self.response.show_loading()
        settings = dict(self.store.settings)
        from .nodes import NodeBook

        node = NodeBook(self.store).current()
        settings["node_proxy"] = NodeBook(self.store).proxy_url()
        if node.get("kind") == "relay":
            settings["relay_node"] = node
        self.response.set_node(node)
        self.client.send(req, settings, self.store.env_vars())

    def _abort(self) -> None:
        for client in (self.sio, self.ws):
            if client.busy:
                client.disconnect_ws()
                return
        self.client.abort()

    # -------------------------------------------------- WebSocket / Socket.IO
    def _realtime_client(self):
        """当前实时标签用哪条连接；不依赖界面当前页，避免跨标签串线。"""
        tab = self._tab(self._ws_tab) if self._ws_tab else None
        if tab is not None and (tab.get("request", {}).get("method") or "").upper() == SIO_METHOD:
            return self.sio
        return self.ws

    @staticmethod
    def _ws_session(tab: Dict[str, Any]) -> Dict[str, Any]:
        sess = tab.get("ws_session")
        if not isinstance(sess, dict):
            sess = {"log": [], "state": "idle", "protocol": "", "latency": 0,
                    "uptime": 0.0, "url": ""}
            tab["ws_session"] = sess
        return sess

    def _realtime_url(self) -> str:
        """实时协议地址：地址栏原文解析环境变量，再拼上「参数」页启用的查询参数。"""
        from urllib.parse import urlencode

        raw = resolve_vars(self.editor.urlbar.url_text(), self.store.env_vars()).strip()
        if not raw:
            return ""
        composer = self.editor.sio if self.editor.is_sio() else self.editor.ws
        env = self.store.env_vars()
        pairs = [(resolve_vars(str(r["key"]), env),
                  resolve_vars(str(r.get("value", "")), env))
                 for r in composer.params.rows()
                 if r.get("enabled", True) and r.get("key")]
        if not pairs:
            return raw
        sep = "&" if "?" in raw else "?"
        return raw + sep + urlencode(pairs)

    def _ws_headers(self, req: Dict[str, Any]) -> List[tuple]:
        """握手头：请求头 + Cookie + 认证，全部按当前环境变量解析。"""
        env = self.store.env_vars()
        out: List[tuple] = []
        seen = set()
        for row in req.get("headers") or []:
            if not row.get("enabled", True) or not str(row.get("key") or "").strip():
                continue
            key = resolve_vars(str(row["key"]), env)
            out.append((key, resolve_vars(str(row.get("value") or ""), env)))
            seen.add(key.lower())
        cookies = [f"{resolve_vars(str(c['key']), env)}={resolve_vars(str(c.get('value') or ''), env)}"
                   for c in req.get("cookies") or []
                   if c.get("enabled", True) and str(c.get("key") or "").strip()]
        if cookies and "cookie" not in seen:
            out.append(("Cookie", "; ".join(cookies)))
        auth = self.client._effective_auth(req, env)
        kind = (auth or {}).get("type") or "none"
        if kind == "bearer" and auth.get("token"):
            out.append(("Authorization", f"Bearer {resolve_vars(auth['token'], env)}"))
        elif kind == "basic":
            raw = f"{auth.get('username', '')}:{auth.get('password', '')}".encode("utf-8")
            out.append(("Authorization", "Basic " + base64.b64encode(raw).decode("ascii")))
        elif kind == "apikey" and auth.get("key"):
            name = str(auth.get("key"))
            value = resolve_vars(str(auth.get("value") or ""), env)
            if (auth.get("add_to") or "header") == "header":
                out.append((name, value))
        if "user-agent" not in seen:
            out.append(("User-Agent", self.store.settings.get("user_agent") or "Ocelot/1.0"))
        return out

    def _ws_show(self, tab: Dict[str, Any]) -> None:
        sess = self._ws_session(tab)
        method = (tab.get("request", {}).get("method") or "").upper()
        kind = "sio" if method == SIO_METHOD else "ws"
        if self._ws_tab == tab["id"]:
            client = self.sio if kind == "sio" else self.ws
            sess["state"] = client.state
            sess["uptime"] = client.stats().get("uptime", 0.0)
        # 切回一个还连着（或已断开）的标签时，按钮要保持「断开 / 连接」的正确语义
        self.editor.set_ws_state(sess["state"] if self._ws_tab == tab["id"] else "idle")
        self.response.show_ws(sess, sess.get("url") or tab["request"].get("url", ""),
                              kind=kind)

    def ws_toggle(self, tab: Dict[str, Any]) -> None:
        """连接 / 断开。切换标签时连接跟着走，但日志各存各的。"""
        tid = tab["id"]
        req = tab["request"]
        sio = (req.get("method") or "").upper() == SIO_METHOD
        client = self.sio if sio else self.ws
        if self._ws_tab == tid and client.busy:
            client.disconnect_ws()
            return
        url = self._realtime_url()
        if not url:
            self.toast.show_message(
                i18n.tr("请先填写 Socket.IO 地址") if sio
                else i18n.tr("请先填写 WebSocket 地址"), "error")
            self.editor.focus_url()
            return
        if client.busy:
            client.disconnect_ws()
        # 前置脚本：先把环境变量 / 认证算好再握手，和 HTTP 一致
        try:
            self.client._run_pre_script(req, self.store.env_vars())
        except Exception:                      # noqa: BLE001
            pass
        self._ws_tab = tid
        sess = self._ws_session(tab)
        sess.update({"log": [], "state": "connecting", "protocol": "", "latency": 0,
                     "uptime": 0.0, "url": url})
        self.editor.set_ws_state("connecting")
        if self.tabstrip.current() == tid:
            self.response.show_ws(sess, url, kind="sio" if sio else "ws")
        verify = bool(self.store.settings.get("verify_ssl", True))
        if sio:
            from .sio_panel import ensure_sio
            option = ensure_sio(req)
            ok = self.sio.connect_to(
                url, self._ws_headers(req), "",
                namespace=str(option.get("namespace") or "/"),
                auth=str(option.get("auth") or ""),
                auto_reconnect=bool(option.get("auto_reconnect", True)),
                ping_secs=0, verify_ssl=verify)
        else:
            option = req.get("ws") or {}
            ok = self.ws.connect_to(
                url, self._ws_headers(req), str(option.get("subprotocol") or ""),
                auto_reconnect=bool(option.get("auto_reconnect", True)),
                ping_secs=int(option.get("ping") or 0), verify_ssl=verify)
        if not ok:
            self.editor.set_ws_state("idle")

    def _on_ws_action(self, action: str) -> None:
        """响应面板「…」菜单里的连接操作，复用地址栏那一套连接逻辑。"""
        tab = self.current_tab()
        if tab is None or (tab.get("request", {}).get("method", "").upper()
                           not in REALTIME_METHODS):
            return
        busy = self._realtime_client().busy
        if action == "disconnect" and not busy:
            self.toast.show_message(i18n.tr("当前没有连接"), "info")
            return
        if action == "connect" and busy:
            return
        self.ws_toggle(tab)

    def _ws_send_from_composer(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        if self.editor.is_sio():
            self._sio_send(self.editor.sio.event_value(), self.editor.sio.payload(),
                           self.editor.sio.ack_enabled())
            return
        text = self.editor.ws.payload()
        if not text.strip():
            self.toast.show_message(i18n.tr("先输入要发送的内容"), "info")
            return
        self._ws_send(text, self.editor.ws.kind_key() == "binary")

    def _sio_send(self, event: str, payload: str, with_ack: bool = False) -> None:
        if not self.sio.is_open:
            self.toast.show_message(i18n.tr("先连接再发送事件"), "error")
            return
        if not self.sio.emit_event(event, payload, with_ack):
            return
        if with_ack:
            self.toast.show_message(i18n.tr("事件已发出，等待 ACK"), "info")

    def _sio_replay(self, event: str, payload: str) -> None:
        """双击事件日志：事件名和载荷一起填回编辑器，改一改就能重发。"""
        self.editor.sio.event_name.setText(event or "")
        self.editor.sio.editor.setPlainText(payload or "")
        self.editor.sio.editor.setFocus()
        self.toast.show_message(i18n.tr("已填入事件编辑器，⌘↵ 发送"), "success")

    def _ws_replay(self, text: str) -> None:
        """双击日志里的一条消息：填回编辑器，改一改就能重发。"""
        if not text:
            return
        self.editor.ws.editor.setPlainText(text)
        self.editor.ws.editor.setFocus()
        self.toast.show_message(i18n.tr("已填入编辑器，⌘↵ 发送"), "success")

    def _ws_send(self, text: str, binary: bool) -> None:
        if not self.ws.is_open:
            self.toast.show_message("还没连接：先点「连接」再发消息", "error")
            return
        if binary:
            raw = b""
            try:
                raw = base64.b64decode(text.strip(), validate=False)
            except Exception:                  # noqa: BLE001
                raw = text.encode("utf-8")
            self.ws.send_binary(raw)
        else:
            self.ws.send_text(text)

    def _ws_tick_update(self) -> None:
        tab = self._tab(self._ws_tab) if self._ws_tab else None
        client = self._realtime_client()
        if tab is None or not client.is_open:
            self._ws_tick.stop()
            return
        stats = client.stats()
        self._ws_session(tab)["uptime"] = stats.get("uptime", 0.0)
        if self.tabstrip.current() == tab["id"]:
            self.response.ws_set_state("open", stats)

    def _on_ws_state(self, state: str) -> None:
        tab = self._tab(self._ws_tab) if self._ws_tab else None
        if tab is not None:
            self._ws_session(tab)["state"] = state
        if tab is not None and self.tabstrip.current() == tab["id"]:
            self.editor.set_ws_state(state)
            self.response.ws_set_state(state, self._realtime_client().stats())

    def _on_ws_opened(self, protocol: str) -> None:
        tab = self._tab(self._ws_tab) if self._ws_tab else None
        client = self._realtime_client()
        sio = client is self.sio
        if tab is not None:
            sess = self._ws_session(tab)
            sess["protocol"] = protocol or ""
            sess["uptime"] = 0.0
        self.editor.set_ws_state("open")
        self._ws_tick.start()
        if tab is not None and self.tabstrip.current() == tab["id"]:
            self.response.ws_set_state("open", client.stats())
        if sio:
            self.toast.show_message(
                i18n.trf("Socket.IO 已连接 · {p}", p=protocol or i18n.tr("默认命名空间")),
                "success")
        else:
            self.toast.show_message(
                i18n.trf("已连接 · 子协议 {p}", p=protocol) if protocol
                else i18n.tr("WebSocket 已连接"), "success")

    def _on_ws_closed(self, code: int, reason: str) -> None:
        tab = self._tab(self._ws_tab) if self._ws_tab else None
        if tab is not None:
            self._ws_session(tab)["uptime"] = 0.0
        self.editor.set_ws_state("idle")
        self._ws_tick.stop()
        if tab is not None and self.tabstrip.current() == tab["id"]:
            self.response.ws_set_state("closed", self._realtime_client().stats())
        if code not in (1000, 1005, 1006):
            self.toast.show_message(i18n.trf("连接已关闭（{code}）{reason}",
                                             code=code, reason=reason), "info")

    def _on_ws_failed(self, message: str) -> None:
        self.editor.set_ws_state("idle")
        # 自动重连会一次次失败：只在第一次弹提示，后面让日志里的系统消息说话
        if getattr(self._realtime_client(), "_attempt", 0) <= 1:
            self.toast.show_message(message, "error")

    def _on_ws_pong(self, ms: int) -> None:
        tab = self._tab(self._ws_tab) if self._ws_tab else None
        if tab is not None:
            self._ws_session(tab)["latency"] = int(ms)
            if self.tabstrip.current() == tab["id"]:
                self.response.pill.setToolTip(i18n.trf("连接往返延迟 {ms} ms", ms=int(ms)))

    def _on_ws_frame(self, frame) -> None:
        tab = self._tab(self._ws_tab) if self._ws_tab else None
        if tab is None:
            return
        sess = self._ws_session(tab)
        log = sess["log"]
        log.append(frame)
        # 日志有上限：长时间订阅的行情类连接不该把内存吃光
        if len(log) > 4000:
            del log[:len(log) - 4000]
        client = self._realtime_client()
        sess["uptime"] = client.stats().get("uptime", 0.0)
        if self.tabstrip.current() == tab["id"]:
            self.response.ws_add_frame(frame)
            self.response.ws_set_state(client.state, client.stats())

    def _on_response(self, resp: Response) -> None:
        tab_id = self._inflight_tab
        self._inflight_tab = None
        self.editor.set_busy(False)
        tab = self._tab(tab_id) if tab_id else self.current_tab()
        if tab is not None:
            tab["response"] = resp
            tab["stale"] = False
            tab["view"] = self.response.view_state() if tab_id == self.tabstrip.current() else None
            # 真实请求里的脚本输出回填到两个脚本页，用户不必再猜日志去哪了
            logs = list(getattr(self.client, "scriptLogs", []) or [])
            tab["console"] = list(getattr(self.client, "console", []) or [])
            self.editor.scripts_pre.set_logs(logs)
            self.editor.scripts_post.set_logs(logs)
            self.store.push_history(tab["request"], resp.status, resp.elapsed)
            self.sidebar.refresh_history()
            self._autosave.start()       # 落盘合并到 700ms，避免每条响应都同步写 100KB
            # 名字还是默认值时，发完这一条顺手让 AI 起个更像人话的名字
            if (tab["request"].get("method") or "").upper() not in REALTIME_METHODS:
                self._ai_auto_name(tab)
        if tab_id is None or tab_id == self.tabstrip.current():
            self.response.set_response(resp)
            self.response.set_console(tab.get("console") if tab is not None else None)
            self._refresh_timeline(tab["request"] if tab is not None else None)
            # 把 Set-Cookie 递给 Cookie 页，登录类请求可以一键收进来
            self.editor.set_last_cookies(resp.cookies)
        if resp.error:
            self.toast.show_message(resp.error, "error")
        else:
            self.toast.show_message(f"{resp.status} {resp.reason} · {human_elapsed(resp.elapsed)}",
                                    "success" if resp.ok else "info")

    # -------------------------------------------------- 保存
    def save_current(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        req = tab["request"]
        node_id = tab.get("node_id")
        if not node_id or self.store.find(node_id) is None:
            parent = None
            node = dict(req)
            node["type"] = "request"
            node["id"] = node.get("id") or new_request()["id"]
            node.pop("children", None)
            self.store.add_node(parent, node)
            tab["node_id"] = node["id"]
            # 标签继续持有自己的快照，不能指向 store 里的节点对象，
            # 否则后续编辑会改到集合树，也会让其他标签跟着变。
            tab["request"] = _copy.deepcopy(node)
            self.sidebar.refresh()
            self._sync_open_ids()
            # 保存后左侧集合树立刻定位到新条目：用户不用自己去树里找，
            # 保存动作和「看到结果」连贯起来。
            self.sidebar.reveal(node["id"])
        self.store.save()
        tab["dirty"] = False
        self.tabstrip.update_tab(tab["id"], dirty=False)
        self.toast.show_message("已保存到集合", "success")

    def _on_stale_never(self) -> None:
        self.store.settings["stale_notice"] = False
        self.response.set_stale_notice(False)
        self.store.save()
        self.toast.show_message("已关闭「请求已修改」提醒", "success")

    def _save_env_var(self, name: str, value: str) -> None:
        """提取结果 → 环境变量（没有激活环境就建一个 Default）。"""
        env = self.store.active_environment()
        if env is None:
            env = {"id": "env_default", "name": "Default", "vars": []}
            self.store.environments.append(env)
            self.store.set_active_env(env["id"])
        for row in env.setdefault("vars", []):
            if row.get("key") == name:
                row["value"] = value
                row["enabled"] = True
                break
        else:
            env["vars"].append({"key": name, "value": value, "enabled": True})
        self.store.save()
        self.env_pill.updateGeometry()
        self.env_pill.update()
        self.toast.show_message(i18n.trf("已保存变量 {{{name}}}", name=name), "success")

    def _pick_var_from_response(self, body: str) -> None:
        """从 JSON 响应里挑字段存成变量（全局 / 当前环境都行）。"""
        from .dialogs import VarPickDialog

        if not (body or "").strip():
            self.toast.show_message("响应是空的，没有可提取的字段", "info")
            return
        dlg = VarPickDialog(self.store, body, self)
        if not dlg.exec():
            return
        self.env_pill.updateGeometry()
        self.env_pill.update()
        scope = dlg.result_scope()
        self.toast.show_message(
            i18n.trf("已存入{where} {{{name}}}",
                     where="全局变量" if scope == "global" else "环境变量",
                     name=dlg.result_name()), "success")

    def _persist(self) -> None:
        self.store.settings["sidebar_width"] = self._sidebar_target
        sizes = self.splitter.sizes()
        if sizes and sum(sizes) > 200:
            self.store.settings["split_ratio"] = round(sizes[0] / sum(sizes), 4)
        self.store.data["open_tabs"] = [t["node_id"] for t in self.tabs_data if t.get("node_id")]
        self._sync_tabs_to_store()
        self.store.save()
        self._cloud_autosync()

    def _sync_tabs_to_store(self) -> None:
        """把标签里的编辑写回集合节点。

        标签持有的是自己的快照（避免两个标签互相串内容），所以保存时必须显式
        回写 —— 否则「改完关掉再打开还是旧内容」，重命名之类的改动也同步不出去。
        """
        for tab in self.tabs_data:
            node_id = tab.get("node_id")
            req = tab.get("request")
            if not node_id or not isinstance(req, dict):
                continue
            node = self.store.find(node_id)
            if node is None or node.get("type") != "request":
                continue
            for key, value in req.items():
                if key in ("id", "type", "children"):
                    continue
                node[key] = _copy.deepcopy(value)
            node["id"] = node_id
            node["type"] = "request"

    def _cloud_autosync(self) -> None:
        """开了「云同步 + 自动上传」时，改动后延迟合并上传一次（不打断操作）。"""
        settings = self.store.settings
        if not (settings.get("cloud_enabled") and settings.get("cloud_auto")):
            return
        if not (settings.get("turso_url") and settings.get("turso_token")):
            return
        timer = getattr(self, "_cloud_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(1500)
            timer.timeout.connect(self._cloud_push_now)
            self._cloud_timer = timer
        timer.start()

    def _cloud_push_now(self) -> None:
        """把最新快照推上去。上一轮还没结束时记一个 dirty，结束后补传 ——
        以前这里是直接 return，连续改几次就会把最后一次改动丢掉。"""
        from .cloud import CloudWorker, client_for

        old = getattr(self, "_cloud_worker", None)
        if old is not None and old.isRunning():
            self._cloud_dirty = True
            return
        self._cloud_dirty = False
        text = json.dumps(self.store.data, ensure_ascii=False)
        client = client_for(self.store.settings)
        worker = CloudWorker(lambda: client.push(text), self)
        self._cloud_worker = worker

        def done(ok, _msg, _data):
            if self._cloud_worker is worker:
                self._cloud_worker = None
            if self._cloud_dirty:
                # 这一轮传的是旧快照，立刻补一次最新的
                QTimer.singleShot(300, self._cloud_push_now)

        worker.done.connect(done)
        worker.start()

    def _wait_cloud(self) -> None:
        """退出前等一次性上传收尾，避免线程还在跑时窗口先被销毁。"""
        worker = getattr(self, "_cloud_worker", None)
        if worker is not None and worker.isRunning():
            try:
                worker.wait(1200)
            except Exception:  # noqa: BLE001
                pass

    def _delete_current(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        node_id = tab.get("node_id")
        if node_id:
            self.sidebar.delete_node(node_id)
        else:
            self.close_tab(tab["id"])

    def _copy_curl(self) -> None:
        from .codegen import to_curl

        tab = self.current_tab()
        if tab is None:
            return
        text = to_curl(tab["request"], self.store.env_vars(), self.store.settings)
        QApplication.clipboard().setText(text)
        self.toast.show_message("已复制 cURL 命令", "success")

    # -------------------------------------------------- 侧栏
    def sidebar_visible(self) -> bool:
        return self.sidebar.isVisible() and self.sidebar.width() > 20

    def toggle_sidebar(self) -> None:
        self._animate_sidebar(0 if self.sidebar_visible() else self._sidebar_target)

    def _on_sidebar_dragged(self, _pos: int, _index: int) -> None:
        # 折叠动画每帧都会 setSizes → splitterMoved → 这里。
        # 若在这时写磁盘（store.save 是同步 IO），一帧一次落盘，动画必然卡成两段。
        if getattr(self, "_side_animating", False):
            return
        w = self.sidebar.width()
        if w > 20:
            self._sidebar_target = w
            self.store.settings["sidebar_width"] = w
            self.store.settings["sidebar_visible"] = True
        else:
            self.store.settings["sidebar_visible"] = False
        # 拖动时每一帧都落盘太重：交给 700ms 的合并写入
        self._autosave.start()
        self.sidebar_btn.update()

    def _finish_sidebar_animation(self, final_width: Optional[int] = None) -> None:
        """无论动画正常结束还是中途被打断，都必须恢复更新、尺寸策略和信号连接。"""
        if not getattr(self, "_side_animating", False):
            return
        anim = getattr(self, "_side_anim", None)
        if anim is not None:
            _anim_stop(anim)
        if final_width is not None:
            total = max(self.split.width(), 400)
            self.split.setSizes([max(final_width, 0), max(total - final_width, 1)])
        content = self.split.widget(1)
        if content is not None:
            content.setUpdatesEnabled(True)
        self.sidebar.setUpdatesEnabled(True)
        # 动画期间临时把 Sidebar 的尺寸策略改成 Ignored，收尾必须还原，
        # 否则以后拖分隔条会无视最小宽度、把侧栏拖成一条缝。
        self._restore_sidebar_metrics()
        try:
            self.split.splitterMoved.disconnect(self._on_sidebar_dragged)
        except (TypeError, RuntimeError):
            pass
        try:
            self.split.splitterMoved.connect(self._on_sidebar_dragged)
        except (TypeError, RuntimeError):
            pass
        self._side_animating = False
        self._side_anim = None
        if content is not None:
            content.update()
        self.sidebar.update()

    def _restore_sidebar_metrics(self) -> None:
        target = max(int(getattr(self, "_sidebar_target", 268) or 268), 200)
        self.sidebar.setMinimumWidth(200 if self.sidebar.isVisible() else 0)
        self.sidebar.setMaximumWidth(420)
        self.sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        if self.split.childrenCollapsible():
            self.split.setChildrenCollapsible(False)
        if self.sidebar.isVisible():
            self._sidebar_target = target

    def _free_sidebar_metrics(self) -> None:
        """动画期间放开限制：QSplitter 平时会用 minimumSizeHint(≈158) 卡住子控件，
        导致 180ms 里前半段完全不动、最后一帧直接消失 —— 这正是「隐藏/显示都卡顿」的根因。"""
        self.sidebar.setMinimumWidth(0)
        self.sidebar.setMaximumWidth(16777215)
        self.sidebar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        if not self.split.childrenCollapsible():
            self.split.setChildrenCollapsible(True)

    def _animate_sidebar(self, target: int) -> None:
        # 上一段还没跑完就再来一次：先把被冻结的界面完整恢复，再开新动画。
        self._finish_sidebar_animation()
        total = max(self.split.width(), 400)
        visible = self.sidebar.isVisible()
        start = self.sidebar.width() if visible and self.sidebar.width() > 2 else 0
        self.store.settings["sidebar_visible"] = target > 0
        if hasattr(self, "sidebar_btn"):
            self.sidebar_btn.update()
        if abs(start - target) <= 2:
            self.split.setSizes([target, max(total - target, 1)])
            self.sidebar.setVisible(target > 0)
            if target > 0:
                self._sidebar_target = target
            self._restore_sidebar_metrics()
            self._autosave.start()
            return

        if target > 0:
            self.sidebar.setVisible(True)
            self._sidebar_target = target

        # 动画期间断开 splitterMoved（避免每帧写磁盘），内容区冻结绘制，
        # 侧栏照常重绘（只有 200 多像素宽，视觉上更跟手）。
        self._side_animating = True
        try:
            self.split.splitterMoved.disconnect(self._on_sidebar_dragged)
        except (TypeError, RuntimeError):
            pass
        content = self.split.widget(1)
        if content is not None:
            content.setUpdatesEnabled(False)
        self._free_sidebar_metrics()

        anim = QVariantAnimation(self)
        self._side_anim = anim        # 常驻引用，避免 DeleteWhenStopped 后 .stop() 崩
        anim.setStartValue(float(start))
        anim.setEndValue(float(target))
        anim.setDuration(190)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        last = [-1]

        def step(v):
            w = int(v)
            if w == last[0]:
                return
            last[0] = w
            self.split.setSizes([max(w, 0), max(total - w, 1)])

        def done():
            self.sidebar.setVisible(target > 0)
            self._finish_sidebar_animation(target)
            self._autosave.start()     # 整段动画只落盘一次（700ms 合并写）

        anim.valueChanged.connect(step)
        anim.finished.connect(done)
        anim.start()

    # -------------------------------------------------- 对话框
    def show_settings(self, page: str = "general") -> None:
        dlg = SettingsDialog(self.store, self, page=page)
        dlg.themeChanged.connect(self._apply_theme)
        dlg.accentChanged.connect(self._on_accent_changed)
        dlg.dataReloaded.connect(self._reload_data)
        dlg.shortcutsChanged.connect(self._install_shortcuts)
        # 字号是就地缩放（settings 里已经处理完），这里只把主窗口重绘一遍，
        # 让自绘部分（侧栏行高、标签条、状态胶囊）跟着新系数画。
        dlg.uiScaleChanged.connect(self._on_scale_applied)
        dlg.settingsChanged.connect(self._on_settings_applied)
        dlg.exec()

    def open_resources(self) -> None:
        """打开资源管理器：应用数据目录的文件管理（浏览 / 打开 / 重命名 / 删除）。"""
        from .resmon import ResourceDialog

        dlg = ResourceDialog(self.store, self,
                             analysis_cache=self._analysis_cache,
                             tabs_count=len(self.tabs_data),
                             on_data_changed=self._on_resources_changed)
        dlg.exec()

    def _on_resources_changed(self) -> None:
        """资源管理器里清过数据：侧栏与历史列表要立刻反映真实状态。"""
        self.sidebar.refresh()
        refresh = getattr(self.sidebar, "refresh_history", None)
        if callable(refresh):
            refresh()

    def _on_settings_applied(self) -> None:
        self.response.set_stale_notice(
            bool(self.store.settings.get("stale_notice", True)))
        # 自动回收的开关 / 间隔改了，立刻按新设置重排定时器
        trim = getattr(self, "_auto_trim", None)
        if trim is not None:
            trim.apply()

    def _ai_explain_response(self) -> None:
        """分析当前响应页：命中缓存直接显示，否则按页签喂证据并流式输出。"""
        from . import ai as ai_mod
        from .dialogs import AiAnswerDialog

        cfg = ai_mod.config(self.store)
        ok, why = ai_mod.ready(cfg)
        if not ok:
            self.toast.show_message(why, "info")
            self.show_settings("ai")
            return
        ctx = self.response.ai_context(self.editor.request)
        key = ai_mod.analysis_key(ctx)
        subtitle = i18n.trf("{page} · {method} {url}",
                            page=ctx.get("tab_label") or "响应",
                            method=str((ctx.get("request") or {}).get("method") or "GET").upper(),
                            url=(ctx.get("request") or {}).get("url") or "")
        dlg = AiAnswerDialog("AI 响应分析", subtitle, parent=self)

        def run() -> None:
            # 重新分析时按「当时的」响应重新算指纹，结果直接覆盖旧缓存。
            context = self.response.ai_context(self.editor.request)
            cache_key = ai_mod.analysis_key(context)
            messages = ai_mod.messages_for_analysis(context)
            dlg.reset()
            dlg.set_busy(True, "正在分析")

            def done(_text: str) -> None:
                result = dlg.result()
                self._analysis_cache.put(cache_key, result)
                dlg.set_result(result)

            self._ai_explain_chat = ai_mod.start(
                messages, cfg=cfg, max_tokens=1400, temperature=0.2,
                on_chunk=dlg.append_chunk,
                on_done=done,
                on_error=lambda err: dlg.set_result(err[:200], error=True))

        dlg.retryRequested.connect(run)
        dlg.copyRequested.connect(lambda: (
            QGuiApplication.clipboard().setText(dlg.result()),
            self.toast.show_message("分析结果已复制", "success")))
        cached = self._analysis_cache.get(key)
        if cached:
            dlg.set_result(cached, cached=True)
        else:
            run()
        dlg.exec()

    def _on_scale_applied(self, _scale: float) -> None:
        for widget in (self.sidebar, self.tabstrip, self.editor, self.response,
                       self.toast):
            try:
                widget.updateGeometry()
                widget.update()
            except RuntimeError:
                pass
        self._sync_open_ids()

    def _reload_data(self) -> None:
        """从云端恢复后整份数据都换了：标签全部关掉，侧栏与主题重新刷一遍。"""
        for tab in list(self.tabs_data):
            self.close_tab(tab["id"])
        self._analysis_cache.clear()
        self.sidebar.refresh()
        self.sidebar.refresh_history()
        self.response.set_stale_notice(bool(self.store.settings.get("stale_notice", True)))
        self.env_pill.updateGeometry()
        self.env_pill.update()
        self._apply_theme(self.store.settings.get("theme", "dark"))
        self.toast.show_message("已载入云端数据", "success")

    def show_envs(self) -> None:
        dlg = EnvDialog(self.store, self)
        if dlg.exec():
            self.env_pill.updateGeometry()
            self.env_pill.update()
            self.toast.show_message("环境变量已更新", "success")

    def import_curl(self) -> None:
        dlg = ImportCurlDialog(self)
        if dlg.exec() and dlg.request is not None:
            self._open_request_obj(dlg.request, node_id=None)
            self.toast.show_message("已从 cURL 导入，⌘S 可保存到集合", "success")

    def import_collection(self) -> None:
        self.open_transfer("import")

    def export_collection(self) -> None:
        self.open_transfer("export")

    def open_transfer(self, page: str = "import") -> None:
        """集合的导入 / 导出：一个对话框里切换来源、选文件、导出。"""
        from .dialogs import TransferDialog

        dlg = TransferDialog(self.store, self)
        dlg.imported.connect(self._on_imported)
        dlg.exec()

    def open_trash(self) -> None:
        """回收站：恢复误删的集合 / 请求，恢复后立即回到原位置。"""
        from .trash_dialog import TrashDialog

        dlg = TrashDialog(self.store, self)
        dlg.changed.connect(self._on_store_changed)
        # 恢复完把左侧集合树刷出来，并滚动定位到恢复的条目——之前 changed
        # 只同步标签元数据、不刷新树，用户会觉得「恢复了但左边没出现」。
        dlg.restored.connect(self._on_trash_restored)
        dlg.exec()

    def _on_trash_restored(self, node_ids: list) -> None:
        """回收站恢复后：刷新集合树并定位到恢复出来的条目。"""
        self.sidebar.refresh()
        self._on_store_changed()
        for nid in node_ids or []:
            self.sidebar.reveal(nid)
        self._sync_open_ids()

    def _on_imported(self, count: int) -> None:
        self.sidebar.refresh()
        self._on_store_changed()
        self._persist()
        self.toast.show_message(i18n.trf("已导入 {n} 个请求", n=count), "success")
        # 导入完直接把新集合滚到眼前并展开，省得用户自己在树里找
        if count:
            newest = (self.store.collections or [None])[-1]
            if newest:
                self.sidebar.reveal(newest.get("id"))
                self.sidebar.expand_node(newest.get("id"))
        self._cloud_autosync()

    def show_code(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        CodeDialog(tab["request"], self.store.env_vars(), self.store.settings, self).exec()

    # -------------------------------------------------- 集合运行器
    def run_collection(self, node_id: str) -> None:
        """顺序跑一个文件夹里的全部请求，结果在弹出面板里逐条刷新。"""
        from .runner import RunnerDialog, flatten_requests

        folder = self.store.find(node_id)
        if not folder or folder.get("type") != "folder":
            self.toast.show_message("请选择要运行的集合文件夹", "error")
            return
        if not flatten_requests(folder):
            self.toast.show_message("这个文件夹里还没有请求", "error")
            return
        dlg = RunnerDialog(self.store, folder, self)
        picked: List[Dict[str, Any]] = []

        def _open(payload: Dict[str, Any]) -> None:
            picked.append(payload)
            dlg.accept()

        dlg.openRequested.connect(_open)
        dlg.exec()
        if picked:
            payload = picked[0]
            req = payload.get("request") or {}
            self._open_request_obj(req, node_id=req.get("id"))
            # 点的是已经跑完的那一条：把那次的响应直接铺开，可以点进去看内容
            resp = payload.get("response")
            if resp is not None:
                tab = self.current_tab()
                if tab is not None:
                    tab["response"] = resp
                    self.response.set_response(resp)
                    self._refresh_timeline(req)

    def run_selected_collection(self) -> None:
        """⌘⇧R：跑当前标签所在文件夹；没标签时跑侧栏里选中的文件夹。"""
        from .sidebar import ROLE_ID

        target = None
        tab = self.current_tab()
        node_id = tab.get("node_id") if tab else None
        while node_id:
            node = self.store.find(node_id)
            if node is None:
                break
            if node.get("type") == "folder":
                target = node_id
                break
            node_id = self.store.parent_id(node_id)
        if target is None:
            item = self.sidebar.tree.currentItem()
            nid = item.data(0, ROLE_ID) if item is not None else None
            node = self.store.find(nid) if nid else None
            if node is not None and node.get("type") == "folder":
                target = nid
        if target is None:
            self.toast.show_message("先选中一个集合文件夹，或打开集合里的请求", "info")
            return
        self.run_collection(target)

    def toggle_theme(self) -> None:
        name = "light" if theme().name == "dark" else "dark"
        self.store.settings["theme"] = name
        self.store.save()
        self._apply_theme(name)

    def _on_accent_changed(self, key: str) -> None:
        """主题色只换强调色，配色方案（深浅/底色）保持不变。"""
        self.store.settings["accent"] = key or "auto"
        self._apply_theme(self.store.settings.get("theme", "dark"))

    def _apply_theme(self, name: str) -> None:
        app = QApplication.instance()
        set_accent(self.store.settings.get("accent", "auto"))
        apply_theme(app, theme_by_name(name))
        self.store.settings["theme"] = name
        self.store.save()
        for w in self.findChildren(QWidget):
            # 不可见的控件不用逐个 update：它们重新显示时本来就会重绘，
            # 大窗口下有几百个控件，全量刷一遍纯属浪费。
            if w.isVisible():
                w.update()
            fn = getattr(w, "refresh_theme", None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
        self.env_pill.updateGeometry()
        self.update()

    # -------------------------------------------------- 命令面板
    def show_palette(self) -> None:
        self.palette.open()

    def _on_palette_action(self, kind: str, payload: Any) -> None:
        if kind == "request":
            self._open_from_sidebar(payload)
            return
        if kind == "env":
            self.store.set_active_env(payload)
            self.store.save()
            self.env_pill.updateGeometry()
            self.env_pill.update()
            self.toast.show_message("已切换环境", "success")
            return
        key = payload
        if key == "new_request":
            self.new_request()
        elif key == "new_ws":
            self.new_websocket()
        elif key == "new_sio":
            self.new_socketio()
        elif key == "new_folder":
            self.sidebar._new_folder()
            self.toast.show_message("已新建文件夹", "success")
        elif key == "send":
            self.send_current()
        elif key == "save":
            self.save_current()
        elif key == "env":
            self.show_envs()
        elif key == "trash":
            self.open_trash()
        elif key == "trash_settings":
            self.show_settings(page="data")
        elif key == "settings":
            self.show_settings()
        elif key == "appearance":
            self.show_settings(page="appearance")
        elif key == "cloud":
            self.show_settings(page="cloud")
        elif key == "doc":
            self.open_doc()
        elif key == "mock":
            self.open_mock()
        elif key == "shortcuts":
            self.show_settings(page="shortcuts")
        elif key == "duplicate":
            self._duplicate_request()
        elif key == "close_tab":
            tab = self.current_tab()
            if tab is not None:
                self.close_tab(tab["id"])
        elif key == "toggle_sidebar":
            self.toggle_sidebar()
        elif key == "import_curl":
            self.import_curl()
        elif key == "import_collection":
            self.import_collection()
        elif key == "export_collection":
            self.export_collection()

    # -------------------------------------------------- 快捷键
    def _shortcut_targets(self) -> Dict[str, Any]:
        """动作 id → 回调。键位在 shortcuts.py，这里只负责「按了做什么」。"""
        current = lambda: self.current_tab()
        return {
            "new_request": self.new_request,
            "send": self.send_current,
            "save": self.save_current,
            "duplicate": self._duplicate_request,
            "close_tab": lambda: current() and self.close_tab(current()["id"]),
            "next_tab": self._next_tab,
            "prev_tab": self._prev_tab,
            "palette": self.show_palette,
            "find": self.response.toggle_find,
            "toggle_sidebar": self.toggle_sidebar,
            "code": self.show_code,
            "doc": lambda: self.open_doc(),
            "mock": self.open_mock,
            "env": self.show_envs,
            "run_collection": self.run_selected_collection,
            "settings": lambda: self.show_settings(),
        }

    def _install_shortcuts(self) -> None:
        """按注册表重建全部快捷键：设置页改完键位立刻生效，不用重启。"""
        from . import shortcuts as sc

        for old in getattr(self, "_shortcuts", []):
            try:
                old.setEnabled(False)
                old.deleteLater()
            except RuntimeError:
                pass
        self._shortcuts = []
        targets = self._shortcut_targets()
        for action, seq in sc.mapping(self.store).items():
            fn = targets.get(action)
            if fn is None or not seq:
                continue
            try:
                hot = QShortcut(QKeySequence(seq), self)
            except Exception:      # noqa: BLE001 — 非法键位不该让窗口起不来
                continue
            hot.setContext(Qt.ShortcutContext.WindowShortcut)
            hot.activated.connect(fn)
            self._shortcuts.append(hot)

    def _auto_start_mock(self) -> None:
        """上次开着本地 Mock 就顺手拉起来（多实例逐个恢复），失败也不打扰。"""
        from .mock_server import mock_config

        cfg = mock_config(self.store.data)
        started = []
        for inst in cfg.get("instances") or []:
            if not inst.get("auto_start"):
                continue
            srv = self.mock.get(inst.get("id") or "main", inst.get("name") or "")
            if srv.running:
                continue
            ok, _msg = srv.start(inst.get("routes") or [], inst.get("port") or 8787,
                                 bool(cfg.get("fallback_echo")), bool(inst.get("lan")))
            if ok:
                inst["port"] = srv.port
                started.append(srv.base)
        self._refresh_mock_badge()
        if started:
            self.toast.show_message(
                i18n.trf("本地 Mock 服务已启动 · {n} 个实例", n=len(started)), "success")

    def _next_tab(self) -> None:
        ids = self.tabstrip.ids()
        if not ids:
            return
        cur = self.tabstrip.current()
        i = (ids.index(cur) + 1) % len(ids) if cur in ids else 0
        self.tabstrip.set_current(ids[i])
        self._on_tab_changed(ids[i])

    def _prev_tab(self) -> None:
        ids = self.tabstrip.ids()
        if not ids:
            return
        cur = self.tabstrip.current()
        i = (ids.index(cur) - 1) % len(ids) if cur in ids else 0
        self.tabstrip.set_current(ids[i])
        self._on_tab_changed(ids[i])

    def _jump_tab(self, index: int) -> None:
        ids = self.tabstrip.ids()
        if 0 <= index - 1 < len(ids):
            self.tabstrip.set_current(ids[index - 1])
            self._on_tab_changed(ids[index - 1])

    # -------------------------------------------------- 会话恢复 / 退出
    def _restore_session(self) -> None:
        if not self.store.settings.get("sidebar_visible", True):
            self.sidebar.setVisible(False)
            self.split.setSizes([0, 1200])
        opened = False
        if self.store.settings.get("restore_session", True):
            for node_id in self.store.data.get("open_tabs", [])[:8]:
                node = self.store.find(node_id)
                if node and node.get("type") == "request":
                    self._open_request_obj(node, node_id=node_id, activate=False)
                    opened = True
        if opened:
            tabs = [t for t in self.tabs_data]
            if tabs:
                self.tabstrip.set_current(tabs[0]["id"], animate=False)
                self._on_tab_changed(tabs[0]["id"])
        self._update_stack()
        self._sync_open_ids()

    def showEvent(self, e):
        super().showEvent(e)
        # 用窗口原生透明度淡入整个窗口，绝不给承载整棵控件树的 root 挂
        # QGraphicsOpacityEffect —— 那是 macOS 上 Qt 渲染层 SIGBUS 的直接诱因
        # （崩溃日志 <no Python frame>）。窗口透明度由系统合成，安全等价。
        fade_window(self, 180)
        if not getattr(self, "_split_applied", False):
            self._split_applied = True
            QTimer.singleShot(0, self._apply_split)
        if getattr(self, "safe_mode", False) and not getattr(self, "_safe_notified", False):
            self._safe_notified = True
            QTimer.singleShot(700, lambda: self.toast.show_message(
                "上次异常退出，本次已临时关闭动画", "info"))

    def _reset_split(self) -> None:
        total = max(300, self.splitter.height() - self.splitter.handleWidth())
        top = total // 2
        self.splitter.setSizes([top, total - top])
        self.store.settings["split_ratio"] = 0.5
        self._autosave.start()
        self.toast.show_message("分栏已恢复 50 / 50")

    def _apply_split(self) -> None:
        total = max(300, self.splitter.height() - self.splitter.handleWidth())
        ratio = self.store.settings.get("split_ratio", 0.46)
        try:
            ratio = float(ratio)
        except (TypeError, ValueError):
            ratio = 0.46
        ratio = max(0.22, min(0.78, ratio))
        top = int(total * ratio)
        self.splitter.setSizes([top, total - top])

    def closeEvent(self, e):
        if self._autosave.isActive():
            self._autosave.stop()
        # 关窗前先收掉输入焦点：macOS 上输入法还挂在正在销毁的输入框上时，
        # 退出瞬间容易在 IMK 里硬崩（终端只看到 bus error）。
        try:
            focus = QApplication.focusWidget()
            if focus is not None:
                focus.clearFocus()
        except Exception:             # noqa: BLE001
            pass
        try:
            self.mock.stop_all()      # 本地 Mock 服务不留后台线程
        except Exception:             # noqa: BLE001
            pass
        try:
            self.ws.abort()           # WebSocket 连接不能留成孤儿
        except Exception:             # noqa: BLE001
            pass
        try:
            self.sio.abort()          # Socket.IO 连接同样不能留成孤儿
        except Exception:             # noqa: BLE001
            pass
        # 分析结果只缓存在内存里，关窗即丢弃，不留常驻占用。
        try:
            self._analysis_cache.clear()
        except Exception:             # noqa: BLE001
            pass
        self._persist()
        self._cloud_upload_on_exit()
        self._wait_cloud()
        self.prepare_quit()
        super().closeEvent(e)

    def prepare_quit(self) -> None:
        """退出前把会让 macOS 在析构阶段硬崩的东西先拆掉。

        bus error（终端里只有一行 `zsh: bus error`，crash.log 里是
        「<no Python frame>」）不是 Python 里的异常：它发生在 Cocoa / Qt 的
        收尾路径上。能提前拆干净的有三类 —— 还在跑的动画、挂在控件上的
        图形特效、以及没停的网络对象。拆完之后窗口销毁就只剩纯控件树。
        """
        from PyQt6.QtCore import QVariantAnimation

        try:
            self._autosave.stop()
        except Exception:                 # noqa: BLE001
            pass
        for anim in self.findChildren(QVariantAnimation):
            try:
                anim.stop()
            except RuntimeError:
                pass
        try:
            from PyQt6.QtWidgets import QApplication

            for w in QApplication.allWidgets():
                try:
                    if w.graphicsEffect() is not None:
                        w.setGraphicsEffect(None)
                except RuntimeError:
                    pass
        except Exception:                 # noqa: BLE001
            pass
        try:
            self.mock.stop_all()
        except Exception:                 # noqa: BLE001
            pass
        try:
            self.ws.abort()
        except Exception:                 # noqa: BLE001
            pass
        try:
            self.sio.abort()
        except Exception:                 # noqa: BLE001
            pass

    def _cloud_upload_on_exit(self) -> None:
        """开了「退出时自动上传」就趁关窗把最新快照推上去，最多等 2 秒不拖住退出。"""
        s = self.store.settings
        if not (s.get("cloud_enabled") and s.get("cloud_auto")):
            return
        try:
            from .cloud import client_for

            client = client_for(s)
            text = json.dumps(self.store.data, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            return
        import threading

        def run():
            try:
                client.push(text)
            except Exception:  # noqa: BLE001
                pass

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(2.0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._round_corners()
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast._place()
        if hasattr(self, "palette") and self.palette.isVisible():
            self.palette.setGeometry(self.card_rect())
            self.palette._layout_card()
