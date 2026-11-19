"""Ocelot 品牌标识：豹猫头线条标（精修版）。

设计意图是「一笔细线」：96 单位画布上只用一条 ~4 单位的线勾出头部，
尖耳、圆颊、窄下颌，脸里落两小块斑（左颊大、下颌小，刻意不对称，
避免读成一张脸）。线一定要细——细才有呼吸感，粗了就成了剪影。

几何上有三处必须成立，这是这版重点修的东西：

* **额顶不能有折角**：两段耳内沿在额顶都取水平切线，曲线一阶连续，
  整条额线是一条顺下来的弧，而不是「两个三角夹一个平台」；
* **下颌不能是平底**：底盘收窄、用一段真正的圆弧收口，脸才不会读成杯子；
* **侧壁不能直**：最宽点落在眼睛高度，往下收、往上也收一点点，
  耳根处只有极轻的一次转折，不能收成「肩」。

对外四样东西：

* `outline()`     —— 轮廓路径（闭合，一笔）；
* `mark_pixmap()` —— 任意尺寸位图，2x 设备像素，Retina 下不糊；
* `app_icon()`    —— Dock 图标，白底 + 深色线条；
* `BrandMark`     —— 带「墨线描出 / 萤火绕行 / 静息呼吸」的控件。

鼠标移上去时不是简单变个色，而是：一条亮线从下颌左侧出发，沿着轮廓
一路把整条线重新「写」一遍，笔尖是一颗小小的萤火，写完后萤火淡去、
线条稳稳停在最亮的状态，整枚标识轻轻上浮，周围浮起一层极淡的光。
移开时这条墨线再原路收回去（不是淡出，是「收笔」）。
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
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QWidget

from .theme import C, theme

# ---------------------------------------------------------------- 几何
BOX = 96.0                       # 设计画布
CENTER = 48.0                    # 画布横轴中心
STROKE_PX = 0.040                # 描边 ≈ 尺寸的 4%（细线，小尺寸靠下限兜底）
MIN_STROKE_PX = 1.05             # 小尺寸兜底，别细到消失
DOTS = ((38.0, 48.2, 2.40), (54.8, 62.6, 1.70))   # 左颊大斑 / 下颌小斑
DOT_U = (0.76, 0.10)             # 两块斑在轮廓（按长度）上的位置，墨线走到才亮
VIEW_CY = 50.8                   # 内容视觉中心（耳朵高，重心略偏上）


@lru_cache(maxsize=1)
def outline() -> QPainterPath:
    """头部轮廓：下颌中 → 右颊 → 右耳 → 额顶 → 左耳 → 左颊 → 回到下颌。

    全部三次贝塞尔、左右严格镜像。三条硬要求：
    * 额头两耳之间**没有折角**——两段内沿在额顶的切线都取水平；
    * 耳朵外沿从耳根向上**微微内收**，到尖部收得住，不读成兔子耳；
    * 下颌是一整段圆 U，底部不能出现方角。
    """
    path = QPainterPath(QPointF(48.0, 84.6))
    # 下颌底 → 右下
    path.cubicTo(54.6, 84.8, 62.0, 82.6, 67.0, 78.2)
    # 右下 → 右颊最宽（眼睛高度）
    path.cubicTo(72.4, 73.6, 75.6, 64.8, 75.6, 55.0)
    # 脸颊 → 右耳尖：一条连续外沿，中间不留节点
    path.cubicTo(75.6, 44.6, 74.8, 31.6, 74.0, 16.0)
    # 耳尖 → 额顶（内凹弧，收尾切线水平，与另一半无缝相接）
    path.cubicTo(68.0, 23.2, 55.4, 30.4, 48.0, 30.4)
    # 额顶 → 左耳尖（严格镜像）
    path.cubicTo(40.6, 30.4, 28.0, 23.2, 22.0, 16.0)
    # 左耳尖 → 左颊最宽
    path.cubicTo(21.2, 31.6, 20.4, 44.6, 20.4, 55.0)
    # 左颊 → 左下
    path.cubicTo(20.4, 64.8, 23.6, 73.6, 29.0, 78.2)
    path.cubicTo(34.0, 82.6, 41.4, 84.8, 48.0, 84.6)
    path.closeSubpath()
    return path


def _stroke_px(side: float) -> float:
    """线宽跟着尺寸走：大图细、小图略加，但整体永远偏细。"""
    return max(MIN_STROKE_PX, side * STROKE_PX)


def _alpha(color: QColor, a: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


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
    """应用图标：白底圆角方块 + 近黑细线，Dock 里在任何壁纸上都干净。"""
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
        edge = QPen(_alpha(QColor("#0A0A0F"), 0.10), max(0.8, size * 0.008))
        p.setPen(edge)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(body, radius, radius)
        # 线条落在白底中央，留出 ~17% 的呼吸边距（再小 Dock 里就显空）
        side = size * 0.83
        p.translate(size / 2, size / 2 + size * 0.005)
        p.translate(-side / 2, -side / 2)
        _paint_mark(p, side, ink, ink, 0.0, 0.0)
        p.end()
        icon.addPixmap(pm)
    return icon


def _paint_mark(p: QPainter, side: float, base: QColor, hot: QColor,
                t: float, breath: float = 0.0) -> None:
    """在 side×side 的方框里画标识。

    t       —— 悬浮进度（0 安静，1 完全点亮并收笔完成）
    breath  —— 静息呼吸（-1..1），只做大尺寸下的极轻微缩放
    """
    if side < 3 or side > 4096:
        return

    k = side / BOX
    # 留 6% 边距：缩放 / 光晕不会被控件边界切掉（之前动画被「盖住」就是这个）
    k *= 0.94 * (1.0 + 0.012 * breath) * (1.0 + 0.045 * t)

    p.save()
    p.translate(side / 2.0, side / 2.0 - side * 0.012 * t)
    p.scale(k, k)
    p.translate(-CENTER, -VIEW_CY)

    width_px = _stroke_px(side)
    # 深色线条落在浅底上会显胖，光学上要收一点，白底图标也靠这条
    if base.lightnessF() < 0.5:
        width_px *= 0.88
    width = width_px / max(k, 1e-6)
    path = outline()

    # 1) 光晕：悬浮时笔尖周围浮起一层极淡的白（深色）/ 黑（浅色），
    #    只在中心附近，不外扩成「发光胶囊」，保持克制
    if t > 0.02:
        g = QRadialGradient(QPointF(CENTER, VIEW_CY), 52.0)
        g.setColorAt(0.0, _alpha(hot, 0.055 * t))
        g.setColorAt(0.62, _alpha(hot, 0.02 * t))
        g.setColorAt(1.0, _alpha(hot, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(CENTER, VIEW_CY), 52.0, 52.0)
        p.setBrush(Qt.BrushStyle.NoBrush)

    # 2) 底下的安静细线
    base_pen = QPen(base, width)
    base_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    base_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(base_pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)

    # 3) 墨线：用虚线偏移把整条轮廓从起点写到终点；笔尖是一颗萤火
    if t > 0.004:
        length = max(path.length(), 1.0)
        progress = min(1.0, t / 0.80)
        ink = QPen(_alpha(hot, 0.55 + 0.45 * min(1.0, t / 0.55)), width * 1.04)
        ink.setCapStyle(Qt.PenCapStyle.RoundCap)
        ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        # 注意：Qt 的虚线长度/偏移都以「笔宽」为单位，所以要先除以 width，
        # 否则整条线会被一次点亮（之前动画「看不见在动」就是这个坑）
        units = length / max(width, 1e-6)
        ink.setDashPattern([units, units])
        ink.setDashOffset(units * (1.0 - progress))
        p.setPen(ink)
        p.drawPath(path)

        # 笔尖萤火：走到哪亮到哪，写完就淡掉，不留一个多余的圆点
        if progress < 0.985:
            tip = path.pointAtPercent(max(0.0, min(1.0, progress)))
            fade = math.sin(math.pi * min(1.0, progress)) ** 0.5
            r = max(0.9, width_px * 0.60)

            # 笔尖后面留三点尾迹：书写才有「划过纸面」的速度感
            p.setPen(Qt.PenStyle.NoPen)
            for back, a, s in ((0.016, 0.20, 0.62), (0.034, 0.11, 0.46),
                               (0.056, 0.05, 0.32)):
                q = path.pointAtPercent(max(0.0, progress - back))
                p.setBrush(_alpha(hot, a * fade))
                p.drawEllipse(q, r * s, r * s)

            halo = QRadialGradient(tip, r * 3.2)
            halo.setColorAt(0.0, _alpha(hot, 0.26 * fade))
            halo.setColorAt(0.45, _alpha(hot, 0.10 * fade))
            halo.setColorAt(1.0, _alpha(hot, 0.0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawEllipse(tip, r * 3.2, r * 3.2)
            p.setBrush(hot)
            p.drawEllipse(tip, r, r)

    # 4) 两块斑：墨线走到哪、哪块斑就晕开——不是一起亮，而是一个个被点到
    progress = min(1.0, t / 0.80)
    min_dot = 0.95 / max(k, 1e-6)
    for (cx, cy, r), u in zip(DOTS, DOT_U):
        local = _clamp((progress - u) / 0.16)
        bloom = _out_back(local)
        radius = max(r * (1.0 + 0.26 * bloom), min_dot)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_mix(base, hot, local))
        p.setOpacity(0.45 + 0.55 * max(local, 0.0))
        p.drawEllipse(QPointF(cx, cy), radius, radius)
        p.setOpacity(1.0)

        # 被点到的一瞬，斑点周围晕开一团柔光（不描圈，免得读成眼镜）
        if 0.0 < local < 1.0:
            g = QRadialGradient(QPointF(cx, cy), radius * 2.6)
            g.setColorAt(0.0, _alpha(hot, 0.13 * math.sin(math.pi * local)))
            g.setColorAt(1.0, _alpha(hot, 0.0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(QPointF(cx, cy), radius * 2.6, radius * 2.6)

    p.restore()


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = _clamp(t)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def _clamp(v: float) -> float:
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def _out_back(v: float, s: float = 1.40158) -> float:
    v -= 1.0
    return v * v * ((s + 1) * v + s) + 1.0


# ---------------------------------------------------------------- 控件


class BrandMark(QWidget):
    """带悬浮动画的品牌标识。

    静止：一条安静的细线标，大尺寸下自己极慢地呼吸（7 秒一个来回）。
    悬浮：亮线从下颌出发，沿轮廓把整条线重写一遍，笔尖带萤火；整枚标识
    上浮 1.2%、放大 4.5%，写完萤火淡去，停在最亮的状态。
    移开：墨线原路收回到起点，620ms 缓收，不闪不跳。
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

    def play_once(self, hold: int = 320) -> None:
        """完整演一遍再回到静止状态。慢一点，别赶。"""
        self._run(1.0, 900, QEasingCurve.Type.InOutQuart,
                  then=lambda: QTimer.singleShot(hold, self._settle))

    def _settle(self) -> None:
        self._run(0.0, 620, QEasingCurve.Type.InOutCubic)

    # -------------------------------------------------- 事件
    def enterEvent(self, e):  # noqa: N802
        # 写完不要死盯着最大放大倍数：缓一口气，落到 0.88 —— 线仍是亮的，
        # 但整枚标识退回一点点，看起来像「刚写完、松了手」而不是被定格
        self._run(1.0, 860, QEasingCurve.Type.InOutQuart,
                  then=lambda: self._run(0.88, 540, QEasingCurve.Type.OutCubic))
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._run(0.0, 620, QEasingCurve.Type.InOutCubic)
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
