"""模态对话框的背景遮罩：把主窗口内容抓成一张图，做真模糊 + 压暗，铺满整窗。

为什么不用 QGraphicsBlurEffect 直接挂在控件上：这个项目在 macOS 上被
QGraphics*Effect 坑过一次（渲染层 SIGBUS）。这里只在「抓下来的静态图片」上
做纯 QImage 缩放运算，既不影响控件树，也不会在合成阶段引入额外图层。

模糊算法：把整窗两级降采样到很小的缩略图（每级都是平滑插值 = 多次盒式平均），
再逐级放回原尺寸。这样得到的模糊在整张图上完全均匀（不会像 Qt 模糊效果那样
在外边缘衰减、也不会因为 scene 边界把图偏移几个像素），而且只要几毫秒、
峰值内存也就几百 KB。
"""
from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtCore import QEasingCurve, QEvent, QRect, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QWidget

from .anim import animations_on, stop as _anim_stop
from .theme import C, theme

# 缩略图最长边：越小越糊、越快（120 ≈ 视觉上 8~10px 半径的高斯，还能看出布局轮廓）
_SMALL_MAX = 120


def _smooth_scale(pix: QPixmap, w: int, h: int) -> QPixmap:
    return pix.scaled(max(1, w), max(1, h), Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


def blur_pixmap(source: QPixmap) -> QPixmap:
    """把一张窗口截图变成模糊底图：两级降采样 + 两级还原，均匀且极快。"""
    if source.isNull():
        return source
    w, h = source.width(), source.height()
    if w < 4 or h < 4:
        return source
    scale = _SMALL_MAX / max(w, h)
    small = _smooth_scale(source, int(w * scale), int(h * scale))
    tiny = _smooth_scale(small, small.width() // 2, small.height() // 2)
    mid = _smooth_scale(tiny, small.width(), small.height())
    return _smooth_scale(mid, w, h)


class Backdrop(QWidget):
    """铺在主窗口上的模糊遮罩；点它不会穿透到下面的控件。"""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.host = host
        self._pix = QPixmap()
        self._alpha = 0.0
        self._anim: Optional[QVariantAnimation] = None
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        host.installEventFilter(self)
        self.hide()

    # -------------------------------------------------- 截图
    def card_rect(self) -> QRect:
        """遮罩应该铺的那块区域：宿主窗口真正的「卡片」范围。

        主窗口是无边框 + 透明背景，四周留了 8px 用来画阴影、圆角 12 —— 如果遮罩
        直接铺满 `host.rect()`，模糊就会盖到阴影上、四个角还是直角，看起来「没对齐
        窗口」。这里问宿主要素一张卡片矩形。
        """
        host = self.host
        fn = getattr(host, "card_rect", None)
        if callable(fn):
            try:
                r = fn()
                if isinstance(r, QRect) and not r.isEmpty():
                    return r
            except Exception:      # noqa: BLE001  宿主没实现好就当整窗
                pass
        return host.rect()

    def card_radius(self) -> float:
        host = self.host
        fn = getattr(host, "card_radius", None)
        if callable(fn):
            try:
                return max(0.0, float(fn()))
            except Exception:      # noqa: BLE001
                pass
        return 0.0

    def capture(self) -> None:
        """抓主窗口当前画面（抓的时候先把自己藏起来，免得把上层的模糊图再糊一遍）。"""
        was_visible = self.isVisible()
        if was_visible:
            self.setVisible(False)
        # 浮层（命令面板）是主窗口的子控件，抓图时会把它们一起拍进去 ——
        # 那背景上就会出现一块面板的鬼影。带 backdropSuppress 标记的临时藏一下。
        hidden = []
        for child in self.host.findChildren(QWidget):
            if child is self or not child.isVisible():
                continue
            if child.property("backdropSuppress"):
                child.setVisible(False)
                hidden.append(child)
        try:
            shot = self.host.grab()
            card = self.card_rect()
            dpr = shot.devicePixelRatio() or 1.0
            if card != self.host.rect():
                # 只取卡片那一块：阴影 / 透明边不参与模糊，边缘才不会脏
                shot = shot.copy(int(card.x() * dpr), int(card.y() * dpr),
                                 max(1, int(card.width() * dpr)),
                                 max(1, int(card.height() * dpr)))
                shot.setDevicePixelRatio(dpr)
            self._pix = blur_pixmap(shot)
        except Exception:      # noqa: BLE001  抓图失败就只压暗，不影响可用性
            self._pix = QPixmap()
        finally:
            for child in hidden:
                child.setVisible(True)
                child.raise_()
            if was_visible:
                self.setVisible(True)
                self.raise_()

    def refresh_theme(self) -> None:
        """主题 / 语言切换时重抓一次，否则遮罩还留着上一套配色。"""
        if self.isVisible():
            self.capture()
            self.update()

    def eventFilter(self, obj, ev):      # noqa: N802
        if obj is self.host and ev.type() == QEvent.Type.Resize and self.isVisible():
            self.sync_geometry()
            self.capture()
            self.update()
        return super().eventFilter(obj, ev)

    def sync_geometry(self) -> None:
        self.setGeometry(self.card_rect())

    # -------------------------------------------------- 显隐
    def fade_to(self, target: float, dur: int = 150, then=None) -> None:
        if not animations_on():
            self._alpha = target
            self.update()
            if then is not None:
                then()
            return
        _anim_stop(self._anim)
        anim = QVariantAnimation(self)
        anim.setStartValue(float(self._alpha))
        anim.setEndValue(float(target))
        anim.setDuration(dur)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _on(value):
            self._alpha = float(value)
            self.update()

        anim.valueChanged.connect(_on)
        if then is not None:
            anim.finished.connect(lambda: then())
        self._anim = anim
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        alpha = max(0.0, min(1.0, self._alpha))
        # 按窗口卡片的圆角裁一刀：模糊图是矩形，不裁的话四个角会露出直角，
        # 跟窗口的弧线对不上（用户看到的就是「模糊没对齐窗口」）。
        path = QPainterPath()
        radius = self.card_radius()
        if radius > 0.5:
            path.addRoundedRect(QRectF(self.rect()), radius, radius)
            p.setClipPath(path)
        if not self._pix.isNull():
            p.setOpacity(alpha)
            p.drawPixmap(self.rect(), self._pix)
            p.setOpacity(1.0)
        # 压暗：深色主题用窗口色加暗；浅色主题用一点黑，否则整个背景会发白糊成一片
        if t.is_dark:
            scrim = QColor(C(t.window))
            scrim.setAlpha(int(92 * alpha))
        else:
            scrim = QColor(0, 0, 0)
            scrim.setAlpha(int(68 * alpha))
        p.fillRect(self.rect(), scrim)
        p.end()

    def mousePressEvent(self, e):      # noqa: N802
        # 吃掉点击：遮罩是模态的延伸，不该把事件传给下面的控件
        e.accept()

    def mouseReleaseEvent(self, e):    # noqa: N802
        e.accept()

    def wheelEvent(self, e):           # noqa: N802
        e.accept()


# ---------------------------------------------------------------- 生命周期

_BY_HOST: Dict[int, Backdrop] = {}
_DEPTH: Dict[int, int] = {}


def _host_of(dialog) -> Optional[QWidget]:
    parent = dialog.parentWidget()
    while parent is not None and not parent.isWindow():
        parent = parent.parentWidget()
    return parent or dialog.parentWidget()


def acquire(dialog) -> Optional[Backdrop]:
    """对话框显示时调用：给它的宿主窗口铺一层模糊遮罩。"""
    host = _host_of(dialog)
    if host is None:
        return None
    key = id(host)
    backdrop = _BY_HOST.get(key)
    if backdrop is None:
        backdrop = Backdrop(host)
        _BY_HOST[key] = backdrop
    _DEPTH[key] = _DEPTH.get(key, 0) + 1
    # 上一次关闭的淡出可能还在飞：它的 finished 回调会把遮罩藏起来，
    # 于是「刚铺上又消失」。这里先掐掉，再重新淡入。
    _anim_stop(backdrop._anim)
    if not backdrop.isVisible():
        backdrop.sync_geometry()
        backdrop.capture()
        backdrop._alpha = 0.0
        backdrop.raise_()
        backdrop.show()
        backdrop.fade_to(1.0, 160)
    else:
        backdrop.sync_geometry()
        backdrop.raise_()
        backdrop.fade_to(1.0, 120)
    return backdrop


def release(dialog) -> None:
    """对话框关闭时调用：最后一个小伙伴走了才撤遮罩。"""
    host = _host_of(dialog)
    if host is None:
        return
    key = id(host)
    depth = max(0, _DEPTH.get(key, 1) - 1)
    _DEPTH[key] = depth
    if depth:
        return
    backdrop = _BY_HOST.get(key)
    if backdrop is None:
        return
    backdrop.fade_to(0.0, 130, then=backdrop.hide)


def refresh_all() -> None:
    """主题 / 语言变了，正在显示的那层遮罩也要跟着重抓。"""
    for key, backdrop in list(_BY_HOST.items()):
        if backdrop.isVisible():
            backdrop.capture()
            backdrop.update()


def resync_all() -> None:
    """窗口尺寸 / 状态变了（最大化、全屏、还原）：先把遮罩重新对齐到卡片，
    再重抓底图。事件过滤器只盯 Resize，最大化本身有时只发 WindowStateChange，
    漏掉之后遮罩就停在旧尺寸，边上露出一条半透明的线。"""
    for key, backdrop in list(_BY_HOST.items()):
        backdrop.sync_geometry()
        if backdrop.isVisible():
            backdrop.capture()
            backdrop.update()
