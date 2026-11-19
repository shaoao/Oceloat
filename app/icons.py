"""自绘矢量图标集。

所有图标在 24x24 的坐标系内以描边方式绘制，输出带 Retina 缩放的 QPixmap，
保证在任何 DPI 下都锐利，且颜色与主题完全一致（不使用系统 emoji）。
"""
from __future__ import annotations

from typing import Callable, Dict

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPixmapCache,
    QPolygonF,
)

CAP = Qt.PenCapStyle.RoundCap
JOIN = Qt.PenJoinStyle.RoundJoin


def _line(p: QPainter, *pts: float) -> None:
    """把一串坐标连成一条折线（2 点即直线，3 点即折角，如 chevron / check）。

    注意：不连续的线段请分多次调用，否则会被连成一笔。
    """
    if len(pts) < 4:
        return
    path = QPainterPath(QPointF(pts[0], pts[1]))
    for i in range(2, len(pts) - 1, 2):
        path.lineTo(QPointF(pts[i], pts[i + 1]))
    p.drawPath(path)


def _plus(p):
    _line(p, 12, 5.5, 12, 18.5)
    _line(p, 5.5, 12, 18.5, 12)


def _minus(p):
    _line(p, 5.5, 12, 18.5, 12)


def _close(p):
    _line(p, 6.5, 6.5, 17.5, 17.5)
    _line(p, 17.5, 6.5, 6.5, 17.5)


def _search(p):
    p.drawEllipse(QRectF(4.2, 4.2, 11.6, 11.6))
    _line(p, 15.5, 15.5, 20, 20)


def _chevron_right(p):
    _line(p, 9.5, 5.5, 15.5, 12, 9.5, 18.5)


def _chevron_left(p):
    _line(p, 14.5, 5.5, 8.5, 12, 14.5, 18.5)


def _chevron_down(p):
    _line(p, 5.5, 9.5, 12, 15.5, 18.5, 9.5)


def _chevron_up(p):
    _line(p, 5.5, 14.5, 12, 8.5, 18.5, 14.5)


def _folder(p):
    path = QPainterPath()
    path.moveTo(3.2, 7.4)
    path.quadTo(3.2, 5.4, 5.2, 5.4)
    path.lineTo(9.0, 5.4)
    path.lineTo(10.9, 7.6)
    path.lineTo(18.8, 7.6)
    path.quadTo(20.8, 7.6, 20.8, 9.6)
    path.lineTo(20.8, 16.6)
    path.quadTo(20.8, 18.6, 18.8, 18.6)
    path.lineTo(5.2, 18.6)
    path.quadTo(3.2, 18.6, 3.2, 16.6)
    path.closeSubpath()
    p.drawPath(path)


def _trash(p):
    _line(p, 4, 6.8, 20, 6.8)
    _line(p, 9.2, 6.8, 9.2, 4.6, 14.8, 4.6, 14.8, 6.8)
    path = QPainterPath()
    path.moveTo(6.4, 8.4)
    path.lineTo(7.3, 19.2)
    path.quadTo(7.4, 20, 8.2, 20)
    path.lineTo(15.8, 20)
    path.quadTo(16.6, 20, 16.7, 19.2)
    path.lineTo(17.6, 8.4)
    p.drawPath(path)
    _line(p, 10.4, 11, 10.4, 17)
    _line(p, 13.6, 11, 13.6, 17)


def _copy(p):
    p.drawRoundedRect(QRectF(8.6, 8.6, 11.6, 11.6), 2.6, 2.6)
    path = QPainterPath()
    path.moveTo(15.4, 8.6)
    path.lineTo(15.4, 5.8)
    path.quadTo(15.4, 4.2, 13.8, 4.2)
    path.lineTo(5.8, 4.2)
    path.quadTo(4.2, 4.2, 4.2, 5.8)
    path.lineTo(4.2, 13.8)
    path.quadTo(4.2, 15.4, 5.8, 15.4)
    path.lineTo(8.6, 15.4)
    p.drawPath(path)


def _download(p):
    _line(p, 12, 4, 12, 15)
    _line(p, 7.8, 10.8, 12, 15, 16.2, 10.8)
    _line(p, 4.6, 19.4, 19.4, 19.4)


def _gear(p):
    """齿轮：外圈 + 8 个齿 + 中心孔。

    之前是「小圆 + 长放射线」，远看像太阳；齿短而粗、圈大一点才读得出是齿轮。
    """
    import math

    col = p.pen().color()
    width = p.pen().widthF()
    # 齿是实心小方块贴着外圈，才像齿轮；细线放射状永远像太阳
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(col))
    for i in range(8):
        p.save()
        p.translate(12, 12)
        p.rotate(i * 45)
        p.drawRoundedRect(QRectF(-1.45, -9.5, 2.9, 4.2), 0.75, 0.75)
        p.restore()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(col, width))
    p.drawEllipse(QRectF(12 - 6.35, 12 - 6.35, 12.7, 12.7))


def _code(p):
    _line(p, 8.8, 7.8, 4.4, 12, 8.8, 16.2)
    _line(p, 15.2, 7.8, 19.6, 12, 15.2, 16.2)


def _send(p):
    _line(p, 5.5, 18.5, 18.2, 5.8)
    _line(p, 9.2, 5.8, 18.2, 5.8, 18.2, 14.8)


def _clock(p):
    p.drawEllipse(QRectF(3.8, 3.8, 16.4, 16.4))
    _line(p, 12, 7.6, 12, 12.4, 15.6, 14.4)


def _more_h(p):
    for x in (6.4, 12, 17.6):
        p.drawEllipse(QRectF(x - 1.15, 10.85, 2.3, 2.3))


def _check(p):
    _line(p, 4.6, 12.4, 9.8, 17.4, 19.6, 6.8)


def _layers(p):
    path = QPainterPath()
    path.moveTo(12, 3.6)
    path.lineTo(20.4, 8.0)
    path.lineTo(12, 12.4)
    path.lineTo(3.6, 8.0)
    path.closeSubpath()
    p.drawPath(path)
    _line(p, 3.6, 12.4, 12, 16.8, 20.4, 12.4)
    _line(p, 3.6, 16.4, 12, 20.8, 20.4, 16.4)


def _sliders(p):
    _line(p, 3.6, 8.2, 20.4, 8.2)
    _line(p, 3.6, 15.8, 20.4, 15.8)
    p.setBrush(p.pen().color())
    p.drawEllipse(QRectF(7.4, 6.2, 4.0, 4.0))
    p.drawEllipse(QRectF(12.6, 13.8, 4.0, 4.0))
    p.setBrush(Qt.BrushStyle.NoBrush)


def _globe(p):
    p.drawEllipse(QRectF(3.6, 3.6, 16.8, 16.8))
    p.drawEllipse(QRectF(8.4, 3.6, 7.2, 16.8))
    _line(p, 3.6, 12, 20.4, 12)


def _lock(p):
    p.drawRoundedRect(QRectF(5.2, 10.6, 13.6, 9.6), 2.4, 2.4)
    path = QPainterPath()
    path.moveTo(8.4, 10.6)
    path.lineTo(8.4, 8.2)
    path.quadTo(8.4, 4.6, 12, 4.6)
    path.quadTo(15.6, 4.6, 15.6, 8.2)
    path.lineTo(15.6, 10.6)
    p.drawPath(path)


def _file(p):
    path = QPainterPath()
    path.moveTo(6.0, 3.4)
    path.lineTo(13.6, 3.4)
    path.lineTo(18.4, 8.2)
    path.lineTo(18.4, 20.0)
    path.quadTo(18.4, 20.6, 17.8, 20.6)
    path.lineTo(6.0, 20.6)
    path.quadTo(5.4, 20.6, 5.4, 20.0)
    path.lineTo(5.4, 4.0)
    path.quadTo(5.4, 3.4, 6.0, 3.4)
    path.closeSubpath()
    p.drawPath(path)
    _line(p, 13.4, 3.6, 13.4, 8.4, 18.2, 8.4)


def _table(p):
    p.drawRoundedRect(QRectF(3.8, 4.6, 16.4, 14.8), 2.2, 2.2)
    _line(p, 3.8, 9.4, 20.2, 9.4)
    _line(p, 3.8, 14.2, 20.2, 14.2)
    _line(p, 9.6, 4.6, 9.6, 19.4)


def _pencil(p):
    _line(p, 4.4, 19.6, 5.2, 15.4, 15.6, 5.0, 19.0, 8.4, 8.6, 18.8, 4.4, 19.6)


def _keyboard(p):
    p.drawRoundedRect(QRectF(2.8, 7.0, 18.4, 10.0), 2.2, 2.2)
    _line(p, 8.4, 14.0, 15.6, 14.0)
    for x in (6.2, 9.0, 11.8, 14.6, 17.4):
        p.drawEllipse(QRectF(x - 0.5, 9.9, 1.0, 1.0))


def _book(p):
    path = QPainterPath()
    path.moveTo(4.2, 5.0)
    path.quadTo(8.4, 3.8, 12, 6.0)
    path.quadTo(15.6, 3.8, 19.8, 5.0)
    path.lineTo(19.8, 18.4)
    path.quadTo(15.6, 17.2, 12, 19.4)
    path.quadTo(8.4, 17.2, 4.2, 18.4)
    path.closeSubpath()
    p.drawPath(path)
    _line(p, 12, 6.2, 12, 19.2)


def _dot(p):
    p.setBrush(p.pen().color())
    p.drawEllipse(QRectF(9.0, 9.0, 6.0, 6.0))


def _play(p):
    p.setBrush(p.pen().color())
    poly = QPolygonF([QPointF(9.0, 6.2), QPointF(18.0, 12.0), QPointF(9.0, 17.8)])
    p.drawPolygon(poly)


def _alert(p):
    """警告三角：圆角三角 + 竖杠 + 点，用作控制台里的 warn / error 图标。"""
    path = QPainterPath()
    path.moveTo(12, 4.4)
    path.lineTo(20.4, 19.0)
    path.quadTo(20.8, 19.9, 19.7, 19.9)
    path.lineTo(4.3, 19.9)
    path.quadTo(3.2, 19.9, 3.6, 19.0)
    path.closeSubpath()
    p.drawPath(path)
    _line(p, 12, 9.6, 12, 14.4)
    p.setBrush(p.pen().color())
    p.drawEllipse(QRectF(11.1, 16.2, 1.8, 1.8))


def _stop(p):
    p.setBrush(p.pen().color())
    p.drawRoundedRect(QRectF(7.4, 7.4, 9.2, 9.2), 1.8, 1.8)


def _refresh(p):
    path = QPainterPath()
    path.arcMoveTo(QRectF(4.2, 4.2, 15.6, 15.6), 60)
    path.arcTo(QRectF(4.2, 4.2, 15.6, 15.6), 60, 280)
    p.drawPath(path)
    _line(p, 17.4, 3.6, 17.4, 8.2, 12.8, 8.2)


def _moon(p):
    path = QPainterPath()
    path.moveTo(19.0, 14.6)
    path.quadTo(11.4, 16.6, 9.4, 5.0)
    path.quadTo(4.6, 7.4, 5.2, 12.2)
    path.quadTo(6.2, 19.2, 13.4, 19.2)
    path.quadTo(17.0, 19.2, 19.0, 14.6)
    p.drawPath(path)


def _grid(p):
    p.drawRoundedRect(QRectF(3.8, 3.8, 7.0, 7.0), 1.8, 1.8)
    p.drawRoundedRect(QRectF(13.2, 3.8, 7.0, 7.0), 1.8, 1.8)
    p.drawRoundedRect(QRectF(3.8, 13.2, 7.0, 7.0), 1.8, 1.8)
    p.drawRoundedRect(QRectF(13.2, 13.2, 7.0, 7.0), 1.8, 1.8)


def _broom(p):
    _line(p, 14.6, 3.6, 10.2, 12.4)
    path = QPainterPath()
    path.moveTo(10.6, 11.4)
    path.lineTo(4.4, 16.4)
    path.lineTo(7.0, 20.4)
    path.lineTo(13.6, 15.2)
    path.closeSubpath()
    p.drawPath(path)
    _line(p, 5.6, 17.6, 8.4, 19.2)


def _link(p):
    """链条：两个斜置的圆角环（先移到画布中心再旋转，否则会转出画布）。"""
    p.save()
    p.translate(12.0, 12.0)
    p.rotate(-45)
    p.drawRoundedRect(QRectF(-8.4, -3.1, 7.6, 6.2), 3.0, 3.0)
    p.drawRoundedRect(QRectF(0.8, -3.1, 7.6, 6.2), 3.0, 3.0)
    p.restore()
    _line(p, 9.8, 14.2, 14.2, 9.8)


def _external(p):
    _line(p, 13.4, 4.6, 19.4, 4.6, 19.4, 10.6)
    _line(p, 19.0, 5.0, 11.6, 12.4)
    path = QPainterPath()
    path.moveTo(17.4, 14.0)
    path.lineTo(17.4, 18.4)
    path.quadTo(17.4, 19.6, 16.2, 19.6)
    path.lineTo(5.6, 19.6)
    path.quadTo(4.4, 19.6, 4.4, 18.4)
    path.lineTo(4.4, 7.8)
    path.quadTo(4.4, 6.6, 5.6, 6.6)
    path.lineTo(10.0, 6.6)
    p.drawPath(path)


def _undo(p):
    _line(p, 9.0, 14.2, 4.0, 9.0)
    _line(p, 4.0, 9.0, 9.0, 3.8)
    path = QPainterPath(QPointF(4.0, 9.0))
    path.lineTo(14.6, 9.0)
    path.arcTo(QRectF(9.1, 9.0, 11.0, 11.0), 90, -180)
    path.lineTo(11.6, 20.0)
    p.drawPath(path)


def _redo(p):
    _line(p, 15.0, 14.2, 20.0, 9.0)
    _line(p, 20.0, 9.0, 15.0, 3.8)
    path = QPainterPath(QPointF(20.0, 9.0))
    path.lineTo(9.4, 9.0)
    path.arcTo(QRectF(3.9, 9.0, 11.0, 11.0), 90, 180)
    path.lineTo(12.4, 20.0)
    p.drawPath(path)


def _cut(p):
    _line(p, 7.6, 17.2, 17.0, 5.6)
    _line(p, 16.4, 17.2, 7.0, 5.6)
    p.drawEllipse(QPointF(6.2, 19.0), 2.4, 2.4)
    p.drawEllipse(QPointF(17.8, 19.0), 2.4, 2.4)


def _paste(p):
    path = QPainterPath()
    path.moveTo(9.2, 5.0)
    path.lineTo(7.0, 5.0)
    path.quadTo(5.4, 5.0, 5.4, 6.6)
    path.lineTo(5.4, 18.8)
    path.quadTo(5.4, 20.4, 7.0, 20.4)
    path.lineTo(17.0, 20.4)
    path.quadTo(18.6, 20.4, 18.6, 18.8)
    path.lineTo(18.6, 6.6)
    path.quadTo(18.6, 5.0, 17.0, 5.0)
    path.lineTo(14.8, 5.0)
    p.drawPath(path)
    tab = QPainterPath()
    tab.addRoundedRect(QRectF(8.8, 3.0, 6.4, 4.2), 1.4, 1.4)
    p.drawPath(tab)


def _panel_left(p):
    path = QPainterPath()
    path.addRoundedRect(QRectF(3.4, 4.6, 17.2, 14.8), 3.2, 3.2)
    p.drawPath(path)
    # 左侧一块实心，表示「侧栏已展开」
    from PyQt6.QtGui import QBrush

    p.save()
    p.setBrush(QBrush(p.pen().color()))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(4.6, 5.8, 5.6, 12.4), 1.8, 1.8)
    p.restore()


def _image(p):
    path = QPainterPath()
    path.addRoundedRect(QRectF(3.4, 5.0, 17.2, 14.0), 2.6, 2.6)
    p.drawPath(path)
    p.drawEllipse(QPointF(8.6, 9.6), 1.5, 1.5)
    _line(p, 4.6, 17.2, 9.8, 12.2)
    _line(p, 9.8, 12.2, 13.4, 15.6)
    _line(p, 13.4, 15.6, 15.6, 13.4)
    _line(p, 15.6, 13.4, 19.4, 17.0)


def _audio(p):
    path = QPainterPath()
    path.moveTo(5.0, 14.6)
    path.lineTo(5.0, 9.4)
    path.quadTo(5.0, 8.2, 6.2, 8.2)
    path.lineTo(11.6, 4.6)
    path.quadTo(13.0, 3.8, 13.0, 5.4)
    path.lineTo(13.0, 18.6)
    path.quadTo(13.0, 20.2, 11.6, 19.4)
    path.lineTo(6.2, 15.8)
    path.quadTo(5.0, 15.8, 5.0, 14.6)
    p.drawPath(path)
    _line(p, 16.4, 8.6, 16.4, 15.4)
    _line(p, 19.2, 6.6, 19.2, 17.4)


def _node(p):
    p.drawEllipse(QPointF(12.0, 6.0), 2.6, 2.6)
    p.drawEllipse(QPointF(6.2, 18.0), 2.6, 2.6)
    p.drawEllipse(QPointF(17.8, 18.0), 2.6, 2.6)
    _line(p, 12.0, 8.6, 12.0, 12.4)
    _line(p, 6.2, 15.4, 6.2, 12.4, 17.8, 12.4)
    _line(p, 17.8, 12.4, 17.8, 15.4)


def _cloud(p):
    """云：左下小圆弧 + 上方两个大圆弧，收在一条水平底边上。"""
    path = QPainterPath()
    path.moveTo(7.0, 18.2)
    path.quadTo(3.4, 18.2, 3.4, 15.2)
    path.quadTo(3.4, 12.6, 6.0, 12.2)
    path.quadTo(6.4, 7.6, 10.6, 7.6)
    path.quadTo(14.2, 7.6, 15.2, 10.8)
    path.quadTo(17.2, 10.4, 18.4, 11.8)
    path.quadTo(20.6, 13.2, 20.6, 15.4)
    path.quadTo(20.6, 18.2, 17.4, 18.2)
    path.closeSubpath()
    p.drawPath(path)


def _transfer(p):
    """导入 / 导出：一进一出两支箭头（上箭头往右进、下箭头往左出）。"""
    _line(p, 4.6, 8.6, 16.4, 8.6)
    _line(p, 13.2, 5.4, 16.4, 8.6, 13.2, 11.8)
    _line(p, 19.4, 15.4, 7.6, 15.4)
    _line(p, 10.8, 12.2, 7.6, 15.4, 10.8, 18.6)


def _sync(p):
    """两个首尾相接的弧 + 箭头，读作「同步」。"""
    path = QPainterPath()
    path.arcMoveTo(QRectF(4.4, 4.4, 15.2, 15.2), 40)
    path.arcTo(QRectF(4.4, 4.4, 15.2, 15.2), 40, 140)
    p.drawPath(path)
    path2 = QPainterPath()
    path2.arcMoveTo(QRectF(4.4, 4.4, 15.2, 15.2), 220)
    path2.arcTo(QRectF(4.4, 4.4, 15.2, 15.2), 220, 140)
    p.drawPath(path2)
    _line(p, 15.6, 3.6, 17.0, 6.4, 14.0, 7.0)
    _line(p, 8.4, 20.4, 7.0, 17.6, 10.0, 17.0)


def _spark(p):
    """四角星：读作「AI / 一键增强」。"""
    path = QPainterPath()
    path.moveTo(12, 3.2)
    path.cubicTo(13.3, 8.4, 15.6, 10.7, 20.8, 12)
    path.cubicTo(15.6, 13.3, 13.3, 15.6, 12, 20.8)
    path.cubicTo(10.7, 15.6, 8.4, 13.3, 3.2, 12)
    path.cubicTo(8.4, 10.7, 10.7, 8.4, 12, 3.2)
    p.drawPath(path)


ICONS: Dict[str, Callable[[QPainter], None]] = {
    "plus": _plus, "minus": _minus, "close": _close, "search": _search,
    "chevron_right": _chevron_right, "chevron_down": _chevron_down, "chevron_up": _chevron_up,
    "chevron_left": _chevron_left,
    "folder": _folder, "trash": _trash, "copy": _copy, "download": _download,
    "gear": _gear, "code": _code, "send": _send, "clock": _clock, "more": _more_h,
    "check": _check, "layers": _layers, "globe": _globe, "lock": _lock, "file": _file,
    "table": _table, "pencil": _pencil, "sliders": _sliders, "keyboard": _keyboard, "book": _book,
    "dot": _dot, "play": _play, "stop": _stop, "refresh": _refresh, "moon": _moon,
    "grid": _grid, "broom": _broom, "external": _external,
    "alert": _alert, "transfer": _transfer, "link": _link,
    "undo": _undo, "redo": _redo, "cut": _cut, "paste": _paste,
    "panel_left": _panel_left, "image": _image, "audio": _audio, "node": _node,
    "cloud": _cloud, "sync": _sync, "spark": _spark,
}

_cache: Dict[tuple, QIcon] = {}


def icon(name: str, color: str = "#ECECEF", size: int = 16, width: float = 1.6) -> QIcon:
    key = (name, color, size, width)
    if key in _cache:
        return _cache[key]
    ic = QIcon(pixmap(name, color, size, width))
    _cache[key] = ic
    return ic


_pm_cache: Dict[tuple, QPixmap] = {}


def draw_centered(p: QPainter, pm: QPixmap, cx: float, cy: float) -> None:
    """把带 devicePixelRatio 的 pixmap 按**逻辑尺寸**居中画到 (cx, cy)。

    坑：PyQt6 的 QPixmap.width() 返回设备像素（dpr=2 时是逻辑值的两倍），
    直接写 `cx - pm.width() / 2` 会让图标整体偏左上 (dpr-1)/2*size 个逻辑像素，
    深色主题下所有自绘图标都会集体偏离中心（用户截图里图标挤在盒子左上角）。
    这里必须用 devicePixelRatio 折算回逻辑尺寸再居中。
    """
    dpr = pm.devicePixelRatio() or 1.0
    w = pm.width() / dpr
    h = pm.height() / dpr
    p.drawPixmap(QPointF(cx - w / 2, cy - h / 2), pm)


def pixmap(name: str, color: str = "#ECECEF", size: int = 16, width: float = 1.6,
           dpr: float = 2.0) -> QPixmap:
    """按逻辑尺寸 size 返回带 dpr 的位图，drawPixmap(QPointF, pm) 即为逻辑尺寸。"""
    key = (name, color, size, width, dpr)
    if key in _pm_cache:
        return _pm_cache[key]
    fn = ICONS.get(name, _dot)
    pm = QPixmap(int(round(size * dpr)), int(round(size * dpr)))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(size * dpr / 24.0, size * dpr / 24.0)
    pen = QPen(QColor(color))
    pen.setWidthF(width * 24.0 / size)
    pen.setCapStyle(CAP)
    pen.setJoinStyle(JOIN)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    try:
        fn(p)
    except Exception:
        pass
    p.end()
    pm.setDevicePixelRatio(dpr)
    _pm_cache[key] = pm
    return pm


def clear_cache() -> int:
    """清空图标缓存，返回被丢弃的条目数。

    图标都是按需重建的：清掉之后下一次绘制会重新生成，界面不会出现空白，
    但这一批 QPixmap 立刻变成可回收对象。资源管理器里的「释放内存」用它。
    """
    n = len(_cache) + len(_pm_cache)
    _cache.clear()
    _pm_cache.clear()
    QPixmapCache.clear()
    return n
