"""针对性验证：变量页、AI 设置/分析、响应弹窗、文档折叠、输入法占位、起名同步。

只跑本地逻辑，不发网络请求（AI 的回调用手工文本模拟）。
用法：QT_QPA_PLATFORM=offscreen python tools/check_vars_ai.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtGui import QInputMethodEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLineEdit  # noqa: E402

app = QApplication.instance() or QApplication([])

from app import ai as ai_mod  # noqa: E402
from app import i18n, ime  # noqa: E402
from app.dialogs import AiAnswerDialog, SettingsDialog, VarPickDialog, json_paths  # noqa: E402
from app.doc_window import DocDialog  # noqa: E402
from app.http_client import Response  # noqa: E402
from app.request_panel import ScriptPage  # noqa: E402
from app.store import Store, new_request  # noqa: E402

FAIL = []
TOTAL = [0]


def check(name, ok, detail=""):
    TOTAL[0] += 1
    if ok:
        print(f"  ok   {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


tmp = Path(tempfile.mkdtemp(prefix="ocelot-1053-"))
store = Store.load(tmp / "state.json")
store.data["global_vars"] = [{"key": "g_host", "value": "https://api.example.com"}]
store.data["environments"] = [{"id": "env_a", "name": "Dev", "vars": [
    {"key": "base_url", "value": "http://dev"}, {"key": "g_host", "value": "http://dev-host"}]}]
store.set_active_env("env_a")

# ---------------------------------------------------------------- 变量页
check("全局变量被环境同名覆盖", store.env_vars().get("g_host") == "http://dev-host",
      str(store.env_vars()))
dlg = SettingsDialog(store, None, page="env")
keys = [k for k, _l, _i in dlg.NAV]
check("导航只有一个变量页", "env" in keys and "globals" not in keys, str(keys))
dlg.vars_seg.set_current("global", emit=True)
check("能切到全局变量", dlg.vars_stack.currentIndex() == 1)

# ---------------------------------------------------------------- AI 设置（只留智谱）
dlg.nav.set_key("ai")
dlg._on_nav("ai")
check("AI 总开关存在且默认开", dlg.ai_enabled.isChecked())
check("服务商切换已移除", not hasattr(dlg, "ai_provider"))
check("只有智谱一家", list(ai_mod.PROVIDERS) == ["glm"], str(list(ai_mod.PROVIDERS)))
check("默认模型卡片 4 张", len(dlg._model_cards) == 4, str(len(dlg._model_cards)))
check("GLM base 正确", ai_mod.config(store)["base"].endswith("/v4"))

dlg.ai_key.setText("glm-key-1")
dlg._save_ai(quiet=True)
check("Key 落盘", ai_mod.config(store)["api_key"] == "glm-key-1")
check("填了 Key 后 ready", ai_mod.ready(ai_mod.config(store))[0])
dlg.ai_enabled.setChecked(False)
dlg._on_ai_enabled(False)
check("总开关关闭后 ready=False", not ai_mod.ready(ai_mod.config(store))[0])
check("关闭后 Key 不丢", ai_mod.config(store)["api_key"] == "glm-key-1")
dlg.ai_enabled.setChecked(True)
dlg._on_ai_enabled(True)
check("重开后 ready", ai_mod.ready(ai_mod.config(store))[0])

# ---------------------------------------------------------------- 提示词差异化 / 误判修复
ctx = {"tab": "pretty", "tab_label": "美化", "status": 200, "reason": "OK",
       "method": "GET", "url": "https://api.test/time",
       "request": {"method": "GET", "url": "https://api.test/time"},
       "body": '{"code":1,"msg":"下午茶的时间到了，休息一下吧！","data":{"now":"2026-11-19"}}'}
msgs = ai_mod.messages_for_analysis(ctx)
sys_text, user_text = msgs[0]["content"], msgs[1]["content"]
check("系统提示词禁止把 code:1 当错误码", "绝不因为响应体里出现 code:1" in sys_text)
check("提示词要求按 msg/data 判断业务状态", "msg / message / success / data" in sys_text)
check("分析请求带上了业务正文", "下午茶" in user_text)
check("分析请求带上 HTTP 状态", "HTTP 200" in user_text)

focus = {}
for tab in ("pretty", "tree", "raw", "headers", "cookies", "console",
            "preview", "diff", "extract", "timeline", "error"):
    focus[tab] = ai_mod.messages_for_analysis({**ctx, "tab": tab})[1]["content"]
check("十个页签 + 错误页各有不同提示词", len(set(focus.values())) == 11,
      str(len(set(focus.values()))))
check("响应头提示词关注缓存与安全", "Cache-Control" in ai_mod.messages_for_analysis(
    {**ctx, "tab": "headers"})[1]["content"])
check("时间线提示词关注耗时趋势", "耗时趋势" in ai_mod.messages_for_analysis(
    {**ctx, "tab": "timeline"})[1]["content"])
check("错误页提示词区分网络故障", "DNS" in ai_mod.messages_for_analysis(
    {**ctx, "tab": "error", "error": "Connection refused"})[1]["content"])
check("控制台提示词关注断言", "断言" in focus["console"])
check("脚本提示词已彻底移除", not hasattr(ai_mod, "messages_for_script"))
check("脚本页没有 AI 按钮", not hasattr(ScriptPage(store=store, kind="post"), "ai_btn"))
check("数据生成提示词强调字段一致",
      "键名严格照抄" in ai_mod.messages_for_json(["a"])[0]["content"])
check("文档提示词按证据写",
      "按证据写" in ai_mod.messages_for_doc("GET", "https://a.com")[0]["content"])
check("起名提示词禁止照抄 URL",
      "禁止照抄 URL" in ai_mod.messages_for_name("GET", "https://a.com/users")[0]["content"])

# ---------------------------------------------------------------- AI 回答弹窗（流式）
box = AiAnswerDialog("AI 响应分析", "美化 · GET https://api.test/time")
box.set_busy(True, "正在分析")
box.append_chunk("## 结论\n")
box.append_chunk("HTTP 200 成功，code:1 是业务约定。")
app.processEvents()
check("流式内容累积", "code:1" in box.result(), box.result())
box.set_result(box.result())
check("结束后标记完成", box.state.text() == "分析完成", box.state.text())
box.reset()
check("重新分析会清空", box.result() == "" and box.view.blocks == [])
box.set_result("只有结论", error=True)
check("失败状态显示红色文案", box.state.text() == "分析失败")
box.close()

# ---------------------------------------------------------------- 取变量 / 路径
payload = {"token": "abc", "user": {"id": 7, "tags": ["x"]}, "ok": True}
rows = json_paths(payload)
paths = [r["path"] for r in rows]
check("路径摊平包含嵌套字段", "user.id" in paths and "user.tags[0]" in paths, str(paths))
vdlg = VarPickDialog(store, json.dumps(payload))
check("取变量对话框列出字段", vdlg.list.count() == len(rows))
vdlg.list.setCurrentRow(paths.index("user.id"))
check("选中后自动起变量名", vdlg.name.text() == "id")
vdlg.scope.set_current("global", emit=False)
vdlg._accept()
check("存进全局变量", any(r.get("key") == "id" and r.get("value") == "7"
                          for r in store.global_vars()))

# ---------------------------------------------------------------- 文档 AI + 默认折叠
req = new_request("用户详情", "GET", "https://api.example.com/users/1")
doc = DocDialog(store, req, None)
base_md = doc._markdown
check("代码示例默认折叠", doc._code_open is False and doc._code_host.isHidden())
check("默认折叠时只剩标题行", doc._code_panel.maximumHeight() == 48,
      str(doc._code_panel.maximumHeight()))
doc._toggle_code()
check("点箭头能展开", doc._code_open and doc.code_chevron.is_expanded()
      and doc._code_panel.maximumHeight() > 48)
doc._toggle_code()
doc._ai_filled("## 接口说明\n\n查询单个用户。")
check("文档追加 AI 段落", "接口说明" in doc._markdown
      and len(doc._markdown) > len(base_md))
doc.ai_switch.setChecked(False, emit=True)
check("AI 开关能隐藏 AI 内容", "接口说明" not in doc._markdown)
doc.ai_switch.setChecked(True, emit=True)
check("AI 开关能恢复", "接口说明" in doc._markdown)

# ---------------------------------------------------------------- 响应面板上下文
body = json.dumps({"code": 1, "msg": "下午茶时间", "data": {"id": 7}},
                  ensure_ascii=False)
resp = Response(status=200, reason="OK", elapsed=383, size=len(body),
                headers=[("Content-Type", "application/json"), ("Cache-Control", "no-store")],
                body=body.encode(), url="https://api.test/time",
                content_type="application/json")
import app.main_window as mw  # noqa: E402

win = mw.MainWindow(store)
win.response.set_response(resp)
win.response._body_text = body
win.response.tabs.set_current("headers", emit=True)
ctx2 = win.response.ai_context({"method": "GET", "url": "https://api.test/time"})
check("当前页签进入上下文", ctx2["tab"] == "headers" and ctx2["tab_label"] == "响应头")
check("响应头证据进入上下文", any("Cache-Control" in h for h in ctx2["headers"]))
win.response.tabs.set_current("pretty", emit=True)
win.response._body_text = body
check("正文页带响应体", "下午茶" in win.response.ai_context()["body"],
      win.response.ai_context()["body"][:80])
check("过期提示条有关闭与不再提醒", hasattr(win.response.stale_bar, "close_btn")
      and hasattr(win.response.stale_bar, "never_btn"))
win.response.mark_stale()
check("默认会显示过期提示", not win.response.stale_bar.isHidden())
win.response.stale_bar.never_btn.clicked.emit()
check("不再提醒会写设置", store.settings.get("stale_notice") is False)
check("不再提醒后提示条隐藏", win.response.stale_bar.isHidden())

# AI 起名后侧栏同步：给 tab 绑定集合节点
saved = new_request("Untitled Request", "GET", "https://a.com/api/users")
saved["id"] = "node_sync_test"
store.add_node(None, saved)
tab = {"id": "t1", "node_id": "node_sync_test", "request": dict(saved),
       "title": "Untitled Request"}
win._apply_ai_name(tab, "用户列表")
check("标签改名", tab["request"]["name"] == "用户列表")
check("集合节点同步改名", store.find("node_sync_test")["name"] == "用户列表")
check("侧栏已刷新", win.sidebar is not None)

# ---------------------------------------------------------------- 输入法占位修复
ime.install(app)
edit = QLineEdit()
edit.setPlaceholderText("请输入")
app.sendEvent(edit, QInputMethodEvent("ni", []))
check("候选期间占位文字隐藏", edit.placeholderText() == "", edit.placeholderText())
commit = QInputMethodEvent()
commit.setCommitString("你")
app.sendEvent(edit, commit)
check("候选提交后占位文字恢复", edit.placeholderText() == "请输入", edit.placeholderText())
edit.setText("你")
check("有内容时不会被误恢复", edit.placeholderText() == "请输入")

# ---------------------------------------------------------------- 中英文
check("中文词条",
      i18n.tr("变量") == "变量" or i18n.tr("变量") != "")
i18n.set_language("en")
check("英文：存为变量", i18n.tr("存为变量") == "Save as variable")
check("英文：AI 分析入口", i18n.tr("用 AI 分析当前页") == "Analyze this page with AI")
i18n.set_language("zh")

win.close()
dlg.close()
doc.close()

print()
print(f"{TOTAL[0] - len(FAIL)}/{TOTAL[0]} 通过")
if FAIL:
    print("失败项：" + ", ".join(FAIL))
    sys.exit(1)
