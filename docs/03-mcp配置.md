# MCP 服务器接入配置

## 服务器信息

- 文件:`mcp-server/server.py`
- 传输:stdio(JSON-RPC 2.0, 换行分隔帧)
- 协议版本:2024-11-05(兼容更高)
- 依赖:`python3` + `requests`;可选 `poppler/pdftotext`(题名核对用)

## 通用配置模板

```json
{
  "mcpServers": {
    "scidown-paper": {
      "command": "python3",
      "args": ["/绝对路径/scidown-paper-downloader/mcp-server/server.py"],
      "env": {
        "SCIDOWN_DL_HOME": "~/.scidown-mcp"
      }
    }
  }
}
```

### 各客户端位置参考

| 客户端 | 配置文件 |
|---|---|
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| ZCode | `~/.zcode/settings.json` 或项目 `.mcp.json` |
| Cursor | `~/.cursor/mcp.json` |
| Cline/Roo | 各自 settings 的 mcpServers 节 |

> server.py 会自动把 `../scripts` 加入 sys.path 寻找 `scidown_lib.py`;
> 若单独拷贝 server.py 使用,请把 `scidown_lib.py` 放同目录。

## 典型会话流(给 AI agent 的操作脚本)

### 场景 A:下载一批 DOI(绝大多数情况)

```
1. register_tasks(tasks=[{no,title,doi},...])        # 可选, 注册编号清单
2. batch_download(dois=[...], titles={doi:title}, max=10)
3. 对返回里 ok=false 的条目看 reason:
   - "缓存与zy9均未命中; 网关路线需要登录" → 场景 B
   - "触发顶象防护" → 停手等待, 或场景 C
```

### 场景 B:未收录文献(需登录)

```
1. scidown_captcha()            → 返回 base64 PNG
2. 用你的视觉能力读出 4 位验证码
3. scidown_login(username, password, code)
4. 重试 download_paper(...)     → 自动走 zdwe 网关路线
```

### 场景 C:被全面风控(人机协作)

```
1. make_workbench(dois=[...])   → 生成并打开 HTML 工作台
2. 请用户逐篇点击(CF 盾自动过), PDF 落到 ~/Downloads
3. harvest_downloads()          → 题名核对、改名、入库
4. library_status()             → 汇报剩余
```

## 工具清单

| 工具 | 登录 | 说明 |
|---|---|---|
| `download_paper(doi, title?, out_dir?, skip_verify?)` | 自动 | 三级路线单篇下载 |
| `batch_download(dois, titles?, max?, delay?)` | 自动 | 批量限速下载(单次≤max) |
| `probe_patterns(doi)` | ❌ | 探测 bban/zy9 模式直链可用性 |
| `scidown_status()` | - | 登录态检查 |
| `scidown_captcha()` | - | 取登录验证码(base64 PNG) |
| `scidown_login(username, password, code)` | - | 登录并持久化会话 |
| `library_status()` | - | 库存 + 任务缺失清单 |
| `harvest_downloads(source_dir?, tasks?)` | - | 从下载文件夹题名匹配收割 |
| `make_workbench(dois)` | - | 生成人工点击工作台 HTML |
| `register_tasks(tasks)` | - | 注册 [{no,title,doi}] 清单 |

## 数据位置

```
~/.scidown-mcp/
├── scidown_cookies.txt   # 登录会话(含明文账号, 勿外传!)
├── tasks.json            # 已注册任务清单
├── library/              # 默认文献库
└── workbench.html        # 最近生成的工作台
```
