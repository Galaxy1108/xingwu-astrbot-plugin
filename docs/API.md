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
| `otp_rate_limited` | 429 | 60s 内重复请求 OTP（`retry_after` 秒） |
| `otp_invalid` | 401 | 验证码错误 / 已使用 / 过期（不区分，防枚举） |
| `otp_attempts_exceeded` | 429 | 校验次数超限，需重新获取 |
| `template_disabled` | 409 | 模板已下架，不能新建 Bot |
| `quota_exceeded` | 409 | Bot 数量超配额 |
| `bot_state_invalid` | 409 | 当前 Bot 状态不允许该操作 |
| `qr_session_exists` | 409 | 同一 Bot 已有扫码会话 |
| `qr_expired` | 410 | 扫码会话已过期/刷新超限 |
| `qr_not_ready` | 409 | 尚未扫码成功，不能 finalize |
| `conflict` | 409 | 其他并发冲突 |
| `internal_error` | 500 | 服务端错误（不泄露堆栈） |

## 1. 认证

### POST /api/auth/otp/request

```json
{ "email": "a@b.com", "invite": "可选，仅新用户注册时必填" }
```

响应 `200`：

```json
{ "sent": true, "resend_after": 60, "dev_code": "123456（仅开发开关打开时出现）" }
```

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
  "version": "0.1.0"
}
```

未登录 → 401。

## 2. 模板（用户可见）

### GET /api/templates

只返回 `enabled=true` 的模板（快照来源），按更新时间倒序。`200 { "items": [Template] }`。

```json
{
  "id": "t_...", "name": "默认陪伴", "description": "…",
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

## 4. 额度 / 访问记录（本期只读，M1 返回空数据）

- `GET /api/wallet` → `{ "balance": 0, "currency": "points" }`
- `GET /api/wallet/ledger?page=1` → `{ "items": [], "total": 0, "page": 1, "page_size": 20 }`
- `GET /api/access-log?page=1` → `{ "items": [], "total": 0, "page": 1, "page_size": 20 }`
- `GET /api/me/encryption` → `{ "enabled": true, "state": "encrypted", "done": 0, "total": 0, "eta": null }`

## 5. 管理端（`role=admin`；否则 403）

### 模板

- `GET /api/admin/templates` → `{ "items": [Template] }`（含下架）
- `POST /api/admin/templates` → `201 { "template": Template }`
- `PATCH /api/admin/templates/{id}` → `200 { "template": Template }`
- `DELETE /api/admin/templates/{id}` → `200 { "deleted": true }`（软删：`enabled=false`）
- 创建/更新字段同 Template；`enabled` 默认 true；`user_overridable` 白名单。

校验：`name` 1–64，`config_patch`/`quota`/`memory_defaults`/`privacy_defaults` 必须是 JSON 对象；`begin_dialogs` 字符串数组。

### 用户

- `GET /api/admin/users?page=1&page_size=20&q=&status=` →
  `{ "items": [ { "id", "email", "role", "status", "created_at", "bot_count", "encryption", "quota": {…}, "balance": 0 } ], "total": 0, "page": 1, "page_size": 20 }`
- `PATCH /api/admin/users/{id}` `{ "status": "active|disabled", "quota": {…} }`
  - 禁用立即撤销全部会话、停用其全部 Bot；写审计。
  - `200 { "user": { … } }`
- `POST /api/admin/invites` `{ "max_uses": 1, "ttl_hours": 72 }` → `201 { "invite": { "code": "明文一次性返回", "expires_at": 0, "max_uses": 1 } }`
- `GET /api/admin/invites` → `{ "items": [ { "code_prefix", "max_uses", "used_count", "expires_at", "revoked_at", "created_at" } ] }`
- `DELETE /api/admin/invites/{code_prefix}` → 作废
- `GET /api/admin/bots` → 全部 Bot `{ "items": [ { …Bot, "owner_email": "…" } ] }`
- `POST /api/admin/bots/{id}/disable` → `{ "bot": Bot }`
- `DELETE /api/admin/bots/{id}` `{ "confirm_name": "…" }` → `{ "deleted": true }`
- `GET /api/admin/audit?page=&action=&actor_id=&target_id=` → `{ "items": [AuditLog], "total": 0, "page", "page_size" }`

AuditLog：`{ "id": 1, "actor_id", "actor_role", "action", "target_type", "target_id", "reason", "detail", "ip", "created_at" }`

- `GET /api/admin/access-log` → 同分页结构（M3 前为空）
- `POST /api/admin/orders` / `POST /api/admin/orders/{id}/confirm` → M3 前返回 501 `not_implemented`
- `GET /api/admin/users/{id}/encryption` → `{ "enabled": true, "state": "encrypted" }`
- `PUT /api/admin/users/{id}/encryption` `{ "enabled": true }` → 只允许开启；关闭 → 403 `forbidden`

## 6. 其他

- `GET /api/version` → `{ "version": "0.1.0", "build": "…" }`
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
