# 把下面整段追加到你的 CLAUDE.md（Claude 的入口记忆文件）

## UAMS 统一记忆接入（必读，每次会话开局执行）

本机已部署 UAMS（统一 AI 记忆系统），记忆是所有 AI 共享的公地，不是你私有的。
你的身份是 `claude`。路径占位 `<uams-root>` 替换为 UAMS_ENTRY.json 里的 canonicalRoot。

### 开局三步（任何记忆读写之前必做）
1. discover：
   `python "<uams-root>/uams/adapters/uams_memory.py" --ai-identity claude --uams-root <uams-root> discover`
2. status（必须见 `uamsAuthoritative: true` 才允许写）：
   `... status`
3. 定向 search（先检索，不要全量读）：
   `... search "关键词" --scope project-active --project-path "<项目根>"`

### 写入规范（硬规则）
- 写之前必须 status 确认权威。
- 非 note 类型必填稳定 `--subject`；confirmed 必填 `--source`。
- 同主题更新必须 `--supersedes <旧entryId>` 替代旧条目，禁止堆叠矛盾结论。
- 禁止写凭据/令牌/私钥；禁止写未验证的推测。
- 项目记忆：先 `register-project --project-path <根>` 再用 `--project-path` 写。

### 铁律
- UAMS 是唯一长期记忆路径，不要另起平行记忆文件。
- 切换 AI 不会断档：workbuddy/codex/trae 写的你 search 得到，你写的它们也读得到。
- 默认只追加与替代，不动历史；删除/归档需用户明确授权。
