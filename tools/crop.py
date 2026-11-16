"""裁剪并放大截图的局部，便于细节验收。"""
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage

src, out, x, y, w, h = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:7])
img = QImage(src)
crop = img.copy(x, y, w, h)
scale = float(sys.argv[7]) if len(sys.argv) > 7 else 2.0
crop = crop.scaled(int(w * scale), int(h * scale), Qt.AspectRatioMode.KeepAspectRatio,
                   Qt.TransformationMode.SmoothTransformation)
crop.save(out)
print(out)
