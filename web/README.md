# AstrBot SaaS 控制台（web/）

M1 控制台前端：Vue 3.5 + Vite 6 + Vuetify 3.7 + Pinia + Vue Router 4（history，base `/console/`）+ TypeScript + dayjs + Vitest。

前后端唯一契约见 [`docs/API.md`](../docs/API.md)。本目录只消费 `/api`，不包含任何业务规则判断（权限、额度均以服务端为准）。

## 本地开发

```bash
cd web
npm install          # 首次
npm run dev          # http://127.0.0.1:5273/console/，/api 代理到 http://127.0.0.1:6180
```

浏览器打开 `http://127.0.0.1:5273/console/`。

- 管理员：`admin@example.com`（OTP 登录，无密码）。
- 新用户注册：邮箱 + 邀请码（如 `INV-EXTS-VMV1`）。
- 开发模式下 OTP 响应含 `dev_code`，登录页会以「开发环境验证码」展示。
- `/api/version` 返回 `dev_mode=true` 时，扫码页会显示「模拟已扫码 / 模拟确认登录 / 模拟过期」按钮（仅开发服务器）。

## 构建、测试、校验

```bash
npm run typecheck    # vue-tsc --noEmit
npm run test         # vitest run（jsdom）
npm run build        # 产物 web/dist/，由插件在 /console/ 静态托管
npm run preview      # 预览构建产物（无后端代理，需自行反代 /api）
```

## 目录

```
src/
├─ api/            client.ts（CSRF/错误归一化/重试/401/403）、auth/bots/wallet/privacy/admin/system/dev
├─ stores/         auth/bots/encryption/admin/ui
├─ router/         index.ts 路由表、guards.ts 登录/角色守卫（纯函数，可单测）
├─ layouts/        ConsoleLayout / AdminLayout / AuthLayout
├─ views/          auth/connect/bots/dashboard/settings/billing/access/admin/errors
├─ components/     QrPanel、EncryptionSwitch、ConfirmDialog、PageHeader、StatCard、StatusChip、
│                  EmptyState、LoadingSkeleton、AccessLogTable
├─ composables/    usePolling（页面隐藏暂停 / 可见补一次）、useClipboard、useAsync
├─ theme/          tokens.ts 设计 token、index.ts Vuetify 主题
├─ styles/         global.css
├─ utils/          format.ts / errors.ts
└─ types.ts        与 API.md 对齐的类型
```

## 约定

- 会话只靠 HttpOnly Cookie，前端不读写 token、不使用 localStorage 存会话。
- 写请求自动带 `X-CSRF-Token`（读取非 HttpOnly 的 `csrf` Cookie）；GET 失败重试 1 次，写请求不重试。
- 统一错误对象 `{ status, code, message, field? }`；401 清 store → `/login?redirect=...`，403 只 toast 不登出。
- 用户内容只做文本插值，不使用 `v-html`。
- 列表页均有加载骨架、空态、错误态（可重试）；管理端列表的筛选与分页保留在 URL query。
- 响应式：`<960px` 抽屉式侧栏，`<600px` 单列 / 卡片化。

## 契约缺口 / 待后端确认（2026-11-07）

1. **成功响应包络**：`docs/API.md` §0.1 写的是 `{ ok: true, data }`，但各接口示例（登录、列表等）直接返回裸对象。前端 `api/client.ts` 对两种形式都做了兼容（有 `ok:true` + `data` 时解包，否则按裸对象返回）。建议契约二选一并统一示例。
2. **OTP 限流 retry_after**：错误码表提到 `otp_rate_limited` 有 `retry_after` 秒，但错误包络只定义了 `{code,message,field}`。前端当前在 429 时回退到 60s 倒计时。
3. **加密切换**：API.md §4 只有 `GET /api/me/encryption`；§7.1 另有 `PUT /api/me/encryption`（`{enabled, confirm}` → 202 + job）与 job 查询，但未定义请求/响应、确认文案与错误码。M1 页面按要求只读：UI 已预留开关与「确认解密」二次确认，确认后仅提示 M3 开放，不发请求。
4. **重新扫码 / 解绑**：§4.2 要求「重新扫码：清旧凭据后重走 QR」，但契约没有解绑/重置接口；`POST /api/bots/{id}/qr/start` 对已绑定（`ready`）Bot 可能返回 `409 bot_state_invalid`。详情页会展示服务端错误并提示，不静默失败。
5. **管理端订单**：`POST /api/admin/orders` 与 confirm 在 M3 前返回 501；`/admin/orders` 仅有占位页。
6. **`GET /api/version` 的 `dev_mode`**：后端已实际返回，API.md §6 未记录；前端仅据此显示开发模式模拟按钮，生产不会调用 `/api/dev/*`。
7. **管理端配额编辑**：契约支持 `PATCH /api/admin/users/{id}` 的 `quota`，M1 需求只要求「配额查看」，故页面暂为只读查看。
8. **`/api/admin/access-log`**：契约存在，但 M1 页面清单未要求，暂未接入页面（用户侧 `/api/access-log` 已接入）。
