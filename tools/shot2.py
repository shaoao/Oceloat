"""补充截图：方法菜单 / 设置各页 / 命令面板悬停 / Tooltip 样式。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMenu, QToolTip  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from app.store import Store  # noqa: E402
from app.theme import apply_theme, theme_by_name  # noqa: E402
from tools.shot import OUT, _isolate_state  # noqa: E402


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    state_path = _isolate_state()
    states = sys.argv[1:] or ["method_menu"]
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    store = Store.load(state_path)
    apply_theme(app, theme_by_name("dark"))
    w = MainWindow(store)
    w.resize(1320, 840)
    w.show()
    results = []

    def grab_widget(widget, name):
        path = os.path.join(OUT, f"{name}.png")
        widget.grab().save(path)
        results.append(path)

    def find_node(keyword):
        for n, _ in store.walk():
            if n.get("type") == "request" and keyword in (n.get("name") or ""):
                return n
        return None

    def run(i: int = 0):
        if i >= len(states):
            app.quit()
            return
        st = states[i]
        node = find_node("Query Params")

        if st == "timing_card":
            from app.http_client import Response as RS
            from PyQt6.QtCore import QEvent

            r = RS(status=200, body='{"ok":true}'.encode(), content_type="application/json",
                   url="https://example.com/j", elapsed=435, size=512,
                   timing={"prepare": 3, "dns": 26, "tcp": 8, "ssl": 11,
                           "ttfb": 355, "download": 4, "process": 0}, header_size=379)
            w.response.set_response(r)
            def tshot():
                card = w.response._timing_card()
                card.show_at(QPoint(300, 330))
                QTimer.singleShot(180, lambda: (grab_widget(card, "timing_card"), card.hide(),
                                                run(i + 1)))
            QTimer.singleShot(300, tshot)
            return
        elif st == "size_card":
            from app.http_client import Response as RS2
            from PyQt6.QtCore import QEvent

            r = RS2(status=200, body=b"x" * 154, content_type="text/plain",
                    url="https://example.com/t", elapsed=120, size=533, header_size=379)
            w.response.set_response(r)
            def sshot():
                card = w.response._size_card()
                card.show_at(QPoint(300, 330))
                QTimer.singleShot(180, lambda: (grab_widget(card, "size_card"), card.hide(),
                                                run(i + 1)))
            QTimer.singleShot(300, sshot)
            return
        elif st == "encoding_menu":
            from app.http_client import Response as RS3

            r = RS3(status=200, body='{"msg":"晚间时间到"}'.encode(),
                    content_type="application/json; charset=utf-8",
                    url="https://example.com/j", elapsed=432, size=200)
            w.response.set_response(r)
            def eshot():
                w.response._choose_encoding()
                for t in QApplication.topLevelWidgets():
                    if isinstance(t, QMenu) and t.isVisible():
                        grab_widget(t, "encoding_menu")
                        t.close()
                        break
                run(i + 1)
            QTimer.singleShot(300, eshot)
            return
        elif st == "loading":
            if node:
                w._open_from_sidebar(node)
            w._update_stack()
            w.response.show_loading()
            QTimer.singleShot(320, lambda: (grab_widget(w, "loading"), run(i + 1)))
            return
        elif st == "english_main":
            from app import i18n

            i18n.set_language("en", notify=False)
            w._retranslate("en")
            QTimer.singleShot(320, lambda: (grab_widget(w, "english_main5"), run(i + 1)))
            return
        if st == "method_menu":
            from app.request_panel import MethodMenu

            if node:
                w._open_from_sidebar(node)
            sel = w.editor.urlbar.method
            m = MethodMenu(sel.method(), w)
            m.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            m.popup(sel.mapToGlobal(QPoint(sel.rect().left(), sel.rect().bottom() + 4)))
            QTimer.singleShot(360, lambda: (grab_widget(m, "method_menu"), m.close(), run(i + 1)))
            return
        elif st.startswith("settings_"):
            from app.dialogs import SettingsDialog

            page = st.split("_", 1)[1]
            dlg = SettingsDialog(store, w, page=page)
            dlg.show()
            QTimer.singleShot(340, lambda: (grab_widget(dlg, st), dlg.close(), run(i + 1)))
            return
        elif st == "whatsnew":
            from app.dialogs import WhatsNewDialog

            dlg = WhatsNewDialog(w)
            dlg.show()
            QTimer.singleShot(340, lambda: (grab_widget(dlg, "whatsnew2"), dlg.close(), run(i + 1)))
            return
        elif st == "palette_hover":
            w.show_palette()
            app.processEvents()
            w.palette.edit.setText("请求")

            def anim():
                pl = w.palette.list
                pl._hover = 2
                pl._hover_v = 1.0
                pl.update()
                QTimer.singleShot(320, lambda: (grab_widget(w.palette, "palette_hover"),
                                                w.palette.close(), run(i + 1)))

            QTimer.singleShot(260, anim)
            return
        elif st == "preview_image":
            from PyQt6.QtCore import QBuffer, QByteArray
            from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap

            if node:
                w._open_from_sidebar(node)
            pm = QPixmap(560, 300)
            g = QLinearGradient(0, 0, 560, 300)
            g.setColorAt(0, QColor("#2b3a44"))
            g.setColorAt(1, QColor("#16202a"))
            p = QPainter(pm)
            p.fillRect(pm.rect(), g)
            p.setPen(QColor("#EDEDF1"))
            p.setFont(QFont("Helvetica Neue", 22))
            p.drawText(pm.rect(), int(Qt.AlignmentFlag.AlignCenter), "图片预览 · 560 × 300")
            p.end()
            ba = QByteArray()          # 必须保住引用，否则 QBuffer 指向已释放内存直接崩
            buf = QBuffer(ba)
            buf.open(QBuffer.OpenModeFlag.WriteOnly)
            pm.save(buf, "PNG")
            buf.close()
            data = bytes(ba)
            from app.http_client import Response as R5

            w.response.set_response(R5(status=200, body=data, elapsed=88, size=len(data),
                                       url="https://api.example.com/cover.png", reason="OK",
                                       headers=[("content-type", "image/png")],
                                       content_type="image/png"))
            w.response.tabs.set_current("preview", emit=True)
            w.response._on_tab("preview")
            QTimer.singleShot(420, lambda: (grab_widget(w, "preview_image"), run(i + 1)))
            return
        elif st == "audio":
            import io
            import math
            import struct
            import wave

            if node:
                w._open_from_sidebar(node)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(8000)
                wf.writeframes(b"".join(
                    struct.pack("<h", int(6000 * math.sin(i / 8.0)))
                    for i in range(8000 * 3)))
            data = buf.getvalue()
            from app.http_client import Response as R6

            w.response.set_response(R6(status=200, body=data, elapsed=132, size=len(data),
                                       url="https://api.example.com/voice.wav", reason="OK",
                                       headers=[("content-type", "audio/wav")],
                                       content_type="audio/wav"))
            w.response.tabs.set_current("preview", emit=True)
            w.response._on_tab("preview")
            QTimer.singleShot(700, lambda: (grab_widget(w, "audio"), run(i + 1)))
            return
        elif st == "sidebar_hidden":
            if node:
                w._open_from_sidebar(node)
            w.toggle_sidebar()
            QTimer.singleShot(520, lambda: (grab_widget(w, "sidebar_hidden"), run(i + 1)))
            return
        elif st == "live_local":
            import json
            import threading
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

            payload = {"ok": True, "name": "Reqly", "count": 3,
                       "items": [{"id": 1, "tag": "alpha"}, {"id": 2, "tag": "beta"}],
                       "中文": "你好世界"}

            class H(BaseHTTPRequestHandler):
                def do_GET(self):  # noqa: N802
                    body = json.dumps(payload, ensure_ascii=False).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *a):
                    pass

            srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            if node:
                w._open_from_sidebar(node)
            else:
                w.new_request()
            w.editor.urlbar.url.setText(f"http://127.0.0.1:{srv.server_port}/json")
            w.send_current()

            def after():
                grab_widget(w, "live_local")
                srv.shutdown()
                run(i + 1)

            QTimer.singleShot(1600, after)
            return
        elif st == "nodes_live":
            from app.node_panel import NodePicker
            from app.nodes import NodeBook

            if node:
                w._open_from_sidebar(node)
            book = NodeBook(store)
            picker = NodePicker(book, w)
            picker.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            picker.refresh_nodes()

            def shot():
                grab_widget(picker, "nodes_live")
                picker.close()
                run(i + 1)

            QTimer.singleShot(3200, shot)
            return
        elif st == "binary_pretty":
            if node:
                w._open_from_sidebar(node)
            from app.http_client import Response as R9

            png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                   b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                   b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
                   b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
            w.response.set_response(R9(status=200, body=png, elapsed=91, size=len(png),
                                       url="https://example.com/a.png", reason="OK",
                                       headers=[("content-type", "image/png")],
                                       content_type="image/png"))
            w.response.tabs.set_current("pretty", emit=True)
            w.response._on_tab("pretty")
            QTimer.singleShot(380, lambda: (grab_widget(w, "binary_pretty"), run(i + 1)))
            return
        elif st == "ctxmenu":
            from app.ctxmenu import _menu_for

            def popup():
                edit = w.editor.urlbar.url
                edit.setSelection(0, 3)
                m = _menu_for(edit)
                m.popup(edit.mapToGlobal(QPoint(20, edit.height())))
                QTimer.singleShot(240, lambda: (grab_widget(m, "ctxmenu"), m.close(), run(i + 1)))

            QTimer.singleShot(320, popup)
            return
        elif st == "tooltip":
            if node:
                w._open_from_sidebar(node)
            QTimer.singleShot(300, lambda: _tooltip(i))
            return
        run(i + 1)

    def _tooltip(i):
        from PyQt6.QtCore import QEvent

        from app.tooltip import TipLabel

        btn = w.editor.urlbar.code_btn
        QApplication.sendEvent(btn, QEvent(QEvent.Type.ToolTip))
        def shot():
            for t in QApplication.topLevelWidgets():
                if isinstance(t, TipLabel) and t.isVisible():
                    grab_widget(t, "tooltip")
                    t.hide()
                    break
            run(i + 1)
        QTimer.singleShot(300, shot)

    QTimer.singleShot(900, lambda: run(0))
    QTimer.singleShot(20000, app.quit)
    code = app.exec()
    print("\n".join(results))
    return code


if __name__ == "__main__":
    sys.exit(main())
