# UAMS —— 统一 AI 记忆系统（Universal AI Memory System）

> 一份工具包，教你怎么把"记忆"从「每个 AI 各写各的私有笔记」升级成「所有 AI 共享、可治理、可移植的公地」。
> 开箱即用：`init_uams.py` 一键初始化，`uams/` 是纯标准库引擎，各 AI 接入片段直接复制即用，也可用 MCP 一键接入主流 AI 客户端。

---

## 0. 这东西解决什么痛点

你频繁在多个 AI 之间切着干活（WorkBuddy / Claude / Codex / Trae / Kiro / DSH …）。原生记忆的坑：

| 痛点 | 原生记忆 | UAMS |
|---|---|---|
| 切到另一个 AI，要重喂背景和进度 | 必重喂 | 共享公地，开局一查就有 |
| 切完"习惯/规矩"变了 | 各 AI 各记各的 | 全局偏好写进 UAMS，谁都读得到 |
| 记忆越写越脏、互相矛盾 | 无治理 | `supersedes` 替代、`source` 必填、审计日志 |
| 换机器/换人没法带走 | 绑死在某 AI 账号 | 本地文件 + 零依赖，clone 即跑 |

**一句话**：UAMS 把记忆从"某 AI 的私产"变成"所有 AI 共享的公地"，且自带治理，不会半年成一锅粥。

---

## 1. 核心概念（30 秒看懂）

- **工具无关**：靠 `--ai-identity` 路由。workbuddy 写的内容，换 claude 身份 `search` 照样读回。
- **三层记忆**：`global`（跨项目通用）/ `project-active`（当前项目）/ `project-archive`（归档，默认不检索）。
- **零依赖可移植**：引擎是纯 Python 标准库，无第三方包；记忆是本地 Markdown/JSON 文件。
- **人机双入口**：`UAMS_ENTRY.json`（机器读）+ `UAMS_ENTRY.md`（人/AI 读）定位根。
- **治理不腐化**：写入有硬校验 + `audit/` 日志（迁移/拒绝/策略决策）。

目录结构（初始化后）：入口文件 `UAMS_ENTRY.*` 放在 uams-root 的**上一级**（与引擎 `discover` 报告的位置一致），其余都在 uams-root 内。

```
<父目录>/                       # 这一层放"记忆地图"入口文件
├── UAMS_ENTRY.json / .md      # 记忆地图入口（discover 也报告这里）
└── <uams-root>/               # --uams-root 指向这里
    ├── uams/                  # 记忆引擎（纯标准库，零依赖）
    │   └── adapters/uams_memory.py   # 主 CLI 入口
    ├── memory/                # 实际记忆内容
    │   ├── global/            #   跨项目通用（偏好/规矩）
    │   └── workbuddy|claude|codex|trae|kiro|dsh/   # 各身份记忆
    ├── migration/             # 写源权威状态 + 迁移验收记录（勿手改）
    ├── index/                 # 检索索引（派生产物，可重建）
    ├── audit/                 # 治理审计日志
    └── .uams-write.lock       # 跨进程写锁（MCP 并发时用，自动清理）
```

---

## 2. 工具包内容

```
uams-kit/
├── init_uams.py              # 一键初始化：生成开箱即用的 uams-root
├── mcp_server.py             # MCP stdio server（纯标准库，让 Claude Code/Cursor/Codex 一行接入）
├── uams/                     # 记忆引擎（纯标准库）
├── assets/
│   ├── workbuddy_skill.md    #   WorkBuddy 的 SKILL.md 全文（复制即用）
│   ├── claude_claude_md.md   #   Claude 的 CLAUDE.md 片段
│   ├── generic_prompt.md     #   Codex/Trae/Kiro/DSH 通用指令
│   └── global_preferences.template.md  # 通用偏好模板（不含任何个人印记）
└── README.md                 # 本文件
```

> 引擎是纯 Python 标准库、已验证可用；工具包把它打包成"别人下载解压即可初始化使用"的形态。

---

## 3. 快速开始（3 步）

### 第 1 步：初始化（生成你的 uams-root）

```bash
# 用 Python 3.7+（标准库即可，无需 pip install）
python uams-kit/init_uams.py --uams-root "D:/my-uams/uams-root"
```

脚本会：① 部署 `uams/` 引擎 ② **预置写源权威状态**（新用户无需迁移即可写入）③ 生成目录骨架与入口文件。
验证：

```bash
python "D:/my-uams/uams-root/uams/adapters/uams_memory.py" \
  --ai-identity workbuddy --uams-root "D:/my-uams/uams-root" status
# 应看到： "uamsAuthoritative": true
```

> **为什么不用先"迁移"也能写？** 引擎为"从旧记忆迁过来"设计了验收闸门，纯新用户反而卡死在 write。
> 工具包在初始化时**预置一条 bootstrap 验收记录 + 写源状态**，让新用户开箱即权威——这是预置数据，不是改引擎。

### 第 2 步：给你的 AI 接钩子（关键，少一个就不"无缝"）

把 `assets/` 里对应文件的内容，复制到该 AI 的入口配置：

| AI | 复制到哪 | 文件 |
|---|---|---|
| WorkBuddy | `~/.workbuddy/skills/uams-memory/SKILL.md` | `assets/workbuddy_skill.md` |
| Claude | `CLAUDE.md`（追加） | `assets/claude_claude_md.md` |
| Codex/Trae/Kiro/DSH | 各自的入口记忆/项目规则文件 | `assets/generic_prompt.md` |

**头号坑**：只接了自己常用的一个 AI，就以为"无缝"了——切到没接的 AI 照样断档。**每个 AI 都要接。**

### 第 3 步：正常用

之后每个 AI 开局会自动走"开局三步"（见第 5 节），你切来切去，背景/进度/偏好都在。

---

## 3.5 用 MCP 接入（Claude Code / Cursor / Codex —— 最省事）

如果你用的是**支持 MCP 的 AI 客户端**（Claude Code、Cursor、Codex、VS Code + MCP、Windsurf、Cline 等），
不用给每个 AI 单独贴钩子——直接跑一个 MCP server，客户端自动拿到 `uams_discover / uams_status / uams_search / uams_write` 四个工具。
这就是"直接能用"的那一步。

> MCP server 是**纯标准库**（`mcp_server.py`），没有任何 pip 依赖；底层仍调用 UAMS CLI。

### 启动 server

```bash
# 先初始化（见第 1 步），然后：
python uams-kit/mcp_server.py --uams-root "D:/my-uams/uams-root"
# 或指定默认身份（写记忆时用的身份，可被每次调用覆盖）
python uams-kit/mcp_server.py --uams-root "D:/my-uams/uams-root" --ai-identity claude
```

### 客户端配置（各加一段 mcpServers）

**Claude Desktop**（`%APPDATA%\Claude\claude_desktop_config.json`）：
```json
{
  "mcpServers": {
    "uams": {
      "command": "python",
      "args": ["D:/uams-kit/mcp_server.py", "--uams-root", "D:/my-uams/uams-root"]
    }
  }
}
```

**Cursor**（Settings → MCP → Add）：Name `uams`，Type `stdio`，Command `python D:/uams-kit/mcp_server.py --uams-root D:/my-uams/uams-root`

**Codex / 通用 MCP 客户端**：同上 JSON 结构，command 换成你环境的 python 绝对路径即可。
重启客户端后，应能在工具列表里看到 `uams_*` 四个工具。

### 四个工具说明

| 工具 | 作用 | 关键参数 |
|---|---|---|
| `uams_discover` | 定位根、列身份 | `ai_identity` |
| `uams_status` | 看权威状态/版本 | `ai_identity` |
| `uams_search` | 检索（工具无关） | `query` / `scope` / `project_path` / `ai_identity` |
| `uams_write` | 写入 | `title` / `body` / `type` / `source` / `confidence` / `subject` / `project_path` / `supersedes` / `ai_identity` |

> MCP server 对 write/search 加了**跨进程写锁**，多个 agent 同时调也不会写坏 JSON。
> 纯 CLI 方式（第 5/6 节）仍是官方入口；MCP 只是给 MCP 客户端包的一层皮。

---

## 3.6 接你已有的 UAMS —— 会破坏吗？能撤销吗？

如果你本地已经有一套 UAMS，想把 MCP 直接指向它，最该想清两件事。结论：**不会破坏结构，可以干净撤销；唯一要清醒的是"写入会新增条目"这件事本身。**

### 两种接法，安全性不同

| 接法 | `--uams-root` 指向 | 用的引擎 | 数据影响 |
|---|---|---|---|
| 全新使用 / 自测 | 新 `init` 出来的根 | 包内 `uams/` | 完全隔离 |
| 接你已有的根 | 你已有的 uams-root | **你已有根里的 `uams/`** | 操作真实数据 |

关键点：MCP server 用的引擎就是 `--uams-root` 那个目录**自己内部的** `uams/`。
**接已有根时，它自动用你已有的引擎，不会拿别的副本去碰你的数据，也不存在"引擎版本错位"风险。**

### 会不会破坏之前的记忆？—— 不会（结构层面）

1. MCP 只暴露 4 个工具：`uams_discover / uams_status / uams_search / uams_write`。
   没有 `delete` / `reset` / `migrate` / `health --repair` / `archive` 这类销毁或强制重建命令。
2. `write` 受引擎治理（schema 校验 + `source`/`subject`/`supersedes`/`audit`），且用原子写 + 并发锁，不会写坏 JSON。
3. `discover / status / search` 纯只读，**零修改**。

### 唯一要清醒的一点：写会"新增"条目

把 MCP 指到已有根并开放 `uams_write`，AI 客户端会往你**已有 UAMS** 写新记忆。
这是"内容层面"的改动，**不是"结构破坏"**——但如果你让某个客户端随意乱写，记忆会被污染（多出无用或错误条目）。
**只读接入（只调 discover/status/search，从不调 write）则零内容风险。**

### 接入后还能撤销吗？—— 能，且干净

- **撤销"接入"本身**：删掉 MCP 客户端配置里的 `mcpServers.uams` 那段，进程不再启动。
  零残留文件、零痕迹，对你已有 UAMS 毫无影响。
- **撤销被写入的条目**（如果你想清理）：
  - 推荐：用 `--supersedes <旧entryId>` 写一条更正条目取代错误结论（保留治理痕迹，旧条目逻辑废弃）。
  - 或直删文件：`memory/global/` 或 `memory/<身份>/` 下对应的 `.md/.json` 条目文件删除即移除该条。
  - 索引是派生产物，可直跑 CLI 重建：
    `python uams/adapters/uams_memory.py --ai-identity <身份> --uams-root <已有根> health --repair`
    （MCP 未暴露 health，需直接跑引擎 CLI）
  - 引擎没有"单条 delete"命令，但上述两条路足够还原到接入前状态。

### 建议

- 不要把任何 `uams/` 目录去覆盖你已有根的 `uams/`；接已有根时，`--uams-root` 直接指已有根路径即可，不要复制 / 移动 `uams` 目录。
- 首次接已有根，先用只读三连（`discover → status → search`）确认无误，再决定是否开放 `write`。

---

## 4. 初始化详解

`init_uams.py` 参数：

| 参数 | 必填 | 说明 |
|---|---|---|
| `--uams-root` | 是 | 目标 UAMS 根目录（将在此创建全部结构） |
| `--identity` | 否 | 默认 AI 身份（仅写入入口提示，默认 `workbuddy`） |
| `--force` | 否 | 目标已存在 `uams/` 包时强制覆盖 |
| `--no-copy-pkg` | 否 | 仅生成配置/状态/骨架，不复制引擎（高级） |

特性：不联网、不依赖第三方包、只写 `--uams-root` 指定目录、幂等可重跑。

---

## 5. 开局三步（每个 AI 接入后自动执行）

把 `<uams-root>` 换成你的根，身份换成你的（如 `claude`）：

```bash
CLI="<uams-root>/uams/adapters/uams_memory.py"
# 1. discover
python "$CLI" --ai-identity workbuddy --uams-root <uams-root> discover
# 2. status  —— 必须见 uamsAuthoritative: true
python "$CLI" --ai-identity workbuddy --uams-root <uams-root> status
# 3. 定向 search（先检索，不要全量读）
python "$CLI" --ai-identity workbuddy --uams-root <uams-root> search "关键词" --scope project-active --project-path "<项目根>"
```

---

## 6. 命令与写入规范

### 6.1 命令表

| 命令 | 作用 |
|---|---|
| `discover` | 定位 uams-root（推断 canonicalRoot、列出支持身份） |
| `status` | 显示权威状态、版本（自报 `0.2.0`）、已注册项目 |
| `read` | 读指定条目/范围（`--scope project-archive` 读归档） |
| `search` | 检索（`--scope` 见下；**不按身份过滤**，工具无关性来源） |
| `write` | 写入（写前闸门要求 `uamsAuthoritative: true`） |
| `archive` | 归档条目（移出 active，默认不检索） |
| `register-project` | 注册项目或加 workspace 别名（写项目记忆前必做） |
| `health --repair` | 校验并重建索引（索引是派生产物，可从正文重建） |

`--scope` 取值：`global` / `project-active` / `project-archive` / `default` / `historical-snapshot`。
> 注意：`search` 的 scope **不含** `project-archive`/`historical-snapshot`，要读归档用 `read --scope project-archive`。

### 6.2 写入硬规则（不守，记忆会脏）

- 写之前**必须** `status` 确认权威（`uamsAuthoritative: true`）。
- 非 `note` 类型**必填稳定 `--subject`**；`confirmed` 必填 `--source`。
- 同主题更新必须 `--supersedes <旧entryId>` **替代**旧条目，禁止堆叠矛盾结论。
- 禁止写凭据/令牌/私钥；禁止写未验证的推测。
- 项目记忆：先 `register-project --project-path <根>` 再用 `--project-path` 写。

### 6.3 写入示例

```bash
# 全局通用记忆（不传 project）
python "$CLI" --ai-identity workbuddy --uams-root <uams-root> write \
  --title "全局偏好：亮色界面文字纯黑" --body "文字默认 #000000，层级靠字号+字重" \
  --type preference --subject "全局偏好/UI配色" --source user-stated --confidence confirmed

# 项目记忆（先 register-project）
python "$CLI" --ai-identity workbuddy --uams-root <uams-root> register-project --project-path "<项目根>"
python "$CLI" --ai-identity workbuddy --uams-root <uams-root> write \
  --title "方案定稿" --body "采用 A 方案" --type decision --subject "架构/xx" \
  --project-path "<项目根>" --source discussion --confidence confirmed
```

---

## 7. 各 AI 接入（复制即用，详见 assets/）

- **WorkBuddy**：`assets/workbuddy_skill.md` 全文放进 `~/.workbuddy/skills/uams-memory/SKILL.md`。
- **Claude**：`assets/claude_claude_md.md` 追加进 `CLAUDE.md`。
- **Codex / Trae / Kiro / DSH**：`assets/generic_prompt.md` 放进各自入口记忆/项目规则。

> 通用指令核心是"开局三步 + 写入硬规则 + 铁律"。任何 AI 只要把这段注入入口配置，就能接上同一份记忆。

---

## 8. 端到端 demo（实测结果，证明工具无关性）

按顺序执行（初始化后）：

```
# ① workbuddy 写入一条全局记忆
python "$CLI" --ai-identity workbuddy --uams-root <uams-root> write \
  --title "第一条记忆" --body "UAMS 初始化验证成功" --type note --source bootstrap --confidence confirmed

# ② workbuddy 搜得到
python "$CLI" --ai-identity workbuddy --uams-root <uams-root> search "UAMS" --scope global
# → 返回刚写的条目

# ③ 换 claude 身份搜 —— 照样读回同一条！
python "$CLI" --ai-identity claude --uams-root <uams-root> search "UAMS" --scope global
# → 同样返回 workbuddy 写的条目（工具无关性成立）
```

`status` 输出示例：

```json
{
  "uamsRoot": "D:\\my-uams\\uams-root",
  "uamsVersion": "0.2.0",
  "aiIdentity": "workbuddy",
  "uamsAuthoritative": true,
  "registeredProjects": []
}
```

---

## 9. 已知短板与边界

| 短板 | 说明 | 缓解 |
|---|---|---|
| 多 AI 钩子需逐个接 | 只装一个 AI 的钩子 = 半无缝，切到没接的会断档 | 第 3 步把每个 AI 都接上 |
| 无真并发锁 | 引擎原子写，多进程同时写仍有损坏风险 | **MCP server 已加跨进程写锁串行化**；纯 CLI 方式仍建议串行 |
| 无多机同步 | 本地单机，不做网络认证/分布式 | 各机各跑一份，自行同步 |
| 无版本/协议演进管理 | CLI 自报 `0.2.0`，但无强制兼容闸门 | 升级 CLI 后留意旧入口配置 |
| 治理靠人遵守 | `supersedes`/`source` 是"应守"非"强执" | 写前自检 + 定期 `health --repair` |
| 检索按词元、不支持子串 | `search` 是 token 匹配不是子串匹配：查 `EnglishTest` 能中，查 `English`（子串）中不了；连字符拉丁词元整体保留（`selftest-写入` 只能整词搜到，搜 `selftest` 为空）。中英文分词规则不同 | **查询用完整关键词/整词**；中文整词最稳；不要用片段去搜 |

**已覆盖的可靠性保障**（别误读成缺陷）：原子写 + 跨进程锁 + 事务恢复日志；`index/` 是派生产物，`health --repair` 可从正文重建；归档默认不检索，噪声隔离。

---

## 10. 通用偏好模板怎么用

`assets/global_preferences.template.md` 是**通用版（不含任何个人印记）**。填入你自己的偏好/规矩，
写进 `memory/global/` 即可。这样切到任意 AI，它都能读到你的习惯，不会"换个人格"。

---

## 11. 一页速查（贴进钩子或书签）

```
初始化：  python init_uams.py --uams-root <根>
状态：    python <根>/uams/adapters/uams_memory.py --ai-identity <身份> --uams-root <根> status
检索：    ... search "词" --scope project-active --project-path <项目根>
写入：    ... write --title .. --body .. --type .. --subject .. --source .. --confidence confirmed
注册项目：... register-project --project-path <项目根>
修索引：  ... health --repair
身份：    workbuddy | claude | codex | trae | kiro | dsh
铁律：    写前必 status；同主题必 --supersedes；不写凭据；切 AI 不断档
```

---

## 12. 竞品对照：为什么不直接用 Mem0 / MemoryLake / Muninn

2026 年"跨 AI 共享记忆"已经是明确痛点（切工具即失忆、厂商故意不开放导出），赛道里有几类玩家：

| 类别 | 代表 | 形态 | 本地优先 | 零依赖 | 工具无关 | 治理 | 记忆检索 |
|---|---|---|---|---|---|---|---|
| 云 API | Mem0 | 云端 REST/SDK（图谱功能在付费档） | ✗ | ✗ | ✗ | 弱 | 向量 |
| 托管 MCP | MemoryLake / pumaDB | 云端 MCP | ✗ | ✗ | ✓ | 弱 | 向量 |
| 本地 MCP（向量） | Muninn | 本地 MCP + ChromaDB/Ollama | ✓ | ✗（需 Ollama） | ✓ | 弱 | 向量 |
| 本地 MCP（混合） | local-memory-mcp | 本地 SQLite，25 工具 | ✓ | ~ | ✓ | 中（矛盾检测） | BM25+向量 |
| 本地 MCP（代码图） | MARM | 本地 SQLite WAL，子 20ms | ✓ | ~ | ✓ | 弱 | 语义+精确 |
| **UAMS（本工具）** | — | **CLI + MCP（纯标准库）** | **✓** | **✓（纯标准库）** | **✓** | **强（source/audit/supersedes）** | **关键词/JSON** |

**UAMS 的差异化优势：**
- **纯标准库零依赖**：丢到任意机器，`python init_uams.py` 即跑，不需要 `pip install`、不需要 Ollama/uv。Muninn/MARM 都逃不掉额外依赖。
- **工具无关路由**：`--ai-identity` 让 workbuddy 写的内容被 claude 搜到，这是"无缝切换"的核心，已实测。
- **治理不腐化**：`source` 必填、`supersedes` 替代旧条目、`audit/` 三层日志——竞品基本是"扁平堆记忆"，半年就成一锅粥。

**UAMS 的短板（诚实清单）：**
- **无语义/向量检索**：靠关键词+JSON 结构，长文语义召回不如向量方案。权衡点是零依赖 + 可审计。
- **无多机同步**：本地单机。要同步就把整个 uams-root 丢进 git 仓库（它本就是纯文件）。
- **检索范围有限**：`search` 不含归档/历史快照，读归档用 `read --scope project-archive`。

**适合谁 / 不适合谁：**
- ✅ 适合：在意隐私/自托管、频繁切多个 AI、重项目要长期记忆、想自己掌控记忆结构的人。
- ❌ 不适合：想要"开箱即语义搜索"且不介意数据上云、或要团队分布式实时同步的人（那种直接上 Mem0/MARM 云版）。
