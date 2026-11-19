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

# ---------------------------------------------------------------- 对象统计
print("\n[对象统计]")
stats = resmon.object_stats(5)
check("对象总数为正", stats["total"] > 0, str(stats["total"]))
check("Top 最多 5 项", len(stats["top"]) <= 5, str(len(stats["top"])))
check("Top 按数量降序",
      [n for _t, n in stats["top"]] == sorted([n for _t, n in stats["top"]], reverse=True))
check("类型数不少于 Top 项数", stats["types"] >= len(stats["top"]))
runtime = resmon.runtime_stats()
check("控件数非负", runtime["widgets"] >= 0, str(runtime["widgets"]))
check("堆块数为正", runtime["blocks"] > 0, str(runtime["blocks"]))

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
dlg.resize(1080, 800)
dlg.show()
app.processEvents()
check("窗口能构建", dlg.width() > 800 and dlg.height() > 600,
      f"{dlg.width()}x{dlg.height()}")
check("四个指标卡都在", all(hasattr(dlg, n) for n in
                            ("tile_mem", "tile_sys", "tile_data", "tile_rt")))
check("六块分节都在", all(hasattr(dlg, n) for n in
                          ("mem_ring", "storage_bar", "disk_bar",
                           "health_ring", "asset_stats", "object_rows")))
check("资产六项齐全", len(dlg.asset_stats) == 6, str(len(dlg.asset_stats)))
check("对象行有五条", len(dlg.object_rows) == 5, str(len(dlg.object_rows)))
check("内存数值已填充", "MB" in dlg.tile_mem.value.text() or "GB" in dlg.tile_mem.value.text(),
      dlg.tile_mem.value.text())
check("系统内存已填充", "%" in dlg.tile_sys.value.text(), dlg.tile_sys.value.text())
check("存储数值已填充", dlg.tile_data.value.text() != "—", dlg.tile_data.value.text())
check("健康分已算出", dlg.health_ring._center.isdigit(), dlg.health_ring._center)
check("趋势至少有一个采样点", len(dlg._samples) >= 1, str(len(dlg._samples)))
check("维护按钮齐全", all(hasattr(dlg, n) for n in
                          ("btn_free", "btn_cache", "btn_trash", "btn_backup")))

# 清空缓存动作真的清
cache.put("x", "y")
dlg._act_cache()
app.processEvents()
check("清空分析缓存生效", len(cache) == 0, str(len(cache)))
check("清空后给出回报", "清空" in dlg.report.text() or "空" in dlg.report.text(),
      dlg.report.text())

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
    "资源管理器", "资源管理器…", "进程内存", "峰值 {v}", "系统内存", "应用数据", "运行时",
    "维护", "释放内存", "清空分析缓存", "清理过期回收站", "清理旧备份",
    "内存构成", "存储构成", "磁盘", "健康度", "数据资产", "对象分布", "Ocelot 进程",
    "其它应用", "可用内存", "状态文件", "自动备份", "运行日志", "其它文件",
    "健康分", "请求数", "集合数", "历史记录", "回收站", "环境数", "标签页",
    "整机 {total}", "已用 {used} / {total}", "{files} 个文件 · 状态 {state}",
    "剩余 {free}（{pct}%）", "共 {n} 个请求", "{n} 个对象 · {k} 种类型",
    "线程 {t} · 控件 {w} · 缓存 {c}", "刚开始采样", " · 现在 {now} · 最低 {lo} · 平均 {avg} · 最高 {hi}",
    "已释放 {v}", "已清空 {n} 份分析缓存", "已清理 {n} 项过期记录",
    "已删除 {n} 个旧备份 · {v}", "没有超过 7 天的备份", "指标已刷新",
    "系统内存 {pct}%，余量不多", "未发现问题，状态良好",
]
i18n.set_language("en", notify=False)
missing = [s for s in strings if i18n.tr(s) == s]
check("英文词条齐全", not missing, "、".join(missing))
check("英文不是拼音", i18n.tr("内存构成") == "Memory composition", i18n.tr("内存构成"))
i18n.set_language("zh", notify=False)

# ---------------------------------------------------------------- 接线
print("\n[接线]")
mw_src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("菜单里有资源管理器入口", "资源管理器…" in mw_src)
check("菜单动作接到 open_resources", "self.open_resources()" in mw_src)
check("open_resources 传入分析缓存", "analysis_cache=self._analysis_cache" in mw_src)
check("清数据后刷新侧栏", "_on_resources_changed" in mw_src)
check("版本 1.0.57", VERSION == "1.0.57", VERSION)
check("更新内容是 1.0.57", CHANGELOG[0]["version"] == "1.0.57")
check("更新内容写了资源管理器",
      any("资源管理器" in x for x in CHANGELOG[0]["items"]))
check("更新内容写了 8 分钟", any("8 分钟" in x for x in CHANGELOG[0]["items"]))

# ---------------------------------------------------------------- 汇总
print(f"\n{len(FAIL)} failed / {TOTAL[0]} checks")
if FAIL:
    for name in FAIL:
        print("  -", name)
sys.exit(1 if FAIL else 0)
