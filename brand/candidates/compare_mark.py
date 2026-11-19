import sys
sys.path.insert(0, '/Users/shaoao/WorkBuddy/spaces/2026_11_16_16-41-16/reqly')
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import (QPixmap, QPainter, QColor, QFont, QPen, QPainterPath)
from PyQt6.QtCore import Qt, QRectF, QPointF

app = QApplication([])
from app import brand

F = ".AppleSystemUIFont"


def f(sz, w=400):
    fo = QFont(F)
    fo.setPixelSize(sz)
    fo.setWeight(QFont.Weight(w))
    return fo


# 旧版（v1.0.59，preview 那一版）的轮廓，原样抄过来做对比
old = QPainterPath(QPointF(48.0, 84.2))
for c in [
    ((42.2, 85.0), (37.6, 82.8), (33.6, 79.7)),
    ((28.3, 76.3), (21.2, 68.0), (21.2, 57.0)),
    ((21.2, 48.6), (21.8, 43.4), (22.6, 39.6)),
    ((22.0, 33.0), (22.4, 24.0), (23.0, 17.0)),
    ((26.0, 24.0), (32.0, 30.0), (41.5, 30.2)),
    ((42.5, 30.3), (45.0, 31.2), (48.0, 30.0)),
    ((51.0, 31.2), (53.5, 30.3), (54.5, 30.2)),
    ((64.0, 30.0), (70.0, 24.0), (73.0, 17.0)),
    ((73.6, 24.0), (74.0, 33.0), (73.4, 39.6)),
    ((74.2, 43.4), (74.8, 48.6), (74.8, 57.0)),
    ((74.8, 68.0), (67.7, 76.3), (62.4, 79.7)),
    ((58.4, 82.8), (53.8, 85.0), (48.0, 84.2)),
]:
    old.cubicTo(*c[0], *c[1], *c[2])
old.closeSubpath()

W, H = 700, 560
cv = QPixmap(W * 2, H * 2)
cv.setDevicePixelRatio(2)
cv.fill(QColor("#FBFBFD"))
p = QPainter(cv)
p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

p.setFont(f(15, 600))
p.setPen(QColor("#17171C"))
p.drawText(QRectF(28, 18, 500, 24), Qt.AlignmentFlag.AlignLeft,
           "Ocelot 标识 · 优化对照")
p.setFont(f(11))
p.setPen(QColor("#8A8A94"))
p.drawText(QRectF(28, 42, 640, 18), Qt.AlignmentFlag.AlignLeft,
           "左：原来的版本（preview 那版）　右：这一版（额顶无折角、下颌圆弧收口、最宽点在眼睛高度、线宽 4%）")


def draw(path, x, y, side, stroke_ratio, color):
    k = side / 96.0 * 0.94
    pen = QPen(QColor(color), side * stroke_ratio * 0.88 / k)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.save()
    p.translate(x + side / 2.0, y + side / 2.0)
    p.scale(k, k)
    p.translate(-48.0, -50.8)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    for (dx, dy, r) in brand.DOTS:
        p.drawEllipse(QPointF(dx, dy), r, r)
    p.restore()


# 大图对照
draw(old, 40, 80, 260, 0.045, "#17171C")
draw(brand.outline(), 380, 80, 260, 0.040, "#17171C")
p.setFont(f(10))
p.setPen(QColor("#A6A6B0"))
p.drawText(QRectF(40, 348, 260, 16), Qt.AlignmentFlag.AlignCenter, "v1.0.59（原）")
p.drawText(QRectF(380, 348, 260, 16), Qt.AlignmentFlag.AlignCenter, "v1.0.61（现在）")

# 真实尺寸行
p.setFont(f(10))
p.setPen(QColor("#8A8A94"))
p.drawText(QRectF(40, 378, 400, 16), Qt.AlignmentFlag.AlignLeft,
           "同一枚标识在真实尺寸下的观感")
x = 100
for s in (16, 21, 24, 32, 44, 64):
    draw(old, x, 404 + (64 - s) / 2, s, 0.045, "#9A9AA2")
    draw(brand.outline(), x, 492 + (64 - s) / 2, s, 0.040, "#17171C")
    p.setPen(QColor("#B0B0BA"))
    p.drawText(QRectF(x, 472, 60, 12), Qt.AlignmentFlag.AlignLeft, str(s))
    x += s + 34

p.setFont(f(11))
p.setPen(QColor("#8A8A94"))
p.drawText(QRectF(40, 424, 60, 16), Qt.AlignmentFlag.AlignLeft, "原")
p.drawText(QRectF(40, 512, 60, 16), Qt.AlignmentFlag.AlignLeft, "今")

p.end()
cv.save('/tmp/mark_compare.png')
print('ok')
