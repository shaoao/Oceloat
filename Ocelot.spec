# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 配方：单目录 + .app，能裁的都裁掉。

体积和启动速度都靠两件事：一是这里把用不到的模块挡在外面（Python 层和 PyQt6
子模块），二是 tools/build_app.py 打包后再把 Qt 里没被链接的框架和插件删掉。
不做 onefile —— 它每次启动都要把上百兆解到临时目录，冷启动会慢一个数量级。
"""
import pkgutil

import PyQt6

# 实际用到的 Qt 模块。QtMultimedia / QtWebSockets 是可选功能（响应的音视频预览、
# WebSocket 页签），缺了会降级，所以必须带上。
KEEP_QT = {
    "QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtWebSockets",
    "QtMultimedia", "QtMultimediaWidgets", "sip",
}

EXCLUDES = [
    f"PyQt6.{m.name}" for m in pkgutil.iter_modules(PyQt6.__path__)
    if m.name not in KEEP_QT
]
EXCLUDES += [
    # 标准库里用不到、但会被顺手拖进来的大件
    "tkinter", "_tkinter", "turtle", "turtledemo", "idlelib",
    "unittest", "doctest", "pydoc", "pydoc_data", "test",
    "lib2to3", "distutils", "setuptools", "pkg_resources", "pip", "wheel",
    "ensurepip", "sqlite3", "_sqlite3", "dbm", "curses", "_curses",
    "multiprocessing", "asyncio", "_asyncio",
    "xmlrpc", "ftplib", "smtplib", "poplib", "imaplib", "telnetlib",
    "this", "antigravity", "turtle demo",
]

HIDDEN = [
    "PyQt6.QtWebSockets", "PyQt6.QtMultimedia", "PyQt6.QtMultimediaWidgets",
    "app.selftest",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Ocelot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="docs/Ocelot.icns",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Ocelot",
)

app = BUNDLE(
    coll,
    name="Ocelot.app",
    icon="docs/Ocelot.icns",
    bundle_identifier="com.shaoao.ocelot",
    version="1.0.70",
    info_plist={
        "CFBundleName": "Ocelot",
        "CFBundleDisplayName": "Ocelot",
        "CFBundleShortVersionString": "1.0.70",
        "CFBundleVersion": "1.0.70",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.developer-tools",
        "NSHumanReadableCopyright": "MIT License",
        "NSRequiresAquaSystemAppearance": False,
    },
)
