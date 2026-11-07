"""Composition root: wires settings, database, services and the AstrBot port."""

from __future__ import annotations

import logging
from pathlib import Path

from .audit import AuditService
from .billing import BillingService
from .conversations import ConversationService, FakeConversationBackend
from .encryption import EncryptionService
from .auth import AuthService, InviteService, OtpService, SessionService, TenantKeyService
from .bots import BotService
from .clock import Clock, SystemClock
from .config import Settings
from .crypto import KeyManager
from .db import Database
from .fake_astrbot import FakeAstrBot
from .mailer import build_mailer
from .memory.api import MemoryAPI
from .memory.extraction.command import CommandExtractor
from .memory.service import LoggingEventBus, MemoryService
from .memory.storage.sqlcipher import MemoryStorage, MemoryStorageError
from .memory.store import SqlCipherMemoryStore
from .ports import AstrBotPort
from .qr import QrService
from .settings_store import SettingsStore
from .templates import TemplateService

logger = logging.getLogger(__name__)


class Container:
    """Owns every long-lived object of the plugin (one per process)."""

    def __init__(
        self,
        settings: Settings,
        *,
        port: AstrBotPort | None = None,
        clock: Clock | None = None,
        memory_plaintext: bool = False,
        conversation_backend=None,
    ) -> None:
        self.settings = settings
        self.settings.ensure_dirs()
        self.clock = clock or SystemClock()
        self.db = Database(settings.db_path)
        self.db.connect()
        self.db.run_migrations(settings.migrations_dir)

        self.key_manager = KeyManager(settings.kek_file)
        self.key_manager.load_kek()  # fail fast: no KEK → no service

        self.audit = AuditService(self.db, self.clock)
        self.tenants = TenantKeyService(self.db, self.key_manager, self.clock)
        self.invites = InviteService(
            self.db,
            settings=settings,
            pepper=self.key_manager.derive_secret("invite/v1"),
            clock=self.clock,
        )
        self.otp = OtpService(
            self.db,
            settings=settings,
            pepper=self.key_manager.derive_secret("otp/v1"),
            clock=self.clock,
        )
        self.sessions = SessionService(
            self.db,
            settings=settings,
            pepper=self.key_manager.derive_secret("session/v1"),
            clock=self.clock,
        )
        self.mailer = build_mailer(settings)
        self.auth = AuthService(
            self.db,
            settings=settings,
            invites=self.invites,
            otp=self.otp,
            sessions=self.sessions,
            keys=self.tenants,
            audit=self.audit,
            mailer=self.mailer,
            clock=self.clock,
        )
        self.settings_store = SettingsStore(self.db, self.key_manager, self.clock)
        self.templates = TemplateService(self.db, self.clock)
        self.billing = BillingService(self.db, audit=self.audit, clock=self.clock)
        self.memory_storage = MemoryStorage(
            settings.memory_dir, force_plaintext=memory_plaintext
        )
        self.memory_store = SqlCipherMemoryStore(
            self.memory_storage, self.memory_key_for_bot
        )
        self.memory_service = MemoryService(
            self.memory_store,
            clock=self.clock,
            extractor=CommandExtractor(),
            events=LoggingEventBus(),
        )
        self.memory_api = MemoryAPI(self.memory_service)
        self.port: AstrBotPort = port or FakeAstrBot()
        self.conversation_backend = conversation_backend or FakeConversationBackend()
        self.bots = BotService(
            self.db,
            port=self.port,
            templates=self.templates,
            memory=self.memory_storage,
            memory_store=self.memory_store,
            tenants=self.tenants,
            settings=settings,
            audit=self.audit,
            clock=self.clock,
        )
        self.conversations = ConversationService(
            self.conversation_backend,
            db=self.db,
            tenants=self.tenants,
            clock=self.clock,
        )
        self.qr = QrService(
            port=self.port,
            bots=self.bots,
            settings=settings,
            audit=self.audit,
            clock=self.clock,
        )
        self.encryption = EncryptionService(self)
        logger.info(
            "SaaS 核心已初始化：data=%s, memory=%s, port=%s",
            settings.data_dir,
            "sqlcipher" if self.memory_storage.encrypted else "plaintext",
            type(self.port).__name__,
        )

    # -- memory --------------------------------------------------------
    def memory_key_for_bot(self, bot_id: str) -> bytes:
        row = self.db.query_one("SELECT user_id FROM bots WHERE id = ?", (bot_id,))
        if row is None:
            raise MemoryStorageError(f"Bot 不存在：{bot_id}")
        return self.tenants.memory_key(row["user_id"], bot_id)

    # -- lifecycle -----------------------------------------------------
    def close(self) -> None:
        self.memory_store.close_all()
        self.db.close()

    # -- seed helpers (scripts / dev server / tests) -------------------
    def seed_defaults(
        self, *, admin_email: str | None = None, templates: bool = True
    ) -> dict:
        """Idempotent bootstrap: admin account, demo templates and an invite."""
        result: dict = {}
        email = (admin_email or self.settings.admin_email or "admin@example.com").lower()
        admin = self.auth.get_user_by_email(email)
        if admin is None:
            admin = self.auth.create_user(email, role="admin")
            result["admin_created"] = admin["email"]
            print(f"[seed] 管理员账号已创建：{email}（OTP 登录，无需密码）")
        elif admin["role"] != "admin":
            self.db.execute(
                "UPDATE users SET role = 'admin' WHERE id = ?", (admin["id"],)
            )
            result["admin_promoted"] = email
        result["admin_id"] = admin["id"]

        if templates and not self.templates.list():
            demo = [
                {
                    "name": "默认陪伴",
                    "description": "通用闲聊人格，适合日常陪伴。",
                    "persona_prompt": (
                        "你是 {bot_name}，一个温柔、可靠、说话简洁的助手。"
                        "记住用户告诉你的重要信息，并在合适的时候主动关心。"
                    ),
                    "begin_dialogs": ["你好呀，我是 {bot_name}。"],
                    "config_patch": {"provider_settings": {}},
                    "memory_defaults": {
                        "auto": False,
                        "max_items": 2000,
                        "retention_days": 90,
                        "recall_top_k": 5,
                    },
                    "privacy_defaults": {"allow_disable": True},
                    "quota": {
                        "max_bots": 3,
                        "monthly_tokens": 1_000_000,
                        "max_memories": 2000,
                    },
                    "user_overridable": ["persona_prompt"],
                },
                {
                    "name": "深夜树洞",
                    "description": "更安静、更长回复的倾听型人格（示例）。",
                    "persona_prompt": (
                        "你是 {bot_name}。你擅长倾听，不急于给建议；"
                        "先复述对方的感受，再温和地追问。"
                    ),
                    "begin_dialogs": [],
                    "config_patch": {"provider_settings": {}},
                    "memory_defaults": {
                        "auto": True,
                        "max_items": 3000,
                        "retention_days": 180,
                        "recall_top_k": 8,
                    },
                    "privacy_defaults": {"allow_disable": False},
                    "quota": {
                        "max_bots": 2,
                        "monthly_tokens": 500_000,
                        "max_memories": 3000,
                    },
                    "user_overridable": [],
                },
            ]
            for payload in demo:
                self.templates.create(payload, actor_id=admin["id"])
            result["templates_created"] = len(demo)
        return result

    def create_invite(self, *, admin_id: str, max_uses: int = 1) -> dict:
        return self.invites.create(created_by=admin_id, max_uses=max_uses)
