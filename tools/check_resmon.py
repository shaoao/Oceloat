"""v1.0.57 资源管理器专项自测。

覆盖：测量函数的正确性与降级、存储分类、健康分逻辑、备份清理只删旧文件、
缓存 8 分钟过期、窗口能建能刷、维护动作真的生效、中英文案齐全、菜单接线。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from app import ai as ai_mod  # noqa: E402
from app import i18n  # noqa: E402
from app import resmon  # noqa: E402
from app.store import CHANGELOG, VERSION, Store  # noqa: E402
from app.theme import apply_theme, theme_by_name  # noqa: E402

apply_theme(app, theme_by_name("dark"))
i18n.set_language("zh", notify=False)

FAIL: list[str] = []
TOTAL = [0]


def check(name: str, ok: bool, detail: str = "") -> None:
    TOTAL[0] += 1
    if ok:
        print(f"  ok   {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


# ---------------------------------------------------------------- 格式化
print("\n[格式化]")
check("0 字节", resmon.human_bytes(0) == "0 B", resmon.human_bytes(0))
check("1024 -> 1.0 KB", resmon.human_bytes(1024) == "1.0 KB", resmon.human_bytes(1024))
check("1.5 MB", resmon.human_bytes(int(1.5 * 1024 ** 2)) == "1.5 MB",
      resmon.human_bytes(int(1.5 * 1024 ** 2)))
check("None 降级为破折号", resmon.human_bytes(None) == "—")
check("千分位", resmon.human_count(31479) == "31,479", resmon.human_count(31479))

# ---------------------------------------------------------------- 测量
print("\n[内存测量]")
proc = resmon.process_memory()
check("能读到常驻内存", proc["rss"] > 0, str(proc["rss"]))
check("峰值不小于当前值", proc["peak"] >= proc["rss"],
      f"{proc['peak']} < {proc['rss']}")
check("线程数至少 1", proc["threads"] >= 1, str(proc["threads"]))

sysmem = resmon.system_memory()
check("读得到整机内存", sysmem["total"] > 0, str(sysmem["total"]))
check("可用内存不超过总量", 0 <= sysmem["available"] <= sysmem["total"],
      f"{sysmem['available']} / {sysmem['total']}")
check("占用率在 0~100 之间", 0 <= sysmem["percent"] <= 100, str(sysmem["percent"]))

# ---------------------------------------------------------------- 存储分类
print("\n[存储分类]")
tmp = Path(tempfile.mkdtemp(prefix="ocelot-res-"))
(tmp / "state.json").write_text("{}", "utf-8")
(tmp / "state.json.bak-20260101-000000").write_text("x" * 4096, "utf-8")
(tmp / "crash.log").write_text("boom", "utf-8")
(tmp / "notes.txt").write_text("hello", "utf-8")
sub = tmp / "media"
sub.mkdir()
(sub / "a.bin").write_bytes(b"0" * 2048)

scan = resmon.storage_scan(tmp)
groups = {g["key"]: g for g in scan["groups"]}
check("状态文件归到 state", groups["state"]["size"] == 2, str(groups["state"]))
check("备份归到 backup", groups["backup"]["size"] == 4096, str(groups["backup"]))
check("日志归到 log", groups["log"]["size"] == 4, str(groups["log"]))
check("子目录算进其它文件", groups["other"]["size"] == 2048 + 5, str(groups["other"]))
check("总量等于分类之和",
      scan["total"] == sum(g["size"] for g in scan["groups"]), str(scan["total"]))
check("文件计数正确", scan["files"] == 5, str(scan["files"]))
check("读得到磁盘余量", scan["disk"]["total"] > 0, str(scan["disk"]))
check("不存在的目录不抛异常", resmon.storage_scan(tmp / "nope")["total"] == 0)

# ---------------------------------------------------------------- 数据资产
print("\n[数据资产]")
st = Store.load(Path(tempfile.mkdtemp(prefix="ocelot-res-st-")) / "state.json")
# 清掉示例集合，计数只反映本测试造的数据
st.collections.clear()
st.history.clear()
st.trash.clear()
st.collections.extend([
    {"id": "f1", "type": "folder", "name": "A", "open": True, "children": [
        {"id": "r1", "type": "request", "name": "one", "method": "GET", "url": "https://a"},
        {"id": "r2", "type": "request", "name": "two", "method": "POST", "url": "https://b"},
    ]},
    {"id": "r3", "type": "request", "name": "three", "method": "GET", "url": "https://c"},
])
st.history.extend([{"id": "h1"}, {"id": "h2"}])
st.trash.extend([{"id": "t1", "node": {}, "deleted_at": time.time()}])
assets = resmon.data_assets(st, tabs=4)
check("请求计数", assets["requests"] == 3, str(assets["requests"]))
check("文件夹计数", assets["folders"] == 1, str(assets["folders"]))
check("集合计数", assets["collections"] == 2, str(assets["collections"]))
check("历史计数", assets["history"] == 2, str(assets["history"]))
check("回收站计数", assets["trash"] == 1, str(assets["trash"]))
check("标签页计数来自运行时", assets["tabs"] == 4, str(assets["tabs"]))

# ---------------------------------------------------------------- 健康分
print("\n[健康分]")
calm = {"total": 16 * 1024 ** 3, "available": 12 * 1024 ** 3,
        "used": 4 * 1024 ** 3, "percent": 25.0}
small = {"total": 300 * 1024}
state = resmon.health_status(calm, small, {"history": 10, "history_limit": 240})
check("一切正常时接近满分", state["score"] >= 95, str(state["score"]))
check("正常状态有提示", len(state["hints"]) >= 1)
check("提示不超过三条", len(state["hints"]) <= 3, str(len(state["hints"])))
tense = dict(calm)
tense["percent"] = 92.0
check("内存吃紧会扣分", resmon.health_status(tense, small, {})["score"] < state["score"])
big = {"total": 400 * 1024 ** 2}
check("数据过大继续扣分",
      resmon.health_status(calm, big, {})["score"] < state["score"])
expired = resmon.health_status(calm, small, {"history": 10}, expired_trash=3)
check("过期回收站会提示", any("回收站" in t for _lv, t in expired["hints"]))
check("分数不会低于 5", resmon.health_status(
    {"percent": 100}, {"total": 999 * 1024 ** 2},
    {"history": 9999, "history_limit": 10}, cache_entries=8, expired_trash=9)["score"] >= 5)

# ---------------------------------------------------------------- 备份清理
print("\n[备份清理]")
old = tmp / "state.json.bak-old"
old.write_bytes(b"x" * 1024)
stamp = time.time() - 9 * 86400
os.utime(old, (stamp, stamp))
fresh = tmp / "state.json.bak-fresh"
fresh.write_bytes(b"y" * 512)
count, freed = resmon.free_backups(tmp, days=7)
check("只删 7 天前的备份", count == 1, str(count))
check("释放字节数正确", freed == 1024, str(freed))
check("旧备份已删除", not old.exists())
check("新备份仍然保留", fresh.exists())

# ---------------------------------------------------------------- 缓存过期
print("\n[分析缓存]")
check("分析缓存 8 分钟过期", ai_mod.AnalysisCache.TTL == 8 * 60,
      str(ai_mod.AnalysisCache.TTL))
cache = ai_mod.AnalysisCache()
cache.put("k", "v")
cache._data["k"] = (time.time() - 8 * 60 - 1, "v")
check("超过 8 分钟不再命中", cache.get("k") is None)

# ---------------------------------------------------------------- 窗口
print("\n[窗口]")
dlg = resmon.ResourceDialog(st, analysis_cache=cache, tabs_count=4)
dlg.show()
app.processEvents()
check("窗口比旧版更小", dlg.width() <= 760 and dlg.height() <= 520,
      f"{dlg.width()}x{dlg.height()}")
check("窗口不至于小到挤成一团", dlg.width() >= 600 and dlg.height() >= 400,
      f"{dlg.width()}x{dlg.height()}")
check("三块内容都在", all(hasattr(dlg, n) for n in
                          ("mem_value", "trend", "storage_bar",
                           "health_ring", "health_hints")))
check("存储四类齐全", len(dlg.storage_cells) == 4, str(len(dlg.storage_cells)))
check("健康提示两行", len(dlg.health_hints) == 2, str(len(dlg.health_hints)))
check("内存数值已填充",
      "MB" in dlg.mem_value.text() or "GB" in dlg.mem_value.text(),
      dlg.mem_value.text())
check("系统内存也写进副标题", "%" in dlg.mem_sub.text(), dlg.mem_sub.text())
check("存储数值已填充", dlg.storage_sub.text() != "—", dlg.storage_sub.text())
check("磁盘余量已填充", "剩余" in dlg.disk_note.text(), dlg.disk_note.text())
check("健康分已算出", dlg.health_ring._center.isdigit(), dlg.health_ring._center)
check("趋势至少有一个采样点", len(dlg._samples) >= 1, str(len(dlg._samples)))
check("维护只留两颗按钮", all(hasattr(dlg, n) for n in ("btn_free", "btn_clean")))
check("旧的四连指标卡已删除", not hasattr(dlg, "tile_mem"))
check("对象分布已删除", not hasattr(dlg, "object_rows"))

# 一键清理：缓存真的清掉、回报里带上条数
cache.put("x", "y")
st.trash.append({"id": "old", "node": {}, "deleted_at": time.time() - 60 * 86400})
dlg._act_clean()
app.processEvents()
check("一键清理清空分析缓存", len(cache) == 0, str(len(cache)))
check("一键清理给出回报", dlg.report.text() != "", dlg.report.text())

# 释放内存不崩、给出回报
dlg._act_free()
check("释放内存有回报", dlg.report.text() != "", dlg.report.text())

# 关窗停表并丢采样
dlg._timer.start()
dlg.done(0)
check("关窗停止采样", not dlg._timer.isActive())
check("关窗清空采样", len(dlg._samples) == 0, str(len(dlg._samples)))

# ---------------------------------------------------------------- 中英文案
print("\n[文案]")
strings = [
    "资源管理器", "资源管理器…", "进程内存", "峰值 {peak}", "存储", "健康度",
    "峰值 {peak} · 系统 {pct}%", "已用 {used} / {total}",
    "{size} · {files} 个文件", "磁盘剩余 {free}（{pct}%）",
    "现在 {now} · 平均 {avg}", "刚开始采样", "采样中…", "近 {m} 分钟",
    "状态文件", "自动备份", "运行日志", "其它文件", "健康分",
    "释放内存", "一键清理", "清过期回收站 + 7 天前的备份 + AI 分析缓存",
    "已清理 {what} · {v}", "{n} 项过期记录", "{n} 个旧备份", "{n} 份分析缓存",
    "没有需要清理的东西", "已释放 {v}", "内存已经很干净，无需释放",
    "指标已刷新", "数据目录 {path}",
]
i18n.set_language("en", notify=False)
missing = [s for s in strings if i18n.tr(s) == s]
check("英文词条齐全", not missing, "、".join(missing))
check("英文不是拼音", i18n.tr("存储") == "Storage", i18n.tr("存储"))
i18n.set_language("zh", notify=False)

# ---------------------------------------------------------------- 接线
print("\n[接线]")
mw_src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("菜单里有资源管理器入口", "资源管理器…" in mw_src)
check("菜单动作接到 open_resources", "self.open_resources()" in mw_src)
check("open_resources 传入分析缓存", "analysis_cache=self._analysis_cache" in mw_src)
check("清数据后刷新侧栏", "_on_resources_changed" in mw_src)
check("版本 1.0.59", VERSION == "1.0.59", VERSION)
check("更新内容是 1.0.59", CHANGELOG[0]["version"] == "1.0.59")
check("更新内容写了资源管理器",
      any("资源管理器" in x for x in CHANGELOG[0]["items"])
      or any("标识" in x for x in CHANGELOG[0]["items"]))

# ---------------------------------------------------------------- 汇总
print(f"\n{len(FAIL)} failed / {TOTAL[0]} checks")
if FAIL:
    for name in FAIL:
        print("  -", name)
sys.exit(1 if FAIL else 0)
