"""模态对话框的背景遮罩：把主窗口内容抓成一张图，做真模糊 + 压暗，铺满整窗。

为什么不用 QGraphicsBlurEffect 直接挂在控件上：这个项目在 macOS 上被
QGraphics*Effect 坑过一次（渲染层 SIGBUS）。这里只在「抓下来的静态图片」上
做纯 QImage 运算，既不影响控件树，也不会在合成阶段引入额外图层。

做法：先把整窗缩到很小（1/12），在缩略图上做两遍盒式模糊，再用平滑插值放回
原尺寸。视觉上就是高斯模糊，成本只有几毫秒。
"""
from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtCore import QEasingCurve, QEvent, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

from .anim import animations_on, stop as _anim_stop
from .theme import C, theme

# 缩略图最长边：越小越糊、越快
_SMALL_MAX = 128
_BLUR_PASSES = 2
_BLUR_RADIUS = 1


def _shrink(img: QImage) -> QImage:
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        return img
    scale = min(1.0, _SMALL_MAX / max(w, h))
    return img.scaled(max(1, int(w * scale)), max(1, int(h * scale)),
                      Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


def _box_blur(img: QImage, radius: int, passes: int) -> QImage:
    """在缩略图上做盒式模糊（两遍 ≈ 高斯）。纯 Python 但图很小，几毫秒。"""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    if w < 3 or h < 3:
        return img
    buf = img.bits()
    buf.setsize(img.sizeInBytes())
    data = bytearray(buf)
    stride = img.bytesPerLine()
    for _ in range(passes):
        # 横向
        out = bytearray(data)
        for y in range(h):
            row = y * stride
            for x in range(w):
                r = g = b = a = n = 0
                for dx in range(-radius, radius + 1):
                    sx = x + dx
                    if 0 <= sx < w:
                        i = row + sx * 4
                        b += data[i]; g += data[i + 1]; r += data[i + 2]; a += data[i + 3]
                        n += 1
                i = row + x * 4
                out[i] = b // n; out[i + 1] = g // n
                out[i + 2] = r // n; out[i + 3] = a // n
        data = out
        # 纵向
        out = bytearray(data)
        for y in range(h):
            for x in range(w):
                b = g = r = a = n = 0
                for dy in range(-radius, radius + 1):
                    sy = y + dy
                    if 0 <= sy < h:
                        i = sy * stride + x * 4
                        b += data[i]; g += data[i + 1]; r += data[i + 2]; a += data[i + 3]
                        n += 1
                i = y * stride + x * 4
                out[i] = b // n; out[i + 1] = g // n
                out[i + 2] = r // n; out[i + 3] = a // n
        data = out
    result = QImage(data, w, h, stride, QImage.Format.Format_ARGB32)
    return result.copy()


def _qt_blur(pix: QPixmap, radius: float) -> QPixmap:
    """用 Qt 自带的模糊效果渲染一张静态图。

    注意：QGraphicsBlurEffect 只作用在离屏的 QGraphicsPixmapItem 上，
    渲染结果直接画进 QImage，**不挂到任何活控件**——这是本项目的红线，
    macOS 上给控件树挂 QGraphicsEffect 会触发渲染层崩溃。
    """
    from PyQt6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene

    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(pix)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    out = QImage(pix.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    scene.render(painter, QRectF(out.rect()), QRectF(pix.rect()))
    painter.end()
    return QPixmap.fromImage(out)


def blur_pixmap(source: QPixmap) -> QPixmap:
    """把一张窗口截图变成模糊底图（半步长渲染 + 平滑放大，够快也够干净）。"""
    if source.isNull():
        return source
    w, h = max(1, source.width() // 2), max(1, source.height() // 2)
    half = source.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    try:
        blurred = _qt_blur(half, 9.0)
    except Exception:      # noqa: BLE001  极端情况下退回纯 Python 小图模糊
        blurred = QPixmap.fromImage(_box_blur(_shrink(source.toImage()),
                                              _BLUR_RADIUS, _BLUR_PASSES))
    return blurred.scaled(source.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)


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
    def capture(self) -> None:
        """抓主窗口当前画面（抓的时候先把自己藏起来，免得把上层的模糊图再糊一遍）。"""
        was_visible = self.isVisible()
        if was_visible:
            self.setVisible(False)
        try:
            self._pix = blur_pixmap(self.host.grab())
        except Exception:      # noqa: BLE001  抓图失败就只压暗，不影响可用性
            self._pix = QPixmap()
        finally:
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
        if self.parentWidget() is not None:
            self.setGeometry(self.parentWidget().rect())

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
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        alpha = max(0.0, min(1.0, self._alpha))
        if not self._pix.isNull():
            p.setOpacity(alpha)
            p.drawPixmap(self.rect(), self._pix)
            p.setOpacity(1.0)
        # 压暗：深色主题用窗口色加暗；浅色主题用一点黑，否则整个背景会发白糊成一片
        if t.is_dark:
            scrim = QColor(C(t.window))
            scrim.setAlpha(int(118 * alpha))
        else:
            scrim = QColor(0, 0, 0)
            scrim.setAlpha(int(46 * alpha))
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
    if not backdrop.isVisible():
        backdrop.sync_geometry()
        backdrop.capture()
        backdrop._alpha = 0.0
        backdrop.raise_()
        backdrop.show()
        backdrop.fade_to(1.0, 160)
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
