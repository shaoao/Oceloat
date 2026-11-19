"""v1.0.59 品牌标识专项自测。

覆盖：细线几何（尖耳 / 圆颊 / 窄下颌）、位图真的画出了东西、白底应用图标、
墨线描出动画真的在推进（而不是一次点亮）、五处接线（标题栏 / 欢迎页 / 关于页 /
响应空状态 / 窗口图标）、主题色随主题变化。
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
check("画布 96 单位", brand.BOX == 96.0, str(brand.BOX))
check("轮廓是一笔闭合", path.elementCount() > 8, str(path.elementCount()))
check("轮廓左右对称",
      abs((bounds.left() - 48.0) + (bounds.right() - 48.0)) < 0.5, str(bounds))
check("耳朵到下颌的高度对得上", 64 <= bounds.height() <= 70, str(bounds.height()))
check("轮廓长度合理", 200 < path.length() < 300, str(path.length()))
check("线宽只占 4.5% 左右", brand.STROKE_PX <= 0.05, str(brand.STROKE_PX))
check("两块斑在脸内部",
      all(abs(x - 48.0) < 24 and 30 < y < 72 for x, y, _r in brand.DOTS),
      str(brand.DOTS))
check("两块斑一大一小", brand.DOTS[0][2] > brand.DOTS[1][2], str(brand.DOTS))
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


def bright_ratio(t: float) -> float:
    """把 t 时刻的标识画出来，统计「亮到接近主题文字色」的像素占比。"""
    pm = QPixmap(200, 200)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    brand._paint_mark(p, 200.0, QColor("#7A7A84"), QColor("#F2F2F5"), t, 0.0)
    p.end()
    img = pm.toImage()
    hit = total = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y)
            if c.alpha() > 60:
                total += 1
                if c.lightness() > 185:
                    hit += 1
    return hit / max(total, 1)


r0, r3, r6, r9 = bright_ratio(0.0), bright_ratio(0.3), bright_ratio(0.6), bright_ratio(1.0)
check("静止时没有一条亮线", r0 < 0.06, f"{r0:.3f}")
check("动画前半段只亮了一小段", 0.05 < r3 < 0.55, f"{r3:.3f}")
check("中段比前段更亮", r6 > r3 + 0.05, f"{r6:.3f} vs {r3:.3f}")
check("写完时整条线都亮", r9 > 0.85, f"{r9:.3f}")
check("虚线单位按笔宽换算",
      "units = length / max(width" in (ROOT / "app" / "brand.py").read_text(encoding="utf-8"))

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
check("版本 1.0.59", VERSION == "1.0.59", VERSION)
check("更新内容是 1.0.59", CHANGELOG[0]["version"] == "1.0.59")
check("更新内容写了品牌标识", any("标识" in x for x in CHANGELOG[0]["items"]))
check("更新内容写了墨线动画",
      any("墨线" in x for x in CHANGELOG[0]["items"]))
check("更新内容写了白底图标",
      any("白底" in x for x in CHANGELOG[0]["items"]))
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
