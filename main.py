"""Ocelot · 为 macOS 开发的 API 调试工具

启动：python3 main.py
"""
#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time

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

_CRASH_FILE = None


def _install_crash_log() -> None:
    """把崩溃现场留下来。

    硬崩（段错误、栈溢出，终端里只会看到 bus error / abort）用 faulthandler 抓，
    普通异常用 excepthook 抓，都写进数据目录的 crash.log —— 否则用户只能贴一句
    「闪退了」，没法查。
    """
    global _CRASH_FILE
    import traceback

    from app.store import APP_DIR

    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        _CRASH_FILE = open(APP_DIR / "crash.log", "a", buffering=1)  # noqa: SIM115
        import faulthandler

        faulthandler.enable(file=_CRASH_FILE, all_threads=True)
    except Exception:                                  # noqa: BLE001
        _CRASH_FILE = None

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        print(text, file=sys.stderr, flush=True)
        if _CRASH_FILE is not None:
            try:
                _CRASH_FILE.write(text + "\n")
            except Exception:                          # noqa: BLE001
                pass

    sys.excepthook = hook


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

    _install_crash_log()
    Store.migrate_legacy()          # 旧版 Reqly 的数据目录搬过来
    store = Store.load()
    set_accent(store.settings.get("accent", "auto"))
    apply_theme(app, theme_by_name(store.settings.get("theme", "dark")))

    # 上次没正常退出（硬崩 / 强杀）时，本次先关掉动画再启动。
    # macOS 上无边框透明窗口 + 图形特效是 SIGBUS 的主要诱因，动画关掉基本绕开；
    # 只是本次生效，不写进设置，下次正常启动会恢复。
    from app.store import APP_DIR

    session = APP_DIR / ".session"
    crashed = session.exists()
    if crashed:
        os.environ["OCELOT_NO_ANIM"] = "1"
        print("[Ocelot] 上次没有正常退出，本次已临时关闭动画以保证稳定。", flush=True)
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        session.write_text(str(time.time()), "utf-8")
    except Exception:                                  # noqa: BLE001
        pass

    window = MainWindow(store)
    window.safe_mode = crashed
    window.show()
    window.raise_()
    window.activateWindow()  # 从 IDE 运行面板启动时也能到最前

    autoquit = os.environ.get("OCELOT_AUTOQUIT") or os.environ.get("REQLY_AUTOQUIT")
    if autoquit:
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(int(autoquit), app.quit)

    code = app.exec()
    try:
        session.unlink()
    except Exception:                                  # noqa: BLE001
        pass
    _shutdown(app, window, code)
    return code


def _shutdown(app, window, code: int) -> None:
    """退出收尾：先拆干净，再直接结束进程。

    退出时偶发的 `zsh: bus error`（crash.log 里是「<no Python frame>」）发生在
    Qt / Cocoa 的析构顺序上，Python 层拦不到：窗口已经关了，但 Python 对象还在
    释放过程中，PyQt 这时再去碰已经销毁的 C++ 对象就会 SIGBUS。所以先把动画、
    图形特效、网络对象、窗口全部停掉、删掉，再 os._exit 直接走人 —— 磁盘上该写
    的在 closeEvent 里已经写完了（状态、草稿），这里不需要 Python 再解释收尾。
    """
    try:
        window.prepare_quit()
    except Exception:                                  # noqa: BLE001
        pass
    try:
        window.hide()
        window.deleteLater()
        app.processEvents()
        app.processEvents()
    except Exception:                                  # noqa: BLE001
        pass
    for stream in (sys.stdout, sys.stderr, _CRASH_FILE):
        try:
            if stream is not None:
                stream.flush()
        except Exception:                              # noqa: BLE001
            pass
    os._exit(int(code or 0))


if __name__ == "__main__":
    sys.exit(main())
