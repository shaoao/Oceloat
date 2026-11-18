"""本轮验收截图：WS 独立页 / 握手头 / 方法下拉 / 命令面板 / 设置外观。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QPoint, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from app.store import Store  # noqa: E402
from app.theme import apply_theme, theme_by_name  # noqa: E402
from tools.shot import OUT, _isolate_state  # noqa: E402


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    state_path = _isolate_state()
    states = sys.argv[1:] or ["ws", "ws_headers", "method_menu", "palette", "appearance"]
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    store = Store.load(state_path)
    apply_theme(app, theme_by_name("dark"))
    w = MainWindow(store)
    w.resize(1320, 840)
    w.show()
    out = []

    def grab(widget, name):
        path = os.path.join(OUT, f"{name}.png")
        widget.grab().save(path)
        out.append(path)

    def run(i: int = 0):
        if i >= len(states):
            print("\n".join(out))
            app.quit()
            return
        st = states[i]
        if st in ("ws", "ws_headers"):
            w.new_websocket()
            w.editor.urlbar.set_url("wss://echo.websocket.events/")
            w.editor._on_url("x")
            if st == "ws_headers":
                w.editor._open_ws_headers()
                w.editor._ws_headers_popup.editor.set_rows([
                    {"key": "Authorization", "value": "Bearer token", "enabled": True},
                    {"key": "Origin", "value": "https://ocelot.app", "enabled": True},
                ])
                QTimer.singleShot(360, lambda: (
                    grab(w.editor._ws_headers_popup, "shot_ws_headers_popup"),
                    run(i + 1)))
                return
            QTimer.singleShot(420, lambda: (grab(w, f"shot_{st}"), run(i + 1)))
            return
        if st == "cards":
            from app.ws_client import WsFrame

            w.new_websocket()
            w.editor.urlbar.set_url("wss://echo.websocket.org")
            w.editor._on_url("x")
            w.editor.set_ws_state("open")
            w.response.ws_set_state("open", {"uptime": 64.2, "bytes_in": 58})
            view = w.response.ws_view
            import time

            for k, text in enumerate(("hello", '{"123":23,"128793":23,"167823":23}',
                                      "ni'hs'i'shei")):
                view.add_frame(WsFrame("in" if k % 2 == 0 else "out", "json" if k == 1 else "text",
                                       text.encode(), time.time() + k * 0.3, len(text)))
            app.processEvents()
            view.list.toggle(0)
            view.list.toggle(1)
            def grab_cards():
                grab(w, "shot_ws_cards")
                view.scroll.verticalScrollBar().setValue(int(view.list._tops[1]))
                QTimer.singleShot(300, lambda: (
                    grab(w, "shot_ws_cards_json"), run(i + 1)))

            QTimer.singleShot(420, grab_cards)
            return
        if st == "method_menu":
            w.new_request()
            QTimer.singleShot(320, lambda: menu_step(i))
            return
        if st == "palette":
            QTimer.singleShot(360, lambda: (w.palette.open(), QTimer.singleShot(
                420, lambda: (grab(w, "shot_palette"), run(i + 1)))))
            return
        if st == "appearance":
            QTimer.singleShot(320, lambda: app_step(i))
            return
        run(i + 1)

    def menu_step(i):
        w.editor.urlbar.method._open_menu()
        menu = w.editor.urlbar.method._menu
        menu.grab().save(os.path.join(OUT, "shot_method_menu.png"))
        out.append(os.path.join(OUT, "shot_method_menu.png"))
        QTimer.singleShot(240, lambda: (menu.close(), run(i + 1)))

    def app_step(i):
        w.show_settings("appearance")
        QTimer.singleShot(420, lambda: (grab(w.settings_dialog, "shot_appearance"),
                                        QTimer.singleShot(200, lambda: (
                                            w.settings_dialog.close(), run(i + 1)))))

    QTimer.singleShot(700, lambda: run(0))
    QTimer.singleShot(20000, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
