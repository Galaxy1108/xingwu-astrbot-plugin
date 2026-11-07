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

## 兑换码 / 用户详情（本轮增量）

- 用户 `/billing`：保留剩余点数与消耗图；新增兑换码卡片（`POST /api/me/redeem {code}`，成功刷新余额/流水，错误码 already_redeemed/expired/invalid 分别提示）；支付方式仅展示支付宝/微信/银行卡「暂不支持」，不提供支付按钮。
- 管理端 `/admin/redemption-codes`（侧栏「兑换码」）：生成表单（点数/备注/数量/单码可用次数/有效期）、生成后可逐条/全部复制、列表分页、状态与禁用；旧 `/admin/orders` 路由保留但不在主导航。
- 管理端用户表格支持行点击或「详情」打开右侧抽屉：基础信息、余额、可编辑配额、名下 Bot、近 30 天用量（`GET /api/admin/users/{id}/usage?page=`）、最近流水（若详情响应携带）。配额保存走 `PATCH /api/admin/users/{id}` 的嵌套 `{quota:{...}}`。
- 图表改为按容器实际宽度渲染 viewBox，轴/日期字号 9px；Bot 下拉过滤空 bot_id；菜单/弹窗/tab 样式统一（菜单 surface、选中浅主色；ConfirmDialog surface/12px/18px 标题/柔和 danger；内容抽屉 tab 40px 紧凑 pill）。
- 订单创建弹窗移除金额字段，payload 不再传 amount_cny。

## Bot 共享 tab / inline 设置（本轮增量）

- 新增 `BotTabs.vue`：概览 / 对话历史 / 记忆 / 笔记 / 设置，40px，选中 pill + 下划线；BotDetail、Conversations、Memory、Notes 顶部统一渲染，切换后 tab 始终保留。设置通过 `/bots/:id?tab=settings` 打开。
- Bot 设置改为详情页 inline tab（不再弹窗）：基础设置（名称、模型配置、启用平台实例、流式输出 streaming）与默认收起的高级设置（compression_max_turns 1–100、truncate_by_turns / llm_compress + 解释文案）；统一保存 `PATCH /api/bots/{id}`，payload 带 `settings`。
- `Bot.settings` 类型：`{streaming, compression_max_turns, compression_overflow_strategy}`；缺省按 false/10/truncate_by_turns 兜底。
- 「添加机器人」模板选择下增加文案：创建时复制模板配置，之后可在 Bot 设置调整，不影响模板本身。
- 微信平台统一为「微信（官方机器人）」及「通过微信官方机器人接口接入，扫码后在手机确认」。

## 账号体系（本轮增量）

- 登录页：验证码登录 / 密码登录双 tab；密码登录 `POST /api/auth/password/login`，错误码 `invalid_credentials/password_not_set` 映射中文；封禁用户统一跳 `/banned`。OTP 流程与 dev_code 保留。
- 注册：主注册改为无邮箱密码注册（邀请码、3–32 用户名、可选昵称、6–128 密码+确认），`POST /api/auth/password/register`；显著警告「不绑定邮箱将无法找回密码；注册后可在账户设置绑定邮箱」，Alpha 提示保留。另提供「邮箱验证码注册」入口复用 OTP 注册。
- 忘记密码：对话框两步（邮箱 → 验证码+新密码），`POST /api/auth/password/reset/request|reset`，通用成功文案 + dev_code。
- 第三方登录：`GET /api/auth/oauth/providers` 仅展示 enabled 项；start 取 `authorize_url` 后同窗口跳转；新增 `/oauth/callback`（实际 `/console/oauth/callback`）读取 `ok/next/error`，刷新 `/api/me` 后跳转，错误中文提示。
- 账户设置 `/settings/account`：基本信息（昵称/用户名 PATCH `/api/me/profile`，username 冲突映射）、修改/设置密码（`POST /api/me/password`，已有密码需当前密码）、绑定邮箱（请求/验证码/绑定，已验证展示邮箱+徽标）、第三方账号（列表/绑定 start mode=bind/解绑，未启用显示「未启用」）。侧栏与 UserMenu 均加入口。
- `/api/me/user` 新字段 username/email_verified/has_password/recovery_available 已接入；页面适配 light/dark、1200/390。

## Bot 详情菜单化 / 记忆 6 级 / 运行状态（本轮增量）

- Bot 详情改为 AstrBot 式 40px 顶部 tab：概览 / 对话历史 / 记忆 / 笔记 / 设置（设置打开原弹窗），刷新改为右侧图标；保留按钮可访问名与 data-testid。
- ConsoleLayout/AdminLayout 主内容加 `.content-shell`（8px 顶部间距 + 12px 左上圆角 + 主题边框）；字体栈切换为 AstrBot/Outfit 组合，正文 14/1.55，表格与数字启用 tabular-nums。
- UsageChart tooltip 跟随数据点：left/top 由 x/y 计算，左右 110px clamp，顶部空间不足翻到点下方，不溢出容器。
- 记忆重要度新增 6「总是注入」；MemoryView 列表/卡片/编辑、管理端内容抽屉编辑与展示均支持；自动提取记忆显示「自动提取」标签；记忆页顶部说明 6 级注入语义。
- 记忆页新增「重要度」筛选并写入 URL query；GET 查询会带 `importance`（后端目前未消费该参数，见契约差异）。
- 记忆 API 设置新增「运行状态」卡片：`GET /api/admin/settings/memory/status`，展示向量化/重排（正常/降级/未配置）、最近测试/错误、FTS 可用与模式；降级红条提示「检索已回退 FTS + 规则重排」。
- behavior 新增 `auto_inject` / `auto_extract` 开关（默认开）与隐私影响说明，PUT 同一接口保存。

## 添加机器人 / 对话分享 / 公开分享（本轮增量）

- 按用户最新要求：扫码接入不弹窗，恢复「添加机器人」内联页面 `/connect`；但改用 `POST /api/qr/sessions` 的扫码会话，**扫码成功前不创建 Bot**，中途取消/离开会 DELETE 会话，不会留下未配置 Bot。步骤：平台 + 名称 + 模板 → 内联二维码轮询（2s）→ finalize → 成功页跳 Bot 详情。
- 「我的 Bot」页头/空态入口改为「添加机器人」；Bot 详情不再有二维码区块与重复设置/笔记按钮，仅保留页头「对话历史 / 记忆 / 笔记 / 设置」。
- 对话历史 `/bots/:id/conversations`：列表（标题/消息数/时间/分页）、详情气泡、创建/复制/撤销只读分享链接（`POST/DELETE …/share`）；公开页 `/share/:token`（实现于 SPA base，实际 `/console/share/:token`）无需登录，展示消息与过期态，底部「星坞 Alpha」。
- 管理端侧栏品牌改为「星坞」+「管理」chip，不再换行；登录/侧栏 Alpha 文案保留，旧 SaaS 文案已清理。
- `ConfirmDialog`/`ReasonDialog` 深色继承、受控弹窗样式沿用上一轮（18px 标题/13px 正文/柔和 danger）。

## 封禁 / 申诉 / 笔记 / Bot 设置（本轮增量）

- 封禁：`/api/me` 读取 `status_reason`/`status_changed_at`/`pending_appeal`；`/banned` 通知页展示原因、时间、余额提醒、申诉表单与历史；守卫允许被封禁用户停留 `/banned`、`/login`，其他路由回 `/banned`。管理端「用户管理」封禁必须填写原因，表格显示原因与「有申诉」徽标。
- 管理端「申诉处理」`/admin/appeals`：按状态筛选，通过/拒绝可填管理员备注；侧栏入口 `mdi-gavel`。
- Bot 管理停用：`PATCH /api/admin/bots/{id} {disabled:true,reason}`（404 时回退旧 POST `/disable`）；`ReasonDialog` 必填原因。用户 Bot 详情展示「被管理员停用：原因」，禁用开关并提供「申请启用」。
- Bot 设置弹窗：名称、模型配置（`GET /api/models`）、启用开关、重新扫码绑定；`PATCH /api/bots/{id}` 支持 `model_profile_id`。扫码区域只在 `pending_qr`、已有会话或用户点重新扫码时显示。
- 笔记：用户 `/bots/:id/notes`（列表/搜索/新建/查看分页正文/删除）与 Bot 详情「笔记」入口；管理端内容抽屉新增「笔记」tab（列表/查看/删除，加密租户走 confirm=1 确认）。
- 弹窗：`ConfirmDialog` 与新增 `ReasonDialog` 全部使用 `--console-surface/text/border` 变量；`html[data-theme='dark']` 同步定义变量，Teleport 到 body 的弹窗在暗色下也继承；标题 18、正文 13、按钮 40、圆角 8/12、取消 ghost、危险柔和红。
- 兑换码日期字段改为「有效期」+「留空永久有效」；用户详情配额说明去掉 API 路径；My Bots 空态只保留「扫码接入」。

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

16. **兑换码接口（本轮后端并行新增）**：前端按 `GET/POST /api/admin/redemption-codes`、`POST /api/me/redeem` 实现；禁用接口未在契约中给出，前端先尝试 `POST /api/admin/redemption-codes/{code}/disable`，404 时回退 `DELETE /api/admin/redemption-codes/{code}`。生成有效期按本地日期 23:59:59 转为 Unix 秒提交；若后端采用 ISO 字符串需调整。接口未就绪时页面显示“尚未就绪”并可重试。
17. **用户详情接口**：前端按 `GET /api/admin/users/{id}` 与 `GET /api/admin/users/{id}/usage?page=` 实现；usage 兼容 `{items|by_bot,summary,total,page,page_size}` 形态；“最近流水”暂从详情响应的 `recent_ledger`/`ledger` 读取（接口未单列）。

18. **封禁/申诉/笔记接口（本轮后端并行）**：运行时 6180 已支持用户详情 `GET /api/admin/users/{id}`（含 bots/recent_ledger）与用量，但 `/api/admin/appeals`、`/api/me/appeals`、`/api/admin/bots/{id}/notes` 仍返回 404；被禁用用户 OTP 请求当前返回 403（契约要求可登录），因此封禁通知页真机验证使用前端 store 注入截图，后端就绪后需复测。字段 `status_reason`/`status_changed_at`/`pending_appeal`、`admin_disabled`/`admin_disabled_reason` 以接口返回为准。
19. **Bot 停用接口**：契约 `PATCH /api/admin/bots/{id} {disabled:true,reason}`；旧实现 `POST /api/admin/bots/{id}/disable` 作为 404/405 回退，原因在回退路径下不会传递。
20. **笔记接口**：用户侧 `/api/bots/{id}/notes` 已可验证；管理端笔记路由当前 404，UI 显示“管理端笔记接口尚未就绪”。管理端笔记读/删均带 `confirm=1` 以兼容加密租户。
21. **封禁用户登录**：前端已按契约处理（登录成功后若 status=disabled → `/banned`），但后端当前在 OTP 请求阶段返回 403，需后端放开后才能端到端验证。

22. **扫码会话接口**：`/api/qr/sessions`、`/poll`、`/finalize`、`DELETE` 当前 6180 尚未就绪（404）。前端 404 显示“添加机器人功能暂未开放”，且绝不调用旧 `POST /bots`，因此未扫码退出不会产生 Bot。
23. **对话/分享/公开分享接口**：`/api/bots/{id}/conversations`、`…/{cid}/share`、`/api/public/conversations/{token}` 当前未就绪（404/401）；前端对 404 显示“接口尚未就绪”，公开页对 404/410 显示“分享已过期”。截图中的对话/分享/公开页使用临时 API mock 验证视觉，后端就绪后需重跑真机。
24. **公开分享 URL 与 base**：控制台 history base 为 `/console/`，因此 SPA 实际路径为 `/console/share/:token`；若后端返回 `/share/:token`，需要后端 302 到 `/console/share/...` 或反代重写。
25. **封禁/申诉/管理端笔记** 仍为上一轮遗留：运行中后端 `/api/admin/appeals`、`/api/me/appeals`、`/api/admin/bots/{id}/notes` 404，被禁用用户 OTP 请求 403；UI 已实现并友好降级。

26. **记忆重要度筛选**：M2 `GET /api/bots/{id}/memories` 目前只接收 kind/tag/q，尚未消费 `importance`；前端已加筛选并带参，后端补齐后即可服务端过滤（否则当前筛选不会改变结果）。
27. **记忆运行状态**：`GET /api/admin/settings/memory/status` 现已可用，真实字段为 `state/configured/enabled/model/last_ok/last_checked/last_error/latency_ms`，前端已兼容；截图中的「降级」状态为 Playwright mock（真实环境当前为 unconfigured），用于验证降级红条。
28. **behavior 自动提取/注入**：运行中后端已支持 `auto_inject/auto_extract`；默认 true。

29. **账号契约**：后端已就绪（280 pytest）。密码注册/登录返回用户+cookie；OAuth start login/register 可匿名，bind 需已登录；回调 302 到 `/console/oauth/callback`。当前环境 `GET /api/auth/oauth/providers` 返回 GitHub `enabled:false`，登录页 GitHub 按钮截图使用 Playwright mock，账号页真实显示「未启用」。
30. **封禁登录截图**：当前没有可用的“有密码且被封禁”测试账号；密码登录→`/banned` 的截图使用临时 API mock 验证，代码路径为登录成功后 `user.status=disabled` 即 replace `/banned`。
31. **邮箱验证码注册**：保留原 OTP 路径，入口在注册页与登录 OTP tab；无邮箱注册不写占位邮箱，`/api/me` 邮箱为空串。

32. **Bot settings 契约**：后端 `PATCH /api/bots/{id}` 已支持 `settings.streaming/compression_max_turns/compression_overflow_strategy`；当前运行中的 Bot 详情响应尚未返回 settings 时，前端按默认值展示，保存后以后端返回为准。
33. **Bot 设置**：旧 dialog 已移除；设置 tab 为 inline 内容，删除/启停危险操作仍在概览页。
