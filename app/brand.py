"""Ocelot 品牌标识：豹猫头线条标。

几何与 `brand/ocelot-mark.svg` 完全一致（96 单位画布、5 单位描边、无五官、
左脸大斑 + 下颌小斑），这里用 QPainterPath 重新构建，好处是：

* 任意尺寸矢量渲染，不依赖 QtSvg，也不吃位图内存；
* 颜色跟着主题走（深色下偏白、浅色下偏黑），切换主题不用换资源；
* 可以在标题栏 / 关于页做「描边沿着轮廓自己画一遍」的悬浮动画。

对外三样东西：`mark_pixmap()` 出位图、`app_icon()` 出 QIcon、
`BrandMark` 是带悬浮动画的控件。
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from .theme import C, theme

# ---------------------------------------------------------------- 几何
BOX = 96.0                      # 设计画布
CX, CY, R = 48.0, 52.0, 27.0    # 脸部圆：圆心、半径
EAR_L, EAR_R = (23.0, 11.0), (73.0, 11.0)
CROWN_L, CROWN_R = (38.77, 26.63), (57.23, 26.63)
CHEEK_L, CHEEK_R = (28.58, 33.24), (67.42, 33.24)
DOTS = ((40.0, 45.0, 3.6), (55.5, 58.0, 2.5))
STROKE = 5.0                    # 描边宽度（画布单位）
VIEW_CY = 45.0                  # 内容视觉中心（耳朵比下颌高，重心偏上）


@lru_cache(maxsize=1)
def outline() -> QPainterPath:
    """头部轮廓：额顶浅弧 → 双耳 → 脸颊 → 下颌，一笔闭合。"""
    face = QRectF(CX - R, CY - R, 2 * R, 2 * R)
    path = QPainterPath(QPointF(*CHEEK_L))
    path.lineTo(*EAR_L)                 # 左耳外沿
    path.lineTo(*CROWN_L)               # 左耳内沿
    path.arcTo(face, 110.0, -40.0)      # 额顶浅弧，落到右耳内侧
    path.lineTo(*EAR_R)                 # 右耳尖
    path.lineTo(*CHEEK_R)               # 右耳内沿
    path.arcTo(face, 44.0, -134.0)      # 右脸 → 下颌
    path.arcTo(face, -90.0, -134.0)     # 下颌 → 左脸，回到起点
    path.closeSubpath()
    return path


def mark_pixmap(size: int, color: QColor | str, stroke_min: float = 1.15) -> QPixmap:
    """把标识渲染成 size×size 的位图（2x 设备像素，Retina 下不糊）。"""
    size = max(4, int(size))
    ratio = 2
    pm = QPixmap(size * ratio, size * ratio)
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _paint_mark(p, float(size), C(color), C(color), 0.0, 0.0, 1.0, stroke_min)
    p.end()
    return pm


def app_icon() -> QIcon:
    """应用图标：Dock / 任务栏用。深色底上画浅色线，浅色底上画深色线。"""
    icon = QIcon()
    light = QColor("#F2F2F5")
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256, 512):
        bg = QPixmap(size * 2, size * 2)
        bg.setDevicePixelRatio(2)
        bg.fill(Qt.GlobalColor.transparent)
        p = QPainter(bg)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        # 圆角方块底：深色主题下用近黑，浅色主题下用近白
        body = QColor("#17171A")
        p.setBrush(body)
        r = QRectF(0, 0, size, size).adjusted(size * 0.04, size * 0.04,
                                              -size * 0.04, -size * 0.04)
        p.drawRoundedRect(r, size * 0.24, size * 0.24)
        p.translate(size / 2, size / 2)
        p.scale(0.78, 0.78)
        p.translate(-size / 2, -size / 2)
        _paint_mark(p, float(size), light, light, 1.0, 0.0, 1.0, 0.9)
        p.end()
        icon.addPixmap(bg)
    return icon


def _paint_mark(p: QPainter, side: float, base: QColor, hot: QColor,
                t: float, rotate: float, scale: float,
                stroke_min: float = 1.15) -> None:
    """在 side×side 的方框里画标识。t=悬浮进度（0 静止，1 完全点亮）。"""
    if side < 3 or side > 4096:
        return
    # 内容比画布窄（左右各留 20 单位），按内容高度铺满，避免小尺寸下图太小
    k = side / BOX * 1.12
    width = STROKE / max(k, 1e-6)
    if width * k < stroke_min:
        width = stroke_min / k

    p.save()
    p.translate(side / 2.0, side / 2.0)
    if rotate:
        p.rotate(rotate)
    p.scale(k * scale, k * scale)
    p.translate(-CX, -VIEW_CY)

    pen = QPen(base, width * (0.92 + 0.08 * t))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    path = outline()

    # 底下一层：静止时就是它，淡淡的、安静的一条线
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)

    # 悬浮层：同样的路径，用虚线偏移把描边「重新画一遍」，颜色更亮
    if t > 0.002:
        progress = min(1.0, t / 0.78)
        length = max(path.length(), 1.0)
        glow = QPen(hot, width * 1.16)
        glow.setCapStyle(Qt.PenCapStyle.RoundCap)
        glow.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        glow.setDashPattern([length, length])
        glow.setDashOffset(length * (1.0 - progress))
        p.setPen(glow)
        p.setOpacity(min(1.0, 0.35 + 0.65 * progress))
        p.drawPath(path)
        p.setOpacity(1.0)

    # 两块斑：静止时安静地待着，悬浮时带一点回弹地弹出来
    min_dot = 0.95 / max(k, 1e-6)          # 小尺寸下别把斑缩没了
    for cx, cy, r in DOTS:
        grow = 1.0 + 0.24 * _out_back(_clamp((t - 0.28) / 0.55))
        radius = max(r * (0.88 + 0.12 * t) * grow, min_dot)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(hot if t > 0.5 else base)
        p.drawEllipse(QPointF(cx, cy), radius, radius)
    p.restore()


def _clamp(v: float) -> float:
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def _out_back(v: float, s: float = 1.70158) -> float:
    v -= 1.0
    return v * v * ((s + 1) * v + s) + 1.0


# ---------------------------------------------------------------- 控件


class BrandMark(QWidget):
    """带悬浮动画的品牌标识。

    静止：一条安静的线条标。鼠标悬浮：轮廓沿起点到终点重新点亮一遍，
    整体轻轻上浮放大，两块斑带回弹弹出；移开再原路收回去。
    `autoplay=True` 时首次显示会自己完整演一遍（关于页用）。
    """

    def __init__(self, size: int = 20, parent: Optional[QWidget] = None,
                 token: str = "text_dim", hover_token: str = "text",
                 autoplay: bool = False, tooltip: str = ""):
        super().__init__(parent)
        self._token = token
        self._hover_token = hover_token
        self._autoplay = autoplay
        self._played = False
        self._t = 0.0
        self.setFixedSize(QSize(size, size))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        if tooltip:
            self.setToolTip(tooltip)

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._on_value)

    # -------------------------------------------------- 动画
    def _on_value(self, value) -> None:
        try:
            self._t = float(value)
        except (TypeError, ValueError):
            return
        self.update()

    def _run(self, target: float, duration: int,
             easing: QEasingCurve.Type = QEasingCurve.Type.OutCubic,
             then=None) -> None:
        self._anim.stop()
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.setDuration(int(duration))
        self._anim.setEasingCurve(easing)
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(float(target))
        if then is not None:
            self._anim.finished.connect(then)
        self._anim.start()

    def play_once(self, hold: int = 160) -> None:
        """完整演一遍再回到静止状态。"""
        self._run(1.0, 560, QEasingCurve.Type.OutCubic,
                  then=lambda: QTimer.singleShot(hold, self._settle))

    def _settle(self) -> None:
        self._run(0.0, 420, QEasingCurve.Type.InOutCubic)

    # -------------------------------------------------- 事件
    def enterEvent(self, e):  # noqa: N802
        self._run(1.0, 560, QEasingCurve.Type.OutCubic)
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._run(0.0, 340, QEasingCurve.Type.InOutCubic)
        super().leaveEvent(e)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if self._autoplay and not self._played:
            self._played = True
            QTimer.singleShot(140, self.play_once)

    def hideEvent(self, e):  # noqa: N802
        self._anim.stop()
        self._t = 0.0
        super().hideEvent(e)

    # -------------------------------------------------- 绘制
    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        base = C(getattr(t, self._token, t.text_dim))
        hot = C(getattr(t, self._hover_token, t.text))
        side = float(min(self.width(), self.height()))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ease = self._t
        scale = 1.0 + 0.075 * math.sin(math.pi * ease)
        rotate = -7.0 * math.sin(math.pi * ease)
        _paint_mark(p, side, base, hot, ease, rotate, scale)
        p.end()
