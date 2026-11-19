"""Ocelot 品牌标识：站立的豹猫剪影（实心 + 负空间）。

设计意图参照 magpie 那类剪影图标——不是描边，而是**一整块实心**，
再用背景色切出眼睛和腹线，让形体内部分出结构：

* 站姿侧身朝右，尾巴从身后扬起、向左收成一条细弧，是整个形的动势；
* 后腿髋部是一块饱满的圆，前腿细、脚掌圆，前低后高；
* 头贴着肩，脖子不留缝；耳朵两枚尖角，左耳略低于右耳（不刻板对称）；
* 负空间只有两处：腹部一道拱形开口、眼睛一颗圆点。少，但每处都在结构上。

对外四样东西：

* `outline()`     —— 主体填充路径（已挖好腹部与眼睛）；
* `mark_pixmap()` —— 任意尺寸位图，2x 设备像素，Retina 下不糊；
* `app_icon()`    —— Dock 图标，白底 + 近黑剪影；
* `BrandMark`     —— 带「尾巴轻甩 / 睁眼点亮 / 静息呼吸」的控件。

鼠标移上去时不是变色，而是：整枚标识轻轻上浮放大，尾巴绕尾根向上甩
一点再稳住，眼睛那颗负空间里亮起一颗小光点——像猫睁开眼；移开时全部
缓缓收回。大尺寸静息时 7 秒一次极轻的呼吸。
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
from PyQt6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PyQt6.QtWidgets import QWidget

from .theme import C, theme

# ---------------------------------------------------------------- 几何
BOX = 96.0                       # 设计画布
CENTER = 44.6                    # 内容视觉中心（尾巴向左伸，重心因此略偏左）
VIEW_CY = 51.0                   # 纵向重心（耳朵高、脚掌低）
EYE = (73.4, 35.4, 2.05)         # 眼睛（负空间圆点，也是悬浮时的光点位置）
TAIL_PIVOT = (30.0, 55.0)        # 尾巴旋转的支点（埋在身体里，甩尾不露缝）


def _ell(cx: float, cy: float, rx: float, ry: Optional[float] = None) -> QPainterPath:
    p = QPainterPath()
    p.addEllipse(QPointF(cx, cy), rx, ry if ry is not None else rx)
    return p


def _poly(pts) -> QPainterPath:
    p = QPainterPath(QPointF(*pts[0]))
    for x, y in pts[1:]:
        p.lineTo(QPointF(x, y))
    p.closeSubpath()
    return p


def _smooth(pts, t: float = 0.82) -> QPainterPath:
    """闭合 Catmull-Rom → 三次贝塞尔：点集就是轮廓控制点，边线连续不出折角。"""
    n = len(pts)
    p = QPainterPath(QPointF(*pts[0]))

    def g(i):
        return pts[i % n]

    for i in range(n):
        p0, p1, p2, p3 = g(i - 1), g(i), g(i + 1), g(i + 2)
        c1 = (p1[0] + (p2[0] - p0[0]) * t / 6.0, p1[1] + (p2[1] - p0[1]) * t / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) * t / 6.0, p2[1] - (p3[1] - p1[1]) * t / 6.0)
        p.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(*p2))
    p.closeSubpath()
    return p


def _cpts(p0, p1, p2, p3, n: int = 44):
    out = []
    for i in range(n + 1):
        u = i / n
        mu = 1 - u
        out.append((
            mu ** 3 * p0[0] + 3 * mu * mu * u * p1[0] + 3 * mu * u * u * p2[0] + u ** 3 * p3[0],
            mu ** 3 * p0[1] + 3 * mu * mu * u * p1[1] + 3 * mu * u * u * p2[1] + u ** 3 * p3[1],
        ))
    return out


def _band(pts, w0: float, w1: Optional[float] = None) -> QPainterPath:
    """沿点集拉一条带子，宽度从 w0 渐变到 w1（尾巴 / 腿都靠它出锥形）。"""
    w1 = w0 if w1 is None else w1
    n = max(1, len(pts) - 1)
    out = QPainterPath()
    for i in range(n):
        a, b = pts[i], pts[i + 1]
        seg = QPainterPath(QPointF(*a))
        seg.lineTo(QPointF(*b))
        st = QPainterPathStroker()
        st.setWidth(max(0.4, w0 + (w1 - w0) * (i / n)))
        st.setCapStyle(Qt.PenCapStyle.RoundCap)
        st.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        out = out.united(st.createStroke(seg))
    return out


def _limb(pts, w0: float, w1: float, paw) -> QPainterPath:
    return _band(pts, w0, w1).united(_ell(*paw))


@lru_cache(maxsize=1)
def tail_path() -> QPainterPath:
    """尾巴：起点埋在身体内部，向左上扬起，尾尖收得很细。

    单独成一条路径，是为了悬浮时能绕尾根轻甩而不牵动身体。
    """
    return _band(_cpts((35.0, 58.0), (14.0, 51.0), (6.4, 26.0), (21.5, 16.6)),
                 8.4, 2.3)


@lru_cache(maxsize=1)
def outline() -> QPainterPath:
    """主体：身体 + 颈 + 头 + 双耳 + 双腿，挖掉腹部拱口与眼睛。"""
    body = _smooth([(26, 55), (34, 46), (48, 42), (61, 42.5), (67, 53),
                    (66, 64), (56, 70), (40, 70), (28, 64)])
    body = body.united(_ell(35, 58, 10.5, 11.5))          # 后腿髋部
    body = body.subtracted(_ell(50, 73.6, 11.6, 4.8))     # 腹部拱口（唯一的负空间之一）

    head = _ell(68.0, 37.0, 12.0, 11.4)
    ear_l = _poly([(56.8, 31.4), (58.8, 16.4), (67.4, 27.2)])
    ear_r = _poly([(70.2, 26.4), (77.4, 15.2), (79.6, 31.2)])

    leg_f = _limb(_cpts((60, 61), (60.6, 73), (60.0, 83), (59.6, 86)),
                  8.6, 6.4, (59.2, 87.2, 4.6, 3.0))
    leg_h = _limb(_cpts((34, 66), (33.2, 76), (32.8, 83), (32.4, 86)),
                  11.0, 8.0, (32.0, 87.2, 5.2, 3.2))

    path = body.united(head).united(ear_l).united(ear_r).united(leg_f).united(leg_h)
    return path.subtracted(_ell(EYE[0], EYE[1], EYE[2]))


@lru_cache(maxsize=1)
def mark_path() -> QPainterPath:
    """完整标识（主体 + 尾巴），导出 SVG / 生成图标用。"""
    return outline().united(tail_path())


def _alpha(color: QColor, a: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def _clamp(v: float) -> float:
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = _clamp(t)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def _out_back(v: float, s: float = 1.70158) -> float:
    v -= 1.0
    return v * v * ((s + 1) * v + s) + 1.0


def mark_pixmap(size: int, color: QColor | str, opacity: float = 1.0) -> QPixmap:
    """把标识渲染成 size×size 的位图（2x 设备像素，Retina 下不糊）。"""
    size = max(4, int(size))
    ratio = 2
    pm = QPixmap(size * ratio, size * ratio)
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setOpacity(max(0.0, min(1.0, opacity)))
    _paint_mark(p, float(size), C(color), C(color), 0.0, 0.0)
    p.end()
    return pm


def app_icon() -> QIcon:
    """应用图标：白底圆角方块 + 近黑剪影，Dock 里在任何壁纸上都干净。"""
    icon = QIcon()
    ink = QColor("#14141A")
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256, 512, 1024):
        pm = QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(0, 0, size, size).adjusted(size * 0.035, size * 0.035,
                                                 -size * 0.035, -size * 0.035)
        radius = size * 0.225
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(body, radius, radius)
        # 一圈极淡的边：纯白图标放在浅色桌面上也有边界
        p.setPen(QPen(_alpha(QColor("#0A0A0F"), 0.10), max(0.8, size * 0.008)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(body, radius, radius)
        # 剪影落在白底中央，留出呼吸边距
        side = size * 0.86
        p.translate(size / 2, size / 2)
        p.translate(-side / 2, -side / 2)
        _paint_mark(p, side, ink, ink, 0.0, 0.0)
        p.end()
        icon.addPixmap(pm)
    return icon


def _paint_mark(p: QPainter, side: float, base: QColor, hot: QColor,
                t: float, breath: float = 0.0) -> None:
    """在 side×side 的方框里画标识。

    t      —— 悬浮进度（0 安静，1 完全点亮）
    breath —— 静息呼吸（-1..1），只做大尺寸下的极轻微缩放
    """
    if side < 3 or side > 4096:
        return

    t = _clamp(t)
    k = side / BOX
    # 留 6% 边距：放大 / 光晕不会被控件边界切掉
    k *= 0.94 * (1.0 + 0.012 * breath) * (1.0 + 0.035 * t)

    p.save()
    p.translate(side / 2.0, side / 2.0 - side * 0.010 * t)
    p.scale(k, k)
    p.translate(-CENTER, -VIEW_CY)
    p.setPen(Qt.PenStyle.NoPen)

    # 1) 极淡的径向光：只在标识中心附近，不外扩成「发光胶囊」
    if t > 0.02:
        g = QRadialGradient(QPointF(CENTER, VIEW_CY), 54.0)
        g.setColorAt(0.0, _alpha(hot, 0.05 * t))
        g.setColorAt(0.62, _alpha(hot, 0.018 * t))
        g.setColorAt(1.0, _alpha(hot, 0.0))
        p.setBrush(g)
        p.drawEllipse(QPointF(CENTER, VIEW_CY), 54.0, 54.0)

    # 2) 主体：一整块实心
    p.setBrush(base)
    p.drawPath(outline())

    # 3) 尾巴：绕尾根向上甩一点（t 的 1.5 次方，起步更软、收尾更稳）
    swing = 4.0 * (t ** 1.5)
    p.save()
    p.translate(TAIL_PIVOT[0], TAIL_PIVOT[1])
    p.rotate(swing)
    p.translate(-TAIL_PIVOT[0], -TAIL_PIVOT[1])
    p.setBrush(base)
    p.drawPath(tail_path())
    p.restore()

    # 4) 睁眼：负空间里亮起一颗小光点。先一点点冒出来（out-back），再稳住
    if t > 0.02:
        grow = _out_back(_clamp(t * 1.25))
        r = EYE[2] * (0.20 + 0.80 * grow)
        p.setBrush(_mix(base, hot, _clamp(t * 1.6)))
        p.drawEllipse(QPointF(EYE[0], EYE[1]), r, r)

        # 眼睛周围一圈极淡的光，像刚睡醒
        if grow > 0.02:
            eye_glow = QRadialGradient(QPointF(EYE[0], EYE[1]), 8.4)
            eye_glow.setColorAt(0.0, _alpha(hot, 0.22 * t))
            eye_glow.setColorAt(0.45, _alpha(hot, 0.07 * t))
            eye_glow.setColorAt(1.0, _alpha(hot, 0.0))
            p.setBrush(eye_glow)
            p.drawEllipse(QPointF(EYE[0], EYE[1]), 8.4, 8.4)

    p.restore()


# ---------------------------------------------------------------- 控件


class BrandMark(QWidget):
    """带悬浮动画的品牌标识。

    静止：一枚安静的剪影，大尺寸下自己极慢地呼吸（7 秒一个来回）。
    悬浮：整枚上浮 1%、放大 3.5%，尾巴绕尾根向上轻甩，眼睛的负空间里
    亮起一颗小光点——像猫睁开眼；移开时全部缓缓收回，620ms 缓收。
    `autoplay=True` 时首次显示会自己演一遍（欢迎页 / 关于页 / 空状态用）。
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
        self._breath = 0.0
        self._breathe = size >= 40          # 小图标不呼吸，免得像哆嗦
        self.setFixedSize(QSize(size, size))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        if tooltip:
            self.setToolTip(tooltip)

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._on_value)

        # 呼吸：80ms 一跳，只在大尺寸下开，开销可以忽略
        self._btimer = QTimer(self)
        self._btimer.setInterval(80)
        self._btimer.timeout.connect(self._on_breath)

    # -------------------------------------------------- 动画
    def _on_value(self, value) -> None:
        try:
            self._t = float(value)
        except (TypeError, ValueError):
            return
        self.update()

    def _on_breath(self) -> None:
        self._breath += 0.08
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

    def play_once(self, hold: int = 360) -> None:
        """完整演一遍再回到静止状态。慢一点，别赶。"""
        self._run(1.0, 880, QEasingCurve.Type.InOutQuart,
                  then=lambda: QTimer.singleShot(hold, self._settle))

    def _settle(self) -> None:
        self._run(0.0, 640, QEasingCurve.Type.InOutCubic)

    # -------------------------------------------------- 事件
    def enterEvent(self, e):  # noqa: N802
        self._run(1.0, 820, QEasingCurve.Type.InOutQuart)
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._run(0.0, 640, QEasingCurve.Type.InOutCubic)
        super().leaveEvent(e)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if self._breathe and not self._btimer.isActive():
            self._btimer.start()
        if self._autoplay and not self._played:
            self._played = True
            QTimer.singleShot(180, self.play_once)

    def hideEvent(self, e):  # noqa: N802
        self._anim.stop()
        self._btimer.stop()
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
        breath = math.sin(self._breath) if self._breathe else 0.0
        _paint_mark(p, side, base, hot, self._t, breath)
        p.end()
