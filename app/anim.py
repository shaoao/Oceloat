"""动画工具：安全停止（Qt 已删除底层对象时不再抛错）+ 全局动效开关。"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QVariantAnimation

_FLAGS = {"animations": True}


def set_animations(on: bool) -> None:
    _FLAGS["animations"] = bool(on)


def animations_on() -> bool:
    return _FLAGS["animations"]


def stop(anim: Optional[QVariantAnimation]) -> None:
    if anim is None:
        return
    try:
        anim.stop()
    except RuntimeError:
        pass


def running(anim: Optional[QVariantAnimation]) -> bool:
    if anim is None:
        return False
    try:
        return anim.state() == QVariantAnimation.State.Running
    except RuntimeError:
        return False
