"""生成 Ocelot 的线条标识资产（SVG）。

几何直接取自应用本体 `app/brand.py`，保证「应用里看到的」和「导出的资产」
是同一条曲线——不再有第二份手抄的坐标。

输出：主标（浅色 / 深色 / 实心）、应用图标（白底 / 深底）、横向组合、字标。
文字仍用 QPainterPath 转成真实路径，SVG 不依赖安装字体。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtGui import QFont as F  # noqa: E402
from PyQt6.QtGui import QGuiApplication, QPainterPath, QTransform  # noqa: E402

OUT = Path(__file__).resolve().parent
APP = None

SW = 96 * 0.040   # 与 app/brand.py 的 4% 线宽对齐（96 画布 → 3.84）


def _d(path: QPainterPath, scale: float = 1.0) -> str:
    """把 QPainterPath 串成 SVG path 的 d 属性（支持 M / L / C）。"""
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
        elif i + 2 < n:
            c1, c2 = path.elementAt(i), path.elementAt(i + 1)
            end = path.elementAt(i + 2)
            out.append(
                f"C {c1.x * scale:.2f} {c1.y * scale:.2f} "
                f"{c2.x * scale:.2f} {c2.y * scale:.2f} "
                f"{end.x * scale:.2f} {end.y * scale:.2f}")
            i += 3
        else:
            i += 1
    return " ".join(out)


def head_d() -> str:
    from app.brand import outline
    return _d(outline())


def features(color: str) -> str:
    """五官：两只竖椭圆眼、倒三角鼻、两颗豹斑。"""
    from app.brand import EYES, NOSE, SPOTS
    out = ""
    for cx, cy, rx, ry in EYES:
        out += (f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" '
                f'rx="{rx:.2f}" ry="{ry:.2f}" fill="{color}"/>')
    cx, cy, hw, h = NOSE
    out += (f'<polygon points="{cx - hw:.2f},{cy - h:.2f} {cx + hw:.2f},{cy - h:.2f} '
            f'{cx:.2f},{cy:.2f}" fill="{color}"/>')
    for px, py, r in SPOTS:
        out += f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{r:.2f}" fill="{color}"/>'
    return out


def mark(color: str = "#111111", sw: float = SW) -> str:
    return (
        f'<path d="{head_d()}" fill="none" stroke="{color}" stroke-width="{sw:.2f}" '
        f'stroke-linecap="round" stroke-linejoin="round"/>' + features(color)
    )


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
    APP = QGuiApplication.instance() or QGuiApplication(sys.argv)

    # 主标：深色用于浅底，反白用于深底；实心版留给极小尺寸
    (OUT / "ocelot-mark.svg").write_text(svg(96, 96, mark("#111111")), "utf-8")
    (OUT / "ocelot-mark-inverse.svg").write_text(svg(96, 96, mark("#F2F2F5")), "utf-8")
    (OUT / "ocelot-mark-solid.svg").write_text(
        svg(96, 96, f'<path d="{head_d()}" fill="none" stroke="#111111" '
                    f'stroke-width="{SW * 1.9:.2f}" stroke-linecap="round" '
                    f'stroke-linejoin="round"/>{features("#111111")}'), "utf-8")

    # 应用图标：白底 + 近黑细线（与应用内 Dock 图标一致），另出深底反白一版
    S, pad, radius = 1024, 208, 232
    size = S - pad * 2
    for name, bg, fg in (("ocelot-icon.svg", "#FFFFFF", "#14141A"),
                         ("ocelot-icon-light.svg", "#14141A", "#F2F2F5")):
        body = (f'<rect width="{S}" height="{S}" rx="{radius}" fill="{bg}"/>'
                f'<g transform="translate({pad} {pad}) scale({size / 96:.4f})">'
                f'{mark(fg, SW * 96 / size)}</g>')
        (OUT / name).write_text(svg(S, S, body), "utf-8")

    # 横向组合：标 + 字（深浅两版）
    mark_px, gap, word_px, h = 140, 24, 236, 156
    d, wh = wordmark("OCELOT", word_px, tracking=13.0, weight=F.Weight.Medium,
                     family="Avenir Next")
    for name, fg in (("ocelot-lockup.svg", "#111111"),
                     ("ocelot-lockup-inverse.svg", "#F2F2F5")):
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
