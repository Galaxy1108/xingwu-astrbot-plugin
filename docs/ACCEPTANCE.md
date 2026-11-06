# M1 独立验收报告（QA）

> 角色：独立验收/QA（不修改 `saas/`、`main.py`、`web/`、`scripts/`）。
> 被测提交：`69b965c`（fix(qr): finalize catches up scan state; fix(web): 403 home action is a real link; docs(api) 澄清）。
> 验收时间：2026-11-07 00:45–01:10（Asia/Shanghai）。
> 结论：**PASS**。API 验收 **25/25 PASS**；浏览器 E2E **9/9 PASS**；无未修复的 FAIL 项。

---

## 1. 环境与前置

| 项 | 值 |
|---|---|
| 控制台 / API | `http://127.0.0.1:6180`（独立 dev server，`SAAS_DEV_MODE=true`） |
| 后端替身 | `FakeAstrBot`（内存态，可注入失败）+ 每 Bot SQLCipher 记忆库 |
| 数据目录 | `devdata/`（`saas.sqlite3`、`memory/`、`keys/root_kek.bin`） |
| 管理员 | `admin@example.com`（OTP 无密码；dev 模式响应含 `data.dev_code`） |
| 前端 | `web/dist/`（由 dev server 托管于 `/console/`，history 路由） |
| 浏览器 | `/usr/bin/chromium` + Playwright `1.65.0`（`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` 安装，未下载浏览器） |
| Python（后端/注入服务器） | `/home/int_256t/Documents/Projects/AstrBot/.venv/bin/python` |

说明：

- 邀请码一律通过管理端 `POST /api/admin/invites` 现建（`max_uses` 按用例取 1），不依赖固定码 `INV-EXTS-VMV1` 的剩余次数，因此可重复执行。
- 管理端 OTP 受 60s 重发限流；API 脚本把管理员会话缓存在 `tests/e2e/artifacts/admin_session.json`，缓存有效时直接复用，失效才重新 OTP 登录（遇到 429 会按 `retry_after` 等待重试）。浏览器 E2E 的管理端页面用例**不复用**该缓存：`admin.spec.ts` 内先做一次真实 UI OTP 登录，同一文件后续用例复用这次登录的 storageState。
- 并行跑 E2E 时用 `E2E_RUN_ID=<id>` 隔离 Playwright 产物目录（默认 `latest`），避免互相清理 trace。

### 复现命令

```bash
# 0) 前提：dev server 已启动（端口 6180，devdata 数据目录）
/home/int_256t/Documents/Projects/AstrBot/.venv/bin/python scripts/dev_server.py --data-dir devdata --port 6180

# 1) 纯 API 验收（A/B/C/D/F，约 1s）
cd /home/int_256t/Documents/Projects/astrbot-saas-plugin
/home/int_256t/Documents/Projects/AstrBot/.venv/bin/python tests/e2e/api_acceptance.py
# 退出码 0 = 全部 PASS；JSON 证据：tests/e2e/artifacts/api_acceptance_report.json

# 2) 浏览器 E2E（D 前端部分 + E + F 页面，约 11s）
cd tests/e2e
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install   # 首次
E2E_RUN_ID=qa npx playwright test
# HTML 报告：tests/e2e/artifacts/playwright-report-qa/
# 截图：tests/e2e/artifacts/screenshots/（artifacts 已 gitignore）
```

---

## 2. 结果总览

| 验收点 | 要求 | 结果 | 证据 |
|---|---|---|---|
| A 邀请码一次性 | 第二次注册 410 `invite_exhausted`；并发仅一个成功 | **PASS** | API `A1/A2/A3`；JSON 报告 |
| B 创建失败可回滚 | DB/人格/配置/路由/平台/记忆库均无残留 | **PASS** | API `B1–B5`；`B5` 为注入中段失败的真实回滚证据 |
| C 扫码 60s 过期、刷新 ≤3 | 前三次 pending 自动刷新，第 4 次 expired；可重新 start | **PASS** | API `C1–C7`（`C4` 为 `expire×4`） |
| D 前端 401/403 | 未登录跳登录、普通用户到 403、禁用后 401 跳登录、CSRF 缺失 403 | **PASS** | API `D1–D5` + Playwright `auth.spec.ts` 4 条 |
| E 完整用户旅程 | 登录→建 Bot→扫码→ready→改名→启停→删除→审计 | **PASS** | Playwright `journey.spec.ts` + 截图 01–05 |
| F 管理端 | 用户/Bot/审计列表可见；管理员不能关闭加密 | **PASS** | API `F1–F4` + Playwright `admin.spec.ts` + 截图 10–13 |
| 回归基线 | 后端 47 个 pytest（由后端维护者负责，本轮不重复执行） | 未重复 | 按任务要求“不要重复单测” |

汇总：

- **API 验收：25 PASS / 0 FAIL / 0 SKIP**（`SUMMARY: 25 PASS / 0 FAIL / 0 SKIP`）。
- **浏览器 E2E：9 passed (10.7s)**，0 failed。
- 测试数据清理：Bot 均在用例内删除（含记忆库 + WAL/SHM），配额恢复为 3，被禁用用户已恢复 active；仅保留 QA 用户/审计记录，以及一个故意下架的 QA 模板（用于 B3）。

---

## 3. 逐条验收记录

### A. 邀请码一次性（FR-A）

| # | 用例 | 命令/操作 | 期望 | 实际 | 结果 |
|---|---|---|---|---|---|
| A0 | 管理员 OTP 登录 | `POST /api/auth/otp/request` → `POST /api/auth/otp/verify` → `GET /api/me` | 200；role=admin；下发 csrf | 200；`role=admin`；`csrf` Cookie 存在 | PASS |
| A1 | 同一一次性邀请码第二次注册 | 管理端建 `max_uses=1` 邀请码 → 邮箱1 注册成功 → 邮箱2 用同码请求 OTP | 第二次 `410 invite_exhausted` | `410 invite_exhausted`；DB `used_count=1` | PASS |
| A2 | 并发使用同一邀请码 | 两个邮箱先各自取 OTP（校验邀请码但不消耗）→ 双线程同时 `verify` | 恰好一个 200、一个 410；仅 1 个用户；`used_count=1` | `[200, 410]`；失败方 `invite_exhausted`；用户数 1；`used_count=1` | PASS |
| A3 | OTP 重放 | 用已成功的同一邮箱 + 同一验证码再次 `verify` | `401 otp_invalid` | `401 otp_invalid` | PASS |

证据：`api_acceptance_report.json` 中 `A1/A2/A3` 条目；A2 使用 `threading.Barrier(2)` 保证同时发出。

### B. 创建 Bot 失败可回滚（FR-D）

所有失败用例在失败后都检查：该用户名下 Bot 数仍为 0、DB 无同名 bot 行、`devdata/memory/` 文件集合与失败前一致。

| # | 失败构造 | 期望 | 实际 | 结果 |
|---|---|---|---|---|
| B1 | `platform=telegram`（非法平台） | `400 validation_error`，`field=platform`，无残留 | 400 / `field=platform`；无 bot 行、memory 无新增 | PASS |
| B2 | 名称空串 / 33 字符 | `400 validation_error`，`field=name`，无残留 | 400 / `field=name`；无残留 | PASS |
| B3 | 管理员新建模板后 `DELETE`（软下架），再用该模板建 Bot | `409 template_disabled`，无残留 | 409 / `template_disabled`；无残留 | PASS |
| B4 | 管理员把用户 `quota.max_bots` 置 0 后建 Bot | `409 quota_exceeded`，无残留 | 409 / `quota_exceeded`；无残留；用例结束恢复配额 3 | PASS |
| B5 | **中段失败全量回滚**（关键证据） | 500 `internal_error`；人格/配置/路由/平台/记忆库/DB 行全部回滚 | 见下 | PASS |

B5 实现（`tests/e2e/rollback_harness.py`，测试专用，不改生产代码）：用真实 `Container + create_app + FakeAstrBot(fail_on=…)` 起一个临时服务器（临时数据目录、独立端口），分别注入 `create_persona` / `create_config` / `bind_route` / `create_platform` 四个步骤失败，再调 `POST /api/bots`：

- 四次均返回 `500 internal_error`；
- 每次失败后通过 `/__test__/state` 断言：`bots=[]`、`bindings=[]`、`memory=[]`、`personas=[]`、`configs=[]`、`routes={}`、`platforms=[]`；
- 对照组：关闭注入后创建成功（1 行 bot + 1 个记忆库文件），删除后再次全部清空。

其中 `create_platform` 失败时记忆库已创建，验证了“删记忆库文件”这一步；`bind_route`/`create_config` 失败验证了人格/配置/路由的回滚顺序。

### C. 扫码接入：60s 过期、刷新 ≤3（FR-B）

| # | 用例 | 期望 | 实际 | 结果 |
|---|---|---|---|---|
| C1 | `POST /api/bots`（weixin_oc） | 201，`status=pending_qr`，`memory_db=memory/<bot_id>.db`，文件已生成 | 一致 | PASS |
| C2 | `POST /api/bots/{id}/qr/start` | `pending`、`refresh_count=0`、`interval=2`、TTL≈60s、`qr_image` 为 PNG data URL | TTL=60s，其余一致 | PASS |
| C3 | 未过期时再次 `qr/start` | `409 qr_session_exists` | 409 / `qr_session_exists` | PASS |
| C4 | 连续 4 次 `POST /api/dev/qr/{id}/expire` + `GET …/qr/poll` | 前三次 `pending` 且 `refresh_count` 1/2/3；第 4 次 `expired` 且 `refresh_count=4`；之后保持 expired | 状态序列 `pending,pending,pending,expired`；计数 `1,2,3,4`；第 5 次仍 expired | PASS |
| C5 | 过期后重新 `start`；未扫码 `finalize`；扫码 → created → `finalize` | 重新 start=200；提前 finalize=`409 qr_not_ready`；最终 `status=ready`、`enabled=true`、`bound=true`、`bot_bindings` 有凭据 | 全部一致 | PASS |
| C6 | 删除 Bot：错误名称 / 正确名称 | 错误名 `400 field=confirm_name`；正确名 200；DB 行、绑定、记忆库 `.db`/`-wal`/`-shm`、列表全部清理 | 一致 | PASS |
| C7 | 待扫码 Bot 直接删除（取消） | 200；记忆库文件与会话无残留 | 一致 | PASS |

说明：dev server 无法控制时钟，C4 用 dev-only `POST /api/dev/qr/{id}/expire` 把 `expires_at` 置为过去再 poll，等价于“第 N 次 60s 自然过期”。真实 60s 自然等待未做（见 §5）。

### D. 401 / 403 / CSRF（API 级 + 浏览器）

| # | 用例 | 期望 | 实际 | 结果 |
|---|---|---|---|---|
| D1 | 匿名 `GET /api/bots`、`/api/me`、`POST /api/bots` | 401 `unauthorized` | 一致 | PASS |
| D2 | 已登录写请求不带 `X-CSRF-Token` | 403 `csrf_invalid` | 一致 | PASS |
| D3 | 错误 `X-CSRF-Token` | 403 `csrf_invalid` | 一致 | PASS |
| D4 | 普通用户 `GET /api/admin/users`、`/api/admin/audit` | 403 `forbidden` | 一致 | PASS |
| D5 | 管理员 `PATCH /api/admin/users/{id} {"status":"disabled"}` 后，用户立刻请求 | 会话立即失效（`/api/me`、`/api/bots` 均 401）；其 ready Bot 变 `disabled` | 一致 | PASS |
| D6 | 浏览器：未登录访问 `/console/bots` | 跳 `/console/login?redirect=/bots` | URL 含 `redirect=/bots`；登录页可见；`localStorage` 为空 | PASS |
| D7 | 浏览器：普通用户访问 `/console/admin/users` | 到 `/console/403`（不静默回首页），仍保持登录 | URL `/console/403`；`403 · 无权限` 可见；`返回总览` 链接可见 | PASS |
| D8 | 浏览器：会话被禁用后触发下一次 API | 401 → 清 store → 跳登录 | 整页 reload 后自动到 `/console/login`；`localStorage` 为空 | PASS |

### E. 完整用户旅程（浏览器，`journey.spec.ts`）

单条用例串起全流程（每个断言失败都会截图 + trace）：

1. **登录/注册**：登录页填邮箱 + 邀请码 → `发送验证码` → 页面提示“开发环境验证码：xxxxxx” → 填 6 位码 → `验证并登录` → 进入 `/console/`。
2. **我的 Bot**：侧栏进入 `/console/bots`，空态“还没有 Bot”。
3. **新建**：`新建 Bot` → 填名称、平台默认“微信（个人号 · 官方接口）”、模板默认“默认陪伴” → `创建` → 跳 `/console/bots/<id>?qr=1`。
4. **扫码页**：自动生成二维码（PNG，倒计时 60s，状态“等待扫码”）；`POST /api/dev/qr/{id}/scanned` 后 API poll 确认 `scanned`；`POST …/confirm` 后前端 2s 轮询到 `created` 并自动 `finalize` → 状态“运行中 / 已绑定”，API 复核 `status=ready, enabled=true, bound=true`。
5. **改名**：`修改名称` → 保存 → 标题更新；API 复核 `name` 变化而 `conf_id`、`memory_db` 不变。
6. **禁用/启用**：切换“启用平台实例”开关 → 状态“已停用” → 再切换 → “运行中”（每步用 API 轮询复核）。
7. **删除**：危险区 `删除 Bot` → 二次确认框输入 Bot 名 → `永久删除` → 回到 `/console/bots`，toast“Bot 已删除”，`GET /api/bots/{id}` → 404。
8. **审计**：管理端 `GET /api/admin/audit?target_id=<bot_id>` 中同时存在 `bot.created`、`bot.qr_started`、`bot.qr_finalized`、`bot.renamed`、`bot.disabled`、`bot.enabled`、`bot.deleted`。

截图证据（`tests/e2e/artifacts/screenshots/`，已 gitignore，本地保留）：

| 文件 | 内容 |
|---|---|
| `01-dashboard-after-login.png` | 登录后总览 + 侧栏 |
| `02-bot-detail-qr.png` | 新建后详情页二维码（等待扫码，TTL 60s） |
| `03-bot-ready.png` | 模拟扫码 + finalize 后：运行中 / 已绑定 / toast“扫码成功，Bot 已上线” |
| `04-bot-renamed.png` | 改名后详情页 |
| `05-bots-after-delete.png` | 删除后列表（回到空态） |

### F. 管理端（FR-G）

| # | 用例 | 期望 | 实际 | 结果 |
|---|---|---|---|---|
| F1 | `GET /api/admin/users?q=<email>` | 200，包含目标用户，含 `bot_count`/`quota`/`encryption` | 一致；`max_bots=3` | PASS |
| F2 | `GET /api/admin/bots?page_size=100` | 200，Bot 项含 `owner_email` | 一致 | PASS |
| F3 | `GET /api/admin/audit?action=…` | 审计包含 Bot 增删、用户状态变更、登录/注册事件 | `bot.created`、`bot.deleted`、`user.status_changed` 均 >0；`auth.login` 或 `auth.register` >0 | PASS |
| F4 | `PUT /api/admin/users/{id}/encryption {"enabled":false}` / `{"enabled":true}` | 关闭 → 403 `forbidden`；开启 → 200 | 一致；状态保持 encrypted | PASS |
| F5 | 浏览器：管理员 UI OTP 登录 | 进入 `/console/`，可见“管理后台”，点击进入 `/console/admin/templates` | 一致 | PASS |
| F6 | 浏览器：`/console/admin/users`、`/admin/bots`、`/admin/audit` | 三个列表均可见且含真实数据 | 用户表含目标邮箱；Bot 表含新建 Bot 与 `owner_email`；审计表含 `bot.created` | PASS |

F3 修订说明：首版断言“最近 100 条审计里必须有 `auth.login`”，在审计量较大时会被分页截断，且复用管理员缓存会话时本轮不一定产生 `auth.login`（新用户首次登录记 `auth.register` 属产品预期）。现已改为按 `action` 精确过滤，并接受 `auth.login` **或** `auth.register`，结果稳定。

截图证据：

| 文件 | 内容 |
|---|---|
| `10-admin-users.png` | 用户管理列表（含状态/配额/加密） |
| `11-admin-bots.png` | Bot 管理列表（含归属用户） |
| `12-admin-audit.png` | 审计日志列表 |
| `13-forbidden-403.png` | 普通用户访问管理端的 403 页（含“返回总览”） |

---

## 4. 本轮发现的问题与处置

> 最终状态均为已修复/已规避，无遗留 FAIL。

| # | 现象 | 最小复现 | 判定 | 处置 |
|---|---|---|---|---|
| 1 | 客户端未先 poll 就直接 `POST /api/bots/{id}/qr/finalize` 时返回 `409 qr_not_ready`（即使 provider 已确认） | 建 Bot → start → dev `scanned` + `confirm` → 不 poll 直接 finalize | 健壮性缺口（契约写“created 后 finalize”，前端轮询可规避） | 已由后端在 finalize 前自动补一次 poll（提交 `69b965c`）；本轮 API/E2E 复验通过 |
| 2 | 403 页缺少明确出口（无“返回总览”） | 普通用户登录后访问 `/console/admin/users` | UX 缺口 | 前端已补 `返回总览`（真实 `<a>` 链接，提交 `6f79c43` + 重建 dist）；`auth.spec.ts` 断言通过 |
| 3 | 审计断言依赖“最近 100 条”分页 | 审计量 >100 后运行 API 验收 F3 | 测试缺陷（非产品 bug） | 改为按 `action` 过滤（见 F3） |
| 4 | E2E 定位器 strict violation（“我的 Bot”/“管理后台”/管理员邮箱多匹配） | 直接跑首版 E2E | 测试缺陷 | 侧栏用 `getByRole('listbox')` 作用域 + `exact`；管理员邮箱改用欢迎标题断言 |
| 5 | 并行运行 E2E 时 trace/产物互相清理导致 ENOENT | 两个 Playwright 进程同时用默认产物目录 | 测试基础设施问题 | 支持 `E2E_RUN_ID` 隔离 `test-results`/`playwright-report` |

---

## 5. 已知未覆盖项

以下项本轮**未**独立验证，或仅做了等价替代，列明原因供后续补测：

1. **真实 60s 自然过期**：用 dev-only `expire` 接口把会话置为过期后 poll，未真实等待 60s；也**未**验证 5 分钟无轮询的会话回收（需等 5min 或可控时钟）。
2. **真实微信/QQ 扫码**：全部使用 `FakeAstrBot` 模拟扫码/确认，未接真实平台接口、未验证真实凭据落盘后的平台上线（5s 内上线只验证了状态机与 `ready` 状态）。
3. **会话时间语义**：普通用户 30 天滑动/90 天绝对、管理员 12 小时绝对未验证（需要可控时钟或改配置，dev server 不可控）。
4. **并发建 Bot / 跨租户访问**：本轮 A2 只覆盖邀请码并发；Bot 创建并发、A 用户访问 B 的 bot/memory 的 404/403 由 47 个 pytest 覆盖，未重复。
5. **记忆模块（M2）**：`/memories` 为 M1 stub（空列表/501），未验证 CRUD、FTS、导入导出。
6. **加密开关与回填（M3）**：只验证“管理员不能关闭加密（403）”与强制开启 200；用户侧关闭/回填/进度/混合态未验证（M3 范围）。
7. **响应式与可访问性**：仅在 1440×960 桌面视口验证；未系统验证 <960px 抽屉侧栏、<600px 单列、键盘焦点陷阱、对比度等。
8. **前端网络异常/重试**：未模拟断网、GET 失败重试、长任务恢复；未做视觉回归。
9. **审计字段完整性**：只断言 action 存在与列表可见，未逐字段核对 IP/actor_role/detail。
10. **删除账号、管理员内容查看/access_log**：M1 未提供或属后续里程碑，未验证。

---

## 6. 证据文件

| 文件 | 说明 |
|---|---|
| `tests/e2e/artifacts/api_acceptance_report.json` | API 25 项 PASS/FAIL + 每项证据文本（运行时间、base_url、data_dir） |
| `tests/e2e/artifacts/screenshots/*.png` | 9 张浏览器截图（见 §3 E/F） |
| `tests/e2e/artifacts/playwright-report-qa/` | Playwright HTML 报告（`E2E_RUN_ID=qa`） |
| `tests/e2e/artifacts/test-results-qa/` | 失败时的 trace/截图目录（本轮无失败，目录可能为空） |

> `tests/e2e/artifacts/`、`tests/e2e/node_modules/` 均已 gitignore，不进入提交。

---

# 附录：M2 记忆模块验收（Lead 追加，2026-11-07 01:10–01:30）

> M1 验收完成后利用剩余时间实现 M2 记忆模块；以下为增量验收记录。
> 范围：分层骨架、SQLCipher 库、FTS 检索、去重、HTTP 管理接口、LLM 工具、前端记忆页。

## A. 自动化

| 项 | 命令 | 结果 |
|---|---|---|
| 后端（含记忆） | `.venv/bin/python -m pytest -q` | **80 passed** |
| 前端单测 | `cd web && npm run test` | **32 passed**（4 文件） |
| 前端构建 | `cd web && npm run build` | 通过（vue-tsc + vite） |
| API 回归 | `python tests/e2e/api_acceptance.py` | **25/25 PASS**（M2 改动未破坏 M1） |
| 浏览器 E2E | `cd tests/e2e && npx playwright test` | **10 passed**（M1 9 + M2 记忆页 1） |
| 真实 AstrBot | 启动 AstrBot 4.29.0-beta.1（6190） | 插件加载、无 ERROR、`/console/` 200、`/api/healthz` ok |

## B. 记忆模块关键验收

| 验收点 | 证据 |
|---|---|
| 契约双实现行为一致 | `tests/test_memory.py` 参数化跑 `InMemoryRepository` / `SqlCipherRepository`（增删改查/筛选/分页/FTS/touch/去重/tag count） |
| 记忆库为密文 | 文件头非 `SQLite format 3\0`；普通 `sqlite3` 打开抛 `DatabaseError` |
| 跨 Bot 不串 | Bot A 写入后 Bot B 列表/召回为空；HTTP 跨租户 404 |
| 删 Bot 清理连接与文件 | `memory_store.close(bot_id)` 后 `.db/-wal/-shm` 全部删除，缓存中无连接 |
| 去重 | 归一化内容 24h 内重复 → `duplicate=true` 不新增；超出窗口可再次写入 |
| 检索排序 | 置顶优先；`0.5*BM25 + 0.3*importance + 0.2*recency`；kind 过滤生效 |
| 性能 | 10,000 条记忆 FTS 查询 **13.4ms**（目标 <20ms） |
| 中文检索 | CJK 单字+bigram 预分词；`杭州`/`西湖 咖啡`/`独立开发` 均可命中 |
| HTTP 管理 | 列表/详情/PATCH/DELETE/搜索/导出；`tag` 筛选 `total` 按标签计数（修复前端发现的问题） |
| LLM 工具 | `memory_remember/recall/forget` 注册进 AstrBot；UMO 前缀非 `b_` 时 fail-closed 拒绝 |
| 前端记忆页 | `/bots/:id/memory`：分页/kind/tag/关键字、编辑 drawer、删除确认、导出、检索预览；E2E 通过 |

## C. M2 未覆盖

- 自动记忆（`LlmExtractor` 默认关，仅命令/LLM 工具写入）。
- 向量检索（第二期预留 `retrieval/vector.py`）。
- `from_angel.py` 的 HTTP 入口（CLI 已实现，未接上传）。
- 记忆衰减/遗忘策略、用户画像/摘要（后续里程碑）。

---

# 附录二：M3 切片验收（手动额度 + 账本）

| 验收点 | 证据 |
|---|---|
| 建单 → 确认 → 入账 | `tests/test_billing.py`；API smoke：201 建单 → confirm 200 `paid` → 余额 +credits |
| 重复确认不重复入账 | `confirm_order` 返回 `already_paid=true`；`ledger.idem_key=order:{id}` 唯一约束兜底 |
| 外部单号防重 | `external_ref` 唯一；重复建单返回 `idempotent=true` 同一订单 |
| 手动加/扣幂等 | `POST /api/admin/ledger` 带 `idem_key` 重复提交返回同一账本行，余额不变 |
| 余额可重算 | `recompute_balance()` = `SUM(ledger.delta)`；`reconcile` 修复被篡改的缓存余额（有测试） |
| 权限 | 普通用户调用 `/api/admin/orders|ledger` → 403；用户只能读自己的余额/流水 |
| 审计 | `order.created` / `order.confirmed` / `wallet.adjusted` 写入 `audit_logs` |
| 回归 | 全量 pytest 87 passed；M1 API 验收 25/25 不受影响 |
