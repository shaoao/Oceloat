"""界面文字大小的就地缩放。

控件在构造时把字号（还有一批定死的行高）量死了，所以「改字号」以前只能重建
整个窗口 —— 设置页会跟着闪一下、重新打开，用户看不到变化过程。

这里改成另一种做法：按比例把**已经存在的**控件就地放大或缩小。
- 字号：QFont.pointSizeF × ratio（自绘控件在 paint 里调 font()/px()，
  会立刻跟着 theme.ui_scale() 走，不需要额外通知）；
- 行高：只动「高度被定死」且不高的控件（胶囊、输入框、按钮、行），
  大面板交给布局自己伸缩，避免把整窗拉变形。

比例是「相对当前」的：从 100% 拨到 150% 传 1.5，再拨回 100% 传 0.667，
所以反复点也不会漂。启动时仍然由 font()/px() 按设置里的系数一次算准。
"""
from __future__ import annotations

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QWidget

# 高度超过这个值就不算「定死的行」了，交给布局
_MAX_FIXED_H = 120


def widgets() -> list:
    app = QApplication.instance()
    return list(app.allWidgets()) if app is not None else []


def apply_scale(ratio: float) -> None:
    """把当前所有窗口按 ratio 就地缩放（字号 + 定死的行高）。"""
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        return
    if ratio <= 0 or abs(ratio - 1.0) < 1e-6:
        return
    for w in widgets():
        _scale_font(w, ratio)
        _scale_height(w, ratio)
    # 有些控件按构造时的字体量好了宽度（胶囊、分段控件），字体换了要重新量一遍
    for w in widgets():
        for name in ("refresh_scale", "sync_width", "_sync_size"):
            fn = getattr(w, name, None)
            if callable(fn):
                try:
                    fn()
                except (RuntimeError, TypeError):
                    pass
                break


def _scale_font(w: QWidget, ratio: float) -> None:
    try:
        f = w.font()
        size = f.pointSizeF()
        if size <= 0:            # 用像素字号设的控件（很老的代码）就按像素算
            px_size = f.pixelSize()
            if px_size <= 0:
                return
            nf = QFont(f)
            nf.setPixelSize(max(6, int(round(px_size * ratio))))
            w.setFont(nf)
            return
        nf = QFont(f)
        nf.setPointSizeF(max(6.0, size * ratio))
        w.setFont(nf)
    except (RuntimeError, AttributeError):
        return


def _scale_height(w: QWidget, ratio: float) -> None:
    try:
        h = w.maximumHeight()
        if h != w.minimumHeight() or h <= 0 or h > _MAX_FIXED_H:
            return
        nh = max(10, int(round(h * ratio)))
        if nh != h:
            w.setFixedHeight(nh)
    except (RuntimeError, AttributeError):
        return
