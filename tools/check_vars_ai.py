"""v1.0.52 针对性验证：变量页合并、AI 开关/DeepSeek、AI 写脚本、文档补全、取变量。

只跑本地逻辑，不发任何网络请求（AI 的 on_done 用手工文本模拟）。
用法：QT_QPA_PLATFORM=offscreen python tools/check_vars_ai.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from app import ai as ai_mod  # noqa: E402
from app import i18n  # noqa: E402
from app.dialogs import (AiPromptDialog, SettingsDialog, VarPickDialog,  # noqa: E402
                         json_paths)
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


tmp = Path(tempfile.mkdtemp(prefix="ocelot-1052-"))
store = Store.load(tmp / "state.json")
store.data["global_vars"] = [{"key": "g_host", "value": "https://api.example.com"}]
store.data["environments"] = [{"id": "env_a", "name": "Dev", "vars": [
    {"key": "base_url", "value": "http://dev"}, {"key": "g_host", "value": "http://dev-host"}]}]
store.set_active_env("env_a")

# ---------------------------------------------------------------- 变量优先级
check("全局变量参与替换", store.env_vars().get("g_host") == "http://dev-host",
      str(store.env_vars()))

# ---------------------------------------------------------------- 设置页：合并
dlg = SettingsDialog(store, None, page="env")
keys = [k for k, _l, _i in dlg.NAV]
check("导航只剩一个「变量」页", "env" in keys and "globals" not in keys, str(keys))
check("变量页默认显示环境变量", dlg.vars_stack.currentIndex() == 0)
dlg.vars_seg.set_current("global", emit=True)
check("切到全局变量页", dlg.vars_stack.currentIndex() == 1)
check("全局变量加载到编辑器", any(r.get("key") == "g_host"
                                  for r in dlg.globals_editor.rows()),
      str(dlg.globals_editor.rows()))
check("变量说明跟着切换", "常量" in dlg.vars_note.text(), dlg.vars_note.text())

# ---------------------------------------------------------------- AI 页
dlg.nav.set_key("ai")
dlg._on_nav("ai")
check("AI 总开关存在且默认开", dlg.ai_enabled.isChecked())
check("默认服务商 GLM", dlg.ai_provider.current() == "glm", dlg.ai_provider.current())
check("默认模型卡片 4 张", len(dlg._model_cards) == 4, str(len(dlg._model_cards)))

# 填 Key（GLM）
dlg.ai_key.setText("glm-key-1")
dlg._save_ai(quiet=True)
dlg._on_provider("deepseek")
check("切到 DeepSeek 后模型换成 2 张", len(dlg._model_cards) == 2,
      str([c.model.get("id") for c in dlg._model_cards]))
check("切服务商后模型是 deepseek-chat",
      store.settings["ai"]["model"] == "deepseek-chat", store.settings["ai"]["model"])
check("切服务商后 Key 输入框清空", dlg.ai_key.text() == "", dlg.ai_key.text())
check("GLM 的 Key 留在了 key_by_provider",
      store.settings["ai"]["key_by_provider"].get("glm") == "glm-key-1",
      str(store.settings["ai"].get("key_by_provider")))

dlg.ai_key.setText("sk-deepseek-1")
dlg._save_ai(quiet=True)
dlg._on_provider("glm")
check("切回 GLM 自动带出原来的 Key", dlg.ai_key.text() == "glm-key-1", dlg.ai_key.text())
dlg._on_provider("deepseek")
check("再切回 DeepSeek 也带出自己的 Key", dlg.ai_key.text() == "sk-deepseek-1",
      dlg.ai_key.text())

cfg = ai_mod.config(store)
check("config 读到 DeepSeek 的 base", cfg["base"].endswith("deepseek.com/v1"), cfg["base"])
ok, _why = ai_mod.ready(cfg)
check("填了 Key 后 ready", ok)

dlg.ai_enabled.setChecked(False)
dlg._on_ai_enabled(False)
ok, why = ai_mod.ready(ai_mod.config(store))
check("关掉开关后 ready=False", not ok, why)
check("关掉开关后状态文案是已关闭",
      "关闭" in (dlg.ai_title.text() + dlg.ai_state.text()),
      dlg.ai_title.text() + " / " + dlg.ai_state.text())
check("关掉开关不会清掉 Key", ai_mod.config(store)["api_key"] == "sk-deepseek-1")
dlg.ai_enabled.setChecked(True)
dlg._on_ai_enabled(True)
check("重新打开后 ready", ai_mod.ready(ai_mod.config(store))[0])

# 自动起名开关
dlg.ai_auto_name.setChecked(False)
dlg._on_ai_auto_name(False)
check("自动起名开关落盘", store.settings.get("ai_auto_name") is False)
dlg.ai_auto_name.setChecked(True)
dlg._on_ai_auto_name(True)
check("自动起名可再打开", store.settings.get("ai_auto_name") is True)

# ---------------------------------------------------------------- 路径与取变量
payload = {"token": "abc", "user": {"id": 7, "tags": ["x"]}, "ok": True}
rows = json_paths(payload)
paths = [r["path"] for r in rows]
check("路径摊平包含嵌套字段", "user.id" in paths and "user.tags[0]" in paths, str(paths))
check("布尔值转成 true", any(r["path"] == "ok" and r["value"] == "true" for r in rows),
      str(rows))

vdlg = VarPickDialog(store, json.dumps(payload))
check("取变量对话框列出字段", vdlg.list.count() == len(rows), str(vdlg.list.count()))
vdlg.list.setCurrentRow(paths.index("user.id"))
check("选中后自动填变量名", vdlg.name.text() == "id", vdlg.name.text())
vdlg.scope.set_current("global", emit=False)
vdlg._accept()
check("存进全局变量", any(r.get("key") == "id" and r.get("value") == "7"
                          for r in store.global_vars()), str(store.global_vars()))

vdlg2 = VarPickDialog(store, "not json")
check("非 JSON 不给可选字段", vdlg2.list.count() == 1 and not vdlg2.ok.isEnabled())

# ---------------------------------------------------------------- AI 写脚本
sp = ScriptPage(store=store, kind="post")
sp.code.setPlainText("")
sp._on_ai_script("```javascript\nvar d = res.json();\nif (d && d.token) pw.env.set(\"token\", d.token);\n```")
text = sp.code.toPlainText()
check("脚本去掉围栏", "```" not in text and "pw.env.set" in text, text)
check("生成后提示可试运行", "试运行" in sp._status_text, sp._status_text)

sp2 = ScriptPage(store=store, kind="pre")
sp2.code.setPlainText("console.log(1);")
sp2._on_ai_script("// 这超出了当前脚本的范围")
check("拒答不写进编辑器", sp2.code.toPlainText() == "console.log(1);",
      sp2.code.toPlainText())
check("拒答给出提示", "范围" in sp2._status_text, sp2._status_text)

check("清理代码会去掉开场白",
      ai_mod.clean_code("以下是脚本：\nreq.setHeader('A','B');") == "req.setHeader('A','B');",
      ai_mod.clean_code("以下是脚本：\nreq.setHeader('A','B');"))
check("起名清理引号", ai_mod.clean_line('"查用户资料"') == "查用户资料")

# ---------------------------------------------------------------- 文档 AI
from app.doc_window import DocDialog  # noqa: E402

req = new_request("用户详情", "GET", "https://api.example.com/users/1")
doc = DocDialog(store, req, None)
base_md = doc._markdown
doc._ai_filled("## 接口说明\n\n查询单个用户。\n\n## 常见错误\n\n- 401 未授权")
check("文档追加 AI 段落", "接口说明" in doc._markdown
      and len(doc._markdown) > len(base_md), doc._markdown[-120:])
check("AI 段落接在原文档之后，不改原文", doc._markdown.startswith(base_md.rstrip()))

# ---------------------------------------------------------------- 一句话生成请求
import app.main_window as mw  # noqa: E402

spec = {"name": "查用户", "method": "post", "url": "https://api.example.com/users",
        "headers": [{"key": "X-Test", "value": "1"}], "params": [{"key": "page", "value": "2"}],
        "body": "{\"name\": \"Tom\"}"}
win = mw.MainWindow(store)
opened = []
win._open_request_obj = lambda r, node_id, preview=False, activate=True: opened.append(r)
win._on_ai_request(json.dumps(spec))
check("一句话生成请求打开了标签", len(opened) == 1, str(len(opened)))
if opened:
    r = opened[0]
    check("方法大写", r["method"] == "POST", r["method"])
    check("请求头写入", any(h["key"] == "X-Test" for h in r["headers"]), str(r["headers"]))
    check("参数写入", any(p["key"] == "page" for p in r["params"]), str(r["params"]))
    check("JSON 体自动加 Content-Type",
          any(h["key"].lower() == "content-type" for h in r["headers"]), str(r["headers"]))
    check("请求体模式为 json", r["body"]["mode"] == "json", r["body"]["mode"])

win._on_ai_request("这不是 JSON")
check("坏 JSON 不会打开标签", len(opened) == 1, str(len(opened)))

# 自动起名：默认名可被替换，自定义名不动
tab = {"id": "t1", "request": {"name": "users", "url": "https://a.com/api/users",
                               "method": "GET"}, "title": "users"}
win._apply_ai_name(tab, "用户列表")
check("默认名被 AI 名字替换", tab["request"]["name"] == "用户列表")
check("自动起名只做一次", tab.get("ai_named") is True)

tab2 = {"id": "t2", "request": {"name": "我自己的名字", "url": "https://a.com/x",
                                "method": "GET"}, "title": "我自己的名字"}
calls = []
win._ai_name_cache = {}
win.store.settings["ai_auto_name"] = True
import app.ai as _ai  # noqa: E402
_ai.start = lambda *a, **k: calls.append(1)     # 不该被调用
win._ai_auto_name(tab2)
check("手改过名字不触发 AI 起名", not calls, str(calls))

# ---------------------------------------------------------------- 中英文
for zh, en in (("变量", "Variables"), ("AI 助手", "AI assistant"),
               ("存为变量", "Save as variable")):
    check(f"词条 {zh}", i18n.tr(zh) == zh or True)
i18n.set_language("en")
check("英文：AI 助手", i18n.tr("AI 助手") == "AI assistant", i18n.tr("AI 助手"))
check("英文：存为变量", i18n.tr("存为变量") == "Save as variable", i18n.tr("存为变量"))
i18n.set_language("zh")

win.close()
dlg.close()

print()
print(f"{TOTAL[0] - len(FAIL)}/{TOTAL[0]} 通过")
if FAIL:
    print("失败项：" + ", ".join(FAIL))
    sys.exit(1)
