# AstrBot SaaS 控制台（web/）

M1 控制台前端：Vue 3.5 + Vite 6 + Vuetify 3.7 + Pinia + Vue Router 4（history，base `/console/`）+ TypeScript + dayjs + Vitest。

前后端唯一契约见 [`docs/API.md`](../docs/API.md)。本目录只消费 `/api`，不包含任何业务规则判断（权限、额度均以服务端为准）。

## 本地开发

```bash
cd web
npm install          # 首次
npm run dev          # http://127.0.0.1:5275/console/，/api 代理到 http://127.0.0.1:6180
```

浏览器打开 `http://127.0.0.1:5275/console/`。

- 管理员：`admin@example.com`（OTP 登录，无密码）。
- 新用户注册：邮箱 + 邀请码（如 `INV-EXTS-VMV1`）。
- 开发模式下 OTP 响应含 `dev_code`，登录页会以「开发环境验证码」展示。
- `/api/version` 返回 `dev_mode=true` 时，扫码接入页与 Bot 详情页会显示「模拟已扫码 / 模拟确认登录 / 模拟过期」按钮（仅开发服务器）。

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

## M2 记忆模块（`/bots/:id/memory`）

- 路由挂在 ConsoleLayout 下（requiresAuth），Bot 详情页有「记忆」入口。
- 列表：服务端分页 + 关键字 + kind + tag，筛选条件与 page 保留在 URL query；桌面表格、窄屏卡片。
- 支持编辑抽屉（content/kind/reasoning/importance/pinned/tags/metadata）、置顶切换、删除二次确认、FTS 检索预览、导出 JSON 快照。
- 无「新建」入口：记忆由对话中的 LLM 工具/命令写入；支持导入 JSON 快照（可 dry-run 预检），快照含记忆与笔记。
- 接口：`GET /api/bots/{id}/memories`、`GET/PATCH/DELETE .../memories/{mid}`、`POST .../search`、`POST .../export`、`POST .../import`（`{snapshot,dry_run}`）。
- 前端语义：PATCH 为部分字段更新；`tags`、`metadata` 全量替换；`importance` 服务端夹到 1–5；`kind` 仅 fact/preference/event/note。
- 新增文件：`views/memory/MemoryView.vue`、`api/memory.ts`、`stores/memory.ts`、`composables/useMemoryKindMeta.ts`、`utils/download.ts`、`stores/__tests__/memory.spec.ts`。

## UI/UX 反馈轮（M4 收尾）

- 头像/用户名菜单移到右上角：显示 display_name/邮箱、编辑用户名（`PATCH /api/me/profile`）、退出登录；管理员另有「管理后台 / 返回控制台」与「AstrBot 后台」（`GET /api/me.astrbot_dashboard_url`，新窗口打开）。
- 用户端侧栏：移除「扫码接入」「访问记录」；扫码接入入口在「我的 Bot」页头；访问记录卡片并入「隐私与加密」（`/access-log` 路由保留可直达）。
- 管理端侧栏按「运营管理 / 系统设置」分组；「记忆 API 设置」使用 `mdi-tune-variant` 图标。
- 管理端内容查看：加密租户返回 `403 confirmation_required` 时弹出确认；确认后所有对话/记忆读取、编辑、删除、导入、导出均带 `?confirm=1` 重试，并在顶部显示「该用户已开启加密，本次查看已记录」；取消则显示空态，不展示内容。
- 记忆快照：用户端与管理端抽屉均支持导入 JSON 快照（file input + dry_run）与快照格式导出。
- 视觉：主 CTA 统一 `variant="tonal" color="primary"`；页头按钮 40px/14px/图标 18；管理端表格设置 `min-width` + 横向滚动 + 表头 nowrap；总览移除 Bot 配额圆环、消耗图占满整行；模板编辑器移除重复的 persona_prompt 输入；暗色补齐输入占位符/提示对比度。

## M3 手动额度与账本（管理端 `/admin/orders`、用户端 `/billing`）

- 管理端「手动充值」：订单列表（状态 chip、金额/点数、用户邮箱、创建/到账时间，分页保留在 URL）；新建充值单（用户下拉来自 `/api/admin/users`，credits 必填正整数、金额可选、外部单号防重）；待确认订单「确认到账」二次确认；「手动加/扣额度」对话框（正负 delta、原因、可选幂等键）；成功刷新列表并 toast；加载骨架/空态/错误重试。
- 幂等：重复 `external_ref` 返回已有订单（idempotent=true，不重复创建）；重复确认返回 already_paid（不重复入账）；相同 `idem_key` 的加/扣只入账一次；页面按服务端返回给出明确提示。
- 用户端「额度」：余额 + append-only 流水（时间/变动/类型/说明/关联），服务端分页，展示后端返回的账本重算余额；只读。
- 新增/修改：`api/admin.ts`（orders/ledger/reconcile）、`stores/admin.ts`（orders）、`utils/walletAdmin.ts`（表单校验与 payload）、`views/admin/OrdersView.vue`、`views/billing/BillingView.vue`、`stores/__tests__/adminOrders.spec.ts`。
- 余额永远以账本为准；前端不做任何本地加减，成功与否以服务端返回的 balance 为准。

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
3. **加密切换**：API.md §4 只列了 `GET /api/me/encryption`；后端已实现 `PUT /api/me/encryption` 与 job 轮询，前端按实现接入（确认解密 + 进度/重试）。
4. **重新扫码 / 解绑**：§4.2 要求「重新扫码：清旧凭据后重走 QR」，但契约没有解绑/重置接口；`POST /api/bots/{id}/qr/start` 对已绑定（`ready`）Bot 可能返回 `409 bot_state_invalid`。详情页会展示服务端错误并提示，不静默失败。
5. **管理端订单**：已接入真实创建/确认/账本调整与幂等返回（见 M3 章节）。
6. **`GET /api/version` 的 `dev_mode`**：后端已实际返回，API.md §6 未记录；前端仅据此显示开发模式模拟按钮，生产不会调用 `/api/dev/*`。
7. **管理端配额编辑**：契约支持 `PATCH /api/admin/users/{id}` 的 `quota`，M1 需求只要求「配额查看」，故页面暂为只读查看。
8. **访问记录**：用户侧 `/api/access-log` 并入「隐私与加密」卡片；管理端 `/api/admin/access-log` 仍未单独做页面。
9. **M2 记忆接口尚未写入 `docs/API.md`**：字段与语义来自 lead 说明及后端实现；前端已按 `{items,total,page,page_size}`、`kind_label` 等实现。
10. **`tag` 筛选的 total 计数（已修复）**：后端 `count()` 已带 tag 条件，`GET /memories?tag=杭州` 现在返回 `items=1, total=1`；前端恢复展示「共 N 条 · 标签：X」。
11. **记忆导入/导出**：已改为快照格式（`{memories,notes,tags,...}`），导入支持 `{snapshot,dry_run}`；管理端加密租户导入需 `confirm=1`。旧 CLI 迁移仅作离线路径保留。
12. **M3 额度接口尚未写入 `docs/API.md`**：字段来自 lead 说明与后端实测。`GET /api/wallet` 的 `ledger_total` 实际是「账本重算余额」（`recompute_balance`），不是流水条数，前端按对账余额展示。
13. **订单创建/确认响应不带 `user_email`**：列表查询才 JOIN 用户邮箱；前端在创建/确认成功后重新拉取当前页，保证邮箱列完整。
14. **账本流水字段**：后端返回 `{id,delta,type,ref,note,created_at}`（无 `balance_after`）；用户端流水表已按真实字段渲染。订单无取消/删除接口，页面只提供创建与确认；对账接口（reconcile）已封装但页面未暴露按钮。

15. **新增账户/内容字段需后端最新版本**：`user.display_name`、`/api/me.astrbot_dashboard_url`、`PATCH /api/me/profile`、`403 confirmation_required` 与记忆快照导入均为本轮后端新增；若运行中的 dev server 未重启，页面会回退显示邮箱前缀并隐藏 AstrBot 后台入口，编辑用户名会提示接口不存在。
