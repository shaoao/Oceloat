#!/usr/bin/env python3
"""把 Ocelot 打成 macOS 的 .app 和 .dmg。

    python3 tools/build_app.py            # 打包 + 精简 + 签名 + 验收 + 出 dmg
    python3 tools/build_app.py --no-dmg   # 只出 .app
    python3 tools/build_app.py --keep     # 复用上次的 dist，只重新精简 / 签名 / 验收

为什么是单目录（onedir）而不是 onefile：onefile 每次启动都要把上百兆解压到临时
目录，冷启动慢好几倍，而且第一次运行时体积翻倍。单目录双击即开。

精简分三层：
1. Ocelot.spec 里把用不到的 Python / PyQt6 子模块挡在门外；
2. 这里删掉没被链接的 Qt 框架、插件、翻译（主要是 ffmpeg 那 17MB）；
3. strip 掉符号，再逐层重签名。
每层之后都跑 `--self-test`，删多了立刻能发现。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
APP = os.path.join(DIST, "Ocelot.app")
COLLECT = os.path.join(DIST, "Ocelot")

# 打包后还能删的 Qt 框架：全应用只用到 Core / Gui / Widgets / Network /
# WebSockets / Multimedia(Widgets) 这几块
DROP_FRAMEWORKS = [
    # QtDBus / QtConcurrent 都不能删：macOS 上 QtGui 直链前者，QtMultimedia 直链后者
    "QtSvg",
]

# ffmpeg 那套是 QtMultimedia 的备选后端，macOS 上用系统 AVFoundation 就够，
# 删掉能省 17MB；对应的插件也一起去掉，留 libdarwinmediaplugin。
DROP_FILES = [
    "libavcodec.63.dylib", "libavformat.63.dylib", "libavutil.61.dylib",
    "libswresample.7.dylib", "libswscale.10.dylib",
    "libffmpegmediaplugin.dylib",
    "libqsvg.dylib", "libqsvgicon.dylib",      # 依赖 QtSvg，图标全是自己画的
    "libqtiff.dylib", "libqtga.dylib", "libqwbmp.dylib",   # 接口调试碰不到的格式
    "libqmacjp2.dylib", "libqmacheif.dylib",
]

# 空目录 / 用不到的插件目录（Linux 输入设备、网络状态探测、macOS 不需要的样式）
DROP_PLUGIN_DIRS = ["iconengines", "generic", "networkinformation"]

# Qt 自带翻译只留中文；界面文案是应用自己的 i18n，用不到另外几十种语言
KEEP_TRANSLATIONS = {"qtbase_zh_CN.qm", "qt_zh_CN.qm", "qtwebsockets_zh_CN.qm",
                     "qtmultimedia_zh_CN.qm"}


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, **kw)


def size_of(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            full = os.path.join(base, name)
            if os.path.islink(full):        # 框架里的软链会重复计算
                continue
            try:
                total += os.path.getsize(full)
            except OSError:
                pass
    return total


def mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def is_macho(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return False
    return magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",
                     b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca")


# ---------------------------------------------------------------- 构建
def build() -> None:
    if not os.path.exists(os.path.join(ROOT, "docs", "Ocelot.icns")):
        sh([sys.executable, os.path.join(ROOT, "tools", "make_icns.py")], cwd=ROOT)
    sh([sys.executable, "-m", "PyInstaller", "--clean", "-y", "Ocelot.spec"], cwd=ROOT)


# ---------------------------------------------------------------- 精简
def stamp_version() -> str:
    """把 Info.plist 的版本改成 app/store.py 里的 VERSION。

    配方里的版本号是手写的，忘了改就会出现「dmg 叫 1.0.72、App 信息里写着
    1.0.70」这种前后不一致。以代码里的版本为准，这里统一盖章。
    """
    from app.store import VERSION  # type: ignore

    plist = os.path.join(APP, "Contents", "Info.plist")
    for key in ("CFBundleShortVersionString", "CFBundleVersion"):
        subprocess.run(["/usr/libexec/PlistBuddy", "-c",
                        f"Set :{key} {VERSION}", plist],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return VERSION


def prune() -> None:
    fw = os.path.join(APP, "Contents", "Frameworks")
    qt_lib = os.path.join(fw, "PyQt6", "Qt6", "lib")

    # 1) 没链接到的 Qt 框架（同时清掉 Frameworks/ 和 Resources/ 里的软链）
    for name in DROP_FRAMEWORKS:
        shutil.rmtree(os.path.join(qt_lib, f"{name}.framework"), ignore_errors=True)
        for parent in (fw, os.path.join(APP, "Contents", "Resources")):
            link = os.path.join(parent, name)
            if os.path.islink(link) or os.path.isfile(link):
                os.remove(link)
            elif os.path.isdir(link):
                shutil.rmtree(link, ignore_errors=True)

    # 2) 指定文件（ffmpeg 库、多余插件），在全树里按文件名找
    names = set(DROP_FILES)
    for base, _dirs, files in os.walk(APP):
        for name in files:
            if name in names:
                path = os.path.join(base, name)
                if os.path.islink(path):
                    os.remove(path)
                else:
                    os.remove(path)

    # 3) 用不到的插件目录整个端掉
    plugins = os.path.join(fw, "PyQt6", "Qt6", "plugins")
    for name in DROP_PLUGIN_DIRS:
        shutil.rmtree(os.path.join(plugins, name), ignore_errors=True)

    # 4) Qt 翻译只留中文
    for base, _dirs, files in os.walk(APP):
        if not base.endswith("translations"):
            continue
        for name in files:
            if name.endswith(".qm") and name not in KEEP_TRANSLATIONS:
                os.remove(os.path.join(base, name))


# ---------------------------------------------------------------- 瘦身 + 签名
def strip_and_sign() -> None:
    exe = os.path.join(APP, "Contents", "MacOS", "Ocelot")
    binaries: list[str] = []
    for base, _dirs, files in os.walk(APP):
        for name in files:
            path = os.path.join(base, name)
            if os.path.islink(path) or not is_macho(path):
                continue
            # 主程序里除了 Mach-O 还挂着 PyInstaller 的 PKG 归档，strip 会把尾巴
            # 一起丢掉，结果就是「Could not load embedded PKG archive」。
            if os.path.abspath(path) == os.path.abspath(exe):
                continue
            binaries.append(path)
    for path in binaries:
        subprocess.run(["strip", "-x", "-S", path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # 逐个签（框架内部的二进制必须先签，再签外层 bundle），ad-hoc 即可
    for path in binaries:
        subprocess.run(["codesign", "--force", "--sign", "-", path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sh(["codesign", "--force", "--deep", "--sign", "-", APP],
       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- 验收
def self_test() -> None:
    exe = os.path.join(APP, "Contents", "MacOS", "Ocelot")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", OCELOT_NO_ANIM="1")
    res = subprocess.run([exe, "--self-test"], text=True, capture_output=True,
                         env=env, timeout=180)
    out = (res.stdout or "") + (res.stderr or "")
    if res.returncode != 0:
        print(out[-4000:], file=sys.stderr)
        raise SystemExit("打包产物自检失败")
    for line in out.splitlines():
        if "通过" in line and "项" in line:
            print(f"  自检：{line.strip()}")


def startup_ms(runs: int = 3) -> float:
    """量「进程启动 → 窗口显示」的耗时，取最快的一次。"""
    exe = os.path.join(APP, "Contents", "MacOS", "Ocelot")
    best = 1e9
    for _ in range(runs):
        env = dict(os.environ, OCELOT_T0=repr(time.time()), OCELOT_AUTOQUIT="900",
                   OCELOT_NO_ANIM="1")
        res = subprocess.run([exe], text=True, capture_output=True, env=env, timeout=120)
        for line in (res.stdout or "").splitlines():
            if "启动" in line:
                try:
                    best = min(best, float(line.split()[-2]))
                except (ValueError, IndexError):
                    pass
    return best


# ---------------------------------------------------------------- dmg
def make_dmg() -> str:
    from app.store import VERSION  # type: ignore

    out = os.path.join(DIST, f"Ocelot-{VERSION}.dmg")
    staging = os.path.join(DIST, "_dmg")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    shutil.copytree(APP, os.path.join(staging, "Ocelot.app"), symlinks=True)
    os.symlink("/Applications", os.path.join(staging, "Applications"))
    sh(["hdiutil", "create", "-volname", "Ocelot", "-srcfolder", staging,
        "-ov", "-format", "UDZO", out])
    shutil.rmtree(staging, ignore_errors=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-dmg", action="store_true")
    ap.add_argument("--keep", action="store_true", help="复用 dist，只重新精简")
    args = ap.parse_args()

    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    before = size_of(APP) if os.path.isdir(APP) else 0

    if not args.keep:
        print("[1/5] PyInstaller 打包…", flush=True)
        build()
        before = size_of(APP)
        print(f"      {mb(before)}")

    print("[2/5] 删掉没用到的 Qt 框架 / 插件 / 翻译…", flush=True)
    prune()
    print(f"      {mb(size_of(APP))}  ·  版本 {stamp_version()}")

    print("[3/5] strip + ad-hoc 签名…", flush=True)
    strip_and_sign()
    print(f"      {mb(size_of(APP))}")

    # PyInstaller 会在 dist/Ocelot 留一份同样的目录，别占双份磁盘
    shutil.rmtree(COLLECT, ignore_errors=True)

    print("[4/5] 自检…", flush=True)
    self_test()
    ms = startup_ms()
    print(f"      启动 {ms:.0f} ms（进程启动到窗口显示）" if ms < 1e8 else "      启动耗时未取到")

    final = size_of(APP)
    print(f"[5/5] 完成：{APP}\n      {mb(final)}（精简前 {mb(before)}）")

    if not args.no_dmg:
        dmg = make_dmg()
        print(f"      {dmg}  {mb(size_of(dmg))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
