"""Ocelot · 为 macOS 开发的 API 调试工具

启动：python3 main.py
"""
#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MIN_PY = (3, 10)


def _fail(msg: str, code: int = 2) -> None:
    """在 IDE 的运行面板里给出可读的中文提示，而不是一大段 traceback。"""
    print(f"\n[Ocelot] {msg}\n", file=sys.stderr, flush=True)
    raise SystemExit(code)


if sys.version_info < MIN_PY:
    _fail(f"需要 Python {MIN_PY[0]}.{MIN_PY[1]} 及以上，当前是 {sys.version.split()[0]}。\n"
          f"  当前解释器：{sys.executable}\n"
          f"  请改用：python3 main.py（或在 IDE 里把运行解释器换成装了 PyQt6 的 3.13）")

try:
    from PyQt6.QtCore import Qt  # noqa: E402
    from PyQt6.QtWidgets import QApplication  # noqa: E402
except ModuleNotFoundError as exc:  # 运行按钮用的解释器没装依赖时最常见
    _fail(f"当前解释器缺少 {exc.name}，无法启动界面。\n"
          f"  当前解释器：{sys.executable}\n"
          f"  修复：\n"
          f"    {sys.executable} -m pip install PyQt6\n"
          f"  或者用装了依赖的解释器启动：python3 main.py")

from app.main_window import MainWindow  # noqa: E402
from app.store import Store  # noqa: E402
from app.theme import apply_theme, set_accent, theme_by_name  # noqa: E402


def main() -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, False)
    app = QApplication(sys.argv)
    app.setApplicationName("Ocelot")
    app.setApplicationDisplayName("Ocelot")
    app.setOrganizationName("Ocelot")
    app.setStyle("Fusion")

    Store.migrate_legacy()          # 旧版 Reqly 的数据目录搬过来
    store = Store.load()
    set_accent(store.settings.get("accent", "auto"))
    apply_theme(app, theme_by_name(store.settings.get("theme", "dark")))

    window = MainWindow(store)
    window.show()
    window.raise_()
    window.activateWindow()  # 从 IDE 运行面板启动时也能到最前

    autoquit = os.environ.get("OCELOT_AUTOQUIT") or os.environ.get("REQLY_AUTOQUIT")
    if autoquit:
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(int(autoquit), app.quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
