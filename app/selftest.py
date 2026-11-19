"""打包后的自检：证明 bundle 里的 Qt 模块、平台插件、Mock 服务、WebSocket 都在。

`python3 main.py --self-test` 会走一遍；打包脚本拿它验收 .app。
每一项都真的跑起来，不做静态判断。
"""
from __future__ import annotations

import json
import os
import socket
import sys
import urllib.request

RESULTS: list[tuple[str, bool, str]] = []


def _mark(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{('  ' + detail) if detail else ''}", flush=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def check_imports() -> None:
    """把 app/ 下每个模块都导一遍：少一个 Qt 子模块这里就炸。"""
    import pkgutil

    import app as pkg

    bad: list[str] = []
    for mod in pkgutil.iter_modules(pkg.__path__):
        try:
            __import__(f"app.{mod.name}")
        except Exception as exc:                        # noqa: BLE001
            bad.append(f"{mod.name}: {exc}")
    _mark("app 下全部模块可导入", not bad, "; ".join(bad[:3]))


def check_qt_modules() -> None:
    """WebSocket / 多媒体是可选模块，缺了对应页面会降级，这里单独点名。"""
    from PyQt6.QtWebSockets import QWebSocket

    sock = QWebSocket()
    sock.close()
    _mark("QtWebSockets 可用", True)

    try:
        from PyQt6.QtMultimedia import QMediaPlayer

        player = QMediaPlayer()
        player.deleteLater()
        _mark("QtMultimedia 可用", True)
    except Exception as exc:                            # noqa: BLE001
        _mark("QtMultimedia 可用（缺了就降级为另存为）", False, str(exc))


def check_media() -> None:
    """真的加载一个音频文件：确认多媒体后端插件还能用（打包时裁掉了 ffmpeg 那一份）。"""
    import struct
    import tempfile
    import wave

    from PyQt6.QtCore import QEventLoop, QTimer, QUrl

    try:
        from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    except Exception as exc:                            # noqa: BLE001
        _mark("多媒体后端能加载文件（缺了就降级为另存为）", False, str(exc))
        return

    path = os.path.join(tempfile.mkdtemp(prefix="ocelot-media-"), "tick.wav")
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"".join(struct.pack("<h", 0) for _ in range(800)))

    player = QMediaPlayer()
    player.setAudioOutput(QAudioOutput())
    player.setSource(QUrl.fromLocalFile(path))

    # 无头环境没有声卡，darwin 后端会停在 LoadingMedia —— 那也说明它认了这个文件，
    # 后端整个缺失时是 NoMedia / InvalidMedia。
    done = (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.LoadingMedia)
    dead = QMediaPlayer.MediaStatus.InvalidMedia, QMediaPlayer.MediaStatus.NoMedia
    state = {"status": player.mediaStatus()}

    def on_status(status):
        state["status"] = status
        # LoadingMedia 只是过程态，等它落到 LoadedMedia / InvalidMedia 再判定
        if status in done or status in dead:
            loop.quit()

    loop = QEventLoop()
    QTimer.singleShot(3000, loop.quit)
    player.mediaStatusChanged.connect(on_status)
    player.errorOccurred.connect(lambda _e, _s="": loop.quit())
    loop.exec()
    ok = state["status"] in done
    _mark("多媒体后端能加载文件", ok, str(state["status"]).split(".")[-1])
    player.deleteLater()


def check_mock() -> None:
    """真的起一个服务、真的发一次请求。"""
    from app.mock_server import MockServer, route

    port = _free_port()
    srv = MockServer("selftest", "自检")
    ok, msg = srv.start([route("自检接口", "GET", "/ping", body='{"pong": true}')], port=port)
    if not ok:
        _mark("Mock 服务能启动", False, msg)
        return
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=5) as resp:
            payload = json.loads(resp.read().decode())
        _mark("Mock 服务能启动", payload == {"pong": True}, f"port {port}")
    except Exception as exc:                            # noqa: BLE001
        _mark("Mock 服务能启动", False, str(exc))
    finally:
        srv.stop()


def check_window() -> None:
    """窗口构造 + 离屏渲染一张图：平台插件、字体、自绘控件都过一遍。"""
    from PyQt6.QtCore import QEventLoop, QTimer

    from app.main_window import MainWindow
    from app.store import Store

    loop = QEventLoop()
    QTimer.singleShot(120, loop.quit)
    loop.exec()

    win = MainWindow(Store.load())
    try:
        win.resize(1200, 800)
        pm = win.grab()
        _mark("主窗口能渲染", not pm.isNull() and pm.width() > 100,
              f"{pm.width()}x{pm.height()}")
    finally:
        win.hide()
        win.deleteLater()


def run() -> int:
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.processEvents()
    print("[Ocelot 自检]", flush=True)
    for fn in (check_imports, check_qt_modules, check_media, check_mock, check_window):
        try:
            fn()
        except Exception as exc:                        # noqa: BLE001
            _mark(fn.__name__, False, repr(exc))
    bad = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(bad)} 通过 / {len(RESULTS)} 项"
          f"{'，失败：' + '、'.join(bad) if bad else ''}", flush=True)
    return 1 if bad else 0
