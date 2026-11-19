"""六款线条标识候选，渲染成对照图（深色 / 浅色 / 真实尺寸）。

用法：
    QT_QPA_PLATFORM=offscreen python3 brand/candidates/build_candidates.py

选定后把对应的几何写进 app/brand.py，再跑 brand/build_brand.py 导出 SVG。
"""
import sys, os, math
sys.path.insert(0, '/Users/shaoao/WorkBuddy/spaces/2026_11_16_16-41-16/reqly')
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import (QPixmap, QPainter, QColor, QPainterPath, QPen, QFont)
from PyQt6.QtCore import QPointF, QRect, QRectF, Qt

app = QApplication([])
HERE = os.path.dirname(os.path.abspath(__file__))


def paint(p, P, size, color, dots=(), solid=False, wratio=0.048):
    k = size / 96.0
    p.save()
    p.scale(k, k)
    w = max(1.0, size * wratio)
    if QColor(color).lightnessF() < 0.5:
        w *= 0.90   # 深线落浅底显胖，光学校细
    w = w / k
    pen = QPen(QColor(color), w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QColor(color) if solid else Qt.BrushStyle.NoBrush)
    p.drawPath(P)
    if dots:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        for cx, cy, r in dots:
            p.drawEllipse(QPointF(cx, cy), max(r, 1.3 / k), max(r, 1.3 / k))
    p.restore()


def lens(cx, cy, rw, rh, blun=0.0):
    P = QPainterPath(QPointF(cx, cy - rh))
    P.cubicTo(cx + rw, cy - rh * 0.5 + blun, cx + rw, cy + rh * 0.5 - blun, cx, cy + rh)
    P.cubicTo(cx - rw, cy + rh * 0.5 - blun, cx - rw, cy - rh * 0.5 + blun, cx, cy - rh)
    P.closeSubpath()
    return P


def almond(w=64.0, top=26.0, bot=62.0):
    cx, cy = 48.0, (top + bot) / 2
    L, R = cx - w / 2, cx + w / 2
    h = bot - top
    P = QPainterPath(QPointF(L, cy))
    P.cubicTo(L + w * 0.15, top + h * 0.10, L + w * 0.34, top, cx, top)
    P.cubicTo(R - w * 0.34, top, R - w * 0.15, top + h * 0.10, R, cy)
    P.cubicTo(R - w * 0.13, bot - h * 0.10, R - w * 0.28, bot, cx, bot)
    P.cubicTo(L + w * 0.28, bot, L + w * 0.13, bot - h * 0.10, L, cy)
    P.closeSubpath()
    return P


def crescent(cx, cy, r, dr, dx, dy):
    a = QPainterPath()
    a.addEllipse(QPointF(cx, cy), r, r)
    b = QPainterPath()
    b.addEllipse(QPointF(cx + dx, cy + dy), dr, dr)
    return a.subtracted(b)


# ---------------------------------------------------------------- 1 O · 斑
def f1():
    P = QPainterPath()
    P.addEllipse(QPointF(46, 52), 25, 25)
    return {"P": P, "dots": [(68.5, 26.5, 4.7)],
            "cap": "字母 O + 一颗豹斑", "note": "斑可绕环走动画"}


# ---------------------------------------------------------------- 2 月牙 · 斑
def f2():
    return {"P": crescent(50, 47, 31, 25, 10, -7), "dots": [(56.0, 56.0, 3.6)],
            "cap": "月牙 + 一颗斑", "note": "蜷起来的猫，安静"}


# ---------------------------------------------------------------- 3 尾卷
def f3():
    P = QPainterPath()
    cx, cy, turns, steps = 47.0, 49.0, 1.44, 320
    for i in range(steps + 1):
        u = i / steps
        th = u * turns * 2 * math.pi
        r = 3.4 + 26.0 * (u ** 1.26)
        x, y = cx + r * math.cos(th - math.pi / 2), cy + r * math.sin(th - math.pi / 2)
        P.moveTo(x, y) if i == 0 else P.lineTo(x, y)
    return {"P": P, "cap": "一笔尾卷", "note": "猫尾 / 循环重试"}


# ---------------------------------------------------------------- 4 请求 · 响应
def f4():
    P = QPainterPath(QPointF(38.0, 22.0))
    P.cubicTo(31.0, 30.0, 22.0, 42.0, 22.0, 48.0)
    P.cubicTo(22.0, 54.0, 31.0, 66.0, 38.0, 74.0)
    Q = QPainterPath(QPointF(58.0, 22.0))
    Q.cubicTo(65.0, 30.0, 74.0, 42.0, 74.0, 48.0)
    Q.cubicTo(74.0, 54.0, 65.0, 66.0, 58.0, 74.0)
    P.addPath(Q)
    return {"P": P, "dots": [(48.0, 48.0, 3.8)],
            "cap": "请求 · 响应", "note": "直给调试语义"}


# ---------------------------------------------------------------- 5 猫眼
def f5():
    return {"P": almond(), "extra": lens(48.0, 44.0, 4.0, 13.4, 1.2),
            "solid_extra": True,
            "cap": "猫眼 · 竖瞳", "note": " feline，辨识最快"}


# ---------------------------------------------------------------- 6 斑列
def f6():
    P = QPainterPath()
    P.addEllipse(QPointF(48, 48), 28, 28)
    return {"P": P, "extra": lens(48.0, 48.0, 4.4, 13.0, 1.2),
            "solid_extra": True,
            "cap": "环 · 竖瞳", "note": "斑里的一条竖瞳"}


CANDS = [("01", f1), ("02", f2), ("03", f3), ("04", f4), ("05", f5), ("06", f6)]


def draw_mark(p, spec, size, color, x, y):
    p.save()
    p.translate(x, y)
    if spec.get("P") is not None and spec["P"].elementCount():
        paint(p, spec["P"], size, color, spec.get("dots", ()))
    elif spec.get("dots"):
        paint(p, QPainterPath(), size, color, spec.get("dots", ()))
    if spec.get("extra") is not None:
        paint(p, spec["extra"], size, color, solid=spec.get("solid_extra", False))
    p.restore()


FONT = ".AppleSystemUIFont"


def font(px, weight=QFont.Weight.Normal, sp=0.0):
    f = QFont(FONT)
    f.setPixelSize(int(round(px)))
    f.setWeight(weight)
    if sp:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, sp)
    return f


def sheet(path, dark, cols=3):
    cw, ch, gap = 306, 232, 18
    W = 18 + cols * (cw + gap)
    H = 18 + 2 * (ch + gap)
    cv = QPixmap(W, H)
    cv.fill(QColor("#0B0B0D") if dark else QColor("#ECECEF"))
    p = QPainter(cv)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    fg = QColor("#EFEFF2") if dark else QColor("#17171C")
    sub = QColor("#7E7E88") if dark else QColor("#8E8E98")
    sub2 = QColor("#5E5E68") if dark else QColor("#A6A6B0")

    for i, (idx, fn) in enumerate(CANDS):
        spec = fn()
        col, row = i % cols, i // cols
        x = 18 + col * (cw + gap)
        y = 18 + row * (ch + gap)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#161619") if dark else QColor("#FFFFFF"))
        p.drawRoundedRect(QRectF(x, y, cw, ch), 14, 14)
        p.setPen(QPen(QColor("#282830") if dark else QColor("#E2E2E7"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(x + 0.5, y + 0.5, cw - 1, ch - 1), 14, 14)

        draw_mark(p, spec, 118, fg.name(), x + cw / 2 - 59, y + 18)

        sx = x + 30
        for s in (16, 21, 32):
            draw_mark(p, spec, s, sub.name(), sx, y + ch - s - 44)
            sx += s + 16

        p.setFont(font(11, QFont.Weight.Medium if False else QFont.Weight.DemiBold, 0.4))
        p.setPen(sub)
        p.drawText(QRect(int(x + 18), int(y + ch - 36), int(cw - 36), 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{idx}   {spec['cap']}")
        p.setFont(font(10.5))
        p.setPen(sub2)
        p.drawText(QRect(int(x + 18), int(y + ch - 21), int(cw - 36), 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   spec["note"])
    p.end()
    cv.save(path)
    print("saved", path)


sheet(os.path.join(HERE, 'candidates-dark.png'), True)
sheet(os.path.join(HERE, 'candidates-light.png'), False)

# 真实尺寸：标题栏 + Dock 图标
def usage(path, dark):
    W, H = 940, 6 * 76 + 30
    cv = QPixmap(W, H)
    cv.fill(QColor("#131316") if dark else QColor("#F2F2F5"))
    p = QPainter(cv)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    fg = QColor("#EDEDF0") if dark else QColor("#17171C")
    sub = QColor("#6E6E78") if dark else QColor("#98989F")
    for i, (idx, fn) in enumerate(CANDS):
        spec = fn()
        y = 15 + i * 76
        bg = QColor("#1C1C20") if dark else QColor("#FFFFFF")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(16, y, W - 32, 64), 12, 12)
        draw_mark(p, spec, 21, fg.name(), 44, y + 21)
        p.setFont(font(13, QFont.Weight.DemiBold, 0.2))
        p.setPen(fg)
        p.drawText(QRect(80, int(y + 18), 150, 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Ocelot")
        # 白底 Dock 图标
        ic = QPixmap(56, 56)
        ic.fill(Qt.GlobalColor.transparent)
        q = QPainter(ic)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(QColor("#FFFFFF"))
        q.drawRoundedRect(QRectF(1, 1, 54, 54), 13, 13)
        q.end()
        # 标识画进图标
        q = QPainter(ic)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        draw_mark(q, spec, 34, "#1A1A20", 11, 11)
        q.end()
        p.drawPixmap(300, y + 4, ic)
        p.setFont(font(10.5))
        p.setPen(sub)
        p.drawText(QRect(378, int(y + 18), 520, 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{idx}  21px 标题栏  ·  56px 白底图标  ·  {spec['cap']}")
    p.end()
    cv.save(path)
    print("saved", path)


usage(os.path.join(HERE, 'candidates-usage.png'), True)
print('ok')
