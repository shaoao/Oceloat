"""主窗口：无边框圆角窗口、交通灯、侧栏、标签、面板分割与全局快捷键。"""
from __future__ import annotations

import json
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
    QPen,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import i18n, icons
from .code_editor import CodeView, human_elapsed
from .dialogs import CodeDialog, CommandPalette, EnvDialog, ImportCurlDialog, SettingsDialog
from .http_client import ApiClient, Response
from .request_panel import RequestEditor
from .response_panel import ResponsePanel
from .sidebar import Sidebar
from .store import Store, kv, new_request, uid
from .tabs import TabStrip
from .anim import running as _anim_running, set_animations, stop as _anim_stop
from .theme import C, S, apply_theme, font, mono, set_accent, theme, theme_by_name
from .widgets import Button, Divider, HBox, Label, Menu, VBox, animate, fade_in, icon_button

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
        self.setFixedHeight(50)
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
        pm = icons.pixmap(self._icon, t.text_dim, 15, 1.6)
        p.drawPixmap(QPointF(16, r.center().y() - 7.5), pm)
        p.setFont(font(12.8, QFont.Weight.Medium))
        p.setPen(C(t.text if self._hover > 0.3 else t.text))
        p.drawText(QRectF(44, r.top() + 8, r.width() - 120, 18),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), i18n.tr(self._title))
        p.setFont(font(10.8))
        p.setPen(C(t.text_faint))
        p.drawText(QRectF(44, r.top() + 26, r.width() - 120, 16),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), i18n.tr(self._subtitle))
        if self._hint:
            fm = QFontMetricsF(mono(10))
            w = fm.horizontalAdvance(self._hint) + 14
            hr = QRectF(r.right() - w - 12, r.center().y() - 9, w, 18)
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

        mark = LogoMark(58)
        holder = HBox(1, mark, 1)
        col.addWidget(holder)
        col.addSpacing(22)
        title = Label(APP_NAME, 27, theme().text, weight=QFont.Weight.Bold, spacing=-0.4)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(title)
        col.addSpacing(7)
        sub = Label("为 macOS 打造的轻量 API 调试工具", 12.5, theme().text_dim)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(sub)
        col.addSpacing(34)

        rows = VBox(spacing=8)
        r1 = ActionRow("plus", "新建请求", "从空白标签页开始", "⌘N")
        r2 = ActionRow("keyboard", "打开命令面板", "搜索请求或快速执行命令", "⌘K")
        r3 = ActionRow("globe", "配置环境变量", "用 {{变量}} 在环境间切换", "⌘E")
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


class LogoMark(QWidget):
    def __init__(self, size: int = 56, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.accent))
        p.drawRoundedRect(r, 16, 16)
        pm = icons.pixmap("send", t.accent_text, 26, 1.9)
        p.drawPixmap(QPointF(r.center().x() - 13, r.center().y() - 13), pm)
        p.end()


# ---------------------------------------------------------------- 主窗口


class MainWindow(QWidget):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.client = ApiClient(self)
        self.client.started.connect(lambda: None)
        self.client.finished.connect(self._on_response)

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
        # 本地 Mock 服务（懒启动）：整个应用一个实例，关窗时统一收掉
        from .mock_server import MockServer

        self.mock = MockServer()
        self._shortcuts: List[QShortcut] = []

        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setMinimumSize(1020, 660)
        self.resize(1320, 840)
        self._margin = 8

        set_animations(bool(store.settings.get("animations", True)))
        CodeView.set_global_size(float(store.settings.get("code_font_size", 11.8)))
        QApplication.instance().setAttribute(
            Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
        from .ctxmenu import install as _install_ctx
        from .tooltip import install as _install_tip

        _install_tip(QApplication.instance())
        _install_ctx(QApplication.instance())
        self._build()
        self._install_shortcuts()
        self._restore_session()
        QTimer.singleShot(400, self._auto_start_mock)
        i18n.set_language(store.settings.get("language", "zh"), notify=False)
        i18n.bus().languageChanged.connect(self._retranslate)
        if i18n.current() == "en":
            i18n.apply_language(self)

    def _retranslate(self, _lang: str) -> None:
        i18n.apply_language(self)
        # 自绘控件的文案不经过 QLabel，逐个刷新
        from .widgets import Button, SegmentedTabs

        for w in self.findChildren(QWidget):
            if isinstance(w, (SegmentedTabs, Button)):
                w.updateGeometry()
                w.update()
            fn = getattr(w, "refresh_theme", None)
            if callable(fn):
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass

    # -------------------------------------------------- 构建
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(self._margin, self._margin, self._margin, self._margin)
        outer.setSpacing(0)

        self.root = QWidget()
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
        self.editor.sendRequested.connect(self.send_current)
        self.editor.cancelRequested.connect(self._abort)
        self.editor.saveRequested.connect(self.save_current)
        self.editor.codeRequested.connect(self.show_code)
        self.editor.copyCurlRequested.connect(self._copy_curl)
        self.editor.deleteRequested.connect(self._delete_current)
        self.editor.urlbar.mockRequested.connect(self.open_mock)
        self.editor.urlbar.duplicateRequested.connect(self._duplicate_request)
        self.response = ResponsePanel()
        self.response.setMinimumHeight(180)
        self.response.requestSaveBody.connect(lambda body, note: self.toast.show_message(
            {"copied": "响应已复制", "redacted": "已脱敏复制（token / Cookie 已打码）"}.get(note, "响应已保存"),
            "success"))
        self.response.saveVariable.connect(self._save_env_var)
        self.response.docRequested.connect(self.open_doc)
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
        self.palette = CommandPalette(self.store, self.root)
        self.palette.execute.connect(self._on_palette_action)
        self._update_stack()
        self.response.show_empty()

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
    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.isMaximized():
            p.fillRect(self.rect(), C(t.window))
            p.end()
            return
        card = QRectF(self.rect()).adjusted(self._margin, self._margin,
                                            -self._margin, -self._margin)
        # 外扩阴影：多层圆角矩形近似
        for i in range(self._margin, 0, -1):
            alpha = int(26 * (1 - (i - 1) / max(1, self._margin)) ** 2)
            c = QColor(0, 0, 0, alpha if t.is_dark else alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(card.adjusted(-i, -i + 1, i, i + 2), 12 + i, 12 + i)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.window))
        p.drawRoundedRect(card, 12, 12)
        p.end()

    def _edge(self, pos: QPoint) -> Qt.Edge:
        m = self._margin + 2
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
        if e.position().y() < 46 + self._margin:
            self.showMaximized() if not self.isMaximized() else self.showNormal()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            self._margin = 0 if self.isMaximized() else 8
            lay = self.layout()
            if lay is not None:
                lay.setContentsMargins(self._margin, self._margin, self._margin, self._margin)
            self.update()
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
        import copy as _copy

        req = _copy.deepcopy(self.editor.request or tab["request"])
        req["id"] = uid()
        req["name"] = (req.get("name") or "Request") + " 副本"
        self._open_request_obj(req, node_id=None)
        self.toast.show_message("已复制为新标签", "success")

    def open_mock(self) -> None:
        """Mock 中心：本地 Mock 服务 + 公开接口清单。"""
        from .mock_panel import MockDialog

        was_running = self.mock.running
        dlg = MockDialog(self.store, self.mock, self)
        dlg.chosen.connect(self._use_mock)
        dlg.trialRequested.connect(self._mock_trial)
        dlg.exec()
        if self.mock.running != was_running:
            self._sync_mock_state()

    def _mock_trial(self, method: str, url: str) -> None:
        """点了某条本地路由的「试用」：建一条指向它的请求，直接发。"""
        req = new_request(f"Mock · {url.rstrip('/').split('/')[-1] or 'root'}", method, url)
        self._open_request_obj(req, node_id=None)
        self.toast.show_message("已连上本地 Mock 路由", "success")
        QTimer.singleShot(80, self.send_current)

    def _sync_mock_state(self) -> None:
        """服务在对话框里启动 / 停止后，标题栏和提示保持同步。"""
        if self.mock.running:
            self.toast.show_message(f"本地 Mock 服务运行在 {self.mock.base}", "success")

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
                import copy as _copy

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
                    t["preview"] = False
                    self.tabstrip.update_tab(t["id"], title=t.get("title"))
                    self.tabstrip.set_current(t["id"])
                    self._on_tab_changed(t["id"])
                    return
        self._open_request_obj(request, node_id=node_id)

    def _open_request_obj(self, request: Dict[str, Any], node_id: Optional[str],
                          preview: bool = False) -> None:
        import copy as _copy

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
                               "preview": preview})
        self._sync_open_ids()
        self._on_tab_changed(tab_id)
        self._update_stack()

    def close_tab(self, tab_id: str) -> None:
        tab = self._tab(tab_id)
        if tab is None:
            return
        if self._inflight_tab == tab_id:
            self._abort()
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
        self._persist()

    def _tab_context_menu(self, tab_id: str, global_pos) -> None:
        """标签栏右键：关闭 / 关闭其他 / 关闭全部 / 复制标签 / 复制为 cURL。"""
        t = theme()
        menu = Menu(self)
        if tab_id:
            a_close = menu.addAction(icons.icon("close", t.text, 13), "关闭")
            a_others = menu.addAction(icons.icon("layers", t.text, 13), "关闭其他")
            a_dup = menu.addAction(icons.icon("copy", t.text, 13), "复制标签")
            a_curl = menu.addAction(icons.icon("code", t.text, 13), "复制为 cURL")
            a_doc = menu.addAction(icons.icon("file", t.text, 13), "查看接口文档…")
            menu.addSeparator()
        else:
            a_close = a_others = a_dup = a_curl = a_doc = None
        a_all = menu.addAction(icons.icon("trash", t.danger, 13), "关闭全部")
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is a_close and tab_id:
            self.close_tab(tab_id)
        elif chosen is a_others and tab_id:
            for other in [x["id"] for x in self.tabs_data if x["id"] != tab_id]:
                self.close_tab(other)
        elif chosen is a_dup and tab_id:
            self._duplicate_tab(tab_id)
        elif chosen is a_curl and tab_id:
            self._copy_tab_as_curl(tab_id)
        elif chosen is a_doc and tab_id:
            self.open_doc(tab_id)
        elif chosen is a_all:
            for other in [x["id"] for x in self.tabs_data]:
                self.close_tab(other)

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
        import copy as _copy

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
        try:
            self.editor.load(tab["request"])
            if tab.get("response") is not None:
                self.response.set_response(tab["response"])
                self._refresh_timeline(tab["request"])
                self.response.restore_state(tab.get("view"))
            else:
                self.response.show_empty()
                self.response.restore_state(tab.get("view"))
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
            import copy as _copy

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
        # 请求一改，上一次响应就作废：绝不让旧图片 / 旧地址留在结果区误导用户。
        had_response = tab.get("response") is not None or self.response.response is not None
        tab["response"] = None
        tab["view"] = None
        if had_response:
            self.response.show_stale()
        # 用户一旦编辑预览标签就把它固定下来（VSCode 行为）
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
                    self.tabstrip.update_tab(tab["id"], title=tab["title"],
                                             method=node.get("method", "GET"))
        self.env_pill.updateGeometry()
        self.env_pill.update()

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
        if self.client.busy:
            self._abort()
            return
        tab = self.current_tab()
        if tab is None:
            return
        req = tab["request"]
        if not (req.get("url") or "").strip():
            self.toast.show_message("请先填写请求地址", "error")
            self.editor.focus_url()
            return
        self._inflight_tab = tab["id"]
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
        self.client.abort()

    def _on_response(self, resp: Response) -> None:
        tab_id = self._inflight_tab
        self._inflight_tab = None
        self.editor.set_busy(False)
        tab = self._tab(tab_id) if tab_id else self.current_tab()
        if tab is not None:
            tab["response"] = resp
            tab["view"] = self.response.view_state() if tab_id == self.tabstrip.current() else None
            self.store.push_history(tab["request"], resp.status, resp.elapsed)
            self.sidebar.refresh_history()
            self._autosave.start()       # 落盘合并到 700ms，避免每条响应都同步写 100KB
        if tab_id is None or tab_id == self.tabstrip.current():
            self.response.set_response(resp)
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
            import copy as _copy

            tab["request"] = _copy.deepcopy(node)
            self.sidebar.refresh()
            self._sync_open_ids()
        self.store.save()
        tab["dirty"] = False
        self.tabstrip.update_tab(tab["id"], dirty=False)
        self.toast.show_message("已保存到集合", "success")

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
        self.toast.show_message(f"已保存变量 {{{{{name}}}}}", "success")

    def _persist(self) -> None:
        self.store.settings["sidebar_width"] = self._sidebar_target
        sizes = self.splitter.sizes()
        if sizes and sum(sizes) > 200:
            self.store.settings["split_ratio"] = round(sizes[0] / sum(sizes), 4)
        self.store.data["open_tabs"] = [t["node_id"] for t in self.tabs_data if t.get("node_id")]
        self.store.save()

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
        dlg.exec()

    def _reload_data(self) -> None:
        """从云端恢复后整份数据都换了：标签全部关掉，侧栏与主题重新刷一遍。"""
        for tab in list(self.tabs_data):
            self.close_tab(tab["id"])
        self.sidebar.refresh()
        self.sidebar.refresh_history()
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
        from .importer import import_collection

        path, _ = QFileDialog.getOpenFileName(self, "导入集合", "", "JSON (*.json);;所有文件 (*)")
        if not path:
            return
        count, err = import_collection(self.store, path)
        if err:
            self.toast.show_message(err, "error")
            return
        self.sidebar.refresh()
        self.toast.show_message(f"已导入 {count} 个集合节点", "success")

    def export_collection(self) -> None:
        from .importer import export_collection

        path, _ = QFileDialog.getSaveFileName(self, "导出集合", "ocelot-collection.json",
                                              "JSON (*.json)")
        if not path:
            return
        try:
            count = export_collection(self.store, path)
            self.toast.show_message(f"已导出 {count} 个集合", "success")
        except Exception as exc:
            self.toast.show_message(f"导出失败：{exc}", "error")

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

        def _open(req: Dict[str, Any]) -> None:
            picked.append(req)
            dlg.accept()

        dlg.openRequested.connect(_open)
        dlg.exec()
        if picked:
            self._open_request_obj(picked[0], node_id=picked[0].get("id"))

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
        elif key == "new_folder":
            self.sidebar._new_folder()
            self.toast.show_message("已新建文件夹", "success")
        elif key == "send":
            self.send_current()
        elif key == "save":
            self.save_current()
        elif key == "env":
            self.show_envs()
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
        """上次开着本地 Mock 就顺手拉起来，失败也不打扰（端口可能被占）。"""
        cfg = self.store.data.get("mock") or {}
        if not cfg.get("auto_start"):
            return
        ok, _msg = self.mock.start(cfg.get("routes") or [], cfg.get("port") or 8787,
                                   bool(cfg.get("fallback_echo")))
        if ok:
            self.toast.show_message(f"本地 Mock 服务已在 {self.mock.base} 运行", "success")

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
                    self._open_request_obj(node, node_id=node_id)
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
        fade_in(self.root, 180)
        if not getattr(self, "_split_applied", False):
            self._split_applied = True
            QTimer.singleShot(0, self._apply_split)

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
        try:
            self.mock.stop()          # 本地 Mock 服务不留后台线程
        except Exception:             # noqa: BLE001
            pass
        self._persist()
        self._cloud_upload_on_exit()
        super().closeEvent(e)

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
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast._place()
        if hasattr(self, "palette") and self.palette.isVisible():
            self.palette.setGeometry(self.rect())
            self.palette._layout_card()
