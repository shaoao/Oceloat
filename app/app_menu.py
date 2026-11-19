"""macOS 屏幕顶部的原生应用菜单：关于 / 设置 / 退出。

只在 macOS 上装。QMenuBar 不挂 parent —— 在 macOS 上它就是全局菜单栏，
第一个菜单自动变成粗体的应用菜单；带 MenuRole 的动作会被系统放到该去的
位置并配上标准快捷键（设置 ⌘,、退出 ⌘Q）。

刻意只放基础几项：菜单越长越没人用，设置和关于能找到就够了。
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QMenuBar

APP_MENU_NAME = "Ocelot"


def build_app_menu(window: Any) -> Tuple[QMenuBar, Dict[str, QAction]]:
    """造好菜单但不一定显示 —— macOS 上 QMenuBar() 无 parent 即全局菜单。

    调用方要把返回的 menubar 存到窗口上（保住引用），否则 Python 回收后菜单会消失。
    """
    bar = QMenuBar()
    menu: QMenu = bar.addMenu(APP_MENU_NAME)
    acts: Dict[str, QAction] = {}

    about = menu.addAction("关于 Ocelot")
    about.setMenuRole(QAction.MenuRole.AboutRole)
    about.triggered.connect(lambda: window.show_settings(page="about_app"))
    acts["about"] = about

    prefs = menu.addAction("设置…")
    prefs.setMenuRole(QAction.MenuRole.PreferencesRole)
    prefs.triggered.connect(lambda: window.show_settings())
    acts["settings"] = prefs

    menu.addSeparator()

    quit_act = menu.addAction("退出 Ocelot")
    quit_act.setMenuRole(QAction.MenuRole.QuitRole)
    quit_act.triggered.connect(lambda: window.close())
    acts["quit"] = quit_act

    return bar, acts


def install_app_menu(app: Any, window: Any) -> Any:
    """macOS 才装；任何异常都吞掉，菜单起不来不该拖垮整个应用。"""
    import sys

    if sys.platform != "darwin":
        return None
    try:
        bar, _acts = build_app_menu(window)
        window._native_menubar = bar
        return bar
    except Exception:       # noqa: BLE001
        return None
