"""v1.0.60 品牌标识专项自测。

覆盖：剪影几何（头身相连、腹部与眼睛是真的负空间、尾巴伸到身后）、
位图真的画出了东西、白底应用图标、悬浮动画（睁眼 + 甩尾 + 上浮）、
五处接线（标题栏 / 欢迎页 / 关于页 / 响应空状态 / 窗口图标）、主题色随主题变化。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEventLoop, QPointF, QRectF, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QEnterEvent, QPainter, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from app import brand, i18n  # noqa: E402
from app.store import CHANGELOG, VERSION, Store  # noqa: E402
from app.theme import apply_theme, theme_by_name  # noqa: E402

apply_theme(app, theme_by_name("dark"))
i18n.set_language("zh", notify=False)

FAIL: list[str] = []
TOTAL = [0]


def check(name: str, ok: bool, detail: str = "") -> None:
    TOTAL[0] += 1
    if ok:
        print(f"  ok   {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


def painted(pm) -> int:
    img = pm.toImage()
    count = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            if img.pixelColor(x, y).alpha() > 12:
                count += 1
    return count


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


# ---------------------------------------------------------------- 几何
print("\n[几何]")
path = brand.outline()
bounds = path.boundingRect()
whole = brand.mark_path()
wb = whole.boundingRect()
check("画布 96 单位", brand.BOX == 96.0, str(brand.BOX))
check("主体是一条闭合填充路径", path.elementCount() > 40, str(path.elementCount()))
check("主体有负空间（多段子路径）", len(path.toSubpathPolygons()) >= 2,
      str(len(path.toSubpathPolygons())))
check("整枚标识留在画布内",
      4 < wb.left() and wb.right() < 92 and 6 < wb.top() and wb.bottom() < 92, str(wb))
check("标识接近满画布（宽 60~84）", 60 <= wb.width() <= 84, str(wb.width()))
check("高度 70~84", 70 <= wb.height() <= 84, str(wb.height()))
check("尾巴伸到身体左侧", brand.tail_path().boundingRect().left() < bounds.left() - 4,
      f"{brand.tail_path().boundingRect().left():.1f} vs {bounds.left():.1f}")
check("腹部是真的挖空", not path.contains(QPointF(50.0, 74.0)))
check("眼睛是真的挖空", not path.contains(QPointF(brand.EYE[0], brand.EYE[1])),
      str(brand.EYE))
check("头部连着身体（不悬空）", path.contains(QPointF(64.0, 44.0)))
check("后腿与身体相连", path.contains(QPointF(33.0, 64.0)))
check("尾巴根部埋进身体", path.contains(QPointF(33.0, 56.0)))
check("标识带静息呼吸", hasattr(brand.BrandMark(48), "_breathe"))

# ---------------------------------------------------------------- 位图
print("\n[位图]")
for size in (16, 21, 44, 96):
    pm = brand.mark_pixmap(size, "#F2F2F5")
    check(f"{size}px 位图有内容", painted(pm) > size // 2, str(painted(pm)))
    check(f"{size}px 尺寸对得上", pm.width() == size * 2, str(pm.width()))
check("彩色也能画", painted(brand.mark_pixmap(44, QColor("#7C6BF5"))) > 40)

icon = brand.app_icon()
sizes = sorted({s.width() for s in icon.availableSizes()})
check("应用图标有多尺寸", len(sizes) >= 6, str(sizes))
check("应用图标包含 256", 256 in sizes, str(sizes))
check("应用图标不是空图", not icon.pixmap(64, 64).isNull())
_pm = icon.pixmap(128, 128).toImage()
check("图标是白底", _pm.pixelColor(14, 64).lightness() > 220,
      str(_pm.pixelColor(14, 64).lightness()))
check("图标中间是深色线条",
      any(_pm.pixelColor(x, y).lightness() < 90
          for y in range(30, 100, 3) for x in range(30, 100, 3)))
check("图标四角透明", _pm.pixelColor(1, 1).alpha() < 40,
      str(_pm.pixelColor(1, 1).alpha()))

# ---------------------------------------------------------------- 动画
print("\n[动画]")


def render(t: float, side: int = 200) -> QPixmap:
    pm = QPixmap(side, side)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    brand._paint_mark(p, float(side), QColor("#7A7A84"), QColor("#F2F2F5"), t, 0.0)
    p.end()
    return pm


def at(img: QPixmap, x: float, y: float, t: float, side: int = 200):
    k = side / brand.BOX * 0.94 * (1.0 + 0.035 * t)
    px = side / 2.0 + (x - brand.CENTER) * k
    py = side / 2.0 - side * 0.010 * t + (y - brand.VIEW_CY) * k
    return img.toImage().pixelColor(int(round(px)), int(round(py)))


img0, img1 = render(0.0), render(1.0)
c0 = at(img0, brand.EYE[0], brand.EYE[1], 0.0)
c1 = at(img1, brand.EYE[0], brand.EYE[1], 1.0)
check("静止时眼睛是空的", c0.alpha() < 70, f"alpha={c0.alpha()}")
check("悬浮时眼睛亮起来", c1.alpha() > 200 and c1.lightness() > 200,
      f"alpha={c1.alpha()} L={c1.lightness()}")

def left_diff(a: QPixmap, b: QPixmap, side: int = 200) -> int:
    """左侧（尾巴独占的区域）两帧之间有多少像素变了。"""
    ia, ib = a.toImage(), b.toImage()
    k = side / brand.BOX * 0.94
    x0 = int(side / 2.0 + (5.0 - brand.CENTER) * k)
    x1 = int(side / 2.0 + (30.0 - brand.CENTER) * k)
    y0 = int(side / 2.0 + (12.0 - brand.VIEW_CY) * k)
    y1 = int(side / 2.0 + (62.0 - brand.VIEW_CY) * k)
    n = 0
    for py in range(max(0, y0), min(side, y1)):
        for px in range(max(0, x0), min(side, x1)):
            if abs(ia.pixelColor(px, py).alpha() - ib.pixelColor(px, py).alpha()) > 60:
                n += 1
    return n


check("尾巴在左侧有实体", at(img0, 14.7, 38.2, 0.0).alpha() > 120,
      f"alpha={at(img0, 14.7, 38.2, 0.0).alpha()}")
check("悬浮时尾巴甩动（左侧像素变化）", left_diff(img0, img1) > 120,
      str(left_diff(img0, img1)))

body0 = at(img0, 48.0, 55.0, 0.0)
body1 = at(img1, 48.0, 55.0, 1.0)
check("主体始终是实心的", body0.alpha() > 240 and body1.alpha() > 240,
      f"{body0.alpha()} / {body1.alpha()}")
check("甩尾是绕尾根的旋转",
      "p.rotate(swing)" in (ROOT / "app" / "brand.py").read_text(encoding="utf-8"))
check("眼睛光点是 out-back bloom",
      "_out_back(_clamp(t * 1.25))" in (ROOT / "app" / "brand.py").read_text(encoding="utf-8"))

mark = brand.BrandMark(21)
mark.show()
app.processEvents()
check("控件尺寸固定", mark.width() == 21 and mark.height() == 21)
check("静止时进度为 0", abs(mark._t) < 0.01, str(mark._t))
mark.enterEvent(QEnterEvent(QPointF(10, 10), QPointF(100, 100), QPointF(100, 100)))
wait(920)
check("悬浮后进度推到 1", mark._t > 0.9, str(mark._t))
mark.leaveEvent(QEnterEvent(QPointF(0, 0), QPointF(0, 0), QPointF(0, 0)))
wait(700)
check("移开后收回 0", mark._t < 0.1, str(mark._t))
mark._run(0.0, 1)
wait(20)
mark.play_once(60)
wait(1800)   # 900ms 描出 + 60ms 停留 + 620ms 收回，再留一点余量
check("play_once 结束回到静止", mark._t < 0.15, str(mark._t))

# ---------------------------------------------------------------- 接线
print("\n[接线]")
store = Store.load(Path(tempfile.mkdtemp(prefix="ocelot-brand-")) / "state.json")
from app.dialogs import SettingsDialog  # noqa: E402
from app.main_window import MainWindow  # noqa: E402

mw = MainWindow(store)
mw.show()
app.processEvents()
check("标题栏有品牌标识", hasattr(mw, "brand_mark") and mw.brand_mark.width() == 21)
bar = mw.brand_mark.parent()
check("标识在标题栏里", bar is not None and bar.height() <= 60,
      str(bar.height() if bar is not None else None))
lay = bar.layout()
order = [lay.itemAt(i).widget() for i in range(lay.count())]
idx_mark = order.index(mw.brand_mark) if mw.brand_mark in order else -1
from app.widgets import Label  # noqa: E402

idx_word = next((i for i, w in enumerate(order)
                 if isinstance(w, Label) and w.text() == "Ocelot"), -1)
check("标识在标题左边", 0 <= idx_mark < idx_word, f"{idx_mark} / {idx_word}")
check("窗口图标也换了", not mw.windowIcon().isNull())
check("欢迎页也放了标识", hasattr(mw.welcome, "mark") and mw.welcome.mark.width() >= 48,
      str(getattr(getattr(mw.welcome, "mark", None), "width", lambda: None)()))
check("欢迎页标识会自己演一遍", mw.welcome.mark._autoplay)
mw.new_request()
app.processEvents()
check("响应空状态也换成标识",
      getattr(mw.response.empty, "mark", None) is not None,
      str(getattr(mw.response.empty, "mark", None)))
check("空状态标识会自己演一遍", mw.response.empty.mark._autoplay)

dlg = SettingsDialog(store, page="about_app")
dlg.show()
app.processEvents()
check("关于页有标识", hasattr(dlg, "about_mark"))
check("关于页标识更大", getattr(dlg, "about_mark", None) is not None
      and dlg.about_mark.width() >= 40, str(getattr(dlg, "about_mark", None)))
check("关于页标识会自己演一遍", dlg.about_mark._autoplay)
dlg.close()
mw.close()

# ---------------------------------------------------------------- 主题
print("\n[主题]")
apply_theme(app, theme_by_name("light"))
mark.show()
pm = QPixmap_probe = mark.grab()  # noqa: F841
check("浅色主题下也能画", painted(pm) > 0, str(painted(pm)))
apply_theme(app, theme_by_name("dark"))

# ---------------------------------------------------------------- 文案 / 版本
print("\n[文案 / 版本]")
check("版本 1.0.60", VERSION == "1.0.60", VERSION)
check("更新内容是 1.0.60", CHANGELOG[0]["version"] == "1.0.60")
check("更新内容写了剪影标识", any("剪影" in x for x in CHANGELOG[0]["items"]))
check("更新内容写了悬浮动画",
      any("尾巴" in x or "睁眼" in x for x in CHANGELOG[0]["items"]))
mw_src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("主窗口导入了 BrandMark", "from .brand import BrandMark" in mw_src)
check("启动时设置应用图标", "app.setWindowIcon" in (ROOT / "main.py").read_text(encoding="utf-8"))
check("关于页导入了 BrandMark",
      "from .brand import BrandMark" in (ROOT / "app" / "dialogs.py").read_text(encoding="utf-8"))

print(f"\n{len(FAIL)} failed / {TOTAL[0]} checks")
if FAIL:
    for name in FAIL:
        print("  -", name)
sys.exit(1 if FAIL else 0)
