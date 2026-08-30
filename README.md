# Scidown Paper Downloader 🔬

**English** | [中文说明见下方](#中文说明)

Download academic papers by DOI through the open-access.shop / Scidown ecosystem —
with route fallback, anti-rate-limit discipline, PDF title verification, and a
human-in-the-loop fallback for Cloudflare-hostile environments.

Ships as **both** an [MCP server](mcp-server/) (10 tools, pure Python, no SDK needed)
and an [AI agent Skill](SKILL.md).

> ⚠️ **Disclaimer**: For personal scholarly use only. This tool automates the public
> user flow of a public website; it does not crack DRM or bypass logins. You are
> responsible for complying with the site's terms of service and copyright law in
> your jurisdiction. Do not use for bulk redistribution.

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

## The three routes (why this works)

| # | Route | Needs login? | Script-friendly? | Covers |
|---|---|---|---|---|
| 1 | `sci.bban.top/pdf/{DOI}.pdf` (public CDN) | ❌ | ✅ requests/curl | most cached papers |
| 2 | `zy9.xeak.top/pdf/{DOI}.pdf` | ❌ | ⚠️ curl only, CF-permissive | some cached papers |
| 3 | Scidown login → `zdwe.sciokk.cn` WebVPN gateway (signed URL) | ✅ | ✅ curl | uncached papers |

Full reverse-engineered flow, risk-control playbook and troubleshooting:
[docs/01-机制分析.md](docs/01-机制分析.md) · [docs/02-风控手册.md](docs/02-风控手册.md)

## When everything is blocked: workbench + harvest (human-in-the-loop)

```bash
python3 -c "..." # or MCP make_workbench(dois=[...])
python3 scripts/harvest_daemon.py 180   # watch ~/Downloads, verify & file PDFs
```

The site rate-limits aggressive clients with a slider CAPTCHA and silently
degrades resolutions. The workbench pattern (generate candidate links → human
clicks in a real browser → daemon harvests ~/Downloads and verifies titles)
survives total blocking and is the recommended mode for large batches.

---

## 中文说明

按 DOI 下载学术文献 PDF 的完整工具箱(open-access.shop / Scidown 生态)。

- **SKILL.md** — AI 技能手册(路线决策树/风控纪律/故障速查),可直接放进 skills 目录
- **scripts/** — CLI:`paper_dl.py`(下载)、`harvest_daemon.py`(下载文件夹收割守护)
- **mcp-server/server.py** — 零依赖 MCP 服务器(纯 Python 标准库 + requests),10 个工具
- **docs/** — 逆向机制分析、风控手册、MCP 接入配置

核心发现(省 90% 力气):
1. `sci.bban.top/pdf/{DOI}.pdf?download=true` 是公开 CDN,**无需登录无验证码**,热门文献直接命中;
2. `zy9.xeak.top/pdf/{DOI}.pdf` 是主线路固定模式,被 Cloudflare 保护,真浏览器可过;
3. 未收录文献需登录后解析,得到 `zdwe.sciokk.cn` WebVPN 网关签名直链(无 CF,curl 可下);
4. 全被风控时用「工作台 + 收割」人机协作:人点链接过盾,脚本监控下载文件夹并按题名核对入库。

仅供个人学习科研使用;请遵守网站服务条款与版权法规,勿用于批量再分发。

## License

MIT

## Install as an agent Skill

Copy `SKILL.md` (+ `scripts/`) into your client's skills directory, e.g.:

```bash
git clone https://github.com/TryLoveMe/scidown-paper-downloader.git
mkdir -p ~/.claude/skills
cp -r scidown-paper-downloader ~/.claude/skills/scidown-paper-downloader
```

The SKILL.md frontmatter (`name`, `description`) lets skill-aware agents auto-trigger
on "下载文献 / download paper by DOI" style requests.
