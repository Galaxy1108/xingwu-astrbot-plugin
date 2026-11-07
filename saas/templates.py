"""Preset templates (FR-C): admin-maintained snapshots for new Bots."""

from __future__ import annotations

import json
import time
from typing import Any

from .clock import Clock, SystemClock
from .db import Database
from .errors import AppError, NotFound, ValidationError
from .security import random_id

JSON_FIELDS = (
    "begin_dialogs",
    "config_patch",
    "memory_defaults",
    "privacy_defaults",
    "quota",
    "user_overridable",
)
DEFAULT_MEMORY = {
    "auto": False,
    "max_items": 2000,
    "retention_days": 90,
    "recall_top_k": 5,
}
DEFAULT_PRIVACY = {"allow_disable": True}
DEFAULT_QUOTA = {"max_bots": 3, "monthly_tokens": 1_000_000, "max_memories": 2000}


def _parse_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def serialize_template(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    for field_name in JSON_FIELDS:
        item[field_name] = _parse_json(item.get(field_name), _default_for(field_name))
    item["enabled"] = bool(item.get("enabled"))
    return item


def _default_for(field_name: str) -> Any:
    return {
        "begin_dialogs": [],
        "config_patch": {},
        "memory_defaults": dict(DEFAULT_MEMORY),
        "privacy_defaults": dict(DEFAULT_PRIVACY),
        "quota": dict(DEFAULT_QUOTA),
        "user_overridable": [],
    }[field_name]


class TemplateService:
    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self.db = db
        self.clock = clock or SystemClock()

    # -- validation ----------------------------------------------------
    @staticmethod
    def _validate(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        if "name" in payload or not partial:
            name = str(payload.get("name") or "").strip()
            if not name or len(name) > 64:
                raise ValidationError("模板名称需为 1–64 字符", field="name")
            cleaned["name"] = name
        if "description" in payload:
            cleaned["description"] = str(payload.get("description") or "")[:500]
        if "base_conf_id" in payload or not partial:
            base_conf_id = str(payload.get("base_conf_id") or "default").strip() or "default"
            if len(base_conf_id) > 128:
                raise ValidationError("base_conf_id 不合法", field="base_conf_id")
            cleaned["base_conf_id"] = base_conf_id
        if "persona_prompt" in payload:
            cleaned["persona_prompt"] = str(payload.get("persona_prompt") or "")
        for field_name in ("begin_dialogs", "user_overridable"):
            if field_name in payload:
                value = payload[field_name]
                if not isinstance(value, list) or not all(
                    isinstance(item, str) for item in value
                ):
                    raise ValidationError(f"{field_name} 必须是字符串数组", field=field_name)
                cleaned[field_name] = value
        for field_name in (
            "config_patch",
            "memory_defaults",
            "privacy_defaults",
            "quota",
        ):
            if field_name in payload:
                value = payload[field_name]
                if not isinstance(value, dict):
                    raise ValidationError(f"{field_name} 必须是 JSON 对象", field=field_name)
                cleaned[field_name] = value
        if "enabled" in payload:
            cleaned["enabled"] = 1 if payload["enabled"] else 0
        return cleaned

    # -- CRUD ----------------------------------------------------------
    def get(self, template_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM templates WHERE id = ?", (template_id,))
        if row is None:
            raise NotFound("模板不存在")
        return serialize_template(row)

    def list(
        self, *, enabled_only: bool = False, page: int = 1, page_size: int = 100
    ) -> list[dict[str, Any]]:
        where = "WHERE enabled = 1" if enabled_only else ""
        rows = self.db.query(
            f"SELECT * FROM templates {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (page_size, (page - 1) * page_size),
        )
        return [serialize_template(row) for row in rows]

    def create(self, payload: dict[str, Any], *, actor_id: str = "") -> dict[str, Any]:
        cleaned = self._validate(payload)
        now = self.clock.now()
        template_id = random_id("t", 8)
        values = {
            "begin_dialogs": cleaned.get("begin_dialogs", []),
            "config_patch": cleaned.get("config_patch", {}),
            "memory_defaults": cleaned.get("memory_defaults", dict(DEFAULT_MEMORY)),
            "privacy_defaults": cleaned.get("privacy_defaults", dict(DEFAULT_PRIVACY)),
            "quota": cleaned.get("quota", dict(DEFAULT_QUOTA)),
            "user_overridable": cleaned.get("user_overridable", []),
        }
        self.db.execute(
            "INSERT INTO templates(id, name, description, persona_prompt, begin_dialogs, "
            "config_patch, memory_defaults, privacy_defaults, quota, user_overridable, "
            "enabled, created_by, created_at, updated_at, base_conf_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                template_id,
                cleaned["name"],
                cleaned.get("description", ""),
                cleaned.get("persona_prompt", ""),
                json.dumps(values["begin_dialogs"], ensure_ascii=False),
                json.dumps(values["config_patch"], ensure_ascii=False),
                json.dumps(values["memory_defaults"], ensure_ascii=False),
                json.dumps(values["privacy_defaults"], ensure_ascii=False),
                json.dumps(values["quota"], ensure_ascii=False),
                json.dumps(values["user_overridable"], ensure_ascii=False),
                int(cleaned.get("enabled", 1)),
                actor_id,
                now,
                now,
                cleaned.get("base_conf_id", "default"),
            ),
        )
        return self.get(template_id)

    def update(self, template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.get(template_id)
        cleaned = self._validate(payload, partial=True)
        if not cleaned:
            return self.get(template_id)
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in cleaned.items():
            assignments.append(f"{key} = ?")
            if key in JSON_FIELDS:
                params.append(json.dumps(value, ensure_ascii=False))
            else:
                params.append(value)
        assignments.append("updated_at = ?")
        params.append(self.clock.now())
        params.append(template_id)
        self.db.execute(
            f"UPDATE templates SET {', '.join(assignments)} WHERE id = ?", params
        )
        return self.get(template_id)

    def disable(self, template_id: str) -> dict[str, Any]:
        self.get(template_id)
        self.db.execute(
            "UPDATE templates SET enabled = 0, updated_at = ? WHERE id = ?",
            (self.clock.now(), template_id),
        )
        return self.get(template_id)

    def snapshot(self, template_id: str) -> dict[str, Any]:
        """Copy used at Bot creation; later template edits never touch it."""
        template = self.get(template_id)
        return {
            "template_id": template["id"],
            "template_name": template["name"],
            "base_conf_id": template.get("base_conf_id", "default"),
            "persona_prompt": template["persona_prompt"],
            "begin_dialogs": template["begin_dialogs"],
            "config_patch": template["config_patch"],
            "memory_defaults": template["memory_defaults"],
            "privacy_defaults": template["privacy_defaults"],
            "quota": template["quota"],
            "user_overridable": template["user_overridable"],
            "captured_at": self.clock.now(),
        }
