"""生成 Ocelot 的线条标识资产（SVG）。

特点：单一线宽 5/96、纯几何、无渐变。文字用 QPainterPath 转成真实路径，
输出的 SVG 不依赖安装字体，任意放大都清晰。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PyQt6.QtGui import QFont as F
from PyQt6.QtGui import QGuiApplication, QPainterPath, QTransform

OUT = Path(__file__).resolve().parent
APP = None

CX, CY, R = 48.0, 52.0, 27.0
SW = 5.0


def P(deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return CX + R * math.cos(a), CY - R * math.sin(a)


def head_path(apex: float = 25.0, apex_y: float = 11.0,
              out_deg: float = 44.0, in_deg: float = 70.0) -> str:
    sh_l, sh_r = P(180 - out_deg), P(out_deg)
    in_l, in_r = P(180 - in_deg), P(in_deg)
    return (
        f"M {sh_l[0]:.2f} {sh_l[1]:.2f} "
        f"L {CX - apex:.2f} {apex_y:.2f} "
        f"L {in_l[0]:.2f} {in_l[1]:.2f} "
        f"A {R} {R} 0 0 1 {in_r[0]:.2f} {in_r[1]:.2f} "
        f"L {CX + apex:.2f} {apex_y:.2f} "
        f"L {sh_r[0]:.2f} {sh_r[1]:.2f} "
        f"A {R} {R} 0 0 1 {CX} {CY + R:.2f} "
        f"A {R} {R} 0 0 1 {sh_l[0]:.2f} {sh_l[1]:.2f} Z"
    )


SPOTS = ((40.0, 45.0, 3.6), (55.5, 58.0, 2.5))


def mark(color: str = "#111111", sw: float = SW, spots: bool = True) -> str:
    out = (
        f'<path d="{head_path()}" fill="none" stroke="{color}" stroke-width="{sw}" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
    )
    if spots:
        for x, y, r in SPOTS:
            out += f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>'
    return out


# ---------------------------------------------------------------- 文字 → 路径
def _to_d(path: QPainterPath, scale: float = 1.0) -> str:
    out: list[str] = []
    i, n = 0, path.elementCount()
    while i < n:
        el = path.elementAt(i)
        if el.type == QPainterPath.ElementType.MoveToElement:
            out.append(f"M {el.x * scale:.2f} {el.y * scale:.2f}")
            i += 1
        elif el.type == QPainterPath.ElementType.LineToElement:
            out.append(f"L {el.x * scale:.2f} {el.y * scale:.2f}")
            i += 1
        else:
            c = path.elementAt(i + 1)
            out.append(f"Q {el.x * scale:.2f} {el.y * scale:.2f} "
                       f"{c.x * scale:.2f} {c.y * scale:.2f}")
            i += 2
    return " ".join(out)


def wordmark(text: str, target_w: float, tracking: float = 7.0,
             size: int = 72, family: str = "Helvetica Neue",
             weight: F.Weight = F.Weight.DemiBold) -> tuple[str, float]:
    f = F(family, size)
    f.setWeight(weight)
    f.setLetterSpacing(F.SpacingType.AbsoluteSpacing, tracking)
    p = QPainterPath()
    p.addText(0, 0, f, text)
    br = p.boundingRect()
    p = QTransform.fromTranslate(-br.left(), -br.top()).map(p)
    k = target_w / p.boundingRect().width()
    return _to_d(p, k), p.boundingRect().height() * k


def svg(w: float, h: float, body: str, bg: str | None = None) -> str:
    rect = f'<rect width="{w}" height="{h}" fill="{bg}"/>' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}">{rect}{body}</svg>')


def build() -> None:
    global APP
    APP = QGuiApplication(sys.argv)

    # 主标 / 反白 / 无斑（极小尺寸用）
    (OUT / "ocelot-mark.svg").write_text(svg(96, 96, mark("#111111")), "utf-8")
    (OUT / "ocelot-mark-inverse.svg").write_text(svg(96, 96, mark("#FFFFFF")), "utf-8")
    (OUT / "ocelot-mark-solid.svg").write_text(
        svg(96, 96, mark("#111111", spots=False)), "utf-8")

    # 应用图标：圆角方 + 线条（深浅两版）
    S, pad, radius = 1024, 208, 232
    size = S - pad * 2
    for name, bg, fg in (("ocelot-icon.svg", "#111111", "#FFFFFF"),
                         ("ocelot-icon-light.svg", "#FFFFFF", "#111111")):
        body = (f'<rect width="{S}" height="{S}" rx="{radius}" fill="{bg}"/>'
                f'<g transform="translate({pad} {pad}) scale({size / 96:.4f})">'
                f'{mark(fg, 7.4 * 96 / size)}</g>')
        (OUT / name).write_text(svg(S, S, body), "utf-8")

    # 横向组合：标 + 字（深浅两版）
    mark_px, gap, word_px, h = 140, 24, 236, 156
    d, wh = wordmark("OCELOT", word_px, tracking=13.0, weight=F.Weight.Medium,
                     family="Avenir Next")
    for name, fg in (("ocelot-lockup.svg", "#111111"),
                     ("ocelot-lockup-inverse.svg", "#FFFFFF")):
        body = (f'<g transform="translate(0 {(h - mark_px) / 2:.1f}) '
                f'scale({mark_px / 96:.4f})">{mark(fg, SW * 96 / mark_px)}</g>'
                f'<g transform="translate({mark_px + gap} {h / 2 - wh / 2:.2f})">'
                f'<path d="{d}" fill="{fg}"/></g>')
        (OUT / name).write_text(svg(mark_px + gap + word_px, h, body), "utf-8")

    # 仅字标
    w2 = 420
    d2, wh2 = wordmark("OCELOT", w2, tracking=15.0, weight=F.Weight.Medium,
                       family="Avenir Next")
    (OUT / "ocelot-wordmark.svg").write_text(
        svg(w2, wh2, f'<path d="{d2}" fill="#111111"/>'), "utf-8")


if __name__ == "__main__":
    build()
    print("done:", sorted(p.name for p in OUT.glob("*.svg")))
