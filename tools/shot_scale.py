"""验证字号设置：点 150% 当场缩放，设置页不关，边上边看。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.dialogs import SettingsDialog  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from app.store import Store  # noqa: E402
from app.theme import apply_theme, theme_by_name  # noqa: E402
from tools.shot import OUT, _isolate_state  # noqa: E402


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    state_path = _isolate_state()
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    store = Store.load(state_path)
    store.settings["ui_scale"] = 1.0
    apply_theme(app, theme_by_name("dark"))
    w = MainWindow(store)
    w.resize(1320, 840)
    w.show()
    out = []

    def grab(widget, name):
        path = os.path.join(OUT, f"{name}.png")
        widget.grab().save(path)
        out.append(path)

    dlg = SettingsDialog(store, w, page="appearance")
    dlg.uiScaleChanged.connect(w._on_scale_applied)

    def step1():
        dlg.show()
        QTimer.singleShot(400, step2)

    def step2():
        grab(dlg, "scale_before")
        grab(w, "scale_main_before")
        dlg.scale_seg.set_current("1.5", emit=True)
        QTimer.singleShot(500, step3)

    def step3():
        grab(dlg, "scale_after")
        page = dlg._page_widgets.get("appearance")
        if page is not None:
            bar = page.verticalScrollBar()
            bar.setValue(bar.maximum())
        QTimer.singleShot(260, step3b)

    def step3b():
        grab(dlg, "scale_appearance_bottom")
        dlg.nav_w = dlg.nav.width()
        dlg.hide()
        QTimer.singleShot(420, step4)

    def step4():
        grab(w, "scale_main_after")
        w.new_request()
        QTimer.singleShot(420, step5)

    def step5():
        w.editor.urlbar.set_url("https://httpbin.org/get?a=1")
        w.editor._on_url("x")
        QTimer.singleShot(360, step6)

    def step6():
        grab(w, "scale_request_after")
        print("scale now", store.settings.get("ui_scale"))
        print("\n".join(out))
        app.quit()

    QTimer.singleShot(700, step1)
    QTimer.singleShot(20000, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
