# 控制台 HTTP API 契约（M1）

> 本文件是前后端唯一契约。后端实现见 `saas/web/`，前端实现见 `web/`。
> 变更契约必须同时改本文件并在 PR/提交里说明。

## 0. 通用约定

- 同源，前缀 `/api`；控制台静态资源在 `/console/`（history 路由，`base='/console/'`）。
- 请求/响应均为 `application/json; charset=utf-8`（导出下载除外）。
- 时间戳统一为 **Unix 秒**（int）。前端用 dayjs 本地化。
- ID：`b_<uuid4hex>`（Bot）、`t_<uuid4hex>`（模板）、`u_<uuid4hex>`（用户）、`j_<uuid4hex>`（任务/扫码会话）。永不自增、不可枚举。

### 0.1 响应包络

成功：

```json
{ "ok": true, "data": { ... } }
```

> 下文各接口示例展示的是 **`data` 字段的内容**（成功时），不再重复包 `ok/data`。
> 列表接口统一返回 `{ items, total, page, page_size }`（无分页的列表只有 `items`）。

失败（HTTP 状态码同步设置）：

```json
{ "ok": false, "error": { "code": "invite_exhausted", "message": "邀请码已被使用", "field": "invite" } }
```

- `field` 仅在表单字段错误时出现，可为 `null`。
- 前端统一把 `error.code` 映射为提示；`message` 可直接展示。

### 0.2 认证与 CSRF

- 会话 Cookie：生产为 `__Host-sid`（HttpOnly / Secure / SameSite=Lax / Path=/，无 Domain）；
  开发（`SAAS_COOKIE_SECURE=false`）自动降级为 `sid`，其余属性相同。
- CSRF：登录/`GET /api/me` 时下发 **非 HttpOnly** Cookie `csrf`（随机 32B base64url）。
  所有 `POST/PUT/PATCH/DELETE` 请求必须带 `X-CSRF-Token` 头，值等于 `csrf` Cookie，否则 `403 csrf_invalid`。
- 会话有效期：普通 30 天滑动 + 90 天绝对；管理员 12 小时绝对。
- 任意接口返回 `401 unauthorized` 表示会话失效：前端清 store → `/login?redirect=...`。
  `403 forbidden` 表示已登录但无权限：前端提示，不登出。

### 0.3 错误码

| code | HTTP | 说明 |
|---|---|---|
| `validation_error` | 400 | 字段校验失败（`field` 指出字段） |
| `unauthorized` | 401 | 未登录 / 会话过期 |
| `csrf_invalid` | 403 | CSRF 校验失败 |
| `forbidden` | 403 | 角色或资源归属不符（跨租户一律 404 优先） |
| `not_found` | 404 | 资源不存在或不属于当前用户 |
| `invite_invalid` | 410 | 邀请码不存在/已作废 |
| `invite_expired` | 410 | 邀请码过期 |
| `invite_exhausted` | 410 | 邀请码已用尽（一次性） |
| `otp_rate_limited` | 429 | 60s 内重复请求 OTP（错误对象含 `retry_after` 秒） |
| `otp_invalid` | 401 | 验证码错误 / 已使用 / 过期（不区分，防枚举） |
| `otp_attempts_exceeded` | 429 | 校验次数超限，需重新获取 |
| `template_disabled` | 409 | 模板已下架，不能新建 Bot |
| `quota_exceeded` | 409 | Bot 数量超配额 |
| `bot_state_invalid` | 409 | 当前 Bot 状态不允许该操作 |
| `qr_session_exists` | 409 | 同一 Bot 已有扫码会话 |
| `qr_expired` | 410 | 扫码会话已过期/刷新超限 |
| `qr_not_ready` | 409 | 尚未扫码成功，不能 finalize |
| `conflict` | 409 | 其他并发冲突 |
| `insufficient_balance` | 409 | 预付费点数不足（`extra` 含 balance/points；M4 可开关） |
| `upstream_error` | 502 | 上游模型/向量 API 探测失败（已脱敏） |
| `internal_error` | 500 | 服务端错误（不泄露堆栈） |

## 1. 认证

### POST /api/auth/otp/request

```json
{ "email": "a@b.com", "invite": "可选，仅新用户注册时必填" }
```

响应 `200`：

```json
{ "sent": true, "resend_after": 60, "delivered": true,
  "dev_code": "123456（仅开发开关打开时出现）" }
```

- `delivered=true` 表示已通过 SMTP 投递；未配置 SMTP 时为 `false`（验证码只写日志，开发用）。

- 已存在用户：`invite` 忽略。
- 新用户：`invite` 必填，校验失败返回 410。
- 新用户校验邀请码，但**不在此时消耗**；在 verify 成功时原子消耗。
- 60s 内重复请求 → `429 otp_rate_limited`。

### POST /api/auth/otp/verify

```json
{ "email": "a@b.com", "code": "123456", "invite": "可选，新用户必填" }
```

响应 `200`（同时 Set-Cookie `sid`（或 `__Host-sid`）与 `csrf`）：

```json
{
  "user": { "id": "u_...", "email": "a@b.com", "role": "user", "status": "active",
            "created_at": 1700000000,
            "encryption": { "enabled": true, "state": "encrypted" } },
  "is_new": true,
  "csrf_token": "…"
}
```

- 邀请码在创建新用户时**原子消耗**；并发重复使用同一个码只有一个成功，其余 410。
- OTP 单次有效、10 分钟、最多 5 次校验、60s 重发。

### POST /api/auth/logout

`200 { "ok": true }`，服务端撤销会话并清 Cookie。

### GET /api/me

`200`：

```json
{
  "user": { "id": "u_...", "email": "…", "role": "user|admin", "status": "active",
            "created_at": 0, "encryption": { "enabled": true, "state": "encrypted" } },
  "csrf_token": "…",
  "limits": { "max_bots": 3, "max_memories": 2000, "monthly_tokens": 1000000 },
  "version": "0.3.0"
}
```

未登录 → 401。

## 2. 模板（用户可见）

### GET /api/templates

只返回 `enabled=true` 的模板（快照来源），按更新时间倒序。`200 { "items": [Template] }`。

```json
{
  "id": "t_...", "name": "默认陪伴", "description": "…",
  "base_conf_id": "default",
  "model_profile_id": "",
  "persona_prompt": "…", "begin_dialogs": ["…"],
  "config_patch": { "provider_settings": {} },
  "memory_defaults": { "auto": false, "max_items": 2000, "retention_days": 90, "recall_top_k": 5 },
  "privacy_defaults": { "allow_disable": true },
  "quota": { "max_bots": 3, "monthly_tokens": 1000000, "max_memories": 2000 },
  "user_overridable": ["persona_prompt"],
  "enabled": true,
  "created_at": 0, "updated_at": 0
}
```

## 3. Bot

Bot 对象：

```json
{
  "id": "b_...", "name": "小明", "platform": "weixin_oc",
  "status": "creating|pending_qr|ready|disabled|deleting|deleted",
  "template_id": "t_...", "template_name": "默认陪伴",
  "persona_name": "小明", "conf_id": "…",
  "enabled": false, "bound": false,
  "created_at": 0, "updated_at": 0, "last_active_at": 0,
  "qr": null
}
```

`qr`（存在进行中的扫码会话时）：

```json
{ "id": "j_...", "status": "pending|scanned|created|expired",
  "qr_content": "https://…", "qr_image": "data:image/png;base64,…",
  "expires_at": 0, "refresh_count": 0, "interval": 2 }
```

> `qr_image` 服务端生成（qrcode 库）；前端可直接 `<img :src>`。

### GET /api/bots

`200 { "items": [Bot] }`（仅当前用户，按创建时间倒序）。

### POST /api/bots

```json
{ "name": "小明", "template_id": "t_...", "platform": "weixin_oc" }
```

- 校验：名称 1–32 字符（去首尾空白）、模板启用、配额（`max_bots`）。
- 创建顺序：人格 → 配置 → UMO 路由 → 记忆库（SQLCipher）→ 平台实例（禁用）→ 注册表。
- 失败必须回滚全部副作用（含记忆库文件），返回 500 `internal_error`，DB 无残留。
- 成功 `201 { "bot": Bot }`，状态 `pending_qr`。

### GET /api/bots/{id}

`200 { "bot": Bot }`；不存在/非本人 → 404。

### PATCH /api/bots/{id}

```json
{ "name": "新名字", "enabled": true }
```

- `name`：只改展示名，技术字段（persona/conf/memory_db）不变。
- `enabled`：启停平台实例；`pending_qr` 状态不允许启用。
- `200 { "bot": Bot }`。

### DELETE /api/bots/{id}

```json
{ "confirm_name": "小明" }
```

- 必须与 Bot 当前名称完全一致，否则 `400 validation_error`（`field=confirm_name`）。
- 顺序：停用 → 解绑 → 删路由/配置/人格 → 关连接 → 删记忆库（含 `-wal`/`-shm`）→ 删绑定 → 审计。
- `200 { "deleted": true }`；再次删除 → 404。

### 扫码

#### POST /api/bots/{id}/qr/start

`200`：

```json
{ "qr": { "id": "j_...", "status": "pending", "qr_content": "…",
          "qr_image": "data:image/png;base64,…", "expires_at": 0,
          "refresh_count": 0, "interval": 2 } }
```

- 同一 Bot 只能有一个扫码会话（未过期时重复 start → 409 `qr_session_exists`）。
- 二维码 TTL **60s**。
- 会话 5 分钟无轮询自动回收；Bot 变回 `pending_qr`。

#### GET /api/bots/{id}/qr/poll

`200 { "qr": Qr }`（`status`：`pending` / `scanned` / `created` / `expired`）。

- 过期后服务端**自动刷新**（新二维码），`refresh_count`+1，响应继续 `pending` 且带 `message`。
- 第 4 次过期（`refresh_count >= 3`）→ `status="expired"`，前端提示重新发起。
- `created` 表示已拿到凭据，等待 finalize。

#### POST /api/bots/{id}/qr/finalize

`200 { "bot": Bot }`：写入加密凭据、启用平台、状态 `ready`，5s 内上线。
未扫码成功 → 409 `qr_not_ready`。

## 3.1 记忆（M2 已实现）

记忆写入只来自 LLM 工具 `memory_remember` / 用户命令 `/记住 ...`，HTTP 只提供管理能力。

Memory 对象：

```json
{
  "id": 1, "kind": "preference", "kind_label": "偏好",
  "content": "用户喜欢深夜聊天", "reasoning": "",
  "importance": 4, "pinned": true, "tags": ["作息"],
  "metadata": {}, "source_conversation_id": "", "source_message_id": "",
  "created_at": 0, "updated_at": 0, "last_recalled_at": 0, "recall_count": 0
}
```

- `GET  /api/bots/{id}/memories?page=&page_size=&kind=&tag=&q=` → `{items,total,page,page_size}`
- `GET  /api/bots/{id}/memories/{mid}` → `{ "memory": Memory }`
- `PATCH /api/bots/{id}/memories/{mid}` `{content?,kind?,reasoning?,importance?,pinned?,tags?,metadata?}` → `{ "memory": Memory }`
  - 部分更新；`tags` / `metadata` 为**全量替换**；`kind ∈ fact|preference|event|note`；`importance ∈ 1..5`。
- `DELETE /api/bots/{id}/memories/{mid}` → `{ "deleted": true }`（软删）
- `POST /api/bots/{id}/memories/search` `{q, kind?, limit?}` → `{items,total,page,page_size}`
- `POST /api/bots/{id}/memories/export` → `{bot_id, exported_at, count, items}`（前端下载 JSON）
- `POST /api/bots/{id}/memories/import` → M2 暂 501（导入走 CLI：`saas/memory/migration/from_angel.py`）

## 3.2 记忆笔记（天使之魂对标）

- `GET/POST /api/bots/{id}/notes?page=&page_size=&tag=&q=` → 笔记列表/新建（`{title,content,tags[]}`）
- `GET/PATCH/DELETE /api/bots/{id}/notes/{short_id}` → 详情/编辑/软删
- `GET /api/bots/{id}/notes/{short_id}/read?offset=&limit=` → `{short_id,title,content,offset,total_length,has_more,next_offset}`（按字符分页，CJK 安全）
- `POST /api/bots/{id}/memories/consolidate` `{dry_run?}` → 规则版「睡眠巩固」报告
  `{bot_id,dry_run,scanned,merged_groups,merged_records,decayed,forgotten,kept}`（写审计）
- 记忆字段新增：`memory_type`(knowledge/preference/relationship/event/emotion/note)、`strength`(0–100)、
  `access_count`、`last_decay_at`；旧 `kind=fact` 视为 `knowledge`。

## 3.3 记忆 API 设置（管理员）

- `GET/PUT /api/admin/settings/memory`：`embedding/rerank/behavior` 三段；GET 中 `api_key` 掩码、
  `has_api_key` 标识；PUT 为深合并，`"••••••••"` 表示保持，`""` 表示清除。
- `POST /api/admin/settings/memory/test` `{kind:"embedding"|"rerank"}` → 实际调用上游，
  `{ok,dim|count,message,latency_ms,model}`；失败 502 `upstream_error`（脱敏）。
- 未配置时检索回退 FTS + 规则重排；配置 embedding 后启用向量候选 + RRF，配置 rerank 后对候选重排
  （失败回退规则，不影响可用性）。

## 4. 额度 / 访问记录（本期只读，M1 返回空数据）

- `GET /api/wallet` → `{ "balance": 0, "currency": "points", "ledger_total": 0 }`
- `GET /api/wallet/usage?days=14` → `{ days, start, end, balance, total_in, total_out, points: [{date, delta, in, out, balance}], scope: "platform_points_ledger" }`（余额走势图）
- `GET /api/wallet/ledger?page=1` → `{ "items": [{id,delta,type,ref,note,created_at}], "total": 0, "page": 1, "page_size": 20 }`
- `GET /api/access-log?page=1` → `{ "items": [], "total": 0, "page": 1, "page_size": 20 }`
- `GET /api/models` → `{items:[{id,name,provider,model,points_per_1k_input,points_per_1k_output,currency,note,...}]}`（仅 enabled，不含 key/base_url）
- `GET /api/me/usage?page=&page_size=` → `{items,total,page,page_size,summary}`（summary 为近 30 天 tokens/points）
- `GET /api/me/encryption` → `{ enabled, state, changed_at, done, total, percent, eta, job? }`
  - `state ∈ encrypted | decrypting | plaintext | encrypting | paused`
  - `job = {id,direction,status,total,done,percent,error,created_at,finished_at}`
- `PUT /api/me/encryption` `{ "enabled": false, "confirm": "确认解密" }` → **202** + 同 GET 的状态；关闭必须输入「确认解密」，开启无需 confirm。
- `GET /api/me/encryption/job` → 同上（轮询用）。
- 关闭语义：对用户全部 Bot 执行 对话解密回填 + 记忆库 SQLCipher→普通 SQLite + 凭据解密；开启反向执行。
  同一用户同时只允许一个任务，重复提交 409。

## 4.1 管理端内容查看（M3，每次访问写 content_access_logs）

- `GET /api/admin/bots/{id}/conversations` → `{items:[{id,title,history:[{role,content}],encrypted,decrypt_error,created_at,updated_at}],total}`
- `GET /api/admin/bots/{id}/memories?page=&q=&kind=` → 同上记忆分页结构
- `PATCH /api/admin/bots/{id}/memories/{mid}` / `DELETE ...` → 管理员编辑/软删记忆（均留痕）
- `POST /api/admin/bots/{id}/memories/export` `{ "confirm": true }` → 导出 JSON（二次确认 + 审计）
- 用户侧 `GET /api/access-log` 可看到这些访问记录。
- `GET/PUT /api/admin/users/{id}/encryption`：GET 同用户状态；PUT 只允许 `{enabled:true}`（强制开启），关闭返回 403。

## 5.0 模型与定价 / 用量（管理员）

- `GET /api/admin/models?page=&page_size=&enabled=` → 分页模型目录（api_key 掩码 + has_api_key）
- `POST /api/admin/models` → 201（name/model 必填；价格 ≥0 点/1K tokens；base_url http(s)）
- `PATCH /api/admin/models/{id}` → 部分更新；`api_key:""` 或 `clear_api_key:true` 清空
- `DELETE /api/admin/models/{id}` → 软禁用（enabled=0，保留历史用量/定价）
- `POST /api/admin/models/{id}/test` → `{ok,status,latency_ms,model,base_url}`；失败 502 脱敏
- `POST /api/admin/usage` `{user_id,bot_id?,model_id,tokens_in,tokens_out,ref?,idem_key?}` → `{usage,points,idempotent,balance}`
  - `points = ceil(tokens_in/1000*in_price + tokens_out/1000*out_price)`；写 `usage_records` + `ledger(type=consume)`
    + 钱包余额 + `quotas.used_tokens`；幂等键重复不重复扣费；`billing.enforce_balance=true` 时余额不足 409。
- `GET /api/admin/usage?user_id=&page=&page_size=` → 分页用量 + `summary`（30 天）

## 5. 管理端（`role=admin`；否则 403）

### 模板

- `GET /api/admin/templates` → `{ "items": [Template] }`（含下架）
- `POST /api/admin/templates` → `201 { "template": Template }`
- `PATCH /api/admin/templates/{id}` → `200 { "template": Template }`
- `DELETE /api/admin/templates/{id}` → `200 { "deleted": true }`（软删：`enabled=false`）
- 创建/更新字段同 Template；`enabled` 默认 true；`user_overridable` 白名单。

校验：`name` 1–64，`base_conf_id` 必须存在于 AstrBot 配置文件列表（默认 `default`），
`config_patch`/`quota`/`memory_defaults`/`privacy_defaults` 必须是 JSON 对象；`begin_dialogs` 字符串数组。
新 Bot 创建时会克隆该 AstrBot 配置文件（模型、温度、上下文等），`config_patch` 仅做增量覆盖。

- `GET /api/admin/conf-profiles` → `{ "items": [ { "id", "name", "is_default" } ] }`（AstrBot 配置文件列表，模板编辑器用）

### 用户

- `GET /api/admin/users?page=1&page_size=20&q=&status=` →
  `{ "items": [ { "id", "email", "role", "status", "created_at", "bot_count", "encryption", "quota": {…}, "balance": 0 } ], "total": 0, "page": 1, "page_size": 20 }`
- `PATCH /api/admin/users/{id}` `{ "status": "active|disabled", "quota": {…} }`
  - 禁用立即撤销全部会话、停用其全部 Bot；写审计。
  - `200 { "user": { … } }`
- `POST /api/admin/invites` `{ "max_uses": 1, "ttl_hours": 72 }` → `201 { "invite": { "code": "明文一次性返回", "expires_at": 0, "max_uses": 1 } }`
- `GET /api/admin/invites` → `{ "items": [ { "code_hint", "max_uses", "used_count", "expires_at", "revoked_at", "created_at", "status" } ], ... }`
- `DELETE /api/admin/invites/{code_hint}` → 作废（也接受完整邀请码）
- `GET /api/admin/bots?page=&page_size=` → `{ "items": [ { …Bot, "owner_email": "…" } ], "total", "page", "page_size" }`
- `POST /api/admin/bots/{id}/disable` → `{ "bot": Bot }`
- `DELETE /api/admin/bots/{id}` `{ "confirm_name": "…" }` → `{ "deleted": true }`
- `GET /api/admin/overview` → 平台账本统计：
  `{ users, bots, ready_bots, balance_total, granted_points, adjusted_in_points, deducted_points, tokens_used, tokens_metered, paid_orders, paid_orders_amount_cny, balance_scope: "platform_points_ledger" }`
  - `balance_total` 是**平台内预付费点数合计**，不是上游模型账户余额（上游余额不查询、不展示）。
  - `tokens_metered` 表示是否已有记录到 `quotas.used_tokens` 的用量（M4 计量后可变为 true）。
- `GET /api/admin/audit?page=&action=&actor_id=&target_id=` → `{ "items": [AuditLog], "total": 0, "page", "page_size" }`

AuditLog：`{ "id": 1, "actor_id", "actor_role", "action", "target_type", "target_id", "reason", "detail", "ip", "created_at" }`

- `GET /api/admin/access-log` → 同分页结构（M3 前为空）
- `GET /api/admin/orders?page=&page_size=` → `{items:[{id,user_id,user_email,amount_cny,credits,source,external_ref,status,created_at,paid_at,operator}],total,page,page_size}`
- `POST /api/admin/orders` `{user_id, credits, amount_cny?, external_ref?, note?}` → 201 `{order, idempotent:false}`；重复 `external_ref` 返回 200 `{order,idempotent:true}`
- `POST /api/admin/orders/{id}/confirm` → `{order, already_paid:false|true}`（幂等；账本 `idem_key=order:{id}` 防重复入账）
- `POST /api/admin/ledger` `{user_id, delta(整数,可负), reason?, idem_key?}` → `{ledger, idempotent, balance}`（写 append-only 账本，不直接改余额）
- `POST /api/admin/users/{id}/wallet/reconcile` → `{user_id, balance}`（用账本重算并修复缓存余额）
- `GET /api/admin/users/{id}/encryption` → `{ "enabled": true, "state": "encrypted" }`
- `PUT /api/admin/users/{id}/encryption` `{ "enabled": true }` → 只允许开启；关闭 → 403 `forbidden`

## 6. 其他

- `GET /api/version` → `{ "version": "0.3.0", "build": "…" }`
- `GET /healthz` → `{ "ok": true }`
- 静态：`GET /console/*` → `web/dist`；找不到路径回退 `index.html`（history 路由）。
- `GET /` → 302 `/console/`。

## 7. 前端页面与 API 映射（M1 必须可用）

| 路由 | 页面 | 使用接口 |
|---|---|---|
| `/login` | OTP 登录 + 邀请码注册 | `otp/request`、`otp/verify`、`me` |
| `/` | 总览（Bot 数、余额、最近活动） | `me`、`bots`、`wallet` |
| `/bots` | Bot 列表 + 新建 | `bots`、`templates`、`POST bots` |
| `/bots/:id` | Bot 详情（启停、改名、删除、重新扫码） | `GET/PATCH/DELETE bots/{id}`、`qr/*` |
| `/connect` | 扫码接入向导（选平台→命名→生成二维码→状态机） | `templates`、`POST bots`、`qr/*` |
| `/settings/privacy` | 加密状态（M3 前只读展示） | `me/encryption` |
| `/billing`、`/access-log` | 只读列表（M1 空态） | `wallet`、`access-log` |
| `/admin/templates`、`/admin/users`、`/admin/bots`、`/admin/audit` | 管理端（M1 打通模板/用户/Bot/审计） | `/api/admin/*` |
| `/403` | 无权限 | — |
