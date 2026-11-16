"""状态模型与持久化。

存储位置：~/Library/Application Support/Ocelot/state.json（原子写入）。
数据结构保持纯 JSON，便于用户直接编辑或版本管理。
"""
from __future__ import annotations

import copy
import json
import os
import random
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_DIR = Path.home() / "Library" / "Application Support" / "Ocelot"
STATE_FILE = APP_DIR / "state.json"
LEGACY_DIR = Path.home() / "Library" / "Application Support" / "Reqly"

VERSION = "1.0.18"

CHANGELOG = [
    {
        "version": "1.0.18",
        "date": "2026-11-17",
        "items": [
            "修复：在输入框上点右键会直接崩掉（QApplication 没有 cursor()，取不到右键位置就抛异常）。"
            "现在按事件自带的屏幕坐标弹菜单，取不到才退回鼠标位置，右键不会再中断程序",
            "修复：本地 Mock 服务「界面显示已停止、浏览器刷新却还能访问」—— 之前只关了监听端口，"
            "浏览器那条 HTTP keep-alive 老连接仍然活着，继续被服务响应。现在停止时会主动断开"
            "所有活着的连接，响应也不再要求复用连接，停就是真停",
            "修复：停止服务时会先把在途连接断开再关端口，避免「停了之后又冒出一个响应」",
            "优化：自测扩到 382 项 —— 新增右键菜单定位、停服务后老连接不再返回数据两项回归检查",
        ],
    },
    {
        "version": "1.0.17",
        "date": "2026-11-17",
        "items": [
            "新功能：Mock 条件规则 —— 一条路由可以按 请求头 / 查询参数 / 请求体 / 方法 "
            "分别返回不同结果：带 token 返回 VIP 数据、不带返回 401，前端能一次把"
            "正常与异常分支都测完；规则支持 等于 / 包含 / 存在 / 不存在 四种匹配，"
            "可单独设状态码、延迟与响应体",
            "新功能：Mock 动态数据 —— 响应体里写 {{@id}} {{@uuid}} {{@name}} {{@cname}} "
            "{{@email}} {{@phone}} {{@city}} {{@now}} {{@int(1,99)}} {{@pick(a,b)}} "
            "之类的占位符，每个请求现算一次，不再永远返回同一份死数据；编辑路由时"
            "可以「预览随机数据」确认占位符写对了",
            "新功能：Mock 请求日志 —— 新增「请求日志」页，实时看到每一次请求的方法、"
            "路径、状态码、耗时，以及命中了哪条路由和哪条规则，边调边看不用翻终端；"
            "顶部统计 2xx / 4xx / 平均耗时，可一键清空",
            "新功能：路由列表显示每条路由的命中次数，配合延迟示例（2 秒慢接口）"
            "与鉴权规则示例，打开就能试",
            "改进：Mock 中心的启动按钮不再固定写「停止服务」—— 未启动时是「启动服务」，"
            "启动后才是「停止服务」，图标与配色一起变",
            "改进：接口文档的表格重做 —— 表头独立成一条淡底栏，行与行之间有分隔线，"
            "首列宽度按最长字段实测后钳在 96~210，长内容自动换行，不再出现列错位与"
            "文字挤在一起",
            "改进：代码示例排版 —— 语言标签与代码正文严格左对齐，代码紧贴标签不再"
            "垂直居中；长行折行后高度按真实行数计算，底部不会切半行、也不会多出"
            "没用的滚动条",
            "改进：设置菜单里的「设置…」换成齿轮图标，并去掉「切换浅色 / 深色」这一项"
            "（主题仍在 设置 → 外观 里切换）",
            "改进：关于页去掉文件名与类名，换成面向用户的能力清单（发请求 / 看响应 / "
            "出文档 / 造假数据 / 多环境 / 可复用）与「一次请求走完的流程」四步说明",
            "修复：停止本地服务后端口可能仍被占用（另一个 Ocelot 实例或上一次没退干净），"
            "现在会等端口真正释放，并在界面上如实提示「端口仍被其它程序占用」；"
            "启动时若 8787 已被别的 Ocelot 占用，会明确告知并自动换端口，不再默默换掉"
            "让人以为 8787 就是自己这个服务",
            "修复：动态数据里含中文时写进 HTTP 响应头会导致响应中断（Content-Length "
            "对不上），现在响应头统一做安全编码",
            "优化：自测扩到 374 项 —— 覆盖菜单条目、按钮状态、占位符随机性、条件规则"
            "命中、请求日志耗时、表格列宽与代码块对齐、超长代码滚动",
        ],
    },
    {
        "version": "1.0.16",
        "date": "2026-11-17",
        "items": [
            "新功能：真正的本地 Mock 服务 —— 在 127.0.0.1 起一个真的 HTTP 服务，"
            "路由、方法、状态码、延迟、响应体全都能自己写；支持前缀通配 /api/users/*、"
            "回显模式（把收到的请求原样返回）、CORS，浏览器和脚本都能直接连。"
            "「试用」一键建请求，还能设置随应用启动；端口被占用会自动换一个",
            "新功能：Mock 中心分两页 —— 本地 Mock 管路由（新建 / 编辑 / 复制地址 / 删除），"
            "公开接口保留 28 个免费 API 清单",
            "新功能：快捷键独立成页 —— 16 个动作全部可改：点键帽录制新组合、一键清除、"
            "恢复默认；两个动作抢同一个键位时旧的那个自动让位。改完立刻生效，不用重启",
            "新功能：接口文档补全内容 —— 概览（方法 / 地址 / 状态 / 耗时 / 体积 / 内容类型）、"
            "鉴权说明、Cookies 表、响应头表与状态码语义，复制或保存出来就是一份能交付的文档",
            "改进：接口文档窗口重排 —— 顶部请求名片带状态 / 耗时 / 体积指标，"
            "左侧目录跟着滚动高亮，代码示例按语言缓存，来回切换不再重算",
            "改进：代码示例十种语言统一语法高亮，命令行的 -X / -H、URL、字符串、数字各自成色；"
            "代码正文与左上角的语言标签严格左对齐（之前被行号槽多推了 16px）",
            "改进：命令面板条目不再被裁掉 —— 列表可滚动、滚轮带缓动，键盘上下选到底部会自动跟随，"
            "卡片高度按整行计算，最后一行不会切半截",
            "改进：Mock 公开接口列表改成子控件 + 布局排版，方法、地址、说明严格纵向对齐；"
            "搜索加 120ms 防抖，连打不再逐字重建列表",
            "改进：标题栏右上角的设置按钮换成真正的齿轮图标（之前是一圈放射线，像太阳）",
            "改进：设置对话框加宽到 940×700；关于页去掉快捷键表，换成「为什么是 Ocelot」"
            "四条优势与六层架构说明",
            "修复：地址里已经写了同名同值参数时，代码生成与文档会重复拼一遍 "
            "（?verbose=true&verbose=true），现在先比对再追加",
            "修复：Mock 面板在服务启动 / 停止后状态胶囊、按钮可用状态不同步",
            "优化：自测扩到 351 项：真起本地服务验证路由 / 回显 / 404、快捷键录制与冲突让位、"
            "命令面板滚动、代码块左对齐与高亮类型、文档新章节",
        ],
    },
    {
        "version": "1.0.15",
        "date": "2026-11-17",
        "items": [
            "新功能：接口文档窗口 —— 响应右上角「更多 → 查看接口文档」，"
            "方法、地址、参数表、请求头、请求体、响应示例排成一页；左侧大纲可跳转，"
            "底部十种语言的代码示例一键切换，右上角开关决定是否把密钥打码，可复制可存成 .md",
            "新功能：Mock 数据面板 —— 内置 28 个免费公开接口（httpbin / JSONPlaceholder / "
            "DummyJSON / ReqRes / 随机图片等），分组 + 搜索，点一行就变成一条填好请求体的请求",
            "新功能：响应时间线 —— 响应面板新增「时间线」，把同一地址的历史耗时画成柱子，"
            "按状态码上色，顶部给出次数 / 成功率 / 平均 / P95 / 最慢，悬停看单次详情",
            "新功能：命令面板加了 Mock 数据、接口文档、复制当前请求、关闭标签四项",
            "改进：参数表的表头与数据行现在严格对齐 —— 勾选框占位改成真控件，"
            "「类型」表头跟着胶囊居中对齐，之前会差 3~8px",
            "改进：地址栏的历史补全换成自绘浮层（圆角、图标、等宽地址、键盘上下选择），"
            "不再用系统白底列表",
            "改进：设置页排版重做 —— 云同步的地址、Token、同步按钮改成整行布局，"
            "窄窗口下不会再被挤出卡片；对话框加宽到 900×672，页面标题层级拉开",
            "改进：关于页重做成一张应用名片 —— 大字标、版本胶囊、运行环境三列、"
            "常用快捷键两列、复制版本信息一键带走",
            "修复：响应头、文档正文这类可选中文字的右键菜单还是 macOS 系统菜单"
            "（英文 Copy / Select All 且半透明），现在统一接管成自己的中文菜单",
            "自测扩到 312 项：表头列对齐、时间线统计、Mock 搜索与分组、设置页控件不被压扁、"
            "文档窗口渲染与保存",
        ],
    },
    {
        "version": "1.0.14",
        "date": "2026-11-17",
        "items": [
            "新功能：一键接口文档 —— 响应右上角「更多」里可以复制整段 Markdown 文档"
            "（方法、地址、Query、请求头、请求体、状态码、耗时、响应示例），不用再手写",
            "新功能：秘密打码 —— 同一菜单里可「脱敏复制响应体」或导出「密钥已打码」的文档，"
            "token / Cookie / password / JWT / Bearer 自动换成 ••••••（长值保留末四位便于对账），"
            "贴群、发工单、截图都不怕漏密钥",
            "新功能：标签右键新增「复制接口文档（Markdown）」，每条请求都能单独导出一份",
            "改进：代码生成（cURL / Python / JS / Go / Java / PHP / C# / Kotlin / PowerShell / HTTPie）"
            "现在会把 Cookies 页里的行合并进 Cookie 请求头，被禁用的行不会带出去 —— "
            "复制出来的代码和点「发送」的结果一致",
            "修复：运行时日志前缀还剩 Reqly 的地方（保存响应 / 保存配置失败提示）统一成 Ocelot",
            "自测扩到 283 项：文档生成的每一段、脱敏规则、截断、结构对比、Cookie 进代码",
        ],
    },
    {
        "version": "1.0.13",
        "date": "2026-11-17",
        "items": [
            "改名：Reqly → Ocelot。标题栏、关于页、菜单、User-Agent 与数据目录全部换成 Ocelot，"
            "首次启动会自动把 ~/Library/Application Support/Reqly 里的旧数据搬到新目录，配置不丢",
            "改进：主题色不再只影响按钮 —— 选中底、聚焦描边、悬停徽标、标签页标题、侧栏选中标记、"
            "设置导航一起同步；文字也会朝强调色偏一点点，整块界面是一致的色温",
            "新功能：请求新增 Cookies 一栏 —— 表格里填的 Cookie 会自动合并成 Cookie 请求头，"
            "响应带 Set-Cookie 时可一键「从响应导入」，登录态跟着请求走",
            "新功能：云同步（Turso）—— 填数据库地址与 Auth Token，先「测试连接」再上传；"
            "可「从云端恢复」（恢复前自动备份 state.json.bak），也能勾选「退出时自动上传」",
            "修复：勾选框选中时多出来的一圈黑边 —— 之前把默认画笔也画了一遍，现在勾选态只有实心块",
            "改进：参数类型胶囊去掉描边，Auto 直接用它的暖沙色、字号加大到 10.2，小胶囊不再显得脏",
            "修复：菜单四个圆角外残留小方块 —— 菜单窗口改为透明底，圆角这才真正生效",
            "修复：主题色第一颗色点的选中环被卡片边缘切掉 —— 第一颗圆心右移，上下也留出描边余量",
            "新功能：地址栏按历史补全 —— 聚焦时列出用过的地址，包含匹配，敲几个字就能选",
            "新功能：命令面板（⌘K）可以直接切换环境、直达外观 / 云同步设置",
            "修复：标签右键「复制为 cURL」点了没反应（to_curl 没导入，NameError）",
            "优化：迁移旧配置、去掉重复的 QMenu 导入、请求计数与 Cookie 提示合并成一次刷新",
            "自测扩到 236 项：Cookie 合并与导入、Turso 地址归一化与快照校验、主题色渗透、"
            "菜单与色点几何",
        ],
    },
    {
        "version": "1.0.12",
        "date": "2026-11-17",
        "items": [
            "新功能：设置 · 外观新增「主题色」—— 7 个色点任选（自动 / 海蓝 / 松青 / 苔绿 / 陶橙 / 绯红 / 藤紫），"
            "主按钮、开关、勾选框与发送键立刻跟着变，「自动」保持原来的黑白反色",
            "改进：参数类型菜单里的 Auto 有了自己的颜色（暖沙），和 Null 的灰、JSON 的橙一眼就能分开",
            "修复：切换配色 / 主题色时，已经销毁的悬浮详情卡会被重新包一层空壳实例、绘制直接崩掉 —— "
            "现在空壳实例自动跳过绘制，切换主题不再有崩溃风险",
            "优化：切换配色只刷新可见控件，隐藏控件等显示时自然重绘，大窗口下切换更顺",
            "自测扩到 228 项：主题色切换与持久化、色点数量与点击、Auto 与 Null 色差",
        ],
    },
    {
        "version": "1.0.11",
        "date": "2026-11-17",
        "items": [
            "修复：打开应用后标签点不动、内容切不过去 —— 标签栏现在无条件发出切换信号；"
            "主窗口新增自愈：编辑器挂错请求、标签栏出现幽灵标签都会自动修好，窗口重新获得焦点时再自检一次",
            "修复：编辑器 load 中途出错会把加载标记卡住，之后所有编辑都不再回写 —— 改为 finally 兜底",
            "优化：侧栏收起 / 展开的卡顿 —— 根因是分隔条按侧栏最小尺寸（≈158）卡住子控件，"
            "动画前三分之二的时间完全不动、最后一帧直接消失；现在动画期间放开最小尺寸与尺寸策略，收尾复原，真正逐帧滑动",
            "优化：切标签、收到响应不再同步写磁盘（合并成 700ms 一次），历史列表改为增量刷新，"
            "不再每发一次请求重建几百个控件",
            "优化：重复点击当前标签不再重新格式化整段响应，大 JSON 下切换明显更顺",
            "优化：大响应改为按需渲染 —— JSON 树与「原始」页点开才构建，190KB 响应从 1 秒降到 60 毫秒；"
            "超过 600KB 只预览前 600KB 并提示用「另存为」取全文，超过 180KB 不再强行语法高亮",
            "新功能：提取结果「存为变量」—— 一键写进当前环境变量，之后用 {{名字}} 引用，"
            "登录拿 token 这类流程不用再手动复制粘贴",
            "新功能：中键点击标签直接关闭；双击请求 / 响应之间的分隔条恢复 50 / 50",
            "新功能：双击标签栏里斜体的预览标签即可转正固定（VSCode 行为），以前双击标签毫无反应",
            "自测扩到 207 项：标签自愈、中键关闭、分栏复位、存为变量、侧栏逐帧动画、历史增量刷新",
        ],
    },
    {
        "version": "1.0.10",
        "date": "2026-11-16",
        "items": [
            "新功能：集合运行器 —— 右键集合文件夹「运行集合」或按 ⌘⇧R，按树里的顺序把整个集合跑一遍，"
            "逐条显示状态码 / 耗时 / 体积，底部汇总成功失败与总耗时，可随时停止、"
            "一键复制结果表（TSV 直接粘进表格），点某一行就打开那条请求",
            "新功能：参数类型新增 File —— 表单里点一下就能选本地文件，走 multipart 真正上传，"
            "代码片段（cURL / Python / JS / Go…）同步生成对应的文件参数",
            "修复：美化把 HTML 挤成一行、或缩成一路向右的楼梯 —— 改成标签 token 流解析："
            "行内标签留在同一行、script / style / pre 内容原样保留、CDATA 不被拆、未闭合标签自动容错",
            "修复：详情卡图标始终对不准 —— 根因是 QPixmap.width() 返回的是设备像素（Retina 下是 2 倍），"
            "按 dpr 折算后图标真正居中，标题与指标行都对齐文字基线",
            "新功能：cURL 导入对话框 —— 粘贴即解析并实时预览，支持 -X / -H / -d / -F / -u / -G / "
            "--data-urlencode 与 -sSL 这类合并短选项",
            "新功能：请求标签右键菜单 —— 关闭其他 / 关闭全部 / 复制标签 / 复制为 cURL",
            "改进：代码片段扩到 10 种语言（含 Go / Java / PHP / C# / Kotlin / PowerShell），全部带语法高亮",
            "改进：格式 / 编码 / 类型下拉统一自绘，不再出现系统菜单的勾选乱码；方法色板按参考图重排并无「自定义」",
            "修复：鼠标点击请求标签内容不跟着切换、切回来东西丢失 —— 标签栏现在真的会发出切换事件",
            "自测扩到 196 项：运行器顺序执行与结果汇总、文件类型、美化结构、图标居中、标签切换全覆盖",
        ],
    },
    {
        "version": "1.0.9",
        "date": "2026-11-16",
        "items": [
            "改进：参数类型首字母大写（Auto / String / Number / Boolean / Null / JSON），每种类型一个语义色，String 为绿色",
            "修复：类型 / 格式 / 编码下拉改为自绘菜单，macOS 原生勾选图标渲染成乱码的问题消失",
            "修复：选中内容时冒出来的「全部展开 / 全部折叠」按钮 —— 彻底隐藏，工具栏只剩格式与编码",
            "修复：详情卡图标错位与脚注压住 Body 行 —— 标题/指标行图标同尺寸同 x，所有区块改为顺序累加排版",
            "新功能：代码片段增加 Go / Java / PHP / C# / Kotlin / PowerShell，并启用多语言语法高亮",
            "改进：HTTP 方法色板对准参考图（GET 绿 / POST 橙 / PUT·HEAD·OPTIONS 蓝 / DELETE 红 / PATCH 粉 / TRACE 紫），去掉「自定义」",
            "修复：鼠标点击请求标签时内容不跟着切换、切回来东西丢失 —— TabStrip 现在会正确发出 currentChanged",
            "自测扩到 186 项：类型色、自绘菜单、详情卡对齐、代码语言、点击标签切换全部覆盖",
        ],
    },
    {
        "version": "1.0.8",
        "date": "2026-11-16",
        "items": [
            "改进：响应时间 / 响应大小悬浮卡改为固定锚点显示，不再跟着鼠标乱跑；重做自绘排版并加上分段图标",
            "新功能：大小卡新增 Header / Body 分配条，时间卡补充「估算」说明，避免误读每段耗时",
            "修复：地址已经改成 time-tx 却还显示上一张图片响应 —— 请求一改动就作废旧响应",
            "修复：多个请求标签点击后内容仍串在一起 —— 响应、格式、编码与当前响应子页全部按标签独立保存",
            "改进：格式 / 编码按钮统一为同一套自绘控件，只在「美化」页显示，其他页不再混入转换按钮",
            "修复：拖动左侧栏宽度后页面出现地址栏消失、描述行上浮 —— 动画被打断时未恢复绘制，现已完整复原",
            "自测扩到 167 项：固定卡片、按钮隔离、标签响应独立、动画中断恢复全部覆盖",
        ],
    },
    {
        "version": "1.0.7",
        "date": "2026-11-16",
        "items": [
            "修复：侧栏折叠卡成两段 —— 根因是动画每帧都触发 splitterMoved 写磁盘，现在动画期间断开信号、只落盘一次，整段丝滑跟手",
            "修复：新建空标签再打开旧请求后两个页面内容变得一样 —— 每个标签改为独立快照，集合树变动只同步标题、不再覆盖编辑内容",
            "新功能：侧栏单击进入 VSCode 式预览（标题斜体、复用同一预览标签），双击才固定打开；编辑预览标签自动转正",
            "修复：更新内容入口太多 —— 只保留「设置 → 关于 Reqly → 查看更新内容」一个入口",
            "新功能：参数类型改为行业通用英文名（auto / string / number / boolean / null / JSON）",
            "新功能：设置 → 通用新增语言切换（简体中文 / English），英文为自然翻译，切换立即生效；菜单、按钮、欢迎页、设置页全量适配",
            "新功能：节点测速覆盖当前分栏全部节点（原先只测前 8 个），并发受控并显示进度；面板注明「速度仅供参考，不代表可用性与整体请求速度」",
            "新功能：响应区新增格式切换（Auto / JSON / XML / HTML / Text）与编码切换（UTF-8 / GBK / GB2312 / ISO-8859-1 / Base64 等 11 种）",
            "新功能：鼠标悬浮响应时间 / 响应大小弹出详情卡 —— 时间显示准备 / DNS / TCP / SSL / TTFB / 下载分段条形图，大小显示 Header / Body 分解",
            "修复：发请求时响应区不转圈像卡住 —— 加载页的 Spinner 从没启动，现在真正旋转，配合骨架屏扫光",
            "自测扩到 155 项：标签隔离、预览打开、语言切换、格式编码、计时详情、转圈状态全部覆盖",
        ],
    },
    {
        "version": "1.0.6",
        "date": "2026-11-16",
        "items": [
            "修复：节点只有 22 个 —— 现在从 tcping.cn 拉取完整的 221 个 IPv4 / 130 个 IPv6 节点，"
            "带地区运营商名称，可随时刷新缓存",
            "新功能：在线节点从「只能看延迟」升级为真正可用：选中后请求经对方服务器转发，"
            "响应指标会标出节点出口 IP、地区与耗时；自建 socks5/http 代理依旧支持",
            "修复：方法菜单/命令面板的灰色悬停条在鼠标已经离开后还追着鼠标跑 —— "
            "Popup 抓鼠标时会收到界外事件，现在先判断落点是否真的在控件内",
            "修复：侧栏折叠展开卡顿 —— 动画期间冻结内容区逐帧重绘，去掉收尾时重建整棵集合树",
            "修复：图片 / 音频响应切到「美化」「原始」显示一排问号 —— "
            "改为友好提示，原始页展示十六进制，并默认进预览页",
            "修复：标签标题变化后选中胶囊宽度没更新，把新建「+」包进了胶囊里",
            "修复：集合树区域出现左右箭头光标，统一回普通箭头",
            "修复：提示框 C++ 对象析构后仍被调用导致崩溃",
            "新功能：「本地」按钮移到「发送」按钮右边，发送操作更顺手",
            "新功能：预览工具栏新增「保存」：图片 / 音频 / 视频 / PDF / 二进制都能直接存到本地",
            "新功能：设置新增「关于 Reqly」页，放在「更新内容」上方，可一键打开更新日志",
            "新功能：更新内容按新功能 / 改进 / 修复分色，扫一眼就知道这版改了什么",
            "新功能：参数表新增「描述（可选）」列，只做备注、不会发送出去",
            "设置页导航改成显式页面映射，切换时不再出现几页内容一样的情况",
            "自测扩到 134 项：节点拉取与 PoW、中继 payload、菜单越界悬停、二进制提示、"
            "关于页导航、参数描述、标签内容隔离全部覆盖",
        ],
    },
    {
        "version": "1.0.5",
        "date": "2026-11-16",
        "items": [
            "修复：集合树选中行左侧总冒出一个灰方块（基类把缩进区按选中色涂了一块），"
            "现在不画缩进区、选中底色置全透明",
            "修复：方法菜单第二次点开会直接崩（RuntimeError: MethodMenu has been deleted），"
            "菜单改为常驻复用，连点多次也稳",
            "修复：折叠侧栏后重启应用直接报错（会话恢复里还引用着已删除的分隔条），改走分栏宽度",
            "修复：命令面板的灰色悬停条跟不上鼠标，改为零延迟跟手；键盘选中行改成细边，不再和鼠标抢视觉",
            "提示框改为自绘：尺寸严格贴合文字（原来系统提示框又大又空），圆角细边、跟随光标",
            "输入框右键菜单换成中文自绘版（撤销 / 重做 / 剪切 / 复制 / 粘贴 / 删除所选 / 全选），"
            "带图标、跟主题一致，不再弹英文系统菜单",
            "修复：响应体带 gzip / deflate / br 压缩时显示成乱码或空白，现在按 Content-Encoding "
            "（并兜底嗅探 gzip 头）先解压再展示",
            "修复：GBK / GB18030 网页中文乱码，未声明 charset 时依次尝试 UTF-8、GB18030 解码",
            "全局统一底色：侧栏与工作区都用 #19191C，去掉「一半深一半浅」的拼色，只留一条 1px 分隔线",
            "设置新增「配色方案」六套：石墨（默认 #19191C）/ 岩蓝 / 暖灰 / 松绿 / 墨黑 / 浅色，缩略图直接点选",
            "设置页整体重做：分区卡片 + 可滚动内容，网络页新增「默认 User-Agent」，数据页新增历史记录上限",
            "侧栏支持拖拽调宽（200–420）与记忆宽度；标题栏新增折叠按钮，⌘B 依然可用",
            "标签栏选中胶囊去掉描边，靠明度区分，界面更干净",
            "新功能「预览」全面升级：图片可滚轮缩放 / 拖拽平移 / 双击自适应 / 棋盘格透明底，"
            "音频视频内嵌播放（进度、暂停、另存），PDF 与二进制给出十六进制视图；"
            "响应是图片 / 音频 / 视频时自动切到预览页",
            "新功能「节点」：URL 栏右侧可选 IPv4 / IPv6 节点，支持搜索地区运营商、一键测速"
            "（TCP 握手 + DNS 往返），默认「本地直连」不受影响",
            "节点支持添加 socks5 / http 代理，选中后请求真正经由该节点发出，响应指标条会标注当前节点",
            "音视频容器格式按魔术字节判定（wav / mp3 / ogg / flac / m4a / webm），"
            "不再一律存成 .bin 导致播不出来",
            "自测扩到 108 项：缩进灰块、菜单复用、悬停零延迟、提示框尺寸、三类预览、节点解析与探测、"
            "中文右键菜单、gzip 解压与 GBK 解码、音视频格式识别",
        ],
    },
    {
        "version": "1.0.4",
        "date": "2026-11-16",
        "items": [
            "深色主题改到 #19191C 体系重新配平：窗口 / 面板 / 卡片 / 悬浮 / 选中五级灰阶，"
            "侧栏与工作区之间加了一层内容面，边界不再糊在一起",
            "参数管理重做：任意参数随时增删，每行可上移 / 下移 / 复制 / 删除，"
            "新增「类型」列（自动 / 文本 / 数字 / 布尔 / null / JSON），填进去就能按正确类型用",
            "智能粘贴：token=abc&debug=true、{\"q\":\"x\"}、多行 k: v 或 Tab 分隔、# 注释行，"
            "粘一次全拆成参数行，注释自动置为禁用",
            "URL 与参数表双向同步：粘贴带 ?a=1&b=2 的地址会自动拆进参数表、URL 只留 base；"
            "参数清空后不会再残留幽灵参数把请求搞挂",
            "方法菜单改为自绘：每个方法带颜色，当前项右侧打对号，行高对齐、无系统菜单的毛边",
            "标签栏右侧「关闭 ×」与「+」重新排版，间距拉到 10px 以上，不再挤在一起",
            "去掉界面里所有彩色圆点（集合树、环境、标签栏），统一换成矢量图标与状态徽标",
            "更新内容面板重做：按版本分块、分类计数、自动换行，长列表滚动不再卡顿重叠",
            "设置整合为单页六分区（通用 / 外观 / 网络 / 环境变量 / 数据 / 更新内容），"
            "不用再一层层开对话框；新增「代码字号」小 / 标准 / 大三档，改完立即生效",
            "新功能「对比」：同一地址的响应与上一次自动逐行 diff，标出状态码与耗时变化，"
            "也可以手动「设为基准」固定一次响应",
            "新功能「提取」：用 a.b[0].c 或 * 这样的 JSON 路径直接取字段，"
            "填错给出可用顶层字段提示，一键复制取值",
            "命令面板悬浮改为软灰色层 + 120ms 缓动，选中行加细边，不再硬切",
            "悬浮提示框改为圆角胶囊样式（更小字、更松的行距、无边框毛刺）",
            "自测扩到 80 项：参数类型推断、URL 拆分、无幽灵参数、三种粘贴格式、"
            "六个设置分页、Diff 统计、JSON 路径提取全部覆盖",
        ],
    },
    {
        "version": "1.0.3",
        "date": "2026-11-16",
        "items": [
            "修复崩溃：鼠标在集合树上移动时报 RuntimeError: wrapped C/C++ object of type "
            "QVariantAnimation has been deleted（悬停动画改用常驻对象，不再随动画结束被销毁）",
            "自测补「反复悬停」回归：集合树来回扫三遍、每次等动画结束并销毁再触发，共 56 项断言",
            "侧栏折叠时相关交互测试会自动展开侧栏，避免测试漏跑",
        ],
    },
    {
        "version": "1.0.2",
        "date": "2026-11-16",
        "items": [
            "修复崩溃：鼠标移到标签栏就 TypeError 退出（QRectF.contains 只接受 QPointF，之前传了 QPoint），"
            "从 IDE 点运行也会被这一条带崩",
            "启动自检：解释器版本过低或缺 PyQt6 时，打印当前解释器路径与修复命令，不再甩一堆 traceback",
            "从运行面板启动时主动置前窗口（raise + activateWindow）",
            "自测补鼠标交互回归：标签栏悬浮 / 点击切换 / 双击空白新建 / 侧栏与分段控件滑过，共 53 项断言",
            "截图脚本改用临时状态文件，不再覆盖真实会话（历史、主题、打开的标签）",
        ],
    },
    {
        "version": "1.0.1",
        "date": "2026-11-16",
        "items": [
            "修复：深色切到浅色主题后，JSON 代码区的属性名变成近乎白色、在白底上看不见（切主题时重新着色）",
            "修复：截图脚本会覆盖真实会话数据（改为读写临时状态文件）",
        ],
    },
    {
        "version": "1.0.0",
        "date": "2026-11-16",
        "items": [
            "macOS 原生质感：无边框圆角窗口、交通灯按钮、边缘拖拽缩放、双击标题栏缩放",
            "纯黑极简双主题（深色 / 浅色），反色实心主按钮，全部图标为矢量自绘",
            "动画：窗口与页面淡入、标签滑动指示器、耗时数字滚动、Toast 上滑、侧栏折叠、骨架屏扫光",
            "请求构造：Query 参数 / 请求头（自动补全、批量编辑）/ 请求体（JSON、表单、URL 编码、二进制）/ 认证（Bearer、Basic、API Key）",
            "JSON 实时校验与格式化；{{变量}} 与 {{$timestamp}} 等动态变量",
            "异步发送可取消，超时、跟随重定向、SSL 校验开关，代理（自动 / 系统 / 直连）",
            "响应六视图：美化 / 树形 / 原始 / 响应头 / Cookies / 图片预览，支持查找高亮、复制、另存",
            "集合树（拖拽排序、右键菜单、搜索）、历史记录、多标签与会话恢复、环境变量管理",
            "代码生成 cURL / Python / JavaScript / HTTPie；导入 cURL 与集合导入导出（兼容 Postman v2.1）",
            "命令面板 ⌘K 与全局快捷键，设置、环境变量、更新内容对话框",
        ],
    },
]


def uid() -> str:
    return uuid.uuid4().hex[:10]


def kv(key: str = "", value: str = "", enabled: bool = True) -> Dict[str, Any]:
    return {"key": key, "value": value, "enabled": enabled}


def new_request(name: str = "Untitled Request", method: str = "GET", url: str = "") -> Dict[str, Any]:
    return {
        "id": uid(),
        "type": "request",
        "name": name,
        "method": method,
        "url": url,
        "params": [],
        "headers": [],
        "cookies": [],
        "body": {"mode": "none", "raw": "", "form": [], "file": ""},
        "auth": {"type": "none", "token": "", "username": "", "password": "",
                 "key": "", "value": "", "add_to": "header"},
        "note": "",
    }


def new_folder(name: str = "New Folder") -> Dict[str, Any]:
    return {"id": uid(), "type": "folder", "name": name, "open": True, "children": []}


def _sample_state() -> Dict[str, Any]:
    auth = new_request("Auth · Bearer Token", "GET", "{{base_url}}/bearer")
    auth["name"] = "Auth · Bearer Token"
    auth["headers"] = [kv("Accept", "application/json")]

    post = new_request("Create · JSON Body", "POST", "{{base_url}}/post")
    post["body"] = {
        "mode": "json",
        "raw": json.dumps({"name": "Ocelot", "platform": "macOS", "tags": ["api", "client"]}, indent=2, ensure_ascii=False),
        "form": [], "file": "",
    }
    post["headers"] = [kv("Content-Type", "application/json")]

    params = new_request("Search · Query Params", "GET", "{{base_url}}/get")
    params["params"] = [kv("q", "macos api client"), kv("page", "1"), kv("limit", "20")]

    put = new_request("Update · PUT", "PUT", "{{base_url}}/put")
    put["body"] = {"mode": "json", "raw": '{\n  "status": "active"\n}', "form": [], "file": ""}

    users = new_request("Users · JSONPlaceholder", "GET",
                        "https://jsonplaceholder.typicode.com/users")
    users["params"] = [kv("_limit", "3")]

    folder_demo = new_folder("httpbin.org")
    folder_demo["children"] = [post, params, auth, put]

    folder_demo2 = new_folder("Public APIs")
    folder_demo2["children"] = [users]
    folder_demo2["open"] = False

    return {
        "version": VERSION,
        "collections": [
            {"id": uid(), "type": "folder", "name": "Examples", "open": True,
             "children": [folder_demo, folder_demo2]},
        ],
        "history": [],
        "environments": [
            {"id": "env_local", "name": "Local", "vars": [
                kv("base_url", "http://localhost:8000"),
            ]},
            {"id": "env_demo", "name": "Demo", "vars": [
                kv("base_url", "https://httpbin.org"),
                kv("token", "demo-token-123"),
            ]},
        ],
        "active_env": "env_demo",
        "settings": {
            "timeout": 30,
            "follow_redirects": True,
            "verify_ssl": True,
            "proxy_mode": "auto",
            "theme": "dark",
            "accent": "auto",
            "language": "zh",
            "code_font_size": 11.8,
            "history_limit": 240,
            "auto_name": True,
            "restore_session": True,
            "animations": True,
            "sidebar_width": 268,
            "sidebar_visible": True,
            "split_ratio": 0.46,
            "cloud_enabled": False,
            "cloud_auto": False,
            "turso_url": "",
            "turso_token": "",
        },
        "open_tabs": [],
        "last_request": None,
        "mock": {"port": 8787, "routes": [], "fallback_echo": False, "auto_start": False},
    }


class Store:
    def __init__(self, data: Dict[str, Any], path: Path = STATE_FILE):
        self.data = data
        self.path = Path(path)      # 允许传字符串，否则 save() 里 .parent 会炸
        self._dirty = False

    # ------------------------------------------------------------ 生命周期
    @classmethod
    def load(cls, path: Path = STATE_FILE) -> "Store":
        path = Path(path)
        data: Optional[Dict[str, Any]] = None
        try:
            if path.exists():
                data = json.loads(path.read_text("utf-8"))
        except Exception:
            data = None
        if not isinstance(data, dict):
            data = _sample_state()
        base = _sample_state()
        for k, v in base.items():
            data.setdefault(k, v)
        for k, v in base["settings"].items():
            data["settings"].setdefault(k, v)
        return cls(data, path)

    @staticmethod
    def migrate_legacy() -> bool:
        """旧版本叫 Reqly：首次以 Ocelot 启动时把旧数据搬过来，别让用户丢配置。"""
        legacy = LEGACY_DIR / "state.json"
        if STATE_FILE.exists() or not legacy.exists():
            return False
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy, STATE_FILE)
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[Ocelot] 迁移旧数据失败: {exc}")
            return False

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
            os.replace(tmp, self.path)
            self._dirty = False
        except Exception as exc:  # 持久化失败不应阻断使用
            print(f"[Ocelot] 保存失败: {exc}")

    # ------------------------------------------------------------ 快捷属性
    @property
    def settings(self) -> Dict[str, Any]:
        return self.data["settings"]

    @property
    def collections(self) -> List[Dict[str, Any]]:
        return self.data["collections"]

    @property
    def history(self) -> List[Dict[str, Any]]:
        return self.data["history"]

    @property
    def environments(self) -> List[Dict[str, Any]]:
        return self.data["environments"]

    # ------------------------------------------------------------ 集合树
    def walk(self):
        """深度优先产出 (node, parent_list)。"""
        stack = [(n, self.collections) for n in reversed(self.collections)]
        while stack:
            node, siblings = stack.pop()
            yield node, siblings
            kids = node.get("children") or []
            for child in reversed(kids):
                stack.append((child, kids))

    def find(self, node_id: str) -> Optional[Dict[str, Any]]:
        for node, _ in self.walk():
            if node.get("id") == node_id:
                return node
        return None

    def find_with_parent(self, node_id: str):
        for node, siblings in self.walk():
            if node.get("id") == node_id:
                return node, siblings
        return None, None

    def parent_id(self, node_id: str) -> Optional[str]:
        """返回所在文件夹的 id；节点在顶层或找不到时返回 None。"""
        for node, _siblings in self.walk():
            for child in node.get("children") or []:
                if child.get("id") == node_id:
                    return node.get("id")
        return None

    def find_request(self, node_id: str) -> Optional[Dict[str, Any]]:
        node = self.find(node_id)
        if node and node.get("type") == "request":
            return node
        return None

    def add_node(self, parent_id: Optional[str], node: Dict[str, Any]) -> None:
        if parent_id:
            parent = self.find(parent_id)
            if parent is None:
                self.collections.append(node)
            else:
                if parent.get("type") != "folder":
                    node2, siblings = self.find_with_parent(parent_id)
                    siblings.insert(siblings.index(node2) + 1, node)
                else:
                    parent.setdefault("children", []).append(node)
                    parent["open"] = True
        else:
            self.collections.append(node)

    def remove_node(self, node_id: str) -> None:
        _, siblings = self.find_with_parent(node_id)
        if siblings is None:
            return
        for i, n in enumerate(siblings):
            if n.get("id") == node_id:
                siblings.pop(i)
                return

    def move_node(self, node_id: str, parent_id: Optional[str], index: int) -> None:
        node, siblings = self.find_with_parent(node_id)
        if node is None:
            return
        # 防止把文件夹拖进自己的子孙
        if parent_id:
            parent = self.find(parent_id)
            if parent is None or parent.get("type") != "folder":
                return
            # 不允许把文件夹拖进自己的子孙节点
            if parent_id == node_id or self._is_descendant(parent_id, node_id):
                return
        siblings.remove(node)
        if parent_id:
            self.find(parent_id).setdefault("children", []).insert(index, node)
        else:
            self.collections.insert(index, node)

    def _is_descendant(self, maybe_child: str, ancestor: str) -> bool:
        node = self.find(ancestor)
        if not node:
            return False
        stack = list(node.get("children") or [])
        while stack:
            cur = stack.pop()
            if cur.get("id") == maybe_child:
                return True
            stack.extend(cur.get("children") or [])
        return False

    def duplicate_node(self, node_id: str) -> None:
        node, siblings = self.find_with_parent(node_id)
        if node is None:
            return

        def clone(n):
            c = copy.deepcopy(n)
            c["id"] = uid()
            if c.get("type") == "folder":
                c["children"] = [clone(k) for k in c.get("children", [])]
            else:
                c["name"] = c.get("name", "Request") + " copy"
            return c

        dup = clone(node)
        if node.get("type") == "request":
            dup["name"] = node.get("name", "Request") + " copy"
        siblings.insert(siblings.index(node) + 1, dup)

    # ------------------------------------------------------------ 历史
    def push_history(self, request: Dict[str, Any], status: int, elapsed: int) -> None:
        entry = {
            "id": uid(),
            "ts": time.time(),
            "method": request.get("method", "GET"),
            "name": request.get("name", ""),
            "url": request.get("url", ""),
            "status": status,
            "elapsed": elapsed,
            "request": copy.deepcopy(request),
        }
        self.history.insert(0, entry)
        try:
            limit = int(self.settings.get("history_limit", 240))
        except (TypeError, ValueError):
            limit = 240
        del self.history[max(20, limit):]

    def clear_history(self) -> None:
        self.history.clear()

    # ------------------------------------------------------------ 环境变量
    def active_environment(self) -> Optional[Dict[str, Any]]:
        eid = self.data.get("active_env")
        for env in self.environments:
            if env["id"] == eid:
                return env
        return None

    def env_vars(self) -> Dict[str, str]:
        env = self.active_environment()
        out: Dict[str, str] = {}
        if env:
            for row in env.get("vars", []):
                if row.get("enabled", True) and row.get("key"):
                    out[row["key"]] = row.get("value", "")
        return out

    def set_active_env(self, env_id: Optional[str]) -> None:
        self.data["active_env"] = env_id


# ---------------------------------------------------------------- 变量替换

def resolve_vars(text: str, variables: Dict[str, str]) -> str:
    """替换 {{var}} 与内置动态变量。未知变量保持原样，便于排查。"""
    if not text or "{{" not in text:
        return text
    import re

    def repl(m):
        name = m.group(1).strip()
        if name == "$timestamp":
            return str(int(time.time()))
        if name == "$timestampMs":
            return str(int(time.time() * 1000))
        if name in ("$uuid", "$guid"):
            return str(uuid.uuid4())
        if name == "$randomInt":
            return str(random.randint(1, 1000))
        if name.startswith("$isoTimestamp"):
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if name in variables:
            return str(variables[name])
        return m.group(0)

    return re.sub(r"\{\{([^{}]+)\}\}", repl, text)


def detect_vars(text: str) -> List[str]:
    import re
    return re.findall(r"\{\{([^{}]+)\}\}", text or "")
