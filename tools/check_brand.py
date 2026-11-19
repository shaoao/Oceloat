"""v1.0.68 品牌标识专项自测。

覆盖：细线几何（尖耳 / 圆颊 / 窄下颌，额顶一阶连续、下颌不是平底、侧壁不直）、
五官（竖椭圆眼 / 倒三角鼻 / 两颗豹斑）与按尺寸分级、位图真的画出了东西、
白底应用图标、墨线描出动画真的在推进、笔尖拖影与细节点亮的时机、
悬停写完会轻轻回位、五处接线、主题色随主题变化。
"""
from __future__ import annotations

import math
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
check("线宽回到 4.2% 左右", 0.039 <= brand.STROKE_PX <= 0.046, str(brand.STROKE_PX))


def heading(u0: float, u1: float) -> float:
    a = path.pointAtPercent(u0)
    b = path.pointAtPercent(u1)
    return math.atan2(b.y() - a.y(), b.x() - a.x())


# 额顶：左右两段在 u=0.5（x=48）处相接，接缝两侧的切线必须是同一方向
left_ang = heading(0.492, 0.4995)
right_ang = heading(0.5005, 0.508)
_diff = abs((right_ang - left_ang + math.pi) % (2 * math.pi) - math.pi)
check("额顶没有折角（切线连续）", _diff < 0.12,
      f"{math.degrees(_diff):.1f}°")

# 下颌：闭合点上下的切线连续 → 底是圆弧收口，不是「平底 + 突然转角」
_b0 = heading(0.980, 0.9994)
_b1 = heading(0.0006, 0.020)
_bd = abs((_b1 - _b0 + math.pi) % (2 * math.pi) - math.pi)
check("下颌是圆弧收口，不是平底", _bd < 0.16, f"{math.degrees(_bd):.1f}°")
check("下颌比脸颊窄（收进去）",
      abs(path.pointAtPercent(0.06).x() - 48.0) < (bounds.width() / 2) * 0.78,
      f"{abs(path.pointAtPercent(0.06).x() - 48.0):.1f}")

check("标识带静息呼吸", hasattr(brand.BrandMark(48), "_breathe"))

# ---------------------------------------------------------------- 五官
print("\n[五官]")


def at(pm, x: float, y: float, side: float):
    img = pm.toImage()
    ratio = pm.devicePixelRatio()
    k = side / brand.BOX * 0.94
    px = int(round((side / 2.0 + (x - brand.CENTER) * k) * ratio))
    py = int(round((side / 2.0 + (y - brand.VIEW_CY) * k) * ratio))
    return img.pixelColor(px, py)


def lit(pm, x, y, side) -> bool:
    return at(pm, x, y, side).alpha() > 150


check("两只眼睛一样大", brand.EYES[0][2:] == brand.EYES[1][2:], str(brand.EYES))
check("眼睛是竖椭圆（比宽高）",
      all(ry > rx for _cx, _cy, rx, ry in brand.EYES), str(brand.EYES))
check("鼻子是倒三角参数（有宽有高）",
      brand.NOSE[2] > 1.0 and brand.NOSE[3] > 1.5, str(brand.NOSE))
check("两颗豹斑一大一小", brand.SPOTS[0][2] > brand.SPOTS[1][2], str(brand.SPOTS))
check("五官都在脸内部",
      all(path.contains(QPointF(cx, cy)) for cx, cy, *_ in brand.EYES)
      and path.contains(QPointF(brand.NOSE[0], brand.NOSE[1] - brand.NOSE[3] / 2))
      and all(path.contains(QPointF(cx, cy)) for cx, cy, _r in brand.SPOTS))

big = brand.mark_pixmap(96, "#FFFFFF")
check("96px 画得出眼睛", all(lit(big, cx, cy, 96) for cx, cy, _a, _b in brand.EYES))
_nx, _ny, _nhw, _nh = brand.NOSE
_ny_base = _ny - _nh + 0.25          # 三角底边内侧，取样最稳
check("96px 画得出鼻", lit(big, _nx, _ny_base, 96))
check("96px 画得出两颗豹斑",
      all(lit(big, cx, cy, 96) for cx, cy, _r in brand.SPOTS))

# 按尺寸分级：小尺寸只留眼睛，放大才补鼻和斑
tiny = brand.mark_pixmap(21, "#FFFFFF")
check("21px 仍画眼睛", lit(tiny, brand.EYES[0][0], brand.EYES[0][1], 21))
check("21px 省掉鼻子", not lit(tiny, _nx, _ny_base, 21))
mid = brand.mark_pixmap(36, "#FFFFFF")
check("36px 补上鼻子", lit(mid, _nx, _ny_base, 36))
check("36px 还不画豹斑", not lit(mid, brand.SPOTS[0][0], brand.SPOTS[0][1], 36))
large = brand.mark_pixmap(56, "#FFFFFF")
check("56px 才画豹斑", lit(large, brand.SPOTS[0][0], brand.SPOTS[0][1], 56))

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
_src = (ROOT / "app" / "brand.py").read_text(encoding="utf-8")
check("虚线单位按笔宽换算", "units = length / max(width" in _src)
check("笔尖带拖尾（书写有速度感）", "尾迹" in _src)
check("细节点亮按尺寸分级", "DETAIL_MIN" in _src and "SPOT_MIN" in _src)
check("斑点亮起是柔光，不是描圈", "柔光" in _src)
check("悬停写完会轻轻回位", "self._run(0.88" in _src)

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
check("版本 1.0.68", VERSION == "1.0.68", VERSION)
check("更新内容是 1.0.68", CHANGELOG[0]["version"] == "1.0.68")
# 历史版本的断言不该随新版本翻篇就失效：把全部条目摊平了一起找
ALL_ITEMS = [item for entry in CHANGELOG for item in entry.get("items", [])]
check("更新内容写了品牌标识", any("标识" in x for x in ALL_ITEMS))
check("更新内容写了墨线动画",
      any("墨线" in x or "描出" in x for x in ALL_ITEMS))
check("更新内容写了五官",
      any("眼睛" in x or "鼻" in x for x in ALL_ITEMS))
check("更新内容写了白底图标",
      any("白底" in x for x in ALL_ITEMS))
mw_src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("主窗口导入了 BrandMark", "from .brand import BrandMark" in mw_src)
check("启动时设置应用图标", "app.setWindowIcon" in (ROOT / "main.py").read_text(encoding="utf-8"))
check("关于页导入了 BrandMark",
      "from .brand import BrandMark" in (ROOT / "app" / "dialogs.py").read_text(encoding="utf-8"))

# ---------------------------------------------------------------- 1.0.63 新增
print("\n[1.0.63 新增]")
_src = (ROOT / "app" / "brand.py").read_text(encoding="utf-8")
_icons_src = (ROOT / "app" / "icons.py").read_text(encoding="utf-8")
_dlg_src = (ROOT / "app" / "dialogs.py").read_text(encoding="utf-8")

check("应用图标是缓存单例", "@lru_cache(maxsize=1)" in _src
      and "def app_icon()" in _src)
check("更新内容支持 1/10/20/50/100 切换",
      all(f"({n}," in _dlg_src for n in (1, 10, 20, 50, 100)))
check("品牌来源图标走缓存",
      "_source_cache" in _icons_src and "def source_pixmap" in _icons_src)

_src_dir = ROOT / "app" / "assets" / "sources"
for _n in ("postman", "apifox", "hoppscotch", "insomnia", "openapi"):
    check(f"来源图标 {_n}.png 存在", (_src_dir / f"{_n}.png").exists())

# ---------------------------------------------------------------- 1.0.64 新增
print("\n[1.0.64 新增]")
_mock_src = (ROOT / "app" / "mock_panel.py").read_text(encoding="utf-8")
_server_src = (ROOT / "app" / "mock_server.py").read_text(encoding="utf-8")
_mw_src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")

check("更新内容按分类分节", "CATEGORY_ORDER" in _dlg_src
      and "def _section" in _dlg_src and "def _version_block" in _dlg_src)
check("范围选择在标题栏", "hl.insertWidget(hl.count() - 1, self.range_btn" in _dlg_src)
check("分类标题带主题色小点", 'Label("●"' in _dlg_src)
check("导入页 Ocelot 用应用标识", '"ocelot": "brand"' in _dlg_src
      and 'if self._icon == "brand"' in _dlg_src)
check("Mock 有多实例 Hub", "class MockHub" in _server_src
      and "def running(self) -> List[MockServer]" in _server_src)
check("Mock 支持局域网监听", '"0.0.0.0"' in _server_src and "def lan_urls" in _server_src)
check("Mock 路由有分组字段", '"group": group or ""' in _server_src)
check("一键 Mock 接了请求面板", "mockizeRequested" in _mw_src
      and "mockizeRequested" in (ROOT / "app" / "request_panel.py").read_text(encoding="utf-8"))
check("底部有 Mock 状态徽章", "class MockBadge" in _mw_src and "mock_badge" in _mw_src)
check("Mock 导入器存在", (ROOT / "app" / "mock_import.py").exists()
      and "routes_from_openapi" in (ROOT / "app" / "mock_import.py").read_text(encoding="utf-8"))
check("Mock AI 生成存在", (ROOT / "app" / "mock_ai.py").exists()
      and "messages_for_routes" in (ROOT / "app" / "mock_ai.py").read_text(encoding="utf-8"))
check("二维码模块存在且无第三方依赖", (ROOT / "app" / "qr.py").exists()
      and "import qrcode" not in (ROOT / "app" / "qr.py").read_text(encoding="utf-8"))
check("云同步统计有元数据", "META_KEY" in (ROOT / "app" / "cloud.py").read_text(encoding="utf-8"))
check("更新内容写了多实例", any("多实例" in x for x in ALL_ITEMS))
check("更新内容写了一键 Mock", any("一键 Mock" in x for x in ALL_ITEMS))
check("更新内容写了二维码", any("二维码" in x for x in ALL_ITEMS))
check("更新内容写了线条加粗", any("4.2%" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.65 新增
print("\n[1.0.65 新增]")
check("状态栏胶囊只在 Mock 运行时出现", "self.status_wrap.setVisible(on)" in _mw_src
      and "self._status_tick.stop()" in _mw_src)
check("右下角不再有版本号", "v{VERSION}" not in _mw_src)
check("AI 用例按钮已并入 AI 生成", "AI 用例" not in _mock_src
      and "result_cases" in _mock_src)
check("扫码按钮跟局域网联动", "self.qr_btn.setVisible(bool(on))" in _mock_src)
check("实例菜单无多余分隔线", "删除当前实例…" in _mock_src)
check("日志增量刷新", "_log_keys" in _mock_src and "def _rebuild_log_rows" in _mock_src)
check("自绘行缓存字体与图标", "_FONTS" in _mock_src and "_PIX" in _mock_src)
check("更新内容写了状态栏收起", any("状态栏" in x for x in ALL_ITEMS))
check("更新内容写了日志增量", any("增量插入" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.66 新增
print("\n[1.0.66 新增]")
check("状态栏横线去掉", "wl.addWidget(Divider())" not in _mw_src
      and "没有分隔线" in _mw_src)
check("状态栏有固定高度", "bar.setFixedHeight(28)" in _mw_src
      and "self.status_wrap = bar" in _mw_src)
check("空路由不隐藏滚动区", "self.scroll.setVisible(bool(routes))" not in _mock_src)
check("macOS 原生菜单模块存在", (ROOT / "app" / "app_menu.py").exists())
_main_src = (ROOT / "main.py").read_text(encoding="utf-8")
_menu_src = (ROOT / "app" / "app_menu.py").read_text(encoding="utf-8")
check("macOS 才装原生菜单", "sys.platform != \"darwin\"" in _menu_src
      and "install_app_menu(app, window)" in _main_src)
check("原生菜单有关于 / 设置 / 退出", all(
    x in _menu_src for x in ("关于 Ocelot", "设置…", "退出 Ocelot",
                             "AboutRole", "PreferencesRole",
                             "QuitRole")))
check("原生菜单保住引用", "window._native_menubar = bar" in _menu_src)
check("更新内容写了横线去掉", any("横线去掉" in x for x in ALL_ITEMS))
check("更新内容写了原生菜单", any("原生应用菜单" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.67 新增
print("\n[1.0.67 新增]")
check("状态条只挂在右半侧内容区", "cl.addWidget(self._build_statusbar())" in _mw_src
      and "root_lay.addWidget(self._build_statusbar())" not in _mw_src)
check("停止后整条收起恢复布局", "self.status_wrap.setVisible(on)" in _mw_src
      and "bar.setVisible(False)" in _mw_src)
check("侧栏不被状态条挤压", "cl.addWidget(self.stack, 1)\n        # Mock 状态条只属于右半侧" in _mw_src)
check("macOS 菜单去掉环境变量项", "环境变量…" not in _menu_src
      and "show_envs()" not in _menu_src)
check("更新内容写了右半侧与恢复", any("右半侧" in x for x in ALL_ITEMS)
      and any("整条收起" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.68 新增
print("\n[1.0.68 新增]")
check("全屏后重绘先清窗", "CompositionMode_Clear" in _mw_src
      and "Qt.GlobalColor.transparent" in _mw_src)
check("卡片不再描浅色边", "卡片本体时把描边笔收掉" in _mw_src
      and "p.setPen(Qt.PenStyle.NoPen)\n        p.setBrush(C(t.window))" in _mw_src)
check("遮罩随窗口状态重对齐", "resync_all()" in _mw_src
      and "def resync_all()" in (ROOT / "app" / "backdrop.py").read_text(encoding="utf-8"))
check("欢迎页简介不再写 macOS", "为 macOS 打造" not in _mw_src
      and "一个窗口全搞定" in _mw_src)
check("README 有新截图", all(
    (ROOT / "docs" / f"shot-{n}.png").exists() for n in
    ("main", "mock", "mock-logs", "qr", "palette", "cloud", "light")))
check("更新内容写了边框修复", any("半透明线" in x for x in ALL_ITEMS))
check("更新内容写了 README 装修", any("README 重新排版" in x for x in ALL_ITEMS))

print(f"\n{len(FAIL)} failed / {TOTAL[0]} checks")
if FAIL:
    for name in FAIL:
        print("  -", name)
sys.exit(1 if FAIL else 0)
