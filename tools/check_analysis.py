"""针对性验证（v1.0.55）：响应分析排版 / 缓存与内存清理 / 提示词 / 状态抖动。

只跑本地逻辑，不发网络请求。
用法：QT_QPA_PLATFORM=offscreen python tools/check_analysis.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

app = QApplication.instance() or QApplication([])

from app import ai as ai_mod, i18n  # noqa: E402
from app.dialogs import AiAnswerDialog  # noqa: E402
from app.markdown_view import AnalysisView  # noqa: E402
from app.store import CHANGELOG, VERSION  # noqa: E402

FAIL = []
TOTAL = [0]


def check(name, ok, detail=""):
    TOTAL[0] += 1
    if ok:
        print(f"  ok   {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


# ---------------------------------------------------------------- 版本 / 更新内容
check("版本号递进到 1.0.56", VERSION == "1.0.56", VERSION)
check("更新内容顶部是 1.0.56", CHANGELOG[0]["version"] == "1.0.56")
check("更新内容写了引用块与圆点",
      any("引用块" in x and "圆点" in x for x in CHANGELOG[0]["items"]))
check("更新内容写了英文动态文案修复",
      any("英文" in x and "拼接" in x for x in CHANGELOG[0]["items"]))
check("上一版仍记录缓存与内存清理",
      any("缓存" in x and "内存" in x for x in CHANGELOG[1]["items"]))

# ---------------------------------------------------------------- 分析结果缓存
cache = ai_mod.AnalysisCache()
cache.put("a", "text-a")
check("能命中缓存", cache.get("a") == "text-a")
for i in range(12):
    cache.put(f"k{i}", f"v{i}")
check("LRU 条数封顶 8", len(cache) == 8, str(len(cache)))
check("最旧的条目被淘汰", cache.get("a") is None)
cache.clear()
check("clear 立刻释放", len(cache) == 0)
cache.put("t", "value")
cache._data["t"] = (time.time() - ai_mod.AnalysisCache.TTL - 10, "value")
check("TTL 过期后不再命中", cache.get("t") is None)
cache.clear()

# ---------------------------------------------------------------- 指纹
ctx = {
    "tab": "pretty", "tab_label": "美化", "status": 200, "reason": "OK",
    "request": {"method": "GET", "url": "https://api.test/time", "headers": [], "params": []},
    "body": '{"code":1,"msg":"下午茶时间到了","data":{"now":"x"}}',
    "headers": ["Content-Type: application/json"], "cookies": [], "console": [],
}
k1 = ai_mod.analysis_key(ctx)
check("同一上下文指纹稳定", k1 == ai_mod.analysis_key(ctx))
ctx_tab = dict(ctx, tab="headers")
check("不同页签指纹不同", k1 != ai_mod.analysis_key(ctx_tab))
ctx_body = dict(ctx, body=ctx["body"] + " ")
check("响应变化指纹不同", k1 != ai_mod.analysis_key(ctx_body))

# ---------------------------------------------------------------- 提示词专业性
sys_text = ai_mod.messages_for_analysis(ctx)[0]["content"]
for token in ("HTTP 状态码是传输层结果", "2xx 一律判定请求成功",
              "## 关键发现", "## 排查建议", "级别｜短标题", "字段=值"):
    check(f"提示词含「{token}」", token in sys_text)
check("11 个页签都有独立关注点", len(ai_mod._TAB_FOCUS) == 11, str(len(ai_mod._TAB_FOCUS)))
check("时间线关注耗时分解", "DNS / TCP / TLS" in ai_mod._TAB_FOCUS["timeline"])
check("响应头关注 CORS 与缓存", "Cache-Control" in ai_mod._TAB_FOCUS["headers"])

# ---------------------------------------------------------------- 状态文字不再抖
dlg = AiAnswerDialog("AI 响应分析", "美化 · GET https://api.test/time")
dlg.set_busy(True, "正在分析")
before = dlg.state.text()
dlg.append_chunk("## 结论\n")
dlg.append_chunk("请求成功")
check("状态文字固定为「正在分析」", before == "正在分析", before)
check("流式追加不再改状态文字", dlg.state.text() == before, dlg.state.text())
dlg.set_result("## 结论\n请求成功")
check("完成时状态切换", "分析完成" in dlg.state.text())
dlg.reset()
dlg.set_result("## 结论\n请求成功", cached=True)
check("命中缓存显示「来自缓存」", "来自缓存" in dlg.state.text(), dlg.state.text())
dlg.close()

# ---------------------------------------------------------------- 分析专用排版
view = AnalysisView()
view.set_markdown(
    "## 结论\n请求成功，耗时偏高。\n\n"
    "## 关键发现\n"
    "- **警告｜未命中缓存**：`eo-cache-status=MISS`，首字节耗时上升\n"
    "- **正常｜传输成功**：`status=200` 且 `data` 有内容\n\n"
    "## 排查建议\n"
    "1. 给该接口加 `Cache-Control: max-age=60`，减少重复回源"
)
dots = [w for w in view.findChildren(QLabel) if w.text() == "•" and w.width() == 9]
nums = [w for w in view.findChildren(QLabel) if w.text() == "01" and w.width() == 18]
check("证据列表圆点独立成列", len(dots) == 2, str(len(dots)))
check("建议列表序号独立成列", len(nums) == 1, str(len(nums)))
check("分节标题按当前节切换样式", view._section == "排查建议", view._section)
view.close()

# ---------------------------------------------------------------- 接线检查
src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("输出预算提到 1400 token", "max_tokens=1400" in src)
check("命中缓存直接呈现", "cached=True" in src)
check("关窗与重载都清空分析缓存", src.count("_analysis_cache.clear()") == 2,
      str(src.count("_analysis_cache.clear()")))

# ---------------------------------------------------------------- v1.0.56 UI
from PyQt6.QtWidgets import QWidget, QSizePolicy  # noqa: E402

view = AnalysisView()
view.set_markdown("## 结论\n请求成功。")
bars = [w for w in view.findChildren(QWidget)
        if "border-radius: 1px" in (w.styleSheet() or "")]
check("结论竖条用主题色", any("#" in (w.styleSheet() or "") for w in bars), str(len(bars)))
check("结论竖条贯穿整块高度",
      any(w.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding for w in bars))
accents = [w for w in view.findChildren(QWidget)
           if "border-radius: 2px" in (w.styleSheet() or "") and w.width() == 5]
check("分节标题有主题色圆点", len(accents) >= 1, str(len(accents)))
view.close()

# 缓存悬浮提示显示真实 TTL
dlg = AiAnswerDialog("AI 响应分析", "美化 · GET https://api.test")
dlg.set_result("## 结论\n成功", cached=True)
tip = dlg.state.toolTip()
check("来自缓存悬浮显示过期分钟数", str(ai_mod.AnalysisCache.TTL // 60) in tip, tip)
check("悬浮提示有「重新分析」指引", "重新分析" in tip, tip)
dlg.close()

# 按钮去边框 + 回收站对齐 + 英文动态文案（源码接线）
resp_src = (ROOT / "app" / "response_panel.py").read_text(encoding="utf-8")
check("Auto / UTF-8 改为无边框按钮",
      resp_src.count('kind="ghost", height=24') >= 2)
trash_src = (ROOT / "app" / "trash_dialog.py").read_text(encoding="utf-8")
check("回收站标签与值统一顶部对齐",
      trash_src.count("hl.addWidget(val, 1, Qt.AlignmentFlag.AlignTop)") == 1)
dlg_src = (ROOT / "app" / "dialogs.py").read_text(encoding="utf-8")
check("设置页有动态文案刷新入口", "def refresh_i18n(self)" in dlg_src)
main_src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("语言切换后重设动态文案",
      "refresh_dynamic(widget)" in main_src and "refresh_i18n" in main_src)
i18n_src = (ROOT / "app" / "i18n.py").read_text(encoding="utf-8")
check("缓存悬浮提示有英文", "Cached result expires after {n} minutes" in i18n_src)

# 实际跑一遍「中文打开 → 切英文」
import tempfile  # noqa: E402
from app.dialogs import SettingsDialog  # noqa: E402
from app.store import Store  # noqa: E402
st = Store.load(Path(tempfile.mkdtemp(prefix="ocelot-1056-")) / "state.json")
st.settings.setdefault("ai", {})["api_key"] = "dummy-key"
i18n.set_language("zh", notify=False)
sd = SettingsDialog(st, None, page="ai")
sd.show(); app.processEvents()
i18n.set_language("en", notify=False)
i18n.apply_language(sd); sd.refresh_i18n()
check("AI 状态行切英文", "Zhipu GLM" in sd.ai_state.text(), sd.ai_state.text())
check("模型标题切英文", "Models ·" in sd.ai_model_title.text(), sd.ai_model_title.text())
check("历史条数切英文", "entries right now" in sd.history_note.text(), sd.history_note.text())
check("关于页路径切英文", "Data folder" in sd.about_foot.text(), sd.about_foot.text())
check("设置标题切英文", "Settings ·" in sd._title_label.text(), sd._title_label.text())
sd.close()
i18n.set_language("zh", notify=False)

print(f"\n{len(FAIL)} failed / {TOTAL[0]} checks")
sys.exit(1 if FAIL else 0)
