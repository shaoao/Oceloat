"""二维码：纯标准库实现，专给「局域网调试地址」用。

为什么自己写：
- 应用一直坚持零第三方依赖（`requirements.txt` 只有 PyQt6），为了一个二维码
  把 `qrcode` / `Pillow` 拖进来不值；
- 我们只需要 byte 模式、纠错级别 L、版本 1~5（最多 106 字节），
  足够放下 `http://192.168.1.23:8787/api/users` 这种地址，代码量很小。

API：
    qr = QrCode("http://192.168.1.23:8787")
    qr.size          # 21 / 25 / ... 模块边长
    qr.get(x, y)     # True = 黑
"""
from __future__ import annotations

from typing import List, Optional

# 版本 -> (数据码字数, 纠错码字数, 边长)
# 只到版本 5：单块纠错，不需要交织，实现最简且覆盖常用 URL 长度
VERSIONS = {
    1: (19, 7, 21),
    2: (34, 10, 25),
    3: (55, 15, 29),
    4: (80, 20, 33),
    5: (108, 26, 37),
}
# byte 模式容量（字节）
CAPACITY = {1: 17, 2: 32, 3: 53, 4: 78, 5: 106}

# 格式信息用的纠错级别位：L = 01
_EC_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}

_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30]}


# ---------------------------------------------------------------- GF(256)
_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _gen_poly(degree: int) -> List[int]:
    """生成多项式 (x - a^0)(x - a^1)...(x - a^(degree-1))，最高次项省略。"""
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= _mul(coef, 1)
            nxt[j + 1] ^= _mul(coef, _EXP[i])
        poly = nxt
    return poly


def _ec_bytes(data: List[int], count: int) -> List[int]:
    gen = _gen_poly(count)
    res = list(data) + [0] * count
    for i in range(len(data)):
        factor = res[i]
        if factor:
            for j, coef in enumerate(gen):
                res[i + j] ^= _mul(coef, factor)
    return res[-count:] if count else []


# ---------------------------------------------------------------- 编码
def _bits_to_codewords(bits: List[int]) -> List[int]:
    out = []
    for i in range(0, len(bits), 8):
        byte = 0
        for b in bits[i:i + 8]:
            byte = (byte << 1) | b
        out.append(byte)
    return out


def _data_codewords(payload: bytes, version: int) -> List[int]:
    total, _ec, _size = VERSIONS[version]
    bits: List[int] = [0, 1, 0, 0]                     # byte 模式
    cnt = len(payload)
    bits += [(cnt >> i) & 1 for i in range(7, -1, -1)]  # 版本 1~9 用 8 位长度
    for byte in payload:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, total * 8 - len(bits))          # 终止符
    while len(bits) % 8:
        bits.append(0)
    words = _bits_to_codewords(bits)
    pad = (0xEC, 0x11)
    i = 0
    while len(words) < total:
        words.append(pad[i % 2])
        i += 1
    return words[:total]


# ---------------------------------------------------------------- 矩阵
class QrCode:
    """一个可直接绘制的二维码矩阵。构造时就把所有模块算好。"""

    def __init__(self, text: str, ec: str = "L"):
        payload = (text or "").encode("utf-8")
        version = self._pick_version(len(payload))
        self.version = version
        self.size = VERSIONS[version][2]
        self.text = text
        self._mod = [[False] * self.size for _ in range(self.size)]
        self._fun = [[False] * self.size for _ in range(self.size)]
        data, ecc = self._codewords(payload, version)
        self._draw_functions()
        self._draw_data(data + ecc)
        self._apply_best_mask(ec)
        self._draw_format(ec, self._mask)

    # ---- 基础
    @staticmethod
    def _pick_version(length: int) -> int:
        for v in sorted(CAPACITY):
            if length <= CAPACITY[v]:
                return v
        return 5                      # 太长就截断成前 106 字节，仍是可扫的

    def _codewords(self, payload: bytes, version: int) -> "tuple[List[int], List[int]]":
        total, ec_count, _size = VERSIONS[version]
        payload = payload[:CAPACITY[version]]
        data = _data_codewords(payload, version)
        return data, _ec_bytes(data, ec_count)

    def _set_fun(self, x: int, y: int, dark: bool) -> None:
        if 0 <= x < self.size and 0 <= y < self.size:
            self._mod[y][x] = dark
            self._fun[y][x] = True

    def _draw_functions(self) -> None:
        s = self.size
        # 定位图形 + 分隔符
        for ox, oy in ((0, 0), (s - 7, 0), (0, s - 7)):
            for dy in range(-1, 8):
                for dx in range(-1, 8):
                    x, y = ox + dx, oy + dy
                    if not (0 <= x < s and 0 <= y < s):
                        continue
                    inside = 0 <= dx <= 6 and 0 <= dy <= 6
                    dark = False
                    if inside:
                        edge = dx in (0, 6) or dy in (0, 6)
                        inner = 2 <= dx <= 4 and 2 <= dy <= 4
                        dark = edge or inner
                    self._set_fun(x, y, dark)
        # 定时图形
        for i in range(8, s - 8):
            dark = i % 2 == 0
            self._set_fun(i, 6, dark)
            self._set_fun(6, i, dark)
        # 校正图形
        centers = _ALIGN[self.version]
        for cy in centers:
            for cx in centers:
                if (cx == 6 and cy == 6) or (cx == 6 and cy == s - 7) or (cx == s - 7 and cy == 6):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        dark = max(abs(dx), abs(dy)) != 1
                        self._set_fun(cx + dx, cy + dy, dark)
        # 预留格式信息区（先占位，最后按掩码写真实值）
        for i in range(9):
            if i != 6:
                self._set_fun(8, i, False)
                self._set_fun(i, 8, False)
        for i in range(8):
            self._set_fun(8, s - 1 - i, False)
            self._set_fun(s - 1 - i, 8, False)
        self._set_fun(8, s - 8, True)                      # 固定的黑模块

    def _draw_data(self, codewords: List[int]) -> None:
        s = self.size
        bits: List[int] = []
        for word in codewords:
            bits += [(word >> i) & 1 for i in range(7, -1, -1)]
        idx = 0
        upward = True
        x = s - 1
        while x > 0:
            if x == 6:
                x -= 1
            rows = range(s - 1, -1, -1) if upward else range(s)
            for y in rows:
                for dx in (0, 1):
                    xx = x - dx
                    if self._fun[y][xx]:
                        continue
                    bit = bits[idx] if idx < len(bits) else 0
                    self._mod[y][xx] = bool(bit)
                    idx += 1
            upward = not upward
            x -= 2

    # ---- 掩码
    @staticmethod
    def _mask_bit(mask: int, x: int, y: int) -> bool:
        if mask == 0:
            return (x + y) % 2 == 0
        if mask == 1:
            return y % 2 == 0
        if mask == 2:
            return x % 3 == 0
        if mask == 3:
            return (x + y) % 3 == 0
        if mask == 4:
            return (y // 2 + x // 3) % 2 == 0
        if mask == 5:
            return (x * y % 2 + x * y % 3) == 0
        if mask == 6:
            return (x * y % 2 + x * y % 3) % 2 == 0
        return ((x + y) % 2 + x * y % 3) % 2 == 0

    def _apply_best_mask(self, ec: str) -> None:
        best: Optional[int] = None
        best_score = None
        base = [row[:] for row in self._mod]
        for mask in range(8):
            for y in range(self.size):
                for x in range(self.size):
                    if not self._fun[y][x] and self._mask_bit(mask, x, y):
                        self._mod[y][x] = not base[y][x]
                    else:
                        self._mod[y][x] = base[y][x]
            self._mask = mask
            self._draw_format(ec, mask)
            score = self._penalty()
            if best_score is None or score < best_score:
                best_score, best = score, mask
        self._mask = best if best is not None else 0
        for y in range(self.size):
            for x in range(self.size):
                if not self._fun[y][x] and self._mask_bit(self._mask, x, y):
                    self._mod[y][x] = not base[y][x]
                else:
                    self._mod[y][x] = base[y][x]
        self._draw_format(ec, self._mask)

    def _penalty(self) -> int:
        s = self.size
        score = 0
        # 规则 1：行 / 列连续同色
        for lines in (self._mod, [[self._mod[y][x] for y in range(s)] for x in range(s)]):
            for line in lines:
                run, prev = 1, line[0]
                for v in line[1:]:
                    if v == prev:
                        run += 1
                    else:
                        if run >= 5:
                            score += 3 + (run - 5)
                        run, prev = 1, v
                if run >= 5:
                    score += 3 + (run - 5)
        # 规则 2：2x2 同色块
        for y in range(s - 1):
            for x in range(s - 1):
                v = self._mod[y][x]
                if v == self._mod[y][x + 1] == self._mod[y + 1][x] == self._mod[y + 1][x + 1]:
                    score += 3
        # 规则 3：类似定位图形的 1:1:3:1:1
        pat1 = [True, False, True, True, True, False, True, False, False, False, False]
        pat2 = list(reversed(pat1))
        for line in self._mod:
            for i in range(s - 10):
                seg = line[i:i + 11]
                if seg == pat1 or seg == pat2:
                    score += 40
        for x in range(s):
            col = [self._mod[y][x] for y in range(s)]
            for i in range(s - 10):
                seg = col[i:i + 11]
                if seg == pat1 or seg == pat2:
                    score += 40
        # 规则 4：黑色占比
        dark = sum(1 for row in self._mod for v in row if v)
        ratio = dark * 100 // (s * s)
        score += abs(ratio - 50) // 5 * 10
        return score

    def _draw_format(self, ec: str, mask: int) -> None:
        s = self.size
        data = (_EC_BITS.get(ec, 1) << 3) | mask
        rem = data << 10
        for _ in range(4, -1, -1):
            if rem.bit_length() - 1 >= 10:
                rem ^= 0b10100110111 << (rem.bit_length() - 11)
        bits = ((data << 10) | rem) ^ 0b101010000010010
        seq = [(bits >> (14 - i)) & 1 for i in range(15)]
        # 第一份：左上角。bit0..5 在 row8 的 col0..5，bit6 在 (8,7)，bit7 在 (8,8)，
        # bit8 在 (7,8)，bit9..14 在 col8 的 row5..0（跳过定时行 6）
        for i in range(15):
            if i < 6:
                self._mod[8][i] = bool(seq[i])
            elif i < 8:
                self._mod[8][i + 1] = bool(seq[i])
            elif i == 8:
                self._mod[7][8] = bool(seq[i])
            else:
                self._mod[14 - i][8] = bool(seq[i])
        # 第二份：bit0..6 竖排在 col8 底部（s-1 → s-7），bit7..14 横排在 row8 右侧。
        # 注意 (s-8, 8) 是固定黑模块，不属于格式信息，别覆盖掉。
        for i in range(15):
            if i < 7:
                self._mod[s - 1 - i][8] = bool(seq[i])
            else:
                self._mod[8][s - 15 + i] = bool(seq[i])

    # ---- 读取
    def get(self, x: int, y: int) -> bool:
        if 0 <= x < self.size and 0 <= y < self.size:
            return self._mod[y][x]
        return False

    def rows(self) -> List[List[bool]]:
        return [row[:] for row in self._mod]


def pixmap(text: str, size: int = 168, fg: str = "#111111", bg: str = "#FFFFFF",
           quiet: int = 3, dpr: float = 2.0):
    """把二维码画成 QPixmap（白底 + 深色模块，留 quiet 个模块的静区）。

    只在 UI 层调用；编码部分保持纯 Python，方便单独测试。
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QPainter, QPixmap

    code = QrCode(text)
    pm = QPixmap(int(round(size * dpr)), int(round(size * dpr)))
    pm.fill(QColor(bg))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(fg))
    total = code.size + quiet * 2
    cell = (size * dpr) / total
    for y in range(code.size):
        for x in range(code.size):
            if code.get(x, y):
                p.drawRect(int((x + quiet) * cell), int((y + quiet) * cell),
                           int(cell) + 1, int(cell) + 1)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm

