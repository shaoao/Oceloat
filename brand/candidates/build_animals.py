"""动物形标识候选（实心剪影 + 负空间），仿 magpie 图标的做法。

magpie 那枚图标的关键不是「画得细」，而是：
  1. 一整块实心黑，边缘全是流畅的长曲线；
  2. 用背景色「切」出腹羽、翅羽、眼睛，形成黑白对比；
  3. 主体斜向构图，姿态在动（仰头、翘尾）。

这里走同一条路：QPainterPath 联合出实心猫科剪影，再用 subtracted
挖出眼睛、胸线、耳内缝、腹部拱形，让大块面之间产生呼吸。

用法：
    QT_QPA_PLATFORM=offscreen python3 brand/candidates/build_animals.py
"""
import math
import os
import sys

ROOT = '/Users/shaoao/WorkBuddy/spaces/2026_11_16_16-41-16/reqly'
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QApplication

app = QApplication([])
HERE = os.path.dirname(os.path.abspath(__file__))
BOX = 96.0


# ---------------------------------------------------------------- 几何工具
def ell(cx, cy, rx, ry=None):
    P = QPainterPath()
    P.addEllipse(QPointF(cx, cy), rx, ry if ry is not None else rx)
    return P


def poly(pts):
    P = QPainterPath(QPointF(*pts[0]))
    for p in pts[1:]:
        P.lineTo(QPointF(*p))
    P.closeSubpath()
    return P


def smooth(pts, t=0.82):
    """闭合 Catmull-Rom → 三次贝塞尔，点集就是轮廓控制点。"""
    n = len(pts)
    P = QPainterPath(QPointF(*pts[0]))

    def g(i):
        return pts[i % n]

    for i in range(n):
        p0, p1, p2, p3 = g(i - 1), g(i), g(i + 1), g(i + 2)
        c1 = (p1[0] + (p2[0] - p0[0]) * t / 6.0, p1[1] + (p2[1] - p0[1]) * t / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) * t / 6.0, p2[1] - (p3[1] - p1[1]) * t / 6.0)
        P.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(*p2))
    P.closeSubpath()
    return P


def cpts(p0, p1, p2, p3=None, n=44):
    """贝塞尔采样；只给三个点就退化成二次。"""
    out = []
    if p3 is None:
        for i in range(n + 1):
            u = i / n
            mu = 1 - u
            out.append((mu * mu * p0[0] + 2 * mu * u * p1[0] + u * u * p2[0],
                        mu * mu * p0[1] + 2 * mu * u * p1[1] + u * u * p2[1]))
        return out
    for i in range(n + 1):
        u = i / n
        mu = 1 - u
        out.append((
            mu ** 3 * p0[0] + 3 * mu * mu * u * p1[0] + 3 * mu * u * u * p2[0] + u ** 3 * p3[0],
            mu ** 3 * p0[1] + 3 * mu * mu * u * p1[1] + 3 * mu * u * u * p2[1] + u ** 3 * p3[1],
        ))
    return out


def band(pts, w0, w1=None):
    """沿点集拉一条带子；宽度从 w0 渐变到 w1（尾巴、腿都用它）。"""
    w1 = w0 if w1 is None else w1
    n = max(1, len(pts) - 1)
    out = QPainterPath()
    for i in range(n):
        a, b = pts[i], pts[i + 1]
        seg = QPainterPath(QPointF(*a))
        seg.lineTo(QPointF(*b))
        st = QPainterPathStroker()
        st.setWidth(max(0.42, w0 + (w1 - w0) * (i / n)))
        st.setCapStyle(Qt.PenCapStyle.RoundCap)
        st.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        out = out.united(st.createStroke(seg))
    return out


def limb(pts, w0, w1, paw=(0, 0, 0, 0)):
    """腿：锥形带 + 末端脚掌（paw = cx,cy,rx,ry）。"""
    b = band(pts, w0, w1)
    if paw[2] > 0:
        b = b.united(ell(*paw))
    return b


def lens(cx, cy, rw, rh, tilt=0.0):
    P = QPainterPath(QPointF(cx, cy - rh))
    P.cubicTo(cx + rw, cy - rh * 0.42, cx + rw, cy + rh * 0.42, cx, cy + rh)
    P.cubicTo(cx - rw, cy + rh * 0.42, cx - rw, cy - rh * 0.42, cx, cy - rh)
    P.closeSubpath()
    if tilt:
        from PyQt6.QtGui import QTransform
        tr = QTransform()
        tr.translate(cx, cy)
        tr.rotate(tilt)
        tr.translate(-cx, -cy)
        P = tr.map(P)
    return P


def U(*paths):
    out = QPainterPath()
    for p in paths:
        out = p if out.isEmpty() else out.united(p)
    return out


def MINUS(base, *holes):
    for h in holes:
        base = base.subtracted(h)
    return base


# ---------------------------------------------------------------- 01 静立·翘尾
def a1():
    body = smooth([(26, 55), (34, 46), (48, 42), (60, 45), (67, 53),
                   (66, 64), (56, 70), (40, 70), (28, 64)])
    body = body.united(ell(35, 58, 10.5, 11.5))          # 后腿髋部块面
    body = MINUS(body, ell(50, 73.6, 11.6, 4.8))            # 腹部拱形开口
    head = ell(68, 37, 12.2, 11.6)
    ear_l = poly([(56.6, 31.6), (58.6, 16.6), (67.6, 27.4)])
    ear_r = poly([(70.2, 26.6), (77.4, 15.4), (79.8, 31.4)])
    leg_f = limb(cpts((61, 60), (61.5, 72), (60.8, 82), (60.2, 86)), 7.2, 5.4, (59.6, 87.0, 4.0, 2.8))
    leg_h = limb(cpts((34, 64), (33.2, 74), (32.8, 82), (32.4, 86)), 9.6, 7.0, (32.0, 87.0, 4.6, 3.0))
    tail = band(cpts((27, 54), (11, 50), (7, 26), (21, 17)), 8.4, 2.9)
    mark = U(body, head, ear_l, ear_r, leg_f, leg_h, tail)
    holes = U(ell(74.6, 30.6, 1.95))
    return {"mark": MINUS(mark, holes), "cap": "静立 · 翘尾", "note": "最经典的一枚，站姿放松"}


# ---------------------------------------------------------------- 02 蹲坐·侧前
def a2():
    body = smooth([(39, 37), (56, 40), (62, 53), (60, 66), (55, 85),
                   (40, 87), (33, 74), (32, 55)])
    body = body.united(ell(38, 69, 12.0, 13.2))
    head = ell(47, 24, 12.0, 11.4)
    ear_l = poly([(35.2, 22.5), (33.4, 8.0), (44.6, 15.5)])
    ear_r = poly([(49.6, 15.5), (60.0, 8.0), (58.8, 22.5)])
    leg_a = limb([(51, 58), (50.6, 74), (50.4, 86)], 6.6, 5.4, (50.2, 87.0, 4.0, 2.7))
    leg_b = limb([(58, 54), (57.4, 72), (57.2, 84)], 6.0, 4.8, (57.0, 85.0, 3.6, 2.5))
    tail = band(cpts((34, 78), (46, 92), (66, 90), (74, 79)), 7.6, 2.5)
    mark = U(body, head, ear_l, ear_r, leg_a, leg_b, tail)
    holes = U(ell(43.0, 24.0, 1.95), ell(52.4, 24.0, 1.95),
              poly([(47.7, 29.8), (45.9, 32.8), (49.5, 32.8)]))
    return {"mark": MINUS(mark, holes), "cap": "蹲坐 · 侧前", "note": "坐着，尾巴绕到身前"}


# ---------------------------------------------------------------- 03 扑击·腾空
def a3():
    body = smooth([(21, 62), (29, 50), (43, 42), (58, 43), (62, 53),
                   (54, 63), (38, 69), (25, 70)])
    head = ell(66, 37, 11.0, 10.4)
    ear_l = poly([(55.6, 32.0), (57.6, 18.0), (65.4, 27.6)])
    ear_r = poly([(67.8, 26.8), (74.2, 16.6), (76.4, 31.8)])
    body = body.united(ell(63, 47, 7.2, 6.4))
    arm_a = limb(cpts((57, 52), (68, 50), (77, 46), (84, 41)), 6.8, 4.6, (85.2, 40.0, 3.8, 2.9))
    arm_b = limb(cpts((54, 60), (66, 60), (75, 57), (81, 52)), 6.2, 4.3, (82.4, 51.0, 3.6, 2.7))
    leg_a = limb(cpts((29, 66), (22, 74), (15, 78), (9, 77)), 9.2, 5.0, (8.0, 77.0, 3.9, 3.0))
    leg_b = limb(cpts((36, 70), (31, 79), (24, 83), (18, 82)), 8.2, 4.6, (17.0, 82.0, 3.6, 2.8))
    tail = band(cpts((21, 58), (10, 50), (5, 34), (12, 24)), 7.2, 2.6)
    mark = U(body, head, ear_l, ear_r, arm_a, arm_b, leg_a, leg_b, tail)
    holes = U(ell(71.4, 35.4, 1.9))
    return {"mark": MINUS(mark, holes), "cap": "扑击 · 腾空", "note": "腾空扑出，四爪张开"}


# ---------------------------------------------------------------- 04 猫头·大面
def a4():
    face = smooth([(48, 16), (31.5, 23), (24.5, 42), (27.5, 61), (38.5, 72.5),
                   (48, 75), (57.5, 72.5), (68.5, 61), (71.5, 42), (64.5, 23)])
    ear_l = poly([(24.6, 29.5), (20.4, 8.0), (39.6, 19.4)])
    ear_r = poly([(56.4, 19.4), (75.6, 8.0), (71.4, 29.5)])
    mark = U(face, ear_l, ear_r)
    holes = U(ell(38.4, 44.2, 2.05), ell(57.6, 44.2, 2.05),
              poly([(48, 55.0), (44.8, 50.6), (51.2, 50.6)]),
              band(cpts((48, 55.2), (48, 58.6), (44.8, 60.2)), 1.4),
              band(cpts((48, 58.6), (51.2, 60.2), (54.2, 58.4)), 1.4),
              # 耳内负空间细缝
              poly([(27.2, 25.4), (25.0, 14.6), (35.0, 20.4)]),
              poly([(61.0, 20.4), (71.0, 14.6), (68.8, 25.4)]))
    return {"mark": MINUS(mark, holes), "cap": "猫头 · 大面", "note": "纯正脸，缩到 16px 最稳"}


# ---------------------------------------------------------------- 05 背影·竖尾
def a5():
    """豹猫（ocelot）的特征：静立剪影上挖出几朵豹斑。"""
    body = smooth([(26, 55), (34, 46), (48, 42), (60, 46), (67, 54),
                   (66, 64), (56, 70), (40, 70), (28, 64)])
    body = body.united(ell(35, 58, 10.5, 11.5))
    body = MINUS(body, ell(50, 71, 12.5, 6.2))
    head = ell(68, 37, 12.2, 11.6)
    ear_l = poly([(56.6, 31.6), (58.6, 16.6), (67.6, 27.4)])
    ear_r = poly([(70.2, 26.6), (77.4, 15.4), (79.8, 31.4)])
    leg_f = limb(cpts((60, 64), (60.6, 74), (60.0, 83), (59.6, 86)), 8.6, 6.4, (59.2, 87.2, 4.6, 3.0))
    leg_h = limb(cpts((34, 66), (33.2, 76), (32.8, 83), (32.4, 86)), 11.0, 8.0, (32.0, 87.2, 5.2, 3.2))
    tail = band(cpts((27, 54), (11, 50), (7, 26), (21, 17)), 8.4, 2.9)
    mark = U(body, head, ear_l, ear_r, leg_f, leg_h, tail)
    spots = [ell(45.6, 51.8, 3.3, 2.5), ell(55.8, 54.0, 2.6, 2.0),
             ell(38.4, 62.2, 2.9, 2.2), ell(33.2, 50.6, 2.0, 1.6)]
    holes = U(ell(74.6, 30.6, 1.95), *spots)
    return {"mark": MINUS(mark, holes), "cap": "豹斑 · 静立", "note": "同一姿态带豹斑，ocelot 本义"}


# ---------------------------------------------------------------- 06 伸懒腰
def a6():
    body = smooth([(26, 68), (29, 56), (39, 50), (52, 49), (64, 53),
                   (70, 62), (69, 72), (58, 78), (40, 80), (29, 76)])
    head = ell(72.0, 57.0, 10.4, 9.8)
    ear_l = poly([(63.0, 53.0), (64.8, 39.6), (71.6, 49.0)])
    ear_r = poly([(73.4, 48.4), (79.0, 39.4), (80.8, 53.2)])
    paw_a = limb(cpts((67, 72), (74, 74), (80, 75), (85, 75)), 6.8, 5.2, (86.2, 75.0, 3.6, 2.8))
    paw_b = limb(cpts((64, 77), (71, 79), (77, 80), (82, 80)), 6.2, 4.8, (83.2, 80.0, 3.4, 2.7))
    tail = band(cpts((27, 75), (15, 73), (8, 62), (13, 51)), 6.6, 2.6)
    mark = U(body, head, ear_l, ear_r, paw_a, paw_b, tail)
    holes = U(ell(76.4, 55.2, 1.85))
    return {"mark": MINUS(mark, holes), "cap": "趴卧 · 前爪", "note": "伏在案头，安静"}


CANDS = [("01", a1), ("02", a2), ("03", a3), ("04", a4), ("05", a5), ("06", a6)]


# ---------------------------------------------------------------- 渲染
def draw(p, mark, size, color, x, y):
    p.save()
    p.translate(x, y)
    p.scale(size / BOX, size / BOX)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.drawPath(mark)
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
    cw, ch, gap = 306, 236, 18
    top, bottom = 64, 40
    W = 18 + cols * (cw + gap)
    H = top + 2 * (ch + gap) + bottom
    cv = QPixmap(W, H)
    cv.fill(QColor("#0B0B0D") if dark else QColor("#ECECEF"))
    p = QPainter(cv)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    fg = QColor("#EFEFF2") if dark else QColor("#17171C")
    sub = QColor("#7E7E88") if dark else QColor("#8E8E98")
    sub2 = QColor("#5E5E68") if dark else QColor("#A6A6B0")

    p.setFont(font(15, QFont.Weight.DemiBold, 0.2))
    p.setPen(fg)
    p.drawText(QRect(20, 16, 520, 22),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "Ocelot · 动物形标识候选（实心剪影 + 负空间）")
    p.setFont(font(11))
    p.setPen(sub2)
    p.drawText(QRect(20, 38, 700, 18),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "仿 magpie：一整块实心，用背景色切出眼睛与腹线；主体斜向构图，姿态在动")

    for i, (idx, fn) in enumerate(CANDS):
        spec = fn()
        col, row = i % cols, i // cols
        x = 18 + col * (cw + gap)
        y = top + row * (ch + gap)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#161619") if dark else QColor("#FFFFFF"))
        p.drawRoundedRect(QRectF(x, y, cw, ch), 14, 14)
        p.setPen(QPen(QColor("#282830") if dark else QColor("#E2E2E7"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(x + 0.5, y + 0.5, cw - 1, ch - 1), 14, 14)

        draw(p, spec["mark"], 122, fg.name(), x + cw / 2 - 61, y + 16)

        sx = x + 30
        for s in (16, 21, 32):
            draw(p, spec["mark"], s, sub.name(), sx, y + ch - s - 44)
            sx += s + 16

        p.setFont(font(11, QFont.Weight.DemiBold, 0.4))
        p.setPen(sub)
        p.drawText(QRect(int(x + 18), int(y + ch - 36), int(cw - 36), 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{idx}   {spec['cap']}")
        p.setFont(font(10.5))
        p.setPen(sub2)
        p.drawText(QRect(int(x + 18), int(y + ch - 21), int(cw - 36), 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   spec["note"])
    p.setFont(font(11))
    p.setPen(sub2)
    p.drawText(QRect(20, H - 32, W - 40, 20),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "我的建议：03 扑击最贴 magpie 的气质；01 静立最稳、通用度最高；04 缩到最小也认得出。")
    p.end()
    cv.save(path)
    print("saved", path)


sheet(os.path.join(HERE, 'animals-dark.png'), True)
sheet(os.path.join(HERE, 'animals-light.png'), False)


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
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1C1C20") if dark else QColor("#FFFFFF"))
        p.drawRoundedRect(QRectF(16, y, W - 32, 64), 12, 12)
        draw(p, spec["mark"], 22, fg.name(), 42, y + 21)
        p.setFont(font(13, QFont.Weight.DemiBold, 0.2))
        p.setPen(fg)
        p.drawText(QRect(78, int(y + 18), 150, 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Ocelot")
        ic = QPixmap(56, 56)
        ic.fill(Qt.GlobalColor.transparent)
        q = QPainter(ic)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(QColor("#FFFFFF"))
        q.drawRoundedRect(QRectF(1, 1, 54, 54), 13, 13)
        q.end()
        q = QPainter(ic)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        draw(q, spec["mark"], 34, "#1A1A20", 11, 11)
        q.end()
        p.drawPixmap(300, y + 4, ic)
        p.setFont(font(10.5))
        p.setPen(sub)
        p.drawText(QRect(378, int(y + 18), 520, 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{idx}  22px 标题栏  ·  56px 白底 Dock  ·  {spec['cap']}")
    p.end()
    cv.save(path)
    print("saved", path)


usage(os.path.join(HERE, 'animals-usage.png'), True)

for idx, fn in CANDS:
    spec = fn()
    cv = QPixmap(420, 420)
    cv.fill(QColor("#141418"))
    p = QPainter(cv)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    draw(p, spec["mark"], 352, "#F2F2F4", 34, 34)
    p.end()
    cv.save(os.path.join(HERE, f'animal-{idx}.png'))
print("ok")
