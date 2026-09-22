---
name: uams-memory
description: 统一记忆系统 UAMS 接入。每次会话开局自动连接共享记忆，跨 AI 切换不丢上下文、不重喂背景、不丢习惯。当用户说"记住""查记忆""项目进度""之前讨论过"或任何涉及长期记忆的诉求时触发。
---

# UAMS 统一记忆接入（WorkBuddy 版）

你是 WorkBuddy 里的 AI 助手。本机已部署 UAMS（统一 AI 记忆系统），记忆是**所有 AI 共享的公地**，不是你私有的。本 skill 负责让你"开局自动接上记忆"。

## 开局三步（每次会话、任何记忆读写之前必做）

先把 uams-root 路径记为 `<uams-root>`（来自 UAMS_ENTRY.json 的 canonicalRoot，或用户告知）。你的身份固定 `workbuddy`。

1. **discover**（定位根，确认存在）
   ```
   python "<uams-root>/uams/adapters/uams_memory.py" --ai-identity workbuddy --uams-root <uams-root> discover
   ```
2. **status**（必须见 `uamsAuthoritative: true` 才允许写）
   ```
   ... status
   ```
3. **定向 search**（先检索，不要全量读）
   ```
   ... search "关键词" --scope project-active --project-path "<项目根>"
   ```

## 写入规范（硬规则，不守记忆会慢慢变脏）

- 写之前必须 `status` 确认权威。
- 非 `note` 类型**必填稳定 `--subject`**；`confirmed` 置信度**必填 `--source`**。
- 同主题更新必须 `--supersedes <旧entryId>` 替代旧条目，**禁止堆叠矛盾结论**。
- 禁止写凭据/令牌/私钥；禁止写未验证的推测。
- 项目记忆：先 `register-project --project-path <根>` 再用 `--project-path` 写。

## 铁律

- UAMS 是唯一长期记忆路径，不要另起平行记忆文件（如 `.workbuddy/memory/*` 当项目记忆）。
- 切换 AI 不会断档：别人写的你 search 得到，你写的别人也读得到。
- 用户明确授权的删除/归档才执行；默认只追加与替代，不动历史。

## 常见踩坑（别犯）

- 忘了 `status` 就 write → 被闸门拒绝。
- 只接了自己一个 AI 的钩子，以为"无缝"了 → 别人切到没接的 AI 照样断档。
- 多 AI 同时写 → 严格串行，不要并发写同一份 UAMS。
