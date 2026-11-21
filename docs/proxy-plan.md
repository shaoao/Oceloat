# 抓包代理 · 设计方案（未实现，供下一版排期）

目标：零依赖、几十 KB 代码，在 Ocelot 里抓本机 / 手机流量，抓到的请求一键存进集合或变成 Mock。

## 1. 架构（只用标准库 + 已有 QtNetwork）
- `app/proxy.py`：`ThreadingHTTPServer` 起在 127.0.0.1:9090（与 Mock 同一套线程模型）。
  - HTTP：解析绝对 URI，转发，回写响应，记录一条 Flow。
  - HTTPS：处理 `CONNECT`。默认**隧道透传**（只记录域名 / 字节数 / 耗时，不解密）；
    对用户勾选的域名才做 MITM。
- MITM 证书：首次启用时用 `openssl`（macOS 自带 LibreSSL）生成本地根 CA，存在
  `~/Library/Application Support/Ocelot/proxy-ca/`；按域名动态签发叶子证书并缓存。
  不引 `cryptography`，安装包体积 +0。
- 系统代理：`networksetup -setwebproxy / -setsecurewebproxy` 一键开关，退出时必定还原
  （atexit + 崩溃日志钩子都还原一次，防止断网）。
- 手机：复用 Mock 的「局域网 + 二维码」，二维码里放代理地址和 CA 下载页。

## 2. 数据
- Flow = {id, ts, method, url, status, req_headers, req_body, resp_headers, resp_body, timing, size}
- 内存环形缓冲：默认 2000 条 / 64 MB，超出丢最旧；body 超 2 MB 只留前 256 KB。
- 不落盘；用户点「保存」才写成 HAR（已有 HAR 导出）。

## 3. 界面（与 Mock 中心同款独立窗口）
- 顶部一行：开关 · 端口 · 系统代理开关 · 过滤（域名 / 方法 / 状态 / 内容类型）· 暂停 · 清空
- 左：流量列表（方法色 + 状态 + 路径 + 耗时 + 体积，等宽对齐）
- 右：复用 ResponsePanel 的 8 种视图；请求侧复用只读 RequestEditor
- 右键：存进集合 / 生成 Mock 路由 / 复制 cURL / 重放 / 编辑后重放

## 4. 差异化
- **录制 → 回放 → Mock 闭环**：选中一组流量 →「生成 Mock 实例」，前端直接切到本地 Mock。
- **断点**：按规则（域名 + 路径通配）拦截请求或响应，就地改了再放行。
- **Map Local / Map Remote**：命中规则时返回本地文件或改写到另一个地址（测灰度很有用）。
- **AI 诊断**：对一组失败流量做批量分析（复用现有 ai.py 的分析模板）。
- **契约漂移**：同一接口多次抓到的响应自动跑现有 contract 对比，结构变化标红。

## 5. 排期建议
1) HTTP 代理 + 列表 + 存进集合（1 周）；2) CONNECT 隧道 + 系统代理开关（3 天）；
3) MITM + CA 安装引导（1 周）；4) 断点 / Map Local（1 周）；5) 录制转 Mock（3 天）。
