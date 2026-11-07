# astrbot-saas-plugin

在一台 **AstrBot** 实例上提供多租户 Bot 托管：邀请制注册 / 邮箱 OTP、预设模板、一人多 Bot、扫码接入微信个人号与 QQ 官方、每 Bot 独立 SQLCipher 加密记忆库、隐私加密与管理后台。

插件即后端：账号、会话、模板、配额、Bot 注册表、审计、密钥、记忆库都在插件内；控制台是插件托管的 Vue3 静态页面 + 同源 JSON API，不引入独立业务后端/Postgres/Redis。

> 当前进度：**M1（账号 + 建 Bot）已完成并通过独立验收**；**M2 记忆模块后端已完成**（分层、SQLCipher、
> FTS 检索、LLM 工具、angel_memory 导入 CLI、HTTP 管理接口；前端记忆页在 M2 收尾中）。
> M3 切片已实现：手动额度订单 + append-only 账本（幂等）与用户余额/流水；隐私加密开关与管理端内容查看仍待实现。

## 快速开始（独立开发模式，无需启动 AstrBot）

```bash
cd /home/int_256t/Documents/Projects/astrbot-saas-plugin

# 1) 安装后端依赖（AstrBot 的 venv 已自带 aiohttp/cryptography/qrcode；
#    这里额外装 SQLCipher wheel）
uv pip install --python ../AstrBot/.venv/bin/python -r requirements.txt

# 2) 启动 dev server（FakeAstrBot + SQLCipher + 种子管理员/模板）
../AstrBot/.venv/bin/python scripts/dev_server.py --data-dir devdata --port 6180
#    → API:     http://127.0.0.1:6180/api/version
#    → 控制台:  http://127.0.0.1:6180/console/  （需先构建 web/）
#    → 管理员:  devdata 首次启动自动创建 admin@example.com（OTP 登录）
#    → 邀请码:  dev server 启动日志里打印一次；也可用 scripts/seed_admin.py --invite

# 3) 构建前端
cd web && npm install && npm run build && cd ..
#    dist 落到 web/dist，由 dev server 在 /console/ 托管

# 4) 测试
../AstrBot/.venv/bin/python -m pytest -q          # 后端 47 个用例
cd web && npm run test                             # 前端 Vitest
```

OTP 邮件默认走日志降级（开发模式接口还会回显 `data.dev_code`）；生产在插件配置或环境变量里设置
`SAAS_SMTP_HOST/PORT/USER/PASSWORD/FROM`（`SAAS_SMTP_SSL=true` 用于 465），响应中的 `delivered`
会变为 `true`。生产必须关闭 `otp_dev_echo`。
并提供仅 dev 可用的扫码模拟接口：`POST /api/dev/qr/{bot_id}/scanned|confirm|expire`。

## 接入真实 AstrBot

1. 把整个目录放到 `AstrBot/data/plugins/astrbot_plugin_saas/`（或指向本目录的符号链接）。
2. 在 AstrBot 插件配置里设置 `console_port`（默认 6180）、`initial_admin_email`、`cookie_secure=true`。
3. 重启 AstrBot；日志出现 `astrbot_plugin_saas: 控制台已启动 http://127.0.0.1:6180/console/`。
4. 反向代理（Nginx/Caddy）到 6180，并启用 HTTPS；**不要**把 6180 直接暴露公网。
5. 首次启动会用 `initial_admin_email` 创建管理员并打印一次性邀请码（72h）。

```nginx
location /console/ { proxy_pass http://127.0.0.1:6180; }
location /api/     { proxy_pass http://127.0.0.1:6180; }
```

## 架构

```
web/                     Vue3 + Vite6 + Vuetify3 + Pinia + TS 控制台（静态托管 /console/）
main.py                  AstrBot 插件入口（Star），启动内置 aiohttp 控制台
saas/
├─ config.py             设置（env/插件配置）
├─ db.py + migrations/   插件 SQLite（WAL、显式事务、顺序迁移）
├─ crypto.py             Root KEK → 租户密钥（信封）→ 每 Bot 子密钥；ENC1 信封
├─ auth/                 邀请、OTP、会话/CSRF、租户密钥、账号用例
├─ templates.py          预设模板（创建快照）
├─ billing.py            手动额度订单 + append-only 账本（幂等、可对账）
├─ bots.py               Bot 生命周期（创建/回滚/启停/改名/删除）
├─ qr.py                 扫码状态机（60s TTL、≤3 自动刷新、5min 空闲回收）
├─ memory/               自研记忆模块：models/ports/service/api，SQLCipher repo + InMemory 契约双实现，
│                        CJK bigram FTS、规则重排、命令抽取、LLM 工具、angel_memory 导入
├─ ports.py              与 AstrBot 的边界协议
├─ astrbot_adapter.py    真实 AstrBot 集成（人格/配置/路由/平台/扫码）
├─ fake_astrbot.py       测试与 dev server 的确定性替身
├─ audit.py              审计 + 内容访问日志
├─ container.py          组合根（装配所有服务）
└─ web/                  aiohttp 应用：中间件、路由、静态托管
```

关键约定：

- **业务代码不 import AstrBot**：`saas/*` 只依赖 `ports.py`；`main.py`/`astrbot_adapter.py` 才接触框架。因此整套后端可在 pytest 里用 `FakeAstrBot` 跑通。
- **会话**：`__Host-sid`（生产，HttpOnly/Secure/SameSite=Lax/30d 滑动+90d 绝对；管理员 12h）；开发 http 下降级为 `sid`。
- **CSRF**：非 HttpOnly Cookie `csrf` + `X-CSRF-Token`，并与会话内保存的 hash 绑定（双提交 + 服务端校验）。
- **加密**：Root KEK 在 DB 外（`keys/root_kek.bin` 0400 或 `SAAS_KEK`）；租户密钥用 KEK 包裹；记忆库 = SQLCipher 文件（密钥 `HKDF(tenant_key, salt=bot_id, info="bot/memory/v1")`）；凭据密文存 `bot_bindings.credential_cipher`。
- **多租户隔离**：Bot ID `b_<uuid4hex>`；所有"仅自己"的接口在服务端校验 `bot.user_id == session.user_id`，跨租户一律 404。
- **失败回滚**：创建顺序 人格 → 配置 → 路由 → 记忆库 → 平台（禁用）→ 注册表；任一步失败逆序回滚并删行（测试逐步骤注入失败验证无残留）。

## 测试与验收

- 后端：`tests/`（94 例）覆盖邀请一次性 410、OTP 规则、会话/禁用、CSRF、模板快照/下架、配额、创建回滚、跨租户 404、QR 60s/≤3 刷新/空闲回收、凭据加密、删除清理、SQLCipher 库不可被普通 sqlite3 打开；记忆模块（契约双实现、去重、召回排序、跨 Bot 隔离、10k FTS 13ms、删 Bot 清理连接/文件）。
- 前端：`web/` 内 Vitest（36 例：守卫 401/403、ConfirmDialog、API client CSRF、记忆 store、额度单）。
- E2E：`tests/e2e/`（Playwright，使用系统 chromium；11 例：M1 登录/权限/扫码/管理端 + M2 记忆页 + M3 额度）；验收记录见 `docs/ACCEPTANCE.md`。

## 安全边界（摘要）

- 能防：DB/备份/磁盘快照被拿走（密文）、跨租户越权（服务端校验 + 404）、管理员隐身查看（访问留痕）、日志误打印明文（不记录）。
- 不能防：拿到 root + KEK 的人、运行时内存 dump、AstrBot 进程被控制。
- KEK 丢失 = 数据永久不可恢复；**KEK 与备份必须分开存放**。

## 许可

AstrBot 本体为 AGPL-3.0；本插件建议与生态一致使用 AGPL-3.0（对外提供 SaaS 前请确认第 13 条源码提供义务与合规要求）。
