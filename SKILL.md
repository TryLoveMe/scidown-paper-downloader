---
name: scidown-paper-downloader
description: 通过 open-access.shop / Scidown 生态按 DOI 下载学术文献 PDF。当用户要求"下载文献/paper/论文 PDF"、"补下文献"、"批量下载 DOI 清单"、或提到 open-access.shop / scidown / sci-hub 替代站时使用。包含路线决策、风控规避、人机协作下载、题名核对入库的完整方法论与可直接调用的脚本/MCP 工具。
---

# Scidown 文献下载技能

按 DOI 下载学术文献 PDF 的完整实战方案。适用于 open-access.shop 及其背后的
Scidown 解析体系。**优先用 MCP 工具**(见 `mcp-server/`),没有 MCP 时用 `scripts/` 里的 CLI。

## ⚠️ 使用边界

- 仅供个人学习科研。不要用于批量再分发;遵守目标网站服务条款与版权法规。
- 该体系有主动风控(顶象滑块验证码、IP 降级、Cloudflare)。**慢就是快**:宁可有礼貌地失败,不要 hammer。

## 核心知识:这个生态怎么运作(逆向还原,2026-08 实测)

```
open-access.shop 搜索(DOI/标题/作者均可)
  └─ Download 弹窗 → 选 "Scidown cloud drive"
       → scidown.cn/lx.php?lx=http://92.223.124.29/<关键词>.opjc   ← .opjc 是"提货凭证"(空文件)
         → 确认页(勾协议,写 download_agreed cookie) → lxapp.php → scixue.php?doi=<DOI>
              ├─ 未登录:「取回本地」表单 action=login.php、隐藏字段 a=""  → 死路,别猜
              └─ 已登录:服务器按文献挑选存储后端,a=<最终直链>:
                   ├─ zy9   http://zy9.xeak.top/pdf/<DOI>.pdf          ← CF 挡脚本,真浏览器可过
                   ├─ bban  https://sci.bban.top/pdf/<DOI>.pdf?download=true ← 公开 CDN,脚本可下 ★
                   ├─ zdwe  http://zdwe.sciokk.cn/https/<webvpn-hex>/content/pdf/<DOI>.pdf?auth_key=<签名>
                   │        ← 无 CF,curl 可直下 ★;auth_key 约1小时有效,解析一次一个
                   └─ 蓝奏云 https://gosci.lanzouq.com/<id>            ← 需浏览器二次点击「普通下载」
```

**两个关键规律(省 90% 力气):**
1. `bban` 和 `zy9` 的地址是**固定模式**:`https://sci.bban.top/pdf/{DOI}.pdf?download=true` 和
   `http://zy9.xeak.top/pdf/{DOI}.pdf`。缓存命中时不需登录、不需解析、无验证码,直接下。
2. Cloudflare 只按 TLS/行为指纹拦脚本,**不拦真浏览器**。脚本被 403 时换 curl 引擎再试一次;
   还不行就把直链交给人点(工作台模式),文件落 ~/Downloads 后脚本收割。

## 路线决策树

```
拿到 DOI
├─ 1. 试缓存直链 https://sci.bban.top/pdf/{DOI}.pdf?download=true
│     校验响应以 %PDF 开头且 >10KB → 命中即完成(大多数热门文献走这里)
├─ 2. 404/403 → 试 http://zy9.xeak.top/pdf/{DOI}.pdf(curl 引擎,偶尔能过;python-requests 基本被 CF 拒)
├─ 3. 仍失败 → 需要登录态解析(未收录文献只有这条路):
│     a. 登录 scidown(账号+图形验证码;有视觉能力可自动识读,见下方"登录"节)
│     b. GET lx.php?lx=<urlencode(http://92.223.124.29/<DOI>.opjc)>
│     c. GET scixue.php?doi=<DOI>(带 Referer lx.php)
│     d. 正则抓 name="a" 的 value → 得到 zdwe 签名直链 / 蓝奏云链接
│     e. zdwe → curl 直下;蓝奏云 → 人工浏览器二次点击
├─ 4. scidown 触发风控(verify.php / btn-popup / 空解析)→ 立刻停止请求!
│     切换"工作台+收割"人机协作模式(见下)
└─ 5. 全部失败 → 如实告知用户,附上人工处理链接,不要编造成功
```

## 风控纪律(违反会全军覆没)

| 规则 | 数值 | 原因 |
|---|---|---|
| scidown 请求间隔 | ≥ 8-10s | 顶象防护按频率触发 |
| bban/zy9 下载间隔 | ≥ 3s | CDN 也会限速 |
| 触发 verify.php 后 | 停止脚本请求 | 越试标记越重,冷却期未知 |
| 解析返回空 `a` | 视为 IP 被降级 | 服务器静默降级,重试无意义 |
| 单次批量 | ≤ 10 篇/调用 | 分批跑,别一口气 50 篇 |
| 登录会话 | 约 30 分钟过期 | 失效重登;cookie 里有明文账号(记住密码功能) |

## 登录(需要网关路线时)

1. `GET https://www.scidown.cn/wangpan/999.jpg` → 4 位图形验证码(数字+字母,彩色扭曲)。
2. 有视觉能力的 AI:把图片转 base64 自己看;没视觉:交给用户。
3. POST login(username, pwd, vercode) → 会话 cookie 存文件。
4. 网页里的滑块验证(顶象)脚本过不了,由用户在浏览器拖一次;通过后 yz 系列 cookie 会刷新信任。

## 人机协作"工作台+收割"模式(被全面风控时的兜底,实战验证有效)

1. 为每篇待下文献生成两个候选直链(bban 模式 + zy9 模式),写成一个 HTML 表格(编号/标题/DOI/按钮)。
2. 用用户默认浏览器打开,人逐篇点击;CF 盾自动过;PDF 落到 ~/Downloads。
3. 脚本监控 ~/Downloads:对每个新 PDF 用 pdftotext 提前两页文本,与任务标题做
   词命中匹配(前8个≥3字母词命中≥60%)→ 通过则按 `编号_作者_年份_标题.pdf` 改名入库。
4. 实测要点:文件名不可信(可能是 21935.pdf 这种),**只认题名核对**;等待文件写完(>10KB 且 2s 内大小稳定)。

## 题名核对纪律

**永远不要因为 HTTP 200 就当下载成功。**必须:① `%PDF` 魔数;② 大小 >10KB;③ pdftotext
前两页与标题词命中 ≥60%。核对不过→丢弃并报告,宁缺毋滥。

## MCP 工具映射

有 MCP 客户端时直接用(配置见 `docs/03-mcp配置.md`):
`download_paper` / `batch_download` / `probe_patterns` / `scidown_captcha`+`scidown_login` /
`harvest_downloads` / `make_workbench` / `library_status` / `register_tasks`

## 无 MCP 时用 CLI

```bash
python3 scripts/paper_dl.py 10.1007/s11033-018-4323-4            # 单篇
python3 scripts/paper_dl.py -f dois.txt -o ~/papers --delay 5    # 批量
python3 scripts/harvest_daemon.py 180                            # 监控 ~/Downloads 180分钟
open 下载工作台.html                                             # 人工点击页
```

## 故障速查

| 症状 | 诊断 | 处置 |
|---|---|---|
| bban 404 | 未收录或缓存未生成 | 走路线3或稍后重试(服务器端抓取有延迟) |
| zy9 403 (5981-6104B) | Cloudflare 拦脚本 | 换 curl 引擎;不行交人工浏览器 |
| scixue 显示"请求信息有误" | 会话未建立/IP 降级 | 先 GET lx.php;或冷却后再试 |
| scixue `a=""` 且 action=login.php | 未登录 | 登录后再解析 |
| verify.php 反复出现 | IP 被标记 | 停脚本,人工浏览器操作,数小时后再试 |
| 网盘里"离线文件"条目点下载提示过期 | 正常,那是临时缓存 | 不以此为准,以直链为准 |
| PDF 打开是 5KB HTML | 那是错误页 | 别入库!题名核对会拦住它 |

## 进阶路线(2026-08-30 实测,详见 `docs/04-实战复盘-20260830.md`)

| 场景 | 打法 |
|---|---|
| scidown 验证码 | 免验证:`GET /lxapp.php?lx=<任意值>` 收 yz cookie 三件套(600s);或自算 `yztoken=md5("1sciq"+ztime+"1")` |
| scixue 空结果 | 必须同时带登录 cookie(`dlzt` 不能少)+ yz 三件套 + Referer;结果在 `input#uname` |
| Wiley 无缓存 | scixue 会给 `share.scifree.shop/zxwileyq.php?...auth_key(5min)` → POST `onlinelibrary.wiley.com/action/authenticateSharedSP`(免账号)→ 同源 fetch `doi/pdfdirect/{DOI}` 拿字节 |
| 出版社区域被墙(EKB 等) | 查 `web.archive.org/cdx` 存档,`/web/<ts>id_/<url>` 取原始字节 |
| 印度 NOPR 文献 | 仓库已改名 `nopr.niscpr.res.in`,bitstream 直链可 curl |
| sci-hub 镜像簇 | .jp(点"No")、.ee/.ren(点 Turnstile 复选框)、存储直链 curl 可下;`pdf.bban.top/<DOI>.pdf` 与 `sci.bban.top/pdf/` 是两个不同前缀都要试 |
| 坏条目识别 | 同一 DOI 各镜像返回字节级相同的无关 PDF = Sci-Hub 共享库坏条目,全网无解,只能找站外拷贝(如 `/uptodate/<PII>.pdf`) |
