"""请求标签栏：自绘胶囊标签 + 滑动选中指示器 + 拖拽重排 + 溢出滚动。"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget

from . import icons
from .anim import animations_on, running as _anim_running, stop as _anim_stop
from .theme import C, font, method_color, method_short, mono, theme

TAB_H = 27
MARGIN_Y = 6


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """两个颜色按 t 线性混合（t=0 → a，t=1 → b），用于高亮淡入淡出。"""
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class TabStrip(QWidget):
    currentChanged = pyqtSignal(str)
    closeRequested = pyqtSignal(str)
    orderChanged = pyqtSignal(list)
    addRequested = pyqtSignal()
    contextMenuRequested = pyqtSignal(str, QPoint)   # (tab_id 或 "", 全局坐标)
    pinRequested = pyqtSignal(str)                   # 双击预览标签：转正固定

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabs: List[Dict] = []
        self._current: Optional[str] = None
        self._hover: Optional[str] = None
        self._hover_close: Optional[str] = None
        self._press_id: Optional[str] = None
        self._drag_id: Optional[str] = None
        self._drag_start = QPoint()
        self._dragging = False
        # 拖拽浮层：记录鼠标相对标签左边缘的抓取偏移，让浮起的标签跟手移动
        self._drag_pos: Optional[QPointF] = None
        self._drag_grab = QPointF()
        # 拖拽期间只标记顺序脏，松手时才向外发一次（每帧发信号会触发主窗口写盘 → 卡顿）
        self._order_dirty = False
        self._font = font(12.2, weight=QFont.Weight.Medium)
        self._fm = QFontMetricsF(self._font)
        self._badge_font = mono(8.2, QFont.Weight.Bold)
        self._badge_fm = QFontMetricsF(self._badge_font)
        # 几何缓存：标签宽度/矩形每帧都会被取好几次，算一遍存起来即可。
        # 任何影响布局的变化（标签增删改、尺寸、滚动）都要 _invalidate_geometry()。
        self._widths: Optional[List[float]] = None
        self._rect_cache: Optional[List[QRectF]] = None
        self._indicator = QRectF()
        self._ind_from = QRectF()
        self._ind_to = QRectF()
        self._ind_anim: Optional[QVariantAnimation] = None
        # 切换过渡：旧标签的高亮在 _switch_t 里淡出，新标签淡入（0→1）
        self._prev_id: Optional[str] = None
        self._switch_t = 1.0
        self._switch_anim: Optional[QVariantAnimation] = None
        self._scroll = 0.0
        self.setFixedHeight(TAB_H + MARGIN_Y * 2)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_ctx)

    def _on_ctx(self, pos) -> None:
        self.contextMenuRequested.emit(self._hit(pos) or "", self.mapToGlobal(pos))

    # -------------------------------------------------- 尺寸计算
    BADGE_W = 27.0
    LEFT_PAD = 11.0
    BADGE_GAP = 8.0
    RIGHT_PAD = 9.0
    CLOSE_W = 16.0

    def _invalidate_geometry(self) -> None:
        """标签内容 / 宽度 / 滚动变了才需要重算几何。"""
        self._widths = None
        self._rect_cache = None

    def _tab_widths(self) -> List[float]:
        if self._widths is not None and len(self._widths) == len(self.tabs):
            return self._widths
        fm = self._fm
        widths = []
        for tab in self.tabs:
            tw = fm.horizontalAdvance(tab.get("title") or "Untitled")
            fixed = self.LEFT_PAD + self.BADGE_W + self.BADGE_GAP + self.RIGHT_PAD + self.CLOSE_W
            widths.append(min(214.0, max(132.0, tw + fixed + 16)))
        avail = max(self.width() - 52, 160)
        total = sum(widths) + 4 * (len(widths) - 1)
        if total > avail and widths:
            # 压缩到最小 100，仍不够则交给滚动
            excess = total - avail
            shrinkable = sum(max(0.0, w - 100) for w in widths)
            if shrinkable > 0:
                factor = min(1.0, excess / shrinkable)
                widths = [w - max(0.0, w - 100) * factor for w in widths]
        self._widths = widths
        return widths

    def _rects(self) -> List[QRectF]:
        if self._rect_cache is not None and len(self._rect_cache) == len(self.tabs):
            return self._rect_cache
        widths = self._tab_widths()
        rects = []
        x = 8.0 - self._scroll
        for w in widths:
            rects.append(QRectF(x, MARGIN_Y, w, TAB_H))
            x += w + 4
        self._rect_cache = rects
        return rects

    def _content_width(self) -> float:
        widths = self._tab_widths()
        return sum(widths) + 4 * max(0, len(widths) - 1) + 38

    # -------------------------------------------------- 数据接口
    def set_tabs(self, tabs: List[Dict], current: Optional[str] = None) -> None:
        self.tabs = [dict(t) for t in tabs]
        self._current = current or (self.tabs[0]["id"] if self.tabs else None)
        self._scroll = 0.0
        self._invalidate_geometry()
        self._snap_indicator()
        self.update()

    def add_tab(self, tab: Dict, activate: bool = True, animate: bool = True) -> None:
        self.tabs.append(dict(tab))
        self._invalidate_geometry()
        if activate or self._current is None:
            prev = self._current
            self._current = tab["id"]
            self._begin_switch(prev)
            if animate:
                self._animate_indicator()
            else:
                self._snap_indicator()
        self.update()

    def remove_tab(self, tab_id: str) -> None:
        self.tabs = [t for t in self.tabs if t["id"] != tab_id]
        self._invalidate_geometry()
        if self._current == tab_id:
            self._current = self.tabs[-1]["id"] if self.tabs else None
            self._begin_switch(None)
        self._normalize_scroll()
        self._animate_indicator()
        self.update()

    def update_tab(self, tab_id: str, title: Optional[str] = None,
                   method: Optional[str] = None, dirty: Optional[bool] = None,
                   preview: Optional[bool] = None) -> None:
        for tab in self.tabs:
            if tab["id"] == tab_id:
                if title is not None:
                    tab["title"] = title
                if method is not None:
                    tab["method"] = method
                if dirty is not None:
                    tab["dirty"] = dirty
                if preview is not None:
                    tab["preview"] = preview
                self._invalidate_geometry()
                # 标题变了宽度也变，的胶囊不跟着更新就会把 + 包进去
                if _anim_running(self._ind_anim):
                    self._animate_indicator()
                else:
                    self._snap_indicator()
                self.update()
                return

    def set_current(self, tab_id: str, animate: bool = True) -> None:
        if tab_id == self._current:
            # 关键：同 id 只补一次对齐，且绝不能在动画进行中补 ——
            # 主窗口点标签时会 set_current 两次（点击 + currentChanged 回调），
            # 以前第二次直接 _snap 把刚起飞的胶囊按住，用户看到的就是「动画没了」。
            if not _anim_running(self._ind_anim):
                self._snap_indicator()
            return
        prev = self._current
        self._current = tab_id
        self._begin_switch(prev)
        if animate:
            self._animate_indicator()
        else:
            self._snap_indicator()
        self.update()

    # -------------------------------------------------- 高亮淡入淡出
    def _begin_switch(self, prev: Optional[str]) -> None:
        self._prev_id = prev
        _anim_stop(self._switch_anim)
        if not animations_on():
            self._switch_t = 1.0
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(240)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._on_switch)
        self._switch_anim = anim
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_switch(self, v):
        self._switch_t = float(v)
        self.update()

    def current(self) -> Optional[str]:
        return self._current

    def ids(self) -> List[str]:
        return [t["id"] for t in self.tabs]

    def tab(self, tab_id: str) -> Optional[Dict]:
        for t in self.tabs:
            if t["id"] == tab_id:
                return t
        return None

    # -------------------------------------------------- 指示器动画
    def _active_rect(self) -> QRectF:
        for tab, rect in zip(self.tabs, self._rects()):
            if tab["id"] == self._current:
                return QRectF(rect)
        return QRectF()

    def _snap_indicator(self) -> None:
        # 关键：先把在飞的动画停掉。否则 _snap 之后残留的 animation 还会继续
        # 把 _indicator 往它启动时算出的旧矩形上写，动画结束就永久停在一个
        # 错的宽度上 —— 启动时「选中胶囊压住隔壁标签」就是这么来的。
        if self._ind_anim is not None:
            _anim_stop(self._ind_anim)
            self._ind_anim = None
        _anim_stop(self._switch_anim)
        self._switch_t = 1.0
        self._prev_id = None
        self._indicator = self._active_rect()
        self.update()

    def _animate_indicator(self) -> None:
        target = self._active_rect()
        if target.isNull():
            self._indicator = target
            self.update()
            return
        if self._indicator.isNull():
            self._indicator = QRectF(target.left(), target.top(), 0, target.height())
        if not animations_on():
            self._snap_indicator()
            return
        _anim_stop(self._ind_anim)
        self._ind_from = QRectF(self._indicator)
        self._ind_to = QRectF(target)
        self._ind_anim = QVariantAnimation(self)
        self._ind_anim.setStartValue(QRectF(self._indicator))
        self._ind_anim.setEndValue(target)
        self._ind_anim.setDuration(260)
        self._ind_anim.setEasingCurve(QEasingCurve.Type.OutQuint)
        self._ind_anim.valueChanged.connect(self._on_ind)
        # 落点一律以「当前真实几何」为准：动画期间窗口可能缩放过、标题可能变过，
        # 结束时直接对齐一次能把残余误差清零（不能在 finished 里调 stop()，
        # DeleteWhenStopped 会在信号发射过程中销毁自己）。
        self._ind_anim.finished.connect(self._on_ind_finished)
        self._ind_anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_ind_finished(self) -> None:
        self._ind_anim = None
        self._indicator = self._active_rect()
        self.update()

    def _on_ind(self, v):
        self._indicator = v
        self.update()

    def _stretch(self) -> float:
        """胶囊飞行时左右轻微拉伸（速度感），落地回弹到 0。"""
        if not _anim_running(self._ind_anim):
            return 0.0
        dist = abs(self._ind_to.left() - self._ind_from.left())
        if dist < 2:
            return 0.0
        travel = abs(self._indicator.left() - self._ind_from.left()) / dist
        travel = min(1.0, max(0.0, travel))
        return 5.0 * (1.0 - abs(2.0 * travel - 1.0))

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._invalidate_geometry()
        if not _anim_running(self._ind_anim):
            self._snap_indicator()

    def _normalize_scroll(self) -> None:
        overflow = self._content_width() - self.width()
        new = max(0.0, min(self._scroll, max(0.0, overflow)))
        if abs(new - self._scroll) > 0.01:
            self._scroll = new
            self._invalidate_geometry()

    # -------------------------------------------------- 交互
    def _hit(self, pos) -> Optional[str]:
        p = QPointF(pos)  # QRectF.contains 只接受 QPointF，传 QPoint 会 TypeError
        for tab, rect in zip(self.tabs, self._rects()):
            if rect.contains(p):
                return tab["id"]
        return None

    def _close_rect(self, rect: QRectF) -> QRectF:
        return QRectF(rect.right() - self.CLOSE_W - 2, rect.center().y() - 6, 12, 12)

    def _badge_rect(self, rect: QRectF) -> QRectF:
        w = self.BADGE_W - 3
        return QRectF(rect.left() + self.LEFT_PAD, rect.center().y() - 7.5, w, 15)

    def _title_left(self, rect: QRectF) -> float:
        return rect.left() + self.LEFT_PAD + self.BADGE_W + self.BADGE_GAP

    def _plus_rect(self) -> QRectF:
        rects = self._rects()
        x = (rects[-1].right() + 14) if rects else 10
        return QRectF(x, MARGIN_Y + 3, 21, 21)

    def mouseMoveEvent(self, e):  # noqa: N802
        pos = e.position().toPoint()
        if not self._dragging:
            rects = self._rects()
            hover = None
            for tab, rect in zip(self.tabs, rects):
                if rect.contains(e.position()):
                    hover = tab["id"]
                    break
            close = None
            if hover:
                for tab, rect in zip(self.tabs, rects):
                    if tab["id"] == hover and self._close_rect(rect).contains(e.position()):
                        close = hover
                        break
            plus_hover = self._plus_rect().contains(e.position())
            if plus_hover != getattr(self, "_hover_plus", False):
                self._hover_plus = plus_hover
                self.update()
            if hover != self._hover or close != self._hover_close:
                self._hover = hover
                self._hover_close = close
                self.setCursor(Qt.CursorShape.PointingHandCursor if (hover or close)
                               else Qt.CursorShape.ArrowCursor)
                self.update()
            if self._press_id and (pos - self._drag_start).manhattanLength() > 6:
                self._dragging = True
                self._drag_id = self._press_id
                self._drag_pos = QPointF(e.position())
                # 拖起来之后不再走悬停高亮，视觉干扰少一半
                self._hover = None
                self._hover_close = None
        if self._dragging and self._drag_id:
            self._drag_pos = QPointF(e.position())   # 浮层实时跟随光标
            rects = self._rects()
            cur = next((j for j, t in enumerate(self.tabs) if t["id"] == self._drag_id), None)
            if cur is not None:
                target = len(self.tabs)
                for j, rect in enumerate(rects):
                    if rect.center().x() > pos.x():
                        target = j
                        break
                if target > cur:
                    target -= 1
                if target != cur and 0 <= target < len(self.tabs):
                    self.tabs.insert(target, self.tabs.pop(cur))
                    self._order_dirty = True
                    self._invalidate_geometry()
                    # 拖拽期间指示器直接对齐：以前每次换序都重启一次动画，
                    # 拖动中每帧都在停/起动画，这才是「拖起来发涩」的主因。
                    if self._ind_anim is not None:
                        _anim_stop(self._ind_anim)
                        self._ind_anim = None
                    self._indicator = self._active_rect()
            # 即使没有跨过别的标签，浮层也要跟着鼠标动
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._hover = None
        self._hover_close = None
        self.update()

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.MiddleButton:
            # 浏览器习惯：中键点标签直接关闭
            hit = self._hit(e.position().toPoint())
            if hit:
                self.closeRequested.emit(hit)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position().toPoint()
        if self._plus_rect().contains(e.position()):
            self.addRequested.emit()
            return
        tab_id = self._hit(pos)
        if tab_id is None:
            return
        self._press_id = tab_id
        self._drag_start = pos
        self._dragging = False
        self._order_dirty = False
        # 抓取偏移在按下瞬间记录：浮层从第一帧就跟着鼠标，而不是先钉在原位
        idx = next((j for j, t in enumerate(self.tabs) if t["id"] == tab_id), None)
        if idx is not None:
            r = self._rects()[idx]
            self._drag_grab = QPointF(pos.x() - r.left(), pos.y() - r.top())
        old = self._current
        if tab_id != self._current:
            self.set_current(tab_id)
        # 关键：主窗口靠 currentChanged 才会把 editor/response 换成该标签的快照。
        # 以前「点了当前标签」或只改指示器时都不发信号，一旦主窗口与标签栏状态
        # 有一丝不同步（比如刚新建、刚恢复会话），内容就永远切不回来。
        # 现在无条件发一次：处理函数本身幂等，最坏情况只是重绘一次。
        if old != tab_id or self._current == tab_id:
            self.currentChanged.emit(tab_id)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        if self._dragging:
            self._dragging = False
            self._press_id = None
            self._drag_id = None
            self._drag_pos = None
            # 顺序只在松手时上报一次：拖拽中每帧上报会让主窗口反复写盘，直接卡成幻灯片
            if self._order_dirty:
                self._order_dirty = False
                self.orderChanged.emit(self.ids())
            self._animate_indicator()
            self.update()
            return
        tab_id = self._hit(pos.toPoint())
        self._press_id = None
        if tab_id:
            for tab, rect in zip(self.tabs, self._rects()):
                if tab["id"] == tab_id and self._close_rect(rect).contains(pos):
                    self.closeRequested.emit(tab_id)
                    return

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._hit(e.position().toPoint())
        if hit is None:
            self.addRequested.emit()
            return
        # VSCode 行为：双击斜体的预览标签 → 转正固定（之前双击标签毫无反应）
        tab = self.tab(hit)
        if tab and tab.get("preview"):
            self.pinRequested.emit(hit)

    def wheelEvent(self, e):  # noqa: N802
        if self._content_width() <= self.width():
            return
        delta = e.angleDelta().y()
        self._scroll = max(0.0, min(self._scroll - delta / 3, self._content_width() - self.width()))
        self._invalidate_geometry()
        self._snap_indicator()
        self.update()

    # -------------------------------------------------- 绘制
    def _draw_tab(self, p: QPainter, tab: Dict, rect: QRectF, is_cur: bool,
                  is_hover: bool, hot: float, *, ghost: bool = False) -> None:
        """画一个标签本体；ghost=拖动时留在原位的半透明占位。"""
        t = theme()
        if ghost:
            p.setOpacity(0.32)
        if is_hover and not is_cur:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.hover))
            p.drawRoundedRect(rect, 7, 7)
        # 方法徽标（替代原先的小色点，信息更明确、更好看）
        method = (tab.get("method") or "GET").upper()
        mcol = C(method_color(method, t))
        br = self._badge_rect(rect)
        fill = QColor(mcol)
        fill.setAlpha(int(22 + 18 * hot))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(br, 4.5, 4.5)
        p.setFont(self._badge_font)
        if hot < 0.999 and (is_cur or tab["id"] == self._prev_id):
            mcol = QColor(mcol)
            mcol.setAlpha(int(150 + 105 * hot))
        p.setPen(mcol)
        p.drawText(br, int(Qt.AlignmentFlag.AlignCenter), method_short(method))
        # 标题（预览态用斜体，仿 VSCode：单击=临时查看，双击=固定）
        if tab.get("preview"):
            pf = QFont(self._font)
            pf.setItalic(True)
            p.setFont(pf)
        else:
            p.setFont(self._font)
        base = C(t.text_dim if is_hover else t.text_faint)
        p.setPen(_mix(base, C(t.accent), hot) if hot > 0.001 else base)
        left = self._title_left(rect)
        avail = rect.right() - self.RIGHT_PAD - self.CLOSE_W - left - 4
        title = self._fm.elidedText(
            tab.get("title") or "Untitled", Qt.TextElideMode.ElideRight, max(avail, 24))
        p.drawText(QRectF(left, rect.top(), avail, rect.height()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), title)
        # 关闭按钮
        show_close = is_cur or is_hover
        if show_close and not ghost:
            cr = self._close_rect(rect)
            if tab["id"] == self._hover_close:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected))
                p.drawRoundedRect(cr.adjusted(-3, -3, 3, 3), 4, 4)
            col = t.text if tab["id"] == self._hover_close else t.text_faint
            pm = icons.pixmap("close", col, 9, 2.1)
            p.drawPixmap(QPointF(cr.left() + 1.5, cr.top() + 1.5), pm)
        if ghost:
            p.setOpacity(1.0)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        rects = self._rects()

        # 选中底：滑动胶囊（无描边，靠明度区分，更干净）
        # 动画没在跑时一律用实时几何，绝不信任可能过期的 _indicator。
        capsule = self._indicator if _anim_running(self._ind_anim) else self._active_rect()
        if not capsule.isNull() and len(rects) == len(self.tabs):
            r = QRectF(capsule)
            stretch = self._stretch()
            if stretch > 0.05:
                r = r.adjusted(-stretch, 0, stretch, 0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.elevated))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)

        for tab, rect in zip(self.tabs, rects):
            is_cur = tab["id"] == self._current
            is_hover = tab["id"] == self._hover
            # 高亮强度：新标签 0→1 淡入，旧标签 1→0 淡出，跟胶囊一起动
            if is_cur:
                hot = self._switch_t if self._prev_id else 1.0
            elif tab["id"] == self._prev_id and self._switch_t < 1.0:
                hot = 1.0 - self._switch_t
            else:
                hot = 0.0
            self._draw_tab(p, tab, rect, is_cur, is_hover, hot,
                           ghost=self._dragging and tab["id"] == self._drag_id)

        # 新建按钮
        pr = self._plus_rect()
        if pr.right() < self.width() + 40:
            if getattr(self, "_hover_plus", False):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected))
                p.drawRoundedRect(pr, 6, 6)
            pm = icons.pixmap("plus", t.text if getattr(self, "_hover_plus", False) else t.text_faint, 13, 1.8)
            p.drawPixmap(QPointF(pr.center().x() - 6.5, pr.center().y() - 6.5), pm)

        # 拖拽浮层：被拖的标签脱离原位，跟随鼠标。纯灰阶描边 + 轻微投影，无彩色无渐变。
        if self._dragging and self._drag_id and self._drag_pos is not None:
            tab = self.tab(self._drag_id)
            if tab:
                idx = next((j for j, x in enumerate(self.tabs) if x["id"] == self._drag_id), None)
                w = self._tab_widths()[idx] if idx is not None else 150.0
                fr = QRectF(self._drag_pos.x() - self._drag_grab.x(),
                            self._drag_pos.y() - self._drag_grab.y(), w, TAB_H)
                # 投影：向下偏移几像素的半透明灰块
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, 70 if t.is_dark else 34))
                p.drawRoundedRect(fr.adjusted(1, 3, 1, 3), 8, 8)
                # 浮层底：比选中胶囊更实一点，靠 border_strong 勾边
                p.setBrush(C(t.elevated))
                p.drawRoundedRect(fr, 7, 7)
                p.setPen(C(t.border_strong))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(fr.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
                self._draw_tab(p, tab, fr, True, False, 1.0)
        p.end()
