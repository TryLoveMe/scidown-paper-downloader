# Scidown Paper Downloader 🔬

**English** | [中文说明见下方](#中文说明)

Download academic papers by DOI with a **multi-route fallback engine**:
cached-CDN direct links → logged-in scidown resolution → Wiley shared-access chain →
Wayback/NOPR/sci-hub mirror offline sources → human-in-the-loop workbench.
Every downloaded PDF is verified (magic bytes + title word-match + DOI check) before filing.

Ships as **both** an [MCP server](mcp-server/) (pure Python, stdio, no SDK needed)
and an [AI agent Skill](SKILL.md).

> ⚠️ **Disclaimer**: For personal scholarly use only. It automates the public user flow
> of a public website; it does not crack DRM or bypass logins. Respect the sites' terms
> of service and copyright law. Never use for bulk redistribution.

---

## Quick start (MCP)

```jsonc
// claude_desktop_config.json / zcode config / cursor mcp.json
{
  "mcpServers": {
    "scidown-paper": {
      "command": "python3",
      "args": ["/path/to/scidown-paper-downloader/mcp-server/server.py"]
    }
  }
}
```

Requires: `python3` with `requests` (`pip3 install requests`), and poppler's
`pdftotext` (`brew install poppler`) for title verification.

Tools: `download_paper` · `batch_download` · `probe_patterns` · `scidown_captcha` /
`scidown_login` / `harvest_downloads` / `make_workbench` / `library_status` /
`register_tasks`

## Quick start (CLI)

```bash
pip3 install requests && brew install poppler   # once
python3 scripts/paper_dl.py 10.1007/s11033-018-4323-4
python3 scripts/paper_dl.py -f examples/dois.txt -o ~/papers --delay 5
```

## The route ladder (2026-08-30)

| # | Route | Login? | Script-friendly? | Covers |
|---|---|---|---|---|
| 0 | OpenAlex/Crossref metadata (OA detection) | ❌ | ✅ API | decide next step |
| 1 | `sci.bban.top/pdf/{DOI}.pdf?download=true` + `pdf.bban.top/{DOI}.pdf` | ❌ | ✅ requests/curl | most cached papers |
| 2 | `zy9.xeak.top/pdf/{DOI}.pdf` | ❌ | ⚠️ curl only | some cached papers |
| 3 | scidown logged-in `scixue.php` resolution (yz-cookie bypass!) | ✅ | ✅ | uncached papers |
| 4 | Wiley: `zxwileyq` → `authenticateSharedSP` → `fetch /doi/pdfdirect` | ✅ (scidown) | ✅ browser/JS | all uncached Wiley |
| 5 | Wayback CDX / NOPR niscpr / sci-hub mirrors (.jp/.red/.ee/.ren) | ❌ | ✅ curl | region-blocked publishers, old papers |
| 6 | Workbench + harvest daemon (human clicks, script files) | ❌ | ✅ | total blocking / hostile cert sites |

## Key reverse-engineered facts (verified, 2026-08-30)

- **Captcha is solvable by formula**: `yztoken = md5("1sciq" + unix_ts + "1")` — no more sliders.
- `scixue.php` renders **synchronously**; there is no task/poll API anywhere on the site.
- An empty `<input id="uname">` has 3 different causes (missing `dlzt` cookie / IP degraded /
  truly uncached) — classify before retrying.
- Wiley uncached papers resolve through `share.scifree.shop/zxwileyq.php` (5-min signature)
  → institution SharedSP auth (no account) → official publisher PDF.
- **HTTP 200 ≠ success**. Every file must pass: `%PDF` magic + >10KB + title word-match (≥60% of first 8 significant words, lowercased) + DOI cross-check.
- Sci-Hub shared DB can contain **poisoned entries** (same unrelated PDF returned byte-identically
  across mirrors) — detect and stop; find the real copy at `/uptodate/<PII>.pdf` style locations.

---

## 中文说明

按 DOI 下载学术文献 PDF 的完整工具箱(open-access.shop / Scidown 生态 + 离线源降级)。

- **SKILL.md** — AI 技能手册(决策树/关键事实/风控纪律/故障速查),可直接放进 skills 目录
- **scripts/** — CLI:`paper_dl.py`(下载, 带校验)、`harvest_daemon.py`(下载文件夹收割守护)
- **mcp-server/server.py** — 零依赖 MCP 服务器(纯 Python 标准库 + requests),10 个工具
- **docs/**
  - `01-机制分析.md` — 协议级逆向:每个端点/响应/cookie/JS 逻辑(含 yz 公式、Wiley 共享链、网盘真相)
  - `02-风控手册.md` — 风险层、频率红线、降级分类、免验证通道、人机分工
  - `03-mcp配置.md` — MCP 接入配置
  - `04-实战复盘-20260830.md` — 5 篇硬骨头的真实路径 + 全部失败档案(负知识)
  - `05-离线源索引.md` — scidown 之外的路线:Wayback/NOPR/sci-hub 镜像矩阵/OpenAlex 一行命令

**给 AI 用的建议阅读顺序**:SKILL.md(执行)→ docs/01 + 05(实现)→ docs/02(别被封)→ docs/04(避坑)。

核心发现:bban 双前缀固定模式免登录;顶象滑块可公式绕过;空结果要先分类;Wiley 走机构共享链;
区域被墙找 Wayback;印度 NOPR 改名 niscpr;Sci-Hub 有坏条目死局(域名+判定法记录在案)。

**仅供个人学习科研使用**;请遵守网站服务条款与版权法规,勿用于批量再分发。
**注意**:站方"文献求助"表单(5篇/天,禁批量)已被明确列入"绝不自动提交"。

## License

MIT

## Install as an agent Skill

```bash
git clone https://github.com/TryLoveMe/scidown-paper-downloader.git
mkdir -p ~/.claude/skills
cp -r scidown-paper-downloader ~/.claude/skills/scidown-paper-downloader
```

The SKILL.md frontmatter (`name`, `description`) lets skill-aware agents auto-trigger
on "下载文献 / download paper by DOI" style requests.
