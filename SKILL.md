---
name: scidown-paper-downloader
description: 通过 open-access.shop / Scidown 生态按 DOI 下载学术文献 PDF 的完整工具箱。当用户要求"下载文献/paper/论文 PDF"、"补下文献"、"批量下载 DOI 清单"、或提到 open-access.shop / scidown / sci-hub / unpaywall / wayback 下载文献时使用。包含从路由决策、免验证解析、离线源降级、风控纪律到题名核对入库的完整方法论。
---

# Scidown 文献下载技能(2026-08-30 v2)

按 DOI 下载学术文献 PDF 的完整实战方案。**优先用 MCP 工具**(`mcp-server/`,无 SDK 纯 stdio);
没有 MCP 时用 `scripts/` CLI。深度细节见 `docs/01-机制分析.md`(协议级逆向)、
`docs/02-风控手册.md`(封号风险)、`docs/04-实战复盘.md`(失败路径)、`docs/05-离线源索引.md`(scidown 之外的所有路线)。

## ⚠️ 使用边界

- 仅供个人学习科研。不要批量再分发;遵守目标网站服务条款与版权法规。
- **绝不自动提交站方"文献求助"表单**(helpadd/helpsubmit)——站方明令禁止批量求助,5篇/天,会把账号送走。
- 该体系有主动风控(顶象滑块、IP 降级、Cloudflare)。**慢就是快**:宁可有礼貌地失败,不要 hammer。

## 决策树(核,顺序=成本从低到高)

```
输入: DOI(或标题) + 期望题名
│
├─ 0. 元数据前置(永远先做,判断 OA 状态)
│     OpenAlex:  api.openalex.org/works/doi:<DOI>  → open_access.oa_status / oa_url
│     bronze/gold OA + 官网 pdfdirect → 试试官网(见 docs/05 §9)
│
├─ 1. 缓存直链(无登录无验证,固定模式)
│     https://sci.bban.top/pdf/<DOI>.pdf?download=true   ★ 脚本首选
│     https://pdf.bban.top/<DOI>.pdf                      (另一个前缀,也要试)
│     http://zy9.xeak.top/pdf/<DOI>.pdf                   (CF 盾: curl 引擎试一次 → 真浏览器)
│     命中标准: %PDF 魔数 + >10KB;404/429/403 都按无货处理
│
├─ 2. scidown 解析链(未缓存文献,需登录态;完整细节见 docs/01 §2.4)
│     a. 免验证: GET lxapp.php?lx=<urlencode(http://92.223.124.29/<DOI>.opjc)> → 收 yz cookie 三件套
│     b. scixue.php?doi=<DOI> (登录 cookie 全带, 尤其 dlzt; Referer 带上)
│     c. 读 <input id="uname" name="a" value="...">:
│          zy9/bban → 按步骤1下载
│          zdwe.sciokk.cn?auth_key= → curl 直下(~1h 签名, 每次重新解析)
│          share.scifree.shop/zxwileyq.php → Wiley 走步骤 3
│          gosci.lanzouq.com → 交人工浏览器
│          https://doi.org/<DOI> → 主站无缓存(Elsevier 系), 跳到步骤 4+
│          ""(空) → 分类!见风控手册 §4(降级 vs 未收录)
│
├─ 3. Wiley 未缓存(唯一正路 = 机构共享链)
│     a. 浏览器走完 取回本地(POST down.sciokk.cn/sci/down1.php?<8hex>, 字段 a=<uname URL>,
│        UA 必须带 " QIHU 360SE" 后缀) → 等待页 JS 跳 zxwileyq 演示页
│     b. 提交 form#asder → onlinelibrary.wiley.com/action/authenticateSharedSP(免账号)
│     c. 认证成功后同源: fetch('/doi/pdfdirect/<DOI>', {credentials:'include'}) → %PDF 字节
│     d. IAB/Electron 下载事件会被 Playwright 拦截取消 → 用页面内 fetch + base64 分片搬出
│
├─ 4. 离线源(按 docs/05 顺序)
│     出版社区域被墙 → Wayback CDX (web.archive.org/cdx?url=<host>/<file*>; /web/<ts>id_/<url>)
│     印度 NOPR      → nopr.niscpr.res.in/bitstream/123456789/<id>/1/<文件名>.pdf (注意新域名 niscpr!)
│     sci-hub 镜像簇 → jp/red/ee/ren;点掉验证后抓存储直链 curl 下 (矩阵见 docs/05 §5)
│     都没 → 按 docs/05 §7 判定是否为 Sci-Hub 坏条目死局
│
└─ 5. 死局输出: 如实报告 + 提供一键人工链接(不编造成功)
```

## 关键事实(背下来,省 90% 力气)

1. `scixue.php` **纯服务端渲染**,全站没有"提交抓取→轮询"接口(所有疑似端点实测 404)。
2. 顶象滑块可以**公式绕过**:`yztoken = md5("1sciq" + 十位时间戳 + "1")`,cookie `yztime/yzcount=1/yztoken`,600s;
   等价捷径 `GET /lxapp.php?lx=<任意>` 白拿 Set-Cookie。**永远不再需要人工验证码。**
3. scixue 空结果的三种原因必须区分:缺 `dlzt`(页面有 PHP Notice)、IP 降级(换有缓存 DOI 复测也空)、真未收录(仅此 DOI 空)。
4. Cloudflare 只按 TLS/行为指纹拦脚本,不拦真浏览器;Turnstile 复选框真浏览器点一下即过(1280x720 坐标约 510,256)。
5. **HTTP 200 ≠ 成功**:错误页/挑战页/坏条目全是 200。唯一标准 = %PDF 魔数 + >10KB + pdftotext 题名词命中(前8个≥3字母词转小写,≥60%)。
6. 文件名不可信(21935.pdf 之类),只认题名核对;重复文件 SHA-256 去重。

## 风控纪律(违反会全军覆没)

| 规则 | 数值 |
|---|---|
| scidown 解析请求间隔 | ≥ 8-10s |
| bban/zy9 下载间隔 | ≥ 3s |
| sci-hub 镜像访问间隔 | ≥ 5s |
| 单次批量 | ≤ 10 篇/调用,批间隔 ≥ 1min |
| 触发 verify.php / 收到空解析 | 立即停脚本,人工稀释标记,冷却几十分钟~数小时 |
| 求助表单 | **永不自动提交** |

## 人机协作(被全面风控 / 遇到真浏览器才放行的链路时)

1. `make_workbench(dois)` 生成 HTML 表格(编号/标题/DOI/①bban ②zy9 ③出版社按钮),用用户默认浏览器打开;
2. 人逐篇点击,CF 盾自动过,PDF 落 ~/Downloads;
3. `harvest_daemon.py <分钟数>` 监控 ~/Downloads:pdftotext 题名核对 + SHA-256 去重 → 按
   `编号_作者_年份_标题.pdf` 改名入库;日志写收割日志.txt。
4. 任何"人点一下就能下"(比如证书坏死站点的"高级→继续前往")→ 工作台给该链接+操作说明。

## MCP 工具映射

`download_paper` / `batch_download` / `probe_patterns` / `scidown_captcha`+`scidown_login` /
`harvest_downloads` / `make_workbench` / `library_status` / `register_tasks`(配置见 docs/03)。

## CLI 速查

```bash
python3 scripts/paper_dl.py 10.1007/s11033-018-4323-4            # 单篇(自动 缓存→解析, 含校验)
python3 scripts/paper_dl.py -f dois.txt -o ~/papers --delay 5    # 批量
python3 scripts/harvest_daemon.py 180                            # 监控 ~/Downloads 180 分钟
```

## 故障速查表

| 症状 | 诊断 | 处置 |
|---|---|---|
| bban 404 / 429("error") | 未收录或限速 | 试 pdf.bban.top 前缀;再走解析链 |
| zy9 403 挑战页 | CF 拦脚本 | curl 引擎;不行交人工浏览器 |
| scixue"请求信息有误" | 无 Referer/会话未建立 | GET lx.php 建链后带 Referer 重试 |
| scixue 302 verify.php | 缺 yz cookie | 公式自算或 lxapp 白拿 |
| scixue Notice dlzt + uname 空 | 登录 cookie 不全 | 补 dlzt/dltoken 全套 |
| scixue uname 空(无 Notice) | 降级 或 真无货 | 换有缓存 DOI 复测区分;降级则停 |
| uname=doi.org | Elsevier 系无缓存,主站放弃 | 转 docs/05 离线源 |
| IAB 点击下载无文件 | Playwright 拦截了 download 事件 | 用页面内 fetch 搬字节 |
| PDF 题名核对失败 | 坏条目 / 错配 | 丢弃!按 §坏条目判定转路 |
| 下载到的是 HTML | 那是错误页 | 别入库 |

## 进阶阅读

- docs/01 机制分析(协议级:每个端点/响应/cookie/JS 逻辑)
- docs/02 风控手册(风险层、红线、降级分类、自救)
- docs/04 实战复盘(5 篇硬骨头的真实路径 + 失败档案)
- docs/05 离线源索引(Wayback/NOPR/sci-hub 镜像矩阵/OpenAlex 的一行命令)
