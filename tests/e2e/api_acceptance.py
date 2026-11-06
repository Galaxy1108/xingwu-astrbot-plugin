#!/usr/bin/env python3
"""M1 独立验收：纯 API 部分（A / B / C / D / F）。

只依赖标准库；对运行中的 dev server 发真实 HTTP 请求，并直接以只读方式
检查 devdata/saas.sqlite3 与 devdata/memory/ 验证副作用。

覆盖：
  A 邀请码一次性（串行 + 并发 + OTP 重放）
  B 创建 Bot 失败可回滚（校验失败无残留 + 注入中段失败的全量回滚）
  C 扫码 60s 过期、自动刷新 <= 3 次、finalize、删除清理
  D API 级 401 / 403 / CSRF / 禁用会话
  F 管理端列表、审计、管理员不能关闭加密

用法（建议用后端同一个 venv）::

    /home/int_256t/Documents/Projects/AstrBot/.venv/bin/python \
        tests/e2e/api_acceptance.py --base-url http://127.0.0.1:6180

退出码：0 = 全部 PASS（允许 SKIP）；1 = 有 FAIL。
"""

from __future__ import annotations

import argparse
import json
import queue
import random
import shutil
import socket
import sqlite3
import string
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent / "rollback_harness.py"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


# ---------------------------------------------------------------------------
# tiny HTTP client (cookies + CSRF, no external deps)
# ---------------------------------------------------------------------------
class Result:
    def __init__(self, status: int, payload: Any, text: str):
        self.status = status
        self.json = payload
        self.text = text

    @property
    def data(self) -> dict[str, Any]:
        if isinstance(self.json, dict) and isinstance(self.json.get("data"), dict):
            return self.json["data"]
        return {}

    @property
    def error(self) -> dict[str, Any]:
        if isinstance(self.json, dict) and isinstance(self.json.get("error"), dict):
            return self.json["error"]
        return {}

    @property
    def code(self) -> str | None:
        return self.error.get("code")

    def describe(self, limit: int = 400) -> str:
        body = self.text if len(self.text) <= limit else self.text[:limit] + "…"
        return f"HTTP {self.status} {body}"


class Api:
    def __init__(
        self,
        base_url: str,
        cookies: dict[str, str] | None = None,
        *,
        csrf_header: bool = True,
        csrf_override: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.cookies: dict[str, str] = dict(cookies or {})
        self.csrf_header = csrf_header
        self.csrf_override = csrf_override

    def _absorb(self, headers) -> None:
        try:
            raw = headers.get_all("Set-Cookie") or []
        except AttributeError:
            raw = []
        for header in raw:
            jar = SimpleCookie()
            try:
                jar.load(header)
            except Exception:  # noqa: BLE001
                continue
            for name, morsel in jar.items():
                expired = morsel["max-age"] == "0" or "1970" in str(morsel["expires"])
                if expired:
                    self.cookies.pop(name, None)
                else:
                    self.cookies[name] = morsel.value

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        csrf: bool = True,
        timeout: int = 25,
    ) -> Result:
        method = method.upper()
        url = self.base_url + path
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.cookies:
            req.add_header(
                "Cookie", "; ".join(f"{key}={value}" for key, value in self.cookies.items())
            )
        if method in WRITE_METHODS and csrf and self.csrf_header:
            token = (
                self.csrf_override
                if self.csrf_override is not None
                else self.cookies.get("csrf", "")
            )
            if token:
                req.add_header("X-CSRF-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status = response.status
                raw = response.read()
                headers = response.headers
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
            headers = exc.headers
        self._absorb(headers)
        text = raw.decode("utf-8", "replace")
        payload: Any = None
        if text:
            try:
                payload = json.loads(text)
            except ValueError:
                payload = None
        return Result(status, payload, text)

    def get(self, path: str, **kwargs) -> Result:
        return self.request("GET", path, None, **kwargs)

    def post(self, path: str, body: Any = None, **kwargs) -> Result:
        return self.request("POST", path, {} if body is None else body, **kwargs)

    def patch(self, path: str, body: Any = None, **kwargs) -> Result:
        return self.request("PATCH", path, {} if body is None else body, **kwargs)

    def put(self, path: str, body: Any = None, **kwargs) -> Result:
        return self.request("PUT", path, {} if body is None else body, **kwargs)

    def delete(self, path: str, body: Any = None, **kwargs) -> Result:
        return self.request("DELETE", path, {} if body is None else body, **kwargs)


# ---------------------------------------------------------------------------
# checks / report
# ---------------------------------------------------------------------------
class CheckFailure(AssertionError):
    pass


def require(condition: Any, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


class Report:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, status: str, name: str, detail: str) -> None:
        self.items.append({"status": status, "name": name, "detail": detail})
        print(f"[{status}] {name}")
        if detail:
            for line in str(detail).splitlines():
                print(f"       {line}")

    def counts(self) -> dict[str, int]:
        return {
            "PASS": sum(1 for item in self.items if item["status"] == "PASS"),
            "FAIL": sum(1 for item in self.items if item["status"] == "FAIL"),
            "SKIP": sum(1 for item in self.items if item["status"] == "SKIP"),
        }


def run_block(report: Report, name: str, func: Callable[[], str]) -> bool:
    started = time.time()
    try:
        detail = func() or ""
    except CheckFailure as exc:
        report.add("FAIL", name, str(exc))
        return False
    except Exception as exc:  # noqa: BLE001
        report.add("FAIL", name, f"{type(exc).__name__}: {exc}")
        return False
    else:
        elapsed = time.time() - started
        report.add("PASS", name, f"{detail}（{elapsed:.1f}s）")
        return True


# ---------------------------------------------------------------------------
# environment helpers
# ---------------------------------------------------------------------------
class Env:
    def __init__(self, args: argparse.Namespace):
        self.base_url = args.base_url.rstrip("/")
        self.data_dir = Path(args.data_dir)
        if not self.data_dir.is_absolute():
            self.data_dir = (ROOT / self.data_dir).resolve()
        self.admin_email = args.admin_email
        self.artifacts = ARTIFACTS
        self.python = args.python
        self.report = Report()
        self.ctx: dict[str, Any] = {}
        self.cleanup: list[tuple[str, Callable[[], None]]] = []

    @property
    def db_path(self) -> Path:
        return self.data_dir / "saas.sqlite3"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"


def unique_email(tag: str) -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"qa-{tag}-{int(time.time())}-{suffix}@example.com"


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def db_rows(env: Env, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{env.db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def db_one(env: Env, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    rows = db_rows(env, sql, params)
    return rows[0] if rows else None


def memory_files(env: Env) -> set[str]:
    if not env.memory_dir.exists():
        return set()
    return {path.name for path in env.memory_dir.iterdir()}


def bot_count_for_user(env: Env, email: str) -> int:
    row = db_one(
        env,
        "SELECT COUNT(*) AS c FROM bots b JOIN users u ON u.id = b.user_id "
        "WHERE u.email = ? AND b.status != 'deleted'",
        (email,),
    )
    return int(row["c"]) if row else 0


def otp_request(
    api: Api,
    email: str,
    invite: str | None = None,
    *,
    retry_rate_limit: bool = True,
) -> Result:
    body: dict[str, Any] = {"email": email}
    if invite:
        body["invite"] = invite
    result = api.post("/api/auth/otp/request", body, csrf=False)
    attempts = 0
    while result.status == 429 and retry_rate_limit and attempts < 2:
        wait = int(result.error.get("retry_after") or 5)
        time.sleep(min(wait + 1, 65))
        result = api.post("/api/auth/otp/request", body, csrf=False)
        attempts += 1
    return result


def ensure_admin(env: Env) -> Api:
    cache = env.artifacts / "admin_session.json"
    if cache.exists():
        try:
            cookies = json.loads(cache.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cookies = {}
        if isinstance(cookies, dict) and cookies:
            api = Api(env.base_url, cookies=cookies)
            me = api.get("/api/me")
            if me.status == 200 and me.data.get("user", {}).get("role") == "admin":
                return api
    api = Api(env.base_url)
    requested = otp_request(api, env.admin_email)
    require(requested.status == 200, f"管理员 OTP 请求失败：{requested.describe()}")
    code = requested.data.get("dev_code")
    require(bool(code), "dev_mode 未返回 dev_code，无法自动登录管理员")
    verified = api.post(
        "/api/auth/otp/verify",
        {"email": env.admin_email, "code": code},
        csrf=False,
    )
    require(verified.status == 200, f"管理员 OTP 校验失败：{verified.describe()}")
    require(
        verified.data.get("user", {}).get("role") == "admin",
        f"管理员角色不正确：{verified.describe()}",
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(api.cookies), encoding="utf-8")
    return api


def create_invite(env: Env, admin: Api, max_uses: int = 1) -> str:
    result = admin.post(
        "/api/admin/invites", {"max_uses": max_uses, "ttl_hours": 72}
    )
    require(result.status == 201, f"创建邀请码失败：{result.describe()}")
    code = result.data.get("invite", {}).get("code")
    require(bool(code), f"邀请码响应缺少 code：{result.describe()}")
    return str(code)


def register_user(env: Env, admin: Api, tag: str) -> tuple[Api, str, str]:
    invite = create_invite(env, admin, 1)
    email = unique_email(tag)
    api = Api(env.base_url)
    requested = otp_request(api, email, invite)
    require(requested.status == 200, f"注册 OTP 请求失败：{requested.describe()}")
    code = requested.data.get("dev_code")
    require(bool(code), f"未拿到 dev_code：{requested.describe()}")
    verified = api.post(
        "/api/auth/otp/verify",
        {"email": email, "code": code, "invite": invite},
        csrf=False,
    )
    require(verified.status == 200, f"注册失败：{verified.describe()}")
    require(verified.data.get("is_new") is True, f"新用户注册 is_new 应为 true：{verified.describe()}")
    user = verified.data.get("user", {})
    return api, email, str(user.get("id"))


def first_template(api: Api) -> dict[str, Any]:
    result = api.get("/api/templates")
    require(result.status == 200, f"读取模板失败：{result.describe()}")
    items = result.data.get("items") or []
    require(bool(items), "没有可用模板，无法继续创建 Bot")
    return items[0]


def poll_until(api: Api, bot_id: str, expected: str, *, tries: int = 8) -> dict[str, Any]:
    last: Result | None = None
    for _ in range(tries):
        last = api.get(f"/api/bots/{bot_id}/qr/poll")
        require(last.status == 200, f"poll 失败：{last.describe()}")
        qr = last.data.get("qr") or {}
        if qr.get("status") == expected:
            return qr
        time.sleep(0.3)
    raise CheckFailure(f"poll 未在 {tries} 次内进入 {expected}：{last.describe() if last else ''}")


def make_ready_bot(api: Api, template_id: str, name: str) -> dict[str, Any]:
    created = api.post(
        "/api/bots", {"name": name, "template_id": template_id, "platform": "weixin_oc"}
    )
    require(created.status == 201, f"创建 Bot 失败：{created.describe()}")
    bot_id = created.data["bot"]["id"]
    started = api.post(f"/api/bots/{bot_id}/qr/start", {})
    require(started.status == 200, f"开始扫码失败：{started.describe()}")
    scanned = api.post(f"/api/dev/qr/{bot_id}/scanned", {})
    require(scanned.status == 200, f"模拟扫码失败：{scanned.describe()}")
    poll_until(api, bot_id, "scanned")
    confirmed = api.post(f"/api/dev/qr/{bot_id}/confirm", {})
    require(confirmed.status == 200, f"模拟确认失败：{confirmed.describe()}")
    poll_until(api, bot_id, "created")
    finalized = api.post(f"/api/bots/{bot_id}/qr/finalize", {})
    require(finalized.status == 200, f"finalize 失败：{finalized.describe()}")
    bot = finalized.data.get("bot") or {}
    require(bot.get("status") == "ready", f"finalize 后状态应为 ready：{finalized.describe()}")
    return bot


# ---------------------------------------------------------------------------
# harness for mid-creation failure injection (check B5)
# ---------------------------------------------------------------------------
def start_harness(env: Env, port: int, data_dir: Path) -> tuple[subprocess.Popen, dict[str, Any]]:
    command = [
        env.python,
        str(HARNESS),
        "--port",
        str(port),
        "--data-dir",
        str(data_dir),
    ]
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    line_queue: queue.Queue[str | None] = queue.Queue()
    lines: list[str] = []

    def _reader() -> None:
        try:
            for line in process.stdout:  # type: ignore[union-attr]
                line_queue.put(line.rstrip())
        except Exception:  # noqa: BLE001
            pass
        finally:
            line_queue.put(None)

    threading.Thread(target=_reader, daemon=True).start()
    deadline = time.time() + 45
    info: dict[str, Any] | None = None
    while time.time() < deadline:
        remaining = max(0.2, deadline - time.time())
        try:
            line = line_queue.get(timeout=min(1.0, remaining))
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if line is None:
            break
        lines.append(line)
        if line.strip().startswith("{"):
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if parsed.get("ready"):
                info = parsed
                break
    if info is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        # drain whatever the process printed before dying (tracebacks included)
        end = time.time() + 1.0
        while time.time() < end:
            try:
                line = line_queue.get(timeout=0.2)
            except queue.Empty:
                break
            if line is None:
                break
            lines.append(line)
        raise CheckFailure("回滚注入服务器启动失败：\n" + "\n".join(lines[-20:]))
    return process, info


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="M1 API 验收（A/B/C/D/F）")
    parser.add_argument("--base-url", default="http://127.0.0.1:6180")
    parser.add_argument("--data-dir", default="devdata")
    parser.add_argument("--admin-email", default="admin@example.com")
    parser.add_argument(
        "--python",
        default=str(ROOT.parent / "AstrBot" / ".venv" / "bin" / "python"),
        help="用于启动回滚注入服务器的 Python（需要 aiohttp/sqlcipher3）",
    )
    parser.add_argument("--json-out", default=str(ARTIFACTS / "api_acceptance_report.json"))
    args = parser.parse_args()

    if not Path(args.python).exists():
        args.python = sys.executable

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    env = Env(args)
    report = env.report

    version = Api(env.base_url).get("/api/version")
    if version.status != 200:
        print(f"无法连接 dev server {env.base_url}：{version.describe()}")
        return 2

    print("=" * 78)
    print(f"M1 API 验收  base={env.base_url}  data={env.data_dir}")
    print(f"version={version.data.get('version')} dev_mode={version.data.get('dev_mode')}")
    print("=" * 78)

    try:
        admin = ensure_admin(env)
        env.ctx["admin"] = admin
    except CheckFailure as exc:
        print(f"致命：管理员登录失败，无法继续：{exc}")
        return 2

    try:
        template = first_template(admin)
        user_api, user_email, user_id = register_user(env, admin, "main")
        env.ctx.update(
            {
                "template": template,
                "user_api": user_api,
                "user_email": user_email,
                "user_id": user_id,
            }
        )
    except CheckFailure as exc:
        print(f"致命：测试用户准备失败，无法继续：{exc}")
        return 2

    ctx = env.ctx
    user_api: Api = ctx["user_api"]
    user_email: str = ctx["user_email"]
    user_id: str = ctx["user_id"]
    template_id: str = ctx["template"]["id"]

    # ---------------------------------------------------------------- A
    def a0() -> str:
        me = admin.get("/api/me")
        require(me.status == 200, f"/api/me 失败：{me.describe()}")
        require(me.data["user"]["role"] == "admin", "管理员角色校验失败")
        require(bool(me.data.get("csrf_token")), "未下发 csrf_token")
        require(bool(admin.cookies.get("csrf")), "缺少 csrf Cookie")
        return f"admin={env.admin_email} role=admin version={me.data.get('version')}"

    def a1() -> str:
        invite = create_invite(env, admin, 1)
        email1 = unique_email("invite1")
        client = Api(env.base_url)
        first = otp_request(client, email1, invite)
        require(first.status == 200, f"首次注册 OTP 请求失败：{first.describe()}")
        code = first.data.get("dev_code")
        require(bool(code), f"未拿到 dev_code：{first.describe()}")
        verified = client.post(
            "/api/auth/otp/verify",
            {"email": email1, "code": code, "invite": invite},
            csrf=False,
        )
        require(verified.status == 200, f"首次注册失败：{verified.describe()}")
        require(verified.data.get("is_new") is True, "首次注册 is_new 应为 true")

        email2 = unique_email("invite2")
        second = otp_request(Api(env.base_url), email2, invite)
        require(
            second.status == 410 and second.code == "invite_exhausted",
            f"同一邀请码第二次注册应 410 invite_exhausted，实际：{second.describe()}",
        )
        used = db_one(env, "SELECT used_count, max_uses FROM invites WHERE code_hint = ?", (invite[:8],))
        require(used is not None, "邀请码记录不存在")
        require(int(used["used_count"]) == 1, f"used_count 应为 1，实际 {used}")
        env.ctx["a1_email"] = email1
        env.ctx["a1_code"] = code
        return f"邀请码 {invite[:8]}… 第二次注册 -> 410 invite_exhausted, used_count=1"

    def a2() -> str:
        invite = create_invite(env, admin, 1)
        email1 = unique_email("concurrent1")
        email2 = unique_email("concurrent2")
        codes: dict[str, str] = {}
        for email in (email1, email2):
            requested = otp_request(Api(env.base_url), email, invite)
            require(requested.status == 200, f"并发注册 OTP 请求失败：{requested.describe()}")
            codes[email] = requested.data["dev_code"]
        barrier = threading.Barrier(2)
        results: dict[str, tuple[int, str | None, str]] = {}

        def worker(email: str) -> None:
            client = Api(env.base_url)
            barrier.wait(timeout=10)
            result = client.post(
                "/api/auth/otp/verify",
                {"email": email, "code": codes[email], "invite": invite},
                csrf=False,
            )
            results[email] = (result.status, result.code, result.text[:200])

        threads = [threading.Thread(target=worker, args=(email,)) for email in (email1, email2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        require(len(results) == 2, f"并发注册未全部返回：{results}")
        statuses = sorted(item[0] for item in results.values())
        require(
            statuses == [200, 410],
            f"并发注册应恰好一个成功一个 410，实际：{results}",
        )
        loser = next(item for item in results.values() if item[0] == 410)
        require(loser[1] == "invite_exhausted", f"失败方错误码应为 invite_exhausted：{loser}")
        used = db_one(env, "SELECT used_count FROM invites WHERE code_hint = ?", (invite[:8],))
        require(used is not None and int(used["used_count"]) == 1, f"并发后 used_count 应为 1：{used}")
        count = db_one(
            env,
            "SELECT COUNT(*) AS c FROM users WHERE email IN (?, ?)",
            (email1, email2),
        )
        require(count is not None and int(count["c"]) == 1, f"并发后应只创建一个用户：{count}")
        return f"并发 verify：{statuses}，仅一个用户创建，used_count=1"

    def a3() -> str:
        email = env.ctx["a1_email"]
        code = env.ctx["a1_code"]
        replay = Api(env.base_url).post(
            "/api/auth/otp/verify", {"email": email, "code": code}, csrf=False
        )
        require(
            replay.status == 401 and replay.code == "otp_invalid",
            f"OTP 重放应 401 otp_invalid，实际：{replay.describe()}",
        )
        return "同一 OTP 第二次校验 -> 401 otp_invalid"

    # ---------------------------------------------------------------- B
    def assert_no_residue(label: str, names: list[str], memory_before: set[str]) -> None:
        rows = db_rows(
            env,
            "SELECT b.id, b.name FROM bots b JOIN users u ON u.id = b.user_id "
            "WHERE u.email = ? AND b.name IN (%s)" % ",".join("?" * len(names)),
            (user_email, *names),
        )
        require(not rows, f"{label}：DB 仍有 bot 行 {rows}")
        require(
            bot_count_for_user(env, user_email) == 0,
            f"{label}：用户 Bot 数应为 0，实际 {bot_count_for_user(env, user_email)}",
        )
        after = memory_files(env)
        require(after == memory_before, f"{label}：memory 目录出现残留 {after - memory_before}")

    def b1() -> str:
        before = memory_files(env)
        name = f"QA-非法平台-{int(time.time())}"
        result = user_api.post(
            "/api/bots",
            {"name": name, "template_id": template_id, "platform": "telegram"},
        )
        require(result.status == 400, f"非法平台应 400，实际：{result.describe()}")
        require(result.code == "validation_error", f"错误码应为 validation_error：{result.describe()}")
        require(result.error.get("field") == "platform", f"field 应为 platform：{result.describe()}")
        assert_no_residue("非法平台", [name], before)
        return "platform=telegram -> 400 validation_error(field=platform)，无 bot/记忆库残留"

    def b2() -> str:
        before = memory_files(env)
        empty = user_api.post("/api/bots", {"name": "   ", "template_id": template_id, "platform": "weixin_oc"})
        require(empty.status == 400 and empty.error.get("field") == "name", f"空名称应 400(field=name)：{empty.describe()}")
        long_name = "长" * 33
        too_long = user_api.post("/api/bots", {"name": long_name, "template_id": template_id, "platform": "weixin_oc"})
        require(
            too_long.status == 400 and too_long.error.get("field") == "name",
            f"超长名称应 400(field=name)：{too_long.describe()}",
        )
        assert_no_residue("非法名称", ["   ", long_name], before)
        return "空名称/33 字符 -> 400 validation_error(field=name)，无残留"

    def b3() -> str:
        created = admin.post(
            "/api/admin/templates",
            {
                "name": f"QA-下架模板-{int(time.time())}",
                "description": "QA acceptance",
                "persona_prompt": "你是 QA。",
            },
        )
        require(created.status == 201, f"创建 QA 模板失败：{created.describe()}")
        disabled_id = created.data["template"]["id"]
        disabled = admin.delete(f"/api/admin/templates/{disabled_id}")
        require(disabled.status == 200, f"下架模板失败：{disabled.describe()}")
        before = memory_files(env)
        name = f"QA-下架-{int(time.time())}"
        result = user_api.post(
            "/api/bots", {"name": name, "template_id": disabled_id, "platform": "weixin_oc"}
        )
        require(result.status == 409 and result.code == "template_disabled", f"下架模板应 409 template_disabled：{result.describe()}")
        assert_no_residue("下架模板", [name], before)
        return f"已下架模板 {disabled_id} -> 409 template_disabled，无残留"

    def b4() -> str:
        before = memory_files(env)
        try:
            patched = admin.patch(f"/api/admin/users/{user_id}", {"quota": {"max_bots": 0}})
            require(patched.status == 200, f"设置配额失败：{patched.describe()}")
            name = f"QA-配额-{int(time.time())}"
            result = user_api.post(
                "/api/bots", {"name": name, "template_id": template_id, "platform": "weixin_oc"}
            )
            require(result.status == 409 and result.code == "quota_exceeded", f"配额超限应 409 quota_exceeded：{result.describe()}")
            assert_no_residue("配额超限", [name], before)
            return "max_bots=0 -> 409 quota_exceeded，无残留"
        finally:
            admin.patch(f"/api/admin/users/{user_id}", {"quota": {"max_bots": 3}})

    def b5() -> str:
        tmp_dir = Path(tempfile.mkdtemp(prefix="saas-qa-rollback-"))
        port = free_port()
        process, info = start_harness(env, port, tmp_dir)
        try:
            base = f"http://{info['host']}:{info['port']}"
            client = Api(base)
            email = unique_email("rollback")
            requested = otp_request(client, email, info["invite"])
            require(requested.status == 200, f"注入服务器注册 OTP 失败：{requested.describe()}")
            verified = client.post(
                "/api/auth/otp/verify",
                {"email": email, "code": requested.data["dev_code"], "invite": info["invite"]},
                csrf=False,
            )
            require(verified.status == 200, f"注入服务器注册失败：{verified.describe()}")
            templates = client.get("/api/templates")
            require(templates.status == 200, f"注入服务器模板读取失败：{templates.describe()}")
            template = templates.data["items"][0]

            def state() -> dict[str, Any]:
                result = client.get("/__test__/state")
                require(result.status == 200, f"读取注入服务器状态失败：{result.describe()}")
                return result.data

            def expect_clean(label: str) -> None:
                snapshot = state()
                require(snapshot["bots"] == [], f"{label}：DB 仍有 bot 行 {snapshot['bots']}")
                require(snapshot["bindings"] == [], f"{label}：仍有绑定 {snapshot['bindings']}")
                require(snapshot["memory"] == [], f"{label}：memory 目录残留 {snapshot['memory']}")
                fake = snapshot["fake"]
                require(fake["personas"] == [], f"{label}：人格残留 {fake['personas']}")
                require(fake["configs"] == [], f"{label}：配置残留 {fake['configs']}")
                require(fake["routes"] == {}, f"{label}：路由残留 {fake['routes']}")
                require(fake["platforms"] == [], f"{label}：平台实例残留 {fake['platforms']}")

            scenarios = [
                ("create_persona", "人格创建失败"),
                ("create_config", "配置创建失败"),
                ("bind_route", "路由绑定失败"),
                ("create_platform", "平台实例创建失败（记忆库已建，需回滚删除）"),
            ]
            for step, label in scenarios:
                reset = client.post("/__test__/reset", {})
                require(reset.status == 200, f"重置注入服务器失败：{reset.describe()}")
                armed = client.post("/__test__/fail_on", {"steps": [step]})
                require(armed.status == 200, f"注入失败步骤失败：{armed.describe()}")
                result = client.post(
                    "/api/bots",
                    {
                        "name": f"QA-回滚-{step}",
                        "template_id": template["id"],
                        "platform": "weixin_oc",
                    },
                )
                require(
                    result.status == 500 and result.code == "internal_error",
                    f"{label} 应 500 internal_error，实际：{result.describe()}",
                )
                expect_clean(label)

            reset = client.post("/__test__/reset", {})
            require(reset.status == 200, f"重置注入服务器失败：{reset.describe()}")
            client.post("/__test__/fail_on", {"steps": []})
            ok_create = client.post(
                "/api/bots",
                {"name": "QA-回滚-正常", "template_id": template["id"], "platform": "weixin_oc"},
            )
            require(ok_create.status == 201, f"无注入时应创建成功：{ok_create.describe()}")
            bot_id = ok_create.data["bot"]["id"]
            snapshot = state()
            require(len(snapshot["bots"]) == 1, f"成功创建后应有 1 行 bot：{snapshot['bots']}")
            require(len(snapshot["memory"]) == 1, f"成功创建后应有 1 个记忆库文件：{snapshot['memory']}")
            deleted = client.delete(f"/api/bots/{bot_id}", {"confirm_name": "QA-回滚-正常"})
            require(deleted.status == 200, f"删除 Bot 失败：{deleted.describe()}")
            expect_clean("删除 Bot 后")
            return (
                "注入 create_persona/create_config/bind_route/create_platform 四种中段失败均 500 internal_error，"
                "人格/配置/路由/平台/记忆库/DB 行全部回滚；对照组创建+删除正常"
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---------------------------------------------------------------- C
    def c1() -> str:
        before = memory_files(env)
        name = f"QA-扫码-{int(time.time())}"
        created = user_api.post(
            "/api/bots", {"name": name, "template_id": template_id, "platform": "weixin_oc"}
        )
        require(created.status == 201, f"创建 Bot 失败：{created.describe()}")
        bot = created.data["bot"]
        require(bot["status"] == "pending_qr", f"新 Bot 状态应为 pending_qr：{bot}")
        require(bot["platform"] == "weixin_oc", f"平台应为 weixin_oc：{bot}")
        require(bot["memory_db"] == f"memory/{bot['id']}.db", f"memory_db 路径不正确：{bot}")
        after = memory_files(env)
        require(f"{bot['id']}.db" in after, f"记忆库文件未创建：{after - before}")
        row = db_one(env, "SELECT status, memory_db FROM bots WHERE id = ?", (bot["id"],))
        require(row is not None and row["status"] == "pending_qr", f"DB 中 Bot 行不正确：{row}")
        env.ctx["c_bot_id"] = bot["id"]
        env.ctx["c_bot_name"] = name
        env.ctx["c_memory_before"] = before
        return f"bot={bot['id']} status=pending_qr memory=memory/{bot['id']}.db（文件已生成）"

    def c2() -> str:
        bot_id = env.ctx["c_bot_id"]
        started = user_api.post(f"/api/bots/{bot_id}/qr/start", {})
        require(started.status == 200, f"qr/start 失败：{started.describe()}")
        qr = started.data["qr"]
        now = int(time.time())
        ttl = int(qr["expires_at"]) - now
        require(qr["status"] == "pending", f"初始状态应为 pending：{qr}")
        require(qr["refresh_count"] == 0, f"初始 refresh_count 应为 0：{qr}")
        require(qr["interval"] == 2, f"轮询间隔应为 2s：{qr}")
        require(55 <= ttl <= 65, f"二维码 TTL 应约 60s，实际 {ttl}s")
        require(
            str(qr.get("qr_image", "")).startswith("data:image/png;base64,"),
            "qr_image 应为 PNG data URL",
        )
        require(bool(qr.get("qr_content")), "qr_content 不应为空")
        env.ctx["c_qr_id"] = qr["id"]
        return f"status=pending refresh_count=0 interval=2 ttl={ttl}s image=png-data-url"

    def c3() -> str:
        bot_id = env.ctx["c_bot_id"]
        again = user_api.post(f"/api/bots/{bot_id}/qr/start", {})
        require(again.status == 409 and again.code == "qr_session_exists", f"重复 start 应 409 qr_session_exists：{again.describe()}")
        return "同一 Bot 重复 start -> 409 qr_session_exists"

    def c4() -> str:
        bot_id = env.ctx["c_bot_id"]
        statuses: list[str] = []
        refreshes: list[int] = []
        for _ in range(4):
            expired = user_api.post(f"/api/dev/qr/{bot_id}/expire", {})
            require(expired.status == 200, f"模拟过期失败：{expired.describe()}")
            polled = user_api.get(f"/api/bots/{bot_id}/qr/poll")
            require(polled.status == 200, f"poll 失败：{polled.describe()}")
            qr = polled.data["qr"]
            statuses.append(qr["status"])
            refreshes.append(int(qr["refresh_count"]))
        require(
            statuses == ["pending", "pending", "pending", "expired"],
            f"四次过期后的状态序列应为 pending×3 + expired，实际 {statuses}",
        )
        require(refreshes == [1, 2, 3, 4], f"refresh_count 序列应为 1..4，实际 {refreshes}")
        stable = user_api.get(f"/api/bots/{bot_id}/qr/poll")
        require(stable.data["qr"]["status"] == "expired", f"超限后应保持 expired：{stable.describe()}")
        return f"expire×4 -> status={statuses} refresh_count={refreshes}（第 4 次 expired，不再自动刷新）"

    def c5() -> str:
        bot_id = env.ctx["c_bot_id"]
        restarted = user_api.post(f"/api/bots/{bot_id}/qr/start", {})
        require(restarted.status == 200, f"过期后重新 start 失败：{restarted.describe()}")
        require(restarted.data["qr"]["status"] == "pending", "重新 start 应为 pending")
        premature = user_api.post(f"/api/bots/{bot_id}/qr/finalize", {})
        require(
            premature.status == 409 and premature.code == "qr_not_ready",
            f"未扫码 finalize 应 409 qr_not_ready：{premature.describe()}",
        )
        scanned = user_api.post(f"/api/dev/qr/{bot_id}/scanned", {})
        require(scanned.status == 200, f"模拟扫码失败：{scanned.describe()}")
        poll_until(user_api, bot_id, "scanned")
        confirmed = user_api.post(f"/api/dev/qr/{bot_id}/confirm", {})
        require(confirmed.status == 200, f"模拟确认失败：{confirmed.describe()}")
        poll_until(user_api, bot_id, "created")
        finalized = user_api.post(f"/api/bots/{bot_id}/qr/finalize", {})
        require(finalized.status == 200, f"finalize 失败：{finalized.describe()}")
        bot = finalized.data["bot"]
        require(bot["status"] == "ready", f"finalize 后应为 ready：{bot}")
        require(bot["enabled"] is True, f"finalize 后应启用：{bot}")
        require(bot["bound"] is True, f"finalize 后应已绑定：{bot}")
        binding = db_one(env, "SELECT platform FROM bot_bindings WHERE bot_id = ?", (bot_id,))
        require(binding is not None, "bot_bindings 无凭据行")
        return f"重新 start -> scanned -> created -> finalize -> status=ready enabled=true bound=true platform={binding['platform']}"

    def c6() -> str:
        bot_id = env.ctx["c_bot_id"]
        name = env.ctx["c_bot_name"]
        wrong = user_api.delete(f"/api/bots/{bot_id}", {"confirm_name": name + "-x"})
        require(
            wrong.status == 400 and wrong.error.get("field") == "confirm_name",
            f"名称不一致应 400(field=confirm_name)：{wrong.describe()}",
        )
        deleted = user_api.delete(f"/api/bots/{bot_id}", {"confirm_name": name})
        require(deleted.status == 200, f"删除 Bot 失败：{deleted.describe()}")
        require(deleted.data.get("deleted") is True, "删除响应 deleted 应为 true")
        require(
            db_one(env, "SELECT id FROM bots WHERE id = ?", (bot_id,)) is None,
            "删除后 DB 仍有 bot 行",
        )
        require(
            db_one(env, "SELECT bot_id FROM bot_bindings WHERE bot_id = ?", (bot_id,)) is None,
            "删除后仍有绑定行",
        )
        require(f"{bot_id}.db" not in memory_files(env), "删除后记忆库文件仍在")
        require(f"{bot_id}.db-wal" not in memory_files(env), "删除后记忆库 WAL 仍在")
        require(f"{bot_id}.db-shm" not in memory_files(env), "删除后记忆库 SHM 仍在")
        listed = user_api.get("/api/bots")
        require(
            all(item["id"] != bot_id for item in listed.data["items"]),
            "删除后列表仍返回该 Bot",
        )
        return "错误名称 400(confirm_name)；正确名称删除 200，DB/绑定/记忆库(+wal/shm)/列表均清理"

    def c7() -> str:
        before = memory_files(env)
        name = f"QA-取消扫码-{int(time.time())}"
        created = user_api.post(
            "/api/bots", {"name": name, "template_id": template_id, "platform": "qq_official"}
        )
        require(created.status == 201, f"创建待扫码 Bot 失败：{created.describe()}")
        bot_id = created.data["bot"]["id"]
        started = user_api.post(f"/api/bots/{bot_id}/qr/start", {})
        require(started.status == 200, f"qr/start 失败：{started.describe()}")
        deleted = user_api.delete(f"/api/bots/{bot_id}", {"confirm_name": name})
        require(deleted.status == 200, f"删除待扫码 Bot 失败：{deleted.describe()}")
        require(f"{bot_id}.db" not in memory_files(env), "取消后记忆库文件残留")
        after = memory_files(env)
        require(after == before, f"取消后 memory 目录残留 {after - before}")
        return "待扫码 Bot 直接删除 -> 记忆库文件/会话均清理，无残留"

    # ---------------------------------------------------------------- D
    def d1() -> str:
        anon = Api(env.base_url)
        bots = anon.get("/api/bots")
        require(bots.status == 401 and bots.code == "unauthorized", f"匿名 /api/bots 应 401：{bots.describe()}")
        me = anon.get("/api/me")
        require(me.status == 401, f"匿名 /api/me 应 401：{me.describe()}")
        write = anon.post("/api/bots", {"name": "x", "template_id": template_id, "platform": "weixin_oc"})
        require(write.status == 401, f"匿名写请求应 401：{write.describe()}")
        return "匿名 GET /api/bots、/api/me、POST /api/bots -> 401 unauthorized"

    def d2() -> str:
        no_csrf = Api(env.base_url, cookies=dict(user_api.cookies), csrf_header=False)
        result = no_csrf.post(
            "/api/bots", {"name": "QA-CSRF", "template_id": template_id, "platform": "weixin_oc"}
        )
        require(
            result.status == 403 and result.code == "csrf_invalid",
            f"缺少 CSRF 头应 403 csrf_invalid：{result.describe()}",
        )
        return "已登录但缺少 X-CSRF-Token -> 403 csrf_invalid"

    def d3() -> str:
        wrong = Api(
            env.base_url,
            cookies=dict(user_api.cookies),
            csrf_override="not-the-real-token",
        )
        result = wrong.post(
            "/api/bots", {"name": "QA-CSRF2", "template_id": template_id, "platform": "weixin_oc"}
        )
        require(
            result.status == 403 and result.code == "csrf_invalid",
            f"错误 CSRF 头应 403 csrf_invalid：{result.describe()}",
        )
        return "错误 X-CSRF-Token -> 403 csrf_invalid"

    def d4() -> str:
        users = user_api.get("/api/admin/users")
        require(users.status == 403 and users.code == "forbidden", f"普通用户访问管理端应 403：{users.describe()}")
        audit = user_api.get("/api/admin/audit")
        require(audit.status == 403 and audit.code == "forbidden", f"普通用户访问审计应 403：{audit.describe()}")
        return "普通用户 GET /api/admin/users、/api/admin/audit -> 403 forbidden"

    def d5() -> str:
        api2, email2, user2_id = register_user(env, admin, "disabled")
        bot = make_ready_bot(api2, template_id, f"QA-禁用-{int(time.time())}")
        bot_id = bot["id"]
        env.cleanup.append(
            (
                "admin_delete_d5_bot",
                lambda: admin.delete(f"/api/admin/bots/{bot_id}", {"confirm_name": bot["name"]}),
            )
        )
        disabled = admin.patch(f"/api/admin/users/{user2_id}", {"status": "disabled"})
        require(disabled.status == 200, f"禁用用户失败：{disabled.describe()}")
        env.cleanup.append(
            (
                "reenable_d5_user",
                lambda: admin.patch(f"/api/admin/users/{user2_id}", {"status": "active"}),
            )
        )
        me = api2.get("/api/me")
        require(me.status == 401 and me.code == "unauthorized", f"禁用后 /api/me 应 401：{me.describe()}")
        bots = api2.get("/api/bots")
        require(bots.status == 401, f"禁用后 /api/bots 应 401：{bots.describe()}")
        row = db_one(env, "SELECT status FROM bots WHERE id = ?", (bot_id,))
        require(row is not None and row["status"] == "disabled", f"禁用用户后其 ready Bot 应为 disabled：{row}")
        return f"禁用用户 {email2} -> 会话立即 401；其 ready Bot {bot_id} 变为 disabled"

    # ---------------------------------------------------------------- F
    def f1() -> str:
        result = admin.get(f"/api/admin/users?q={user_email}")
        require(result.status == 200, f"管理端用户列表失败：{result.describe()}")
        require(int(result.data.get("total", 0)) >= 1, f"用户列表应包含 {user_email}：{result.describe()}")
        item = next((row for row in result.data["items"] if row["email"] == user_email), None)
        require(item is not None, "用户列表缺少目标用户")
        require("bot_count" in item and "quota" in item, f"用户项缺少 bot_count/quota：{item}")
        require(item["quota"]["max_bots"] == 3, f"配额应已恢复为 3：{item['quota']}")
        return f"用户列表可见 {user_email}，bot_count={item['bot_count']} max_bots={item['quota']['max_bots']}"

    def f2() -> str:
        result = admin.get("/api/admin/bots?page_size=100")
        require(result.status == 200, f"管理端 Bot 列表失败：{result.describe()}")
        items = result.data.get("items") or []
        require(items, "管理端 Bot 列表为空（D5 已创建 ready Bot，不应为空）")
        require(
            all("owner_email" in item for item in items),
            "Bot 列表项缺少 owner_email",
        )
        sample = items[0]
        return f"Bot 列表 total={result.data.get('total')}，owner_email 示例={sample.get('owner_email')}"

    def f3() -> str:
        # 按 action 精确过滤，避免“最近 N 条”分页把较早的管理员登录截掉；
        # 新用户首次登录记 auth.register（产品预期），已有用户登录记 auth.login，
        # 因此“登录/注册”事件接受二者之一。
        def audit_total(action: str) -> int:
            result = admin.get(f"/api/admin/audit?action={action}&page_size=100")
            require(result.status == 200, f"审计过滤 {action} 失败：{result.describe()}")
            return int(result.data.get("total", 0))

        listed = admin.get("/api/admin/audit?page_size=5")
        require(listed.status == 200, f"审计列表失败：{listed.describe()}")
        require(bool(listed.data.get("items")), "审计列表第一页为空")
        counts = {
            action: audit_total(action)
            for action in (
                "bot.created",
                "bot.deleted",
                "user.status_changed",
                "auth.login",
                "auth.register",
            )
        }
        require(counts["bot.created"] > 0, f"审计缺少 bot.created：{counts}")
        require(counts["bot.deleted"] > 0, f"审计缺少 bot.deleted：{counts}")
        require(counts["user.status_changed"] > 0, f"审计缺少 user.status_changed：{counts}")
        require(
            counts["auth.login"] > 0 or counts["auth.register"] > 0,
            f"审计缺少登录/注册事件（auth.login 或 auth.register）：{counts}",
        )
        return f"审计按 action 过滤：{counts}；登录事件以 auth.login/auth.register 之一计"

    def f4() -> str:
        before = admin.get(f"/api/admin/users/{user_id}/encryption")
        require(before.status == 200, f"读取加密状态失败：{before.describe()}")
        require(before.data.get("enabled") is True, "初始应为加密开启")
        forbidden = admin.put(f"/api/admin/users/{user_id}/encryption", {"enabled": False})
        require(
            forbidden.status == 403 and forbidden.code == "forbidden",
            f"管理员关闭加密应 403 forbidden：{forbidden.describe()}",
        )
        allowed = admin.put(f"/api/admin/users/{user_id}/encryption", {"enabled": True})
        require(allowed.status == 200, f"管理员强制开启加密应 200：{allowed.describe()}")
        after = admin.get(f"/api/admin/users/{user_id}/encryption")
        require(after.data.get("enabled") is True, "强制开启后状态应为 enabled=true")
        return "PUT encryption enabled=false -> 403 forbidden；enabled=true -> 200，状态仍为加密"

    blocks: list[tuple[str, Callable[[], str]]] = [
        ("A0 管理员 OTP 登录 + /api/me", a0),
        ("A1 邀请码一次性：第二次注册 410 invite_exhausted", a1),
        ("A2 邀请码并发：恰好一个成功，其余 410", a2),
        ("A3 OTP 重放被拒绝（401 otp_invalid）", a3),
        ("B1 非法平台创建失败且无残留", b1),
        ("B2 非法名称创建失败且无残留", b2),
        ("B3 已下架模板创建失败且无残留", b3),
        ("B4 配额超限创建失败且无残留", b4),
        ("B5 中段失败全量回滚（注入 create_persona/config/route/platform）", b5),
        ("C1 创建 Bot -> pending_qr + 记忆库文件", c1),
        ("C2 扫码 start：TTL≈60s、间隔 2s、PNG 二维码", c2),
        ("C3 同一 Bot 重复 start -> 409 qr_session_exists", c3),
        ("C4 连续 4 次过期：刷新 3 次后 expired", c4),
        ("C5 重新 start、未扫码 finalize 409、扫码后 finalize -> ready", c5),
        ("C6 删除 Bot：名称确认、DB/绑定/记忆库清理", c6),
        ("C7 取消待扫码 Bot 无残留", c7),
        ("D1 匿名访问 -> 401 unauthorized", d1),
        ("D2 缺少 CSRF 头的写请求 -> 403 csrf_invalid", d2),
        ("D3 错误 CSRF token -> 403 csrf_invalid", d3),
        ("D4 普通用户访问管理端 -> 403 forbidden", d4),
        ("D5 禁用用户：会话立即 401 + 其 Bot 停用", d5),
        ("F1 管理端用户列表可见", f1),
        ("F2 管理端 Bot 列表可见（含 owner_email）", f2),
        ("F3 审计列表可见（按 action 过滤：Bot 增删/用户状态/登录注册）", f3),
        ("F4 管理员不能关闭加密（403）", f4),
    ]

    try:
        for name, func in blocks:
            run_block(report, name, func)
    finally:
        for label, action in reversed(env.cleanup):
            try:
                action()
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] 清理 {label} 失败：{exc}")

    counts = report.counts()
    print("=" * 78)
    print(f"SUMMARY: {counts['PASS']} PASS / {counts['FAIL']} FAIL / {counts['SKIP']} SKIP")
    if counts["FAIL"]:
        print("FAIL 项：")
        for item in report.items:
            if item["status"] == "FAIL":
                print(f"  - {item['name']}\n    {item['detail']}")
    print("=" * 78)

    payload = {
        "generated_at": int(time.time()),
        "base_url": env.base_url,
        "data_dir": str(env.data_dir),
        "summary": counts,
        "items": report.items,
    }
    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON 报告：{out}")
    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
