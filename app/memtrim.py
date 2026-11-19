"""内存维护：定时回收，把闲置的内存还给系统。

三件事，每次几十毫秒，任意时刻跑都不会卡界面：

1. ``gc.collect()`` 两轮 —— 循环引用第一轮常常收不干净；
2. 丢掉图标 / 图片缓存 —— 都是可再生资源，下次用到重画一次而已；
3. 让分配器把空闲页真的还给系统：macOS 用 ``malloc_zone_pressure_relief``，
   Linux 用 ``malloc_trim``。少了这一步，Python 已经释放的内存仍然挂在进程上，
   任务管理器里一点都不会降。

默认 15 分钟一次，可在「设置 → 通用」里关掉或改成 5 / 30 分钟；同一页还有一颗
「立即释放」，想马上收一次不用等定时器。资源管理器那边只管文件，不再显示内存。
"""
from __future__ import annotations

import gc
import os
import sys
import time
from typing import Any, Dict

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal

# 间隔下限：再短就是无意义的抖动，GC 本身也要花时间
MIN_MINUTES = 5
DEFAULT_MINUTES = 15
MAX_MINUTES = 120

_LAST: Dict[str, Any] = {"at": 0.0, "freed": 0, "entries": 0, "runs": 0, "after": 0}


# ------------------------------------------------------------------ 测量


def _current_rss() -> int:
    """当前常驻内存（字节）。读不到返回 0，界面显示「—」即可，不抛异常。"""
    try:
        with open("/proc/self/statm", "r", encoding="utf-8") as f:
            pages = int(f.read().split()[1])
        return pages * int(os.sysconf("SC_PAGE_SIZE"))
    except Exception:  # noqa: BLE001
        pass
    value = _mac_rss()
    if value:
        return value
    return _peak_rss()


_PROC_LIB: Any = None


def _mac_rss() -> int:
    """macOS：proc_pidinfo(PROC_PIDTASKINFO) 的 pti_resident_size。

    不拉起子进程，2 秒一次也不心疼；受限环境里 ps 常常直接 PermissionError。
    """
    if sys.platform != "darwin":
        return 0
    global _PROC_LIB
    try:
        if _PROC_LIB is None:
            import ctypes
            import ctypes.util

            lib = ctypes.CDLL(ctypes.util.find_library("c") or "/usr/lib/libSystem.B.dylib")
            lib.proc_pidinfo.restype = ctypes.c_int
            lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int,
                                         ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
            _PROC_LIB = (ctypes, lib)
        ctypes, lib = _PROC_LIB
        buf = ctypes.create_string_buffer(128)
        if lib.proc_pidinfo(os.getpid(), 4, 0, buf, ctypes.sizeof(buf)) >= 16:
            return int.from_bytes(buf.raw[8:16], "little")
    except Exception:  # noqa: BLE001
        return 0
    return 0


def _peak_rss() -> int:
    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    except Exception:  # noqa: BLE001
        return 0


def rss() -> int:
    return _current_rss()


# ------------------------------------------------------------------ 动作


def _release_pages() -> None:
    """把分配器里空闲的页交还给系统。失败就算了，不影响功能。"""
    try:
        if sys.platform == "darwin":
            import ctypes
            import ctypes.util

            lib = ctypes.CDLL(ctypes.util.find_library("c") or "/usr/lib/libSystem.B.dylib")
            # zone 传 NULL、goal 传 0 = 所有 zone 能还多少还多少
            lib.malloc_zone_pressure_relief.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            lib.malloc_zone_pressure_relief.restype = ctypes.c_size_t
            lib.malloc_zone_pressure_relief(None, 0)
        elif sys.platform.startswith("linux"):
            import ctypes

            ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:  # noqa: BLE001
        pass


def trim(release_pages: bool = True) -> Dict[str, Any]:
    """立即做一次回收，返回 {before, after, freed, entries, at}。

    在主线程里同步执行，耗时通常 5~40 ms；调用方若担心卡顿，
    可以放到 idle 时机（QTimer.singleShot）再调用。
    """
    before = _current_rss()
    entries = 0
    try:
        from . import icons

        entries = icons.clear_cache()
    except Exception:  # noqa: BLE001
        entries = 0
    gc.collect()
    gc.collect()
    if release_pages:
        _release_pages()
    after = _current_rss()
    report = {
        "before": before,
        "after": after,
        "freed": max(0, before - after),
        "entries": entries,
        "at": time.time(),
    }
    _LAST.update(report)
    _LAST["runs"] = int(_LAST.get("runs") or 0) + 1
    return report


def last_report() -> Dict[str, Any]:
    return dict(_LAST)


def auto_enabled(settings: Dict[str, Any]) -> bool:
    return bool(settings.get("auto_trim", True))


def auto_minutes(settings: Dict[str, Any]) -> int:
    try:
        value = int(settings.get("auto_trim_min", DEFAULT_MINUTES) or DEFAULT_MINUTES)
    except (TypeError, ValueError):
        value = DEFAULT_MINUTES
    return max(MIN_MINUTES, min(MAX_MINUTES, value))


# ------------------------------------------------------------------ 定时器


class AutoTrim(QObject):
    """按设置里的间隔悄悄回收一次。跟主窗口同寿命，设置改动后调 apply()。"""

    trimmed = pyqtSignal(dict)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._timer = QTimer(self)
        # CoarseTimer：省电，这种间隔不需要毫秒精度
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self._run)
        self.apply()

    def apply(self) -> None:
        """重读设置：开关与间隔。关掉就彻底停表，不留后台唤醒。"""
        settings = getattr(self.store, "settings", {}) or {}
        self._timer.setInterval(auto_minutes(settings) * 60_000)
        if auto_enabled(settings):
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def stop(self) -> None:
        self._timer.stop()

    def interval_ms(self) -> int:
        return self._timer.interval()

    def is_active(self) -> bool:
        return self._timer.isActive()

    def _run(self) -> None:
        # 界面正忙时先让一让：等用户这一刻的操作处理完再回收，避免掉帧
        QTimer.singleShot(1200, self._trim_and_emit)

    def _trim_and_emit(self) -> None:
        report = trim()
        self.trimmed.emit(report)
