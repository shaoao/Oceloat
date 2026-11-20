"""设计令牌、字体与全局样式表。

设计方向：macOS 原生质感 + 纯黑极简。
- 深灰底色 (#19191C)，层次靠白灰明暗区分，不使用彩色渐变/光晕。
- 主按钮为反色实心（深色主题白底黑字、浅色主题黑底白字）。
- 语义色（成功/警告/危险）仅用于状态指示，饱和度低。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from string import Template
from typing import Union

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette, QPainter
from PyQt6.QtCore import QRectF, Qt

Color = Union[str, tuple]


def paint_kind_dot(p: QPainter, x: float, y: float, color: Color,
                   radius: float = 3.2, halo: bool = True) -> None:
    """画一颗「类型灯」：外圈半透明底 + 中心实心点，颜色跟请求方法 / 协议走。

    请求项、历史行、标签页共用这一颗，HTTP 显示方法色、WS / SIO / SSE 显示
    各自的协议色。纯 QPainter 绘制，不开图片、不占缓冲，重绘代价可以忽略。
    """
    c = C(color)
    if halo:
        bg = QColor(c)
        bg.setAlpha(46)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawEllipse(QRectF(x - radius * 1.9, y - radius * 1.9,
                             radius * 3.8, radius * 3.8))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))


def C(c: Color) -> QColor:
    """令牌 -> QColor。透明色用 (r, g, b, a) 元组表示。"""
    if isinstance(c, tuple):
        r, g, b, a = c
        return QColor(r, g, b, a)
    return QColor(c)


def S(c: Color) -> str:
    """令牌 -> QSS 颜色字符串。"""
    if isinstance(c, tuple):
        r, g, b, a = c
        return f"rgba({r},{g},{b},{round(a / 255 * 100)}%)"
    return c


@dataclass(frozen=True)
class Theme:
    name: str
    window: str
    panel: str
    panel_alt: str
    elevated: str
    card: str
    border: Color
    border_strong: Color
    text: str
    text_dim: str
    text_faint: str
    accent: str            # 反色实心
    accent_text: str
    hover: Color
    selected: Color
    success: str
    warning: str
    danger: str
    info: str
    selection: Color
    code_bg: str
    detail_bg: str
    scroll: Color
    scroll_hover: Color
    shadow: Color
    dark: bool = True
    label: str = ""
    # 强调色的两级透明版本：accent_soft 用于胶囊底/徽标底，accent_dim 用于聚焦描边。
    # 单独列出来是为了让「换主题色」能一路渗到选中、聚焦、徽标，而不只是按钮。
    accent_soft: Color = (255, 255, 255, 26)
    accent_dim: Color = (255, 255, 255, 90)

    @property
    def is_dark(self) -> bool:
        return self.dark


def _shift(hex_color: str, delta: int) -> str:
    """整体提亮/压暗一个颜色（保持色相，不做饱和处理）。"""
    c = QColor(hex_color)
    return QColor(
        max(0, min(255, c.red() + delta)),
        max(0, min(255, c.green() + delta)),
        max(0, min(255, c.blue() + delta)),
    ).name()


def _mix(fg: str, bg: str, amount: float) -> str:
    """把 fg 朝 bg 混 amount（0~1）。用于「白字轻微偏向强调色」这类整体染色。"""
    a, b = QColor(fg), QColor(bg)
    k = max(0.0, min(1.0, amount))
    return QColor(
        round(a.red() + (b.red() - a.red()) * k),
        round(a.green() + (b.green() - a.green()) * k),
        round(a.blue() + (b.blue() - a.blue()) * k),
    ).name()


def _alpha(hex_color: str, alpha: int) -> tuple:
    c = QColor(hex_color)
    return (c.red(), c.green(), c.blue(), max(0, min(255, alpha)))


def _dark_scheme(key: str, label: str, base: str) -> Theme:
    """统一底色方案：侧栏、工作区、窗口用同一个底色，层次只靠卡片提亮。

    这是用户明确要求的「不要一半深一半浅」——整块背景只有一种颜色。
    """
    return Theme(
        name=key,
        window=base,
        panel=base,
        panel_alt=_shift(base, 7),
        elevated=_shift(base, 20),
        card=_shift(base, 9),
        border=(255, 255, 255, 18),
        border_strong=(255, 255, 255, 34),
        text="#EDEDF1",
        text_dim="#A0A0AA",
        text_faint="#6E6E78",
        accent="#F2F2F5",
        accent_text=base,
        hover=(255, 255, 255, 14),
        selected=(255, 255, 255, 24),
        success="#69C79A",
        warning="#D8B172",
        danger="#E48178",
        info="#89AECE",
        selection=(255, 255, 255, 48),
        code_bg=_shift(base, -2),
        detail_bg=_shift(base, -10),
        scroll=(255, 255, 255, 28),
        scroll_hover=(255, 255, 255, 60),
        shadow=(0, 0, 0, 180),
        dark=True,
        label=label,
        accent_soft=(255, 255, 255, 26),
        accent_dim=(255, 255, 255, 88),
    )


def _light_scheme(key: str, label: str, base: str) -> Theme:
    return Theme(
        name=key,
        window=base,
        panel=base,
        panel_alt=_shift(base, -6),
        elevated="#FFFFFF",
        card="#FFFFFF",
        border=(0, 0, 0, 20),
        border_strong=(0, 0, 0, 44),
        text="#151517",
        text_dim="#68686F",
        text_faint="#98989F",
        accent="#151517",
        accent_text="#FFFFFF",
        hover=(0, 0, 0, 10),
        selected=(0, 0, 0, 18),
        success="#0E9463",
        warning="#A97018",
        danger="#C8433A",
        info="#2C6BAD",
        selection=(0, 0, 0, 38),
        code_bg="#FFFFFF",
        detail_bg=_shift(base, -4),
        scroll=(0, 0, 0, 28),
        scroll_hover=(0, 0, 0, 64),
        shadow=(0, 0, 0, 48),
        dark=False,
        label=label,
        accent_soft=(0, 0, 0, 22),
        accent_dim=(0, 0, 0, 74),
    )


# 主题强调色：主按钮、开关、勾选框、发送键都用它。
# 默认「自动」= 反色实心（深色主题白底黑字），其余是低饱和的语义色，不做荧光。
# 每项：key -> (名字, (深色主色, 深色文字), (浅色主色, 浅色文字))
ACCENTS: dict[str, tuple[str, tuple[str, str], tuple[str, str]]] = {
    "auto": ("自动", ("#F2F2F5", "#19191C"), ("#151517", "#FFFFFF")),
    "blue": ("海蓝", ("#4F86F0", "#FFFFFF"), ("#2C63B4", "#FFFFFF")),
    "teal": ("松青", ("#3E9BA8", "#08252A"), ("#1F6E7A", "#FFFFFF")),
    "green": ("苔绿", ("#4FA37B", "#07211A"), ("#1F7A54", "#FFFFFF")),
    "orange": ("陶橙", ("#D0803F", "#22150A"), ("#A35620", "#FFFFFF")),
    "rose": ("绯红", ("#CB6470", "#FFFFFF"), ("#A03D4A", "#FFFFFF")),
    "purple": ("藤紫", ("#8C6DD2", "#FFFFFF"), ("#6247A8", "#FFFFFF")),
}

ACCENT_ORDER = ["auto", "blue", "teal", "green", "orange", "rose", "purple"]

# 配色方案：默认就是用户给的 #19191C，其它几套在同一结构上换一点点色相
SCHEMES: list[tuple[str, str]] = [
    ("graphite", "石墨"),
    ("slate", "岩蓝"),
    ("ash", "暖灰"),
    ("moss", "松绿"),
    ("ink", "墨黑"),
    ("light", "浅色"),
]

_THEMES = {
    "graphite": _dark_scheme("graphite", "石墨", "#19191C"),
    "slate": _dark_scheme("slate", "岩蓝", "#171A21"),
    "ash": _dark_scheme("ash", "暖灰", "#1D1A17"),
    "moss": _dark_scheme("moss", "松绿", "#171C19"),
    "ink": _dark_scheme("ink", "墨黑", "#111113"),
    "light": _light_scheme("light", "浅色", "#E9E9E6"),
    "dark": _dark_scheme("graphite", "石墨", "#19191C"),   # 兼容旧配置
}

DARK = _THEMES["graphite"]
LIGHT = _THEMES["light"]

_state = {"theme": DARK, "accent": "auto"}


def theme() -> Theme:
    return _state["theme"]


def set_theme(t: Theme) -> None:
    _state["theme"] = t


def accent_name() -> str:
    return _state.get("accent", "auto")


def set_accent(key: str) -> None:
    """只记录选择；真正生效要在下一次 theme_by_name() 里套上。"""
    _state["accent"] = key if key in ACCENTS else "auto"


def accent_swatch(key: str, dark: bool = True) -> tuple[str, str]:
    """给设置面板取色用：(主色, 文字色)。"""
    _l, d, lt = ACCENTS.get(key, ACCENTS["auto"])
    return d if dark else lt


def _with_accent(t: Theme, key: str) -> Theme:
    """把强调色套到主题上，并让它渗进整套配色。

    auto 保持原来的黑白反色；选了彩色就整体朝那个色相偏一点：
    主按钮 / 开关 / 勾选框 / 选中底 / 聚焦描边 / 徽标底 / 文字色一起同步，
    而不是只有按钮变了、满屏还是白字。
    """
    if key not in ACCENTS or key == "auto":
        return t
    bg, fg = accent_swatch(key, t.is_dark)
    from dataclasses import replace

    soft = 0.10 if t.is_dark else 0.15
    return replace(
        t,
        accent=bg,
        accent_text=fg,
        text=_mix(t.text, bg, soft),
        text_dim=_mix(t.text_dim, bg, soft * 1.4),
        text_faint=_mix(t.text_faint, bg, soft * 1.2),
        selected=_alpha(bg, 40 if t.is_dark else 30),
        selection=_alpha(bg, 105 if t.is_dark else 78),
        accent_soft=_alpha(bg, 30 if t.is_dark else 22),
        accent_dim=_alpha(bg, 130 if t.is_dark else 105),
    )


def accent_is_auto() -> bool:
    return accent_name() == "auto"


def theme_by_name(name: str) -> Theme:
    return _with_accent(_THEMES.get(name or "", DARK), accent_name())


def is_light_name(name: str) -> bool:
    return not theme_by_name(name).is_dark


# ---------------------------------------------------------------- 字体

def _families() -> set[str]:
    try:
        return set(QFontDatabase.families())
    except Exception:
        return set()


_BODY_CANDIDATES = ["SF Pro Text", "SF Pro Display", ".AppleSystemUIFont", "Helvetica Neue", "PingFang SC"]
_MONO_CANDIDATES = ["SF Mono", "Menlo", "JetBrains Mono", "Monaco", "Consolas"]


def body_families() -> list[str]:
    fams = _families()
    picked = [f for f in _BODY_CANDIDATES if f in fams]
    return picked or ["Helvetica Neue"]


def mono_families() -> list[str]:
    fams = _families()
    picked = [f for f in _MONO_CANDIDATES if f in fams]
    return picked or ["Menlo", "monospace"]


# ------------------------------------------------------------------ 界面字号
# 全局文字缩放：所有 font() / mono() 都会乘上这个系数。控件在构造时把字体
# 定死，所以运行中改缩放走 app.zoom 的就地缩放；启动时由 MainWindow 先按设置
# 里的系数建窗口，两边用的是同一个系数，不会出现「一半大一半小」。
_UI_SCALE = 1.0


def set_ui_scale(scale: float) -> None:
    global _UI_SCALE
    try:
        value = float(scale)
    except (TypeError, ValueError):
        value = 1.0
    _UI_SCALE = max(0.85, min(1.6, value))


def ui_scale() -> float:
    return _UI_SCALE


def px(value: float) -> int:
    """像素尺寸跟着文字一起放大（固定高度的胶囊、图标框用）。"""
    return int(round(value * _UI_SCALE))


def font(size: float = 13, weight: QFont.Weight = QFont.Weight.Normal,
         mono: bool = False, spacing: float = 0.0) -> QFont:
    f = QFont()
    f.setFamilies(mono_families() if mono else body_families())
    f.setPointSizeF(max(6.0, size * _UI_SCALE))
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def mono(size: float = 12, weight: QFont.Weight = QFont.Weight.Normal, spacing: float = 0.0) -> QFont:
    return font(size, weight, mono=True, spacing=spacing)


# 与参考图对齐：GET 绿 / POST 橙 / PUT·HEAD·OPTIONS 蓝 / DELETE 红 /
# PATCH 粉 / TRACE 紫。深色主题用高亮版，浅色主题用同色相的暗版。
METHOD_COLORS_DARK = {
    "WS": "#3E9E9C",
    "SIO": "#4FA3B8",
    "SSE": "#7C8CD8",
    "GET": "#49A665",
    "POST": "#DA6530",
    "PUT": "#4283F0",
    "PATCH": "#D74AAF",
    "DELETE": "#D9483A",
    "HEAD": "#4283F0",
    "OPTIONS": "#4283F0",
    "CONNECT": "#5966E8",
    "TRACE": "#5966E8",
}
METHOD_COLORS_LIGHT = {
    "WS": "#2A6E6C",
    "SIO": "#2F6E7E",
    "SSE": "#4A57A8",
    "GET": "#2E7A48",
    "POST": "#A64A1C",
    "PUT": "#2C63B4",
    "PATCH": "#A33285",
    "DELETE": "#A83228",
    "HEAD": "#2C63B4",
    "OPTIONS": "#2C63B4",
    "CONNECT": "#414BB0",
    "TRACE": "#414BB0",
}


def method_color(method: str, t: Theme | None = None) -> str:
    t = t or theme()
    table = METHOD_COLORS_DARK if t.is_dark else METHOD_COLORS_LIGHT
    return table.get((method or "GET").upper(), t.text_dim)


# 侧栏 / 标签徽标里的方法缩写：超过 4 个字符的方法一律压成 3 字母，
# 免得 DELETE / OPTIONS 把方法列撑歪、把请求名挤到看不见。
METHOD_SHORT = {
    "DELETE": "DEL",
    "OPTIONS": "OPT",
    "PATCH": "PAT",
    "CONNECT": "CON",
    "TRACE": "TRC",
}


def method_short(method: str) -> str:
    """方法名缩写：GET/POST/PUT 原样，其余长方法压到 3 字母。"""
    m = (method or "GET").upper()
    return METHOD_SHORT.get(m, m)


def status_color(code: int, t: Theme | None = None) -> str:
    t = t or theme()
    if code == 0:
        return t.danger
    if 200 <= code < 300:
        return t.success
    if 300 <= code < 400:
        return t.info
    if 400 <= code < 500:
        return t.warning
    return t.danger


# ---------------------------------------------------------------- 样式表

_QSS = Template(
    """
    QWidget { color: $text; }
    QToolTip {
        background: $elevated; color: $text; border: 1px solid $border_strong;
        padding: 4px 8px; border-radius: 6px; font-size: 11px;
    }
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox {
        background: transparent; border: none; color: $text;
        selection-background-color: $selection; selection-color: $text;
    }
    QLineEdit#Field {
        background: $panel_alt; border: 1px solid $border; border-radius: 7px;
        padding: 5px 8px; font-size: 12.5px;
    }
    QLineEdit#Field:focus { border: 1px solid $accent_dim; background: $elevated; }
    QLineEdit#Field:disabled { color: $text_faint; }
    QLineEdit#Bare { background: transparent; border: none; padding: 0px; }
    QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
    QScrollBar:vertical { background: transparent; width: 9px; margin: 0px; }
    QScrollBar::handle:vertical {
        background: $scroll; border-radius: 4px; min-height: 26px; margin: 2px 2px 2px 3px;
    }
    QScrollBar::handle:vertical:hover { background: $scroll_hover; }
    QScrollBar:horizontal { background: transparent; height: 9px; margin: 0px; }
    QScrollBar::handle:horizontal {
        background: $scroll; border-radius: 4px; min-width: 26px; margin: 3px 2px 2px 2px;
    }
    QScrollBar::handle:horizontal:hover { background: $scroll_hover; }
    QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; border: none; }
    QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
    QMenu {
        background: $elevated; border: 1px solid $border_strong; border-radius: 11px;
        padding: 6px;
    }    QMenu::item {
        padding: 7px 26px 7px 12px; border-radius: 7px; font-size: 12.5px; color: $text;
        margin: 1px 2px;
    }
    QMenu::item:selected { background: $selected; }
    QMenu::item:disabled { color: $text_faint; }
    QMenu::separator { height: 1px; background: $border; margin: 6px 10px; }
    QMenu::icon { left: 10px; }
    QComboBox {
        background: $panel_alt; border: 1px solid $border; border-radius: 7px;
        padding: 5px 8px; font-size: 12.5px;
    }
    QComboBox:focus { border: 1px solid $border_strong; }
    QComboBox QAbstractItemView {
        background: $elevated; border: 1px solid $border_strong; border-radius: 8px;
        selection-background-color: $selected; padding: 4px; outline: none;
    }
    QCheckBox { font-size: 12.5px; color: $text; spacing: 7px; }
    QCheckBox::indicator {
        width: 13px; height: 13px; border: 1px solid $border_strong;
        border-radius: 4px; background: transparent;
    }
    QCheckBox::indicator:hover { border: 1px solid $text_faint; }
    QCheckBox::indicator:checked { background: $accent; border: 1px solid $accent; }
    QTreeWidget, QListWidget { background: transparent; border: none; outline: none; }
    QTreeWidget::item, QListWidget::item { border: none; }
    QPlainTextEdit#Code, QTextEdit#Code {
        background: $code_bg; color: $text; border: none;
    }
    QLabel#H1 { font-size: 15px; font-weight: 600; }
    QLabel#Dim { color: $text_dim; }
    QLabel#Faint { color: $text_faint; font-size: 11.5px; }
    QLabel#Section {
        color: $text_faint; font-size: 10.5px; font-weight: 600; letter-spacing: 1px;
    }
    QDialog { background: $panel; }
    QSplitter::handle { background: transparent; }
    """
)


def stylesheet(t: Theme | None = None) -> str:
    t = t or theme()
    data = {k: (S(v) if isinstance(v, tuple) else v) for k, v in asdict(t).items()}
    return _QSS.substitute(data)


def apply_theme(app, t: Theme) -> None:
    from .ime import install as _install_ime_fix
    _install_ime_fix(app)   # 输入法候选期间隐藏 placeholder（全局一次，后续控件无需处理）
    set_theme(t)
    app.setStyleSheet(stylesheet(t))
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, C(t.window))
    pal.setColor(QPalette.ColorRole.Base, C(t.panel))
    pal.setColor(QPalette.ColorRole.Text, C(t.text))
    pal.setColor(QPalette.ColorRole.WindowText, C(t.text))
    pal.setColor(QPalette.ColorRole.Highlight, C(t.selected))
    pal.setColor(QPalette.ColorRole.HighlightedText, C(t.text))
    pal.setColor(QPalette.ColorRole.PlaceholderText, C(t.text_faint))
    app.setPalette(pal)
    app.setFont(font(13))
