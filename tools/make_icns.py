"""把品牌标识导出成 docs/Ocelot.icns（打包用）。

用法：python3 tools/make_icns.py
母图用 app.brand.app_icon() 的 1024pt 位图（2048px），再按 Apple 要求的
十个尺寸缩放，交给 iconutil 合成。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "Ocelot.icns")

# iconutil 要求的文件名 → 像素边长
SIZES = {
    "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
}


def main() -> int:
    app = QApplication(sys.argv[:1])
    from app.theme import apply_theme, theme_by_name

    apply_theme(app, theme_by_name("dark"))
    from app.brand import app_icon

    master_pm = app_icon().pixmap(1024, 1024)
    master = master_pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    if master.width() < 1024:
        master = master.scaled(1024, 1024, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)

    tmp = tempfile.mkdtemp(prefix="ocelot-icns-")
    iconset = os.path.join(tmp, "Ocelot.iconset")
    os.makedirs(iconset)
    for name, px in SIZES.items():
        img = master.scaled(px, px, Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        img.save(os.path.join(iconset, name), "PNG")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", OUT], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"{OUT}  {os.path.getsize(OUT) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
