"""v1.0.72 品牌标识专项自测。

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
check("版本 1.0.81", VERSION == "1.0.81", VERSION)
check("更新内容是 1.0.81", CHANGELOG[0]["version"] == "1.0.81")
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
check("状态条只挂在右半侧内容区", "bar.setParent(self.content)" in _mw_src
      and "root_lay.addWidget(self._build_statusbar())" not in _mw_src)
check("停止后整条收起恢复布局", "self.status_wrap.setVisible(on)" in _mw_src
      and "bar.setVisible(False)" in _mw_src)
check("侧栏不被状态条挤压", "def _place_statusbar" in _mw_src
      and "cl.addWidget(self.stack, 1)" in _mw_src)
check("macOS 菜单去掉环境变量项", "环境变量…" not in _menu_src
      and "show_envs()" not in _menu_src)
check("更新内容写了右半侧与恢复", any("右半侧" in x for x in ALL_ITEMS)
      and any("整条收起" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.68 新增
print("\n[1.0.68 新增]")
check("全屏后重绘先清窗", "CompositionMode_Clear" in _mw_src
      and "Qt.GlobalColor.transparent" in _mw_src)
check("卡片不再画多层投影", "for i in range(m, 0, -1):" not in _mw_src)
check("遮罩随窗口状态重对齐", "resync_all()" in _mw_src
      and "def resync_all()" in (ROOT / "app" / "backdrop.py").read_text(encoding="utf-8"))
check("欢迎页简介不再写 macOS", "为 macOS 打造" not in _mw_src)
check("README 有新截图", all(
    (ROOT / "docs" / f"shot-{n}.png").exists() for n in
    ("main", "mock", "mock-logs", "qr", "palette", "cloud", "light")))
check("更新内容写了边框修复", any("半透明线" in x for x in ALL_ITEMS))
check("更新内容写了 README 装修", any("README 重新排版" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.69 新增
print("\n[1.0.69 新增]")
check("卡片铺满窗口，不留投影留白", "卡片铺满整个窗口" in _mw_src
      and "CARD_RADIUS = 12" in _mw_src)
check("圆角改由窗口遮罩裁", "self.setMask(_rounded_region" in _mw_src
      and "self.root.clearMask()" in _mw_src)
check("圆角逐行解析算弧", "_rounded_region" in _mw_src
      and "math.sqrt" in _mw_src and "toFillPolygon" not in _mw_src)
check("最大化时清掉窗口遮罩", "if not self.mask().isEmpty():" in _mw_src
      and "self.clearMask()" in _mw_src)
check("窗口边缘有 1px 细描边", "p.setPen(QPen(C(t.border), 1))" in _mw_src)
check("欢迎页简介不再说一个窗口", "一个窗口全搞定" not in _mw_src
      and "离线可用" in _mw_src)
check("i18n 同步了新简介",
      "Debug requests, run mock servers, write API docs" in
      (ROOT / "app" / "i18n.py").read_text(encoding="utf-8"))
check("更新内容写了方形透明修复", any("方形透明块" in x for x in ALL_ITEMS))
check("更新内容写了简介纠正", any("并不准确" in x for x in ALL_ITEMS))
check("更新内容写了 README 精简", any("README 又精简" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.70 新增
print("\n[1.0.70 新增]")
_spec = (ROOT / "Ocelot.spec").read_text(encoding="utf-8")
_build = ROOT / "tools" / "build_app.py"
_mainsrc = (ROOT / "main.py").read_text(encoding="utf-8")
check("有 PyInstaller 配方", _spec.count("BUNDLE(") == 1 and "main.py" in _spec)
check("配方保留了必要的 Qt 模块",
      all(x in _spec for x in ("QtWebSockets", "QtMultimedia", "QtNetwork", "QtWidgets")))
check("配方挡掉了用不到的 Qt 模块", "iter_modules(PyQt6.__path__)" in _spec
      and "KEEP_QT" in _spec)
check("单目录打包，不用 onefile",
      "exclude_binaries=True" in _spec and "onefile" not in _spec.lower().replace(
          "不做 onefile", ""))
check("打包脚本存在且会自检", _build.exists()
      and "self_test" in _build.read_text(encoding="utf-8"))
check("自检入口接在 main.py", "--self-test" in _mainsrc
      and (ROOT / "app" / "selftest.py").exists())
check("应用图标能用于打包", (ROOT / "docs" / "Ocelot.icns").exists()
      and (ROOT / "docs" / "Ocelot.icns").stat().st_size > 20_000)
check("更新内容写了打包", any("打包" in x for x in ALL_ITEMS))
check("更新内容写了体积与启动", any("62MB" in x for x in ALL_ITEMS)
      and any("0.6 秒" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.71 新增
print("\n[1.0.71 新增]")
_res = (ROOT / "app" / "resmon.py").read_text(encoding="utf-8")
_trim = (ROOT / "app" / "memtrim.py").read_text(encoding="utf-8")
_dlg_src = (ROOT / "app" / "dialogs.py").read_text(encoding="utf-8")
check("资源管理器不再测内存", "process_memory" not in _res and "health_status" not in _res)
check("文件管理有面包屑与筛选", "def _rebuild_crumbs" in _res and "i18n.placeholder" in _res)
check("文件列表支持三列排序", "class SortHeader" in _res and '"size"' in _res
      and '"time"' in _res)
check("删除走系统废纸篓", "osascript" in _res and ".trash" in _res)
check("有新建 / 重命名 / 删除", all(x in _res for x in
      ("def _act_new_folder", "def _act_rename", "def _delete")))
check("定时回收支持 macOS 与 Linux",
      "malloc_zone_pressure_relief" in _trim and "malloc_trim" in _trim)
check("回收只清可再生的缓存", "icons.clear_cache" in _trim and "gc.collect()" in _trim)
check("AutoTrim 跟随开关启停", "def apply" in _trim and "auto_enabled" in _trim)
check("主窗口持有一个 AutoTrim", "self._auto_trim = AutoTrim(self.store, self)" in _mw_src)
check("设置页只有一个内存开关", "自动释放内存" in _dlg_src
      and "trim_seg" not in _dlg_src and "trim_now" not in _dlg_src)
check("设置默认开启自动回收", '"auto_trim": True' in (ROOT / "app" / "store.py")
      .read_text(encoding="utf-8"))
check("i18n 登记了文件管理文案",
      "Show in Finder" in (ROOT / "app" / "i18n.py").read_text(encoding="utf-8")
      and "Automatic memory cleanup" in
      (ROOT / "app" / "i18n.py").read_text(encoding="utf-8"))
check("更新内容写了定时回收", any("自动释放内存" in x for x in ALL_ITEMS))
check("更新内容写了文件管理", any("资源管理器彻底改成文件管理" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.72 新增
print("\n[1.0.72 新增]")
_spec_src = (ROOT / "Ocelot.spec").read_text(encoding="utf-8")
_mock_src = (ROOT / "app" / "mock_panel.py").read_text(encoding="utf-8")
_icons_src = (ROOT / "app" / "icons.py").read_text(encoding="utf-8")
_mw2 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("配方带上了 app/assets", 'datas=[("app/assets", "app/assets")]' in _spec_src)
check("资源路径兼容打包环境", "_MEIPASS" in _icons_src and "def assets_root" in _icons_src)
check("自检会验品牌图标", "品牌图标能着色渲染" in
      (ROOT / "app" / "selftest.py").read_text(encoding="utf-8"))
check("Mock 中心是独立窗口", "MODELESS = True" in _mock_src
      and "class MockDialog" in _mock_src)
check("主窗口复用同一个 Mock 窗口", "_mock_dialog" in _mw2
      and "dlg.isVisible()" in _mw2)
check("Mock 用 show() 打开而不是 exec()",
      "dlg.show()" in _mw2.split("def open_mock")[1].split("def _mock_trial")[0])
check("对话框都设了系统窗口标题", "self.setWindowTitle(title or \"Ocelot\")" in _dlg_src)
check("存档每次落盘前备份", "def backup_now" in
      (ROOT / "app" / "store.py").read_text(encoding="utf-8")
      and "_maybe_snapshot" in
      (ROOT / "app" / "storage.py").read_text(encoding="utf-8"))
check("坏存档先隔离再恢复", "corrupt-" in (ROOT / "app" / "store.py").read_text(encoding="utf-8")
      and "def _newest_valid_backup" in
      (ROOT / "app" / "store.py").read_text(encoding="utf-8"))
check("文件管理器能恢复备份", "def _restore_backup" in _res
      and "restore_from" in _res)
check("清理备份至少留 3 份", "keep: int = 3" in _res)
check("云端覆盖前会确认", "_request_count" in _dlg_src
      and "云端数据比本机少" in _dlg_src)
check("打包脚本对齐版本号", "def stamp_version" in
      (ROOT / "tools" / "build_app.py").read_text(encoding="utf-8"))
check("i18n 登记了恢复文案",
      "Restore from this backup" in
      (ROOT / "app" / "i18n.py").read_text(encoding="utf-8"))
check("更新内容写了打包图标修复", any("Postman / Apifox" in x for x in ALL_ITEMS))
check("更新内容写了独立 Mock 窗口", any("Mock 中心改成独立窗口" in x for x in ALL_ITEMS))
check("更新内容写了存档备份", any("存档自动备份" in x for x in ALL_ITEMS))
check("更新内容写了窗口标题", any("⌘` 切换" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.74 新增
print("\n[1.0.74 新增]")
_st = (ROOT / "app" / "storage.py").read_text(encoding="utf-8")
_sto = (ROOT / "app" / "store.py").read_text(encoding="utf-8")
_res2 = (ROOT / "app" / "resmon.py").read_text(encoding="utf-8")
_sb2 = (ROOT / "app" / "sidebar.py").read_text(encoding="utf-8")
check("存储层是独立模块", (ROOT / "app" / "storage.py").is_file())
check("每集合一份文件", "MODULES_DIR = \"collections\"" in _st
      and "def _module_text" in _st)
check("写入是原子替换", "os.replace(tmp, path)" in _st and "os.fsync(fh.fileno())" in _st)
check("文件自带校验和", "checksum" in _st and "def digest" in _st)
check("索引最后写", _st.index("atomic_write(path, text)")
      < _st.index("atomic_write(self.index_path, text)"))
check("坏文件先隔离", "def _quarantine" in _st and "corrupted" in _st)
check("单个坏文件只跳过它", "已跳过" in _st or "读不出来，已跳过" in _st)
check("孤儿集合会被挂回来", "未登记的集合" in _st)
check("删掉的集合文件进备份", "def _retire" in _st and "removed-" in _st)
check("备份有总量预算", "BACKUP_BUDGET" in _st and "SNAPSHOT_KEEP" in _st)
check("旧单文件存档自动迁移", "已从单文件存档拆成按集合分文件" in _st)
check("存储层有完整性检查", "def verify" in _st and "def repair" in _st)
check("Store 走模块化存储", "self._storage.write(self.data)" in _sto
      and "def snapshot_text" in _sto)
check("历史 / 回收站有硬上限", "HISTORY_BYTES" in _sto and "TRASH_MAX" in _sto
      and "def _trim" in _sto)
check("云同步传完整快照", "self.store.snapshot_text()" in
      (ROOT / "app" / "main_window.py").read_text(encoding="utf-8"))
check("云恢复按模块重写", "replace_all(data)" in
      (ROOT / "app" / "dialogs.py").read_text(encoding="utf-8"))
check("资源管理器按存储分组", "\"quarantine\"" in _res2 and "ChipStrip" in _res2)
check("能检查完整性 / 重建索引", "检查完整性" in _res2 and "重建索引" in _res2)
check("连续新建文件夹不会层层嵌套", "_creation_parent" in _sb2
      and "def _unique_name" in _sb2)
check(".oce 与 CLI 已移除", not (ROOT / "app" / "oce.py").exists()
      and not (ROOT / "app" / "cli.py").exists())
check("README 写了模块化存储", "collections/<id>.json" in
      (ROOT / "README.md").read_text(encoding="utf-8"))
check("更新内容写了分文件", any("每个集合单独一份" in x for x in ALL_ITEMS))
check("更新内容写了防膨胀", any("防无限膨胀" in x for x in ALL_ITEMS))
check("历史与回收站各自一份文件",
      "\"history\": \"history.json\"" in _st and "\"trash\": \"trash.json\"" in _st)
check("可丢弃的缓存单独放", "SIDE_FILE = \"cache.json\"" in _st)
check("写历史只碰历史文件", "LIST_MODULES" in _st and "_write_lists" in _st)


# ---------------------------------------------------------------- 1.0.75 新增
print("\n[1.0.75 新增]")
_rp2 = (ROOT / "app" / "request_panel.py").read_text(encoding="utf-8")
_mw3 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
_rs3 = (ROOT / "app" / "resmon.py").read_text(encoding="utf-8")
_sb3 = (ROOT / "app" / "sidebar.py").read_text(encoding="utf-8")
_sc3 = (ROOT / "app" / "shortcuts.py").read_text(encoding="utf-8")
_rd3 = (ROOT / "README.md").read_text(encoding="utf-8")
check("新建文件夹不再用不存在的 QPen.setAlphaF",
      "pen.setAlphaF" not in _sb3 and "ring.setAlphaF" in _sb3)
check("生成 Mock 路由收进更多菜单", "生成 Mock 路由" in _rp2
      and "self.mockize_btn" not in _rp2)
check("地址栏只剩保存 / 代码 / 更多", "tl.addWidget(self.mockize_btn)" not in _rp2)
check("内存回收间隔固定 15 分钟", "return DEFAULT_MINUTES" in
      (ROOT / "app" / "memtrim.py").read_text(encoding="utf-8"))
check("设置页去掉间隔与手动按钮", "trim_seg" not in _dlg_src and "trim_now" not in _dlg_src)
check("误关标签留 60 秒草稿", "DRAFT_TTL = 60" in _mw3 and "def _save_draft" in _mw3)
check("重开请求能接回草稿", "self._take_draft(node_id)" in _mw3)
check("⌘⇧T 恢复关闭的标签", "reopen_closed_tab" in _mw3 and "Meta+Shift+T" in _sc3)
check("草稿放 cache.json 不进索引", '"drafts"' in
      (ROOT / "app" / "storage.py").read_text(encoding="utf-8"))
check("Mock 试用后焦点回主窗口", "self.setFocus(Qt.FocusReason.OtherFocusReason)" in _mw3)
check("Mock 胶囊去掉描边", "p.setPen(QPen(C(t.border), 1))" not in _mw3.split("class MockBadge")[-1][:2600])
check("资源管理器有存储说明视角", "def _build_notes" in _rs3 and "存储说明" in _rs3)
check("存储说明讲清每个文件", all(x in _rs3 for x in
      ("state.json", "collections/", "history.json", "trash.json", "cache.json",
       "backups/", "corrupted/")))
check("存储说明讲了保障手段", all(x in _rs3 for x in ("校验和", "临时文件", "隔离")))
check("README 写了存储技术栈与好处", "纯文件" in _rd3 and "hashlib" in _rd3
      and "改一点只写一点" in _rd3)
check("更新内容写了误关恢复", any("误关标签" in x or "⌘⇧T" in x for x in ALL_ITEMS))
check("更新内容写了崩溃修复", any("setAlphaF" in x for x in ALL_ITEMS))
check("更新内容写了存储说明", any("存储说明" in x for x in ALL_ITEMS))


# ---------------------------------------------------------------- 1.0.76 新增
print("\n[1.0.76 新增]")
_sse_src = (ROOT / "app" / "sse_client.py").read_text(encoding="utf-8")
_ssep_src = (ROOT / "app" / "sse_panel.py").read_text(encoding="utf-8")
_rp4 = (ROOT / "app" / "request_panel.py").read_text(encoding="utf-8")
_mw4 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
_ms4 = (ROOT / "app" / "mock_server.py").read_text(encoding="utf-8")
_ma4 = (ROOT / "app" / "mock_ai.py").read_text(encoding="utf-8")
_mp4 = (ROOT / "app" / "mock_panel.py").read_text(encoding="utf-8")
_tr4 = (ROOT / "app" / "transfer.py").read_text(encoding="utf-8")
_rd4 = (ROOT / "README.md").read_text(encoding="utf-8")
check("SSE 客户端是流式的", "QNetworkAccessManager" in _sse_src
      and "readyRead" in _sse_src and "Last-Event-ID" in _sse_src)
check("SSE 解析按规范拆字段", all(x in _sse_src for x in
      ('"data"', '"event"', '"id"', '"retry"')))
check("SSE 有自动重连", "def _reconnect" in _sse_src and "retrying" in _sse_src)
check("SSE 页与 WebSocket 同款骨架", "SseLogView(WsLogView)" in _ssep_src
      and "SegmentedTabs" in _ssep_src)
check("SSE 进了新建菜单", "SSE 请求" in (ROOT / "app" / "sidebar.py").read_text(
      encoding="utf-8") and "SSE_METHOD" in _rp4)
check("SSE 有自己的响应视图", "sse_view" in (ROOT / "app" / "response_panel.py").read_text(
      encoding="utf-8"))
check("SSE 导入导出可往返", '"sse"' in _tr4 and "ensure_sse" in _tr4)
check("Mock 支持循环", "LOOP_OPEN_RE" in _ms4 and "{{/for}}" in _ms4)
check("Mock 支持分页参数", "def page_args" in _ms4 and '"page"' in _ms4)
check("循环展开有上限", "MAX_REPEAT" in _ms4 and "MAX_PAGE_SIZE" in _ms4)
check("AI 会写循环模板", "{{for size}}" in _ma4 and "BODY_PRESETS" in _ma4)
check("AI 响应体对话框", "class BodyAiDialog" in _mp4 and "_ai_body" in _mp4)
check("路由编辑器有例子菜单", "def _examples" in _mp4 and "BODY_SNIPPETS" in _mp4)
check("导入导出恢复成完整面板", "def open_transfer" in _mw4
      and "sidebar.transferRequested" in _mw4 and "TransferDialog(self.store, self)" in _mw4
      and "_import_clipboard" not in _mw4)
check("圆角遮罩用解析区域", "_rounded_region" in _mw4 and "QRegion(0, 0, w, h)" in _mw4)
check("标题栏左右留白一致", "lay.setContentsMargins(16, 0, 16, 0)" in _mw4)
check("改名统一为 Mock 服务", "Mock 数据…" not in (ROOT / "app" / "request_panel.py").read_text(
      encoding="utf-8") and '"Mock 服务…"' in _mw4)
check("README 写了 SSE 与循环", "SSE" in _rd4 and "{{for size}}" in _rd4)
check("更新内容写了 SSE", any("SSE 请求" in x for x in ALL_ITEMS))
check("更新内容写了 Mock 循环", any("{{for size}}" in x for x in ALL_ITEMS))
check("更新内容写了导入导出小弹层", any("小弹层" in x for x in ALL_ITEMS))
check("更新内容写了圆角修复", any("圆角" in x for x in ALL_ITEMS))


# ---------------------------------------------------------------- 1.0.77 新增
print("\n[1.0.77 新增]")
_mw5 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
_sp5 = (ROOT / "app" / "sse_panel.py").read_text(encoding="utf-8")
_sc5 = (ROOT / "app" / "sse_client.py").read_text(encoding="utf-8")
_rp5 = (ROOT / "app" / "request_panel.py").read_text(encoding="utf-8")
_rd5 = (ROOT / "README.md").read_text(encoding="utf-8")

check("圆角遮罩零拷贝", "_rounded_region" in _mw5 and "createAlphaMask" not in _mw5
      and "SmoothTransformation" not in _mw5)
check("界面回调有兜底", "def _guard" in _mw5 and "_guard(\"MainWindow.resizeEvent\"" in _mw5)
check("崩溃现场抄进 crash.log", "_tee_stderr" in (ROOT / "main.py").read_text(encoding="utf-8"))
check("不再用 QRegion 拼圆角", "RegionType.Ellipse" not in _mw5)
check("导入导出恢复完整面板", "TransferDialog(self.store, self)" in _mw5
      and "_import_clipboard" not in _mw5 and "_export_bundle" not in _mw5)
check("分栏可切左右", "def toggle_layout" in _mw5 and "setOrientation(Qt.Orientation.Vertical if horiz" in _mw5)
check("分栏方向记进设置", '"split_layout"' in _mw5)
check("分栏切换有动画", "animate(self, 0.18, ratio, 280" in _mw5)
check("分栏按钮图标会转", "rotate_icon(0.0 if horiz else 90.0, 260)" in _mw5)
check("分栏按钮不挂在 splitter 上", "parent=self.content" in _mw5
      and "parent=self.splitter" not in _mw5)
check("断开按钮变红", 'self.send_btn.set_kind("danger")' in _rp5)
check("Mock 停止服务也变红", "danger" in (ROOT / "app" / "mock_panel.py").read_text(
      encoding="utf-8"))
check("SSE 记下状态码与响应头", "self.status = int(status or 0)" in _sc5
      and "rawHeaderPairs" in _sc5)
check("SSE 失败写错误正文", 'kind="error"' in _sc5 and 'f"HTTP {status}"' in _sc5)
check("SSE 顶部握手条", "def set_stream" in _sp5 and "text/event-stream" in _sp5)
check("SSE 事件名动态筛选", "def _rebuild_chips" in _sp5 and "MAX_CHIPS" in _sp5)
check("SSE 可暂停缓冲", "def toggle_pause" in _sp5 and "_pending" in _sp5)
check("SSE 心跳默认不混进列表", 'if frame.kind == "ping":' in _sp5)
check("SSE 重连显示次数", "def set_retry" in _sp5)
check("README 写了分栏与 SSE 差异", "左右并排" in _rd5 and "握手结果" in _rd5)
check("更新内容写了圆角修复", any("圆角" in x for x in ALL_ITEMS))
check("更新内容写了分栏切换", any("分栏" in x for x in ALL_ITEMS))
check("更新内容写了 SSE 暂停", any("暂停" in x for x in ALL_ITEMS))
check("更新内容写了断开变红", any("断开" in x and "红" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.78 新增
print("\n[1.0.78 新增]")
_mw6 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
_main6 = (ROOT / "main.py").read_text(encoding="utf-8")

check("圆角按圆的方程逐行算", "def _rounded_region" in _mw6 and "math.sqrt" in _mw6)
check("圆角不再开整窗位图", "w * ss" not in _mw6 and "createAlphaMask" not in _mw6)
check("圆角四角各减去细条", "_rounded_region(1320" not in _mw6 and "region -= QRegion(0, y, inset, 1)" in _mw6)
check("窗口回调有兜底", "def _guard" in _mw6
      and '_guard("MainWindow.resizeEvent", self._round_corners)' in _mw6)
check("分栏回调有兜底", '_guard("PanelSplitter.resizeEvent", self.resized.emit)' in _mw6)
check("SSE 状态点自绘有兜底", "_guard(\"SseStatusDot.paintEvent\"" in
      (ROOT / "app" / "sse_panel.py").read_text(encoding="utf-8"))
check("C 层 traceback 抄进 crash.log", "def _tee_stderr" in _main6
      and "os.dup2(write_fd, 2)" in _main6)
check("更新内容写了闪退修复", any("一闪就没了" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.79 新增
print("\n[1.0.79 新增]")
_mw7 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
_sp7 = (ROOT / "app" / "sse_panel.py").read_text(encoding="utf-8")
_sb7 = (ROOT / "app" / "sidebar.py").read_text(encoding="utf-8")
_tp7 = (ROOT / "app" / "tabs.py").read_text(encoding="utf-8")
_th7 = (ROOT / "app" / "theme.py").read_text(encoding="utf-8")

check("状态条浮在内容区不占布局", "bar.setParent(self.content)" in _mw7
      and "def _place_statusbar" in _mw7)
check("分栏按钮挂在 content 与状态条同行", "parent=self.content" in _mw7
      and 'if getattr(self, "_status_on", False)' in _mw7)
check("内容区右缘内缩 1px 对齐标题栏", "self.width() - 1, self.height() - 1" in _mw7)
check("内容区画右下的圆角弧", "path.arcTo" in _mw7 and "radius * 2" in _mw7)
check("SSE 未连接不重复", 'self.status_label.setText("")' in _sp7)
check("更新内容写了五项修复", any("顶上去" in x for x in ALL_ITEMS)
      and any("类型灯" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.80 新增
print("\n[1.0.80 新增]")
_rp8 = (ROOT / "app" / "response_panel.py").read_text(encoding="utf-8")
_wg8 = (ROOT / "app" / "widgets.py").read_text(encoding="utf-8")

check("响应胶囊状态灯可复用", "dot: bool = False" in _wg8
      and "if self._dot:" in _wg8 and "dot=True" in _rp8)
check("侧栏和标签页不再画小点", "paint_kind_dot" not in _sb7
      and "paint_kind_dot" not in _tp7)
check("SSE 控制条并进头部第一行", "self._meta_layout.addWidget(self.sse_view.strip)" in _rp8
      and "self.strip = strip" in _sp7)
check("分栏手柄按方向画线", 'if self.orientation() == Qt.Orientation.Horizontal:' in _mw7
      and 'p.drawLine(x, 4, x, self.height() - 4)' in _mw7)
check("更新内容写了这轮调整", any("状态灯放到" in x for x in ALL_ITEMS)
      and any("控制条不再单独占一行" in x for x in ALL_ITEMS)
      and any("左右分栏看得清" in x for x in ALL_ITEMS))

# ---------------------------------------------------------------- 1.0.81 新增
print("\n[1.0.81 新增]")
_wp8 = (ROOT / "app" / "ws_panel.py").read_text(encoding="utf-8")
_rq8 = (ROOT / "app" / "request_panel.py").read_text(encoding="utf-8")

check("播放按钮归到头部右侧按钮组", 'hl.insertWidget(hl.indexOf(self.more_btn), self.sse_view.pause_btn)' in _rp8
      and '_strip_lay.removeWidget(self.sse_view.pause_btn)' in _rp8)
check("实时空态共用品牌动画", "self.empty_mark = BrandMark" in _wp8
      and "autoplay=True" in _wp8)
check("节点按钮按模式收起", "self.node_btn.setVisible(not realtime)" in _rq8)
check("节点代理只服务 HTTP", "node_proxy" in (ROOT / "app" / "http_client.py").read_text(encoding="utf-8")
      and "node_proxy" not in (ROOT / "app" / "sse_client.py").read_text(encoding="utf-8"))
check("更新内容写了这三项", any("播放 / 暂停按钮挪到" in x for x in ALL_ITEMS)
      and any("三个页面没消息时" in x for x in ALL_ITEMS)
      and any("实时协议页藏起节点" in x for x in ALL_ITEMS))

print(f"\n{len(FAIL)} failed / {TOTAL[0]} checks")
if FAIL:
    for name in FAIL:
        print("  -", name)
sys.exit(1 if FAIL else 0)
