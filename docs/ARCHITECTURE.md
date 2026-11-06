# 架构决策与实现说明（M1）

本文记录 M1 实现中**偏离交接文档**或文档未明确的地方，便于后续接手。

## 1. HTTP 层：插件内置 aiohttp 子应用（已定）

- 交接文档 §3.1 要求「插件起一个轻量 HTTP 子应用（aiohttp，端口可配，默认 127.0.0.1）」。
- 没有使用 AstrBot Dashboard 的 `context.register_web_api`：该通道挂在 `/api/plug/...` 且要求 Dashboard JWT，
  不适合面向终端用户的 Cookie 会话 SaaS 控制台（用户不应登录 AstrBot Dashboard）。
- 因此 `saas/web/app.py` 是一个独立 ASGI 级 aiohttp 应用，`main.py` 在插件加载时启动它；
  `scripts/dev_server.py` 用同一应用 + FakeAstrBot 独立运行，前后端可脱离 AstrBot 联调。

## 2. 数据模型补充（`saas/migrations/001_init.sql`）

在文档 §5 基础上增加了以下字段/表（均有注释）：

| 补充 | 原因 |
|---|---|
| `otp_codes` 表 | FR-A 的 OTP 规则（10min/60s/5 次/单次）需要持久化 |
| `invites.code_hint` | 管理端列表只展示前 8 位，避免明文邀请码入库 |
| `sessions.absolute_expires_at` | 30d 滑动 + 90d 绝对 / 管理员 12h 绝对 |
| `sessions.csrf_token_hash` | CSRF 双提交 cookie 与会话绑定 |
| `bots.snapshot` | 模板是快照（§4.3），创建后不随模板变化 |
| `invites.code_hash` 用 TEXT(hex) | 便于索引与唯一性；文档 BLOB 的语义不变 |

## 3. 账号与会话

- 邀请码：`INV-XXXX-XXXX`，HMAC-SHA256(server pepper) 存 hash；一次性通过
  `UPDATE ... WHERE used_count < max_uses` 原子消耗；重复使用 → **410 `invite_exhausted`**。
- OTP：6 位数字，HMAC(pepper, email:code) 入库；60s 重发（`429` + `retry_after`）、10 分钟、
  单次、5 次错误上限；校验失败不区分「不存在/过期」。
- 会话：Cookie 只放随机 token，DB 存 `sha256(token)`；滑动续期写回 `expires_at`；
  管理员会话固定 12h 不滑动。
- 禁用用户：撤销全部会话（立即 401）并停用其所有 Bot（`bot.disabled_all` 审计）。

## 4. Bot 创建与回滚

顺序（与 easy_setup `_create_bot_core` 对齐，记忆部分改为自研）：

```
写入 creating 行 → 人格 → 配置 profile → UMO 路由 {bot_id}:: → SQLCipher 记忆库 → 平台（禁用）→ 状态 pending_qr
失败 → 逆序：平台 → 记忆库文件 → 路由 → 配置 → 人格 → 删除 bots 行
```

- 每步单独 `_safe`，回滚失败只告警不中断其余步骤；测试对 `create_persona/create_config/bind_route/create_platform`
  逐项注入失败，断言 DB 行、人格/配置/路由/平台、`memory/*.db*` 全部为空。
- 技术字段（`persona_name` = `saas_<bot_id>`、`conf_id`、`memory_db`）创建后不再改变；改名只改 `name`。
- 删除：停用 → 解绑 → 删配置/人格/平台 → 删记忆库（含 `-wal`/`-shm`）→ 删 binding → 删行 → 审计；
  必须输入完全一致的 Bot 名。

## 5. 扫码状态机

- 会话保存在内存（单进程），每个 Bot 同时只允许一个；**TTL 60s**、**最多自动刷新 3 次**、**5 分钟无轮询回收**。
- `poll` 返回 `pending/scanned/created/expired`；过期时先自动刷新（`refresh_count+1`），第 4 次置 `expired`。
- `finalize` 才写凭据：`AES-256-GCM(tenant key, AAD tenant|bot|credential|bot_id)` 存 `bot_bindings`，
  然后 `apply_credentials` 到平台配置并启用平台，状态 `ready`。
- 真实实现直接复用 AstrBot `weixin_oc` / `qq_official` 的 `login_registration` 模块；
  `FakeAstrBot` 提供确定性替身（测试/演示）。

## 6. 记忆模块（M2，已实现后端）

### 6.1 分层（按交接文档 §4.5.1）

```
saas/memory/
├─ models.py           纯 dataclass：Memory/MemoryDraft/RecallHit/Turn/RecallContext
├─ ports.py            Protocol：MemoryRepository/Retriever/Extractor/EventBus/MemoryStore
├─ service.py          MemoryService：去重→写入→索引→事件；召回编排
├─ api.py              MemoryAPI：对 HTTP / LLM 工具的用例门面（不写 SQL）
├─ storage/
│  ├─ sqlcipher.py     建库/删库/连接 + 逐版本 schema 迁移
│  ├─ repository.py    唯一写 SQL 的地方（SQLCipher 实现）
│  ├─ in_memory.py     契约测试用同行为实现
│  └─ schema/          001_init / 002_fts / 003_fts_standalone
├─ retrieval/          fts.py（BM25 候选）+ rules.py（0.5/0.3/0.2 重排）+ vector.py 预留
├─ extraction/         command.py（/记住 ... #tag kind:event importance:4）+ llm.py 预留
├─ tools/llm_tools.py  memory_remember / memory_recall / memory_forget 的 schema + dispatch
├─ migration/from_angel.py  只读导入 + 报告（成功/跳过/失败，幂等）
└─ store.py            SQLCipherMemoryStore（LRU ≤64 连接）/ InMemoryStore
```

### 6.2 存储与索引

- 每 Bot 一个 SQLCipher 文件（`data/memory/<bot_id>.db`），WAL；建库后校验文件头不是
  `SQLite format 3\0`；普通 sqlite3 打开报 `DatabaseError`（有测试）。
- **FTS 采用 standalone 索引表**（不是 external content）：因为 tags 在另一张表，
  external-content 的触发器在更新时用“新 tags”删除“旧索引行”会导致索引损坏
  （实测 `database disk image is malformed`）。
- **中文检索**：unicode61 不分词，因此入库/查询都做预分词（CJK 单字 + 相邻 bigram、ASCII 整词），
  查询优先用 bigram（选择性高）；10k 条 FTS 查询实测 13–21ms（目标 <20ms）。
- 检索管道：FTS 前 50 → `RulesReranker`（0.5×BM25 归一 + 0.3×importance + 0.2×新近度，置顶加 10）
  → token 预算裁剪（默认 800）→ 注入格式 `[记忆]\n- (偏好) ... (2026-11-02)`。
- 召回后异步更新 `last_recalled_at/recall_count`（当前同步写，负载低）。
- 去重：内容去空白/标点后 24h 内相同 → 返回已有记录（`duplicate=true`），不新增。
- 写路径：LLM 工具 / `/记住` 命令 → `MemoryService.remember()`；HTTP 只提供管理（列/查/改/删/搜索/导出）。
- 删除 Bot：先 `memory_store.close(bot_id)` 关连接，再删 `.db`/`-wal`/`-shm`（测试断言连接已释放）。
- 降级：环境无 SQLCipher 时 `MemoryStorage` 显式报错并记录降级日志，不静默写明文。

### 6.3 测试与指标

- 契约测试：同一组用例分别跑 `InMemoryRepository` 与 `SqlCipherRepository`（增删改查、筛选、分页、
  FTS、touch、去重）。
- 集成：真实 SQLCipher 文件不可被普通 sqlite3 打开；跨 Bot 不串；删 Bot 清理。
- 性能：10,000 条记忆、查询 “西湖 咖啡” → 13.4ms（`pytest -s` 打印）。
- 导入：`saas/memory/migration/from_angel.py` 只读源库，`judgment→content`、`tags` 拆表、保留 `created_at`，
  幂等；HTTP import 仍 501（M2 走 CLI）。

## 7. 前端（web/）

- Vue3 + Vite6 + Vuetify3 + Pinia + TS；history 路由 `base=/console/`；同源 `/api`，无 CORS。
- API client：`credentials:'include'`、`X-CSRF-Token`（从 `csrf` cookie 读）、统一错误对象、
  401 → 清 store 跳登录、403 → 提示不登出、GET 重试 1 次。
- 视觉延续 AstrBot（primary `#3c96ca`、8px 圆角、56px 顶栏 + 232px 侧栏）；
  只参考 demo，不照搬其 hash 路由/mock/单文件结构。

## 8. 未实现（M2/M3 占位）

| 能力 | 现状 |
|---|---|
| 记忆 CRUD/FTS/LLM 工具/导入 | 后端已完成（M2）；前端记忆页在 M2 收尾 |
| 加密开关（关闭=全部解密） | `/api/me/encryption` 只读；M3 实现回填任务 |
| 管理员内容查看 / 内容访问留痕 | 数据表与路由骨架已就位（M3） |
| 手动充值/账本 | 表结构就位；`/api/admin/orders` → 501，M3 实现 |
| AstrBot 启动时孤儿 Bot 对账 | `stale_creating_rows()` 提供基础查询，M3 接入 |
