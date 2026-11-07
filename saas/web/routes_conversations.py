"""Conversation history viewing + public share links (user-facing).

Owner routes never write ``content_access_logs`` (that table is reserved for
admin content access); they only let a user read their own Bot. Public share
links are read-only and served without a session.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from ..conversation_shares import ConversationShareService
from ..errors import AppError, NotFound, ValidationError
from .app import client_ip, container_of, current_user, ok

routes = web.RouteTableDef()


def shares_of(container: Any) -> ConversationShareService:
    service = getattr(container, "conversation_shares", None)
    if service is None:
        service = ConversationShareService(container.db, clock=container.clock)
        container.conversation_shares = service
    return service


# ----------------------------------------------------------------- helpers
def _owned(container, request: web.Request) -> tuple[dict[str, Any], dict[str, Any]]:
    user = current_user(request)
    bot = container.bots.get_for_user(user["id"], request.match_info["bot_id"])
    return user, bot


def _summary(conversation: dict[str, Any]) -> dict[str, Any]:
    history = conversation.get("history") or []
    return {
        "id": conversation.get("id", ""),
        "title": _title(conversation),
        "created_at": int(conversation.get("created_at") or 0),
        "updated_at": int(conversation.get("updated_at") or 0),
        "message_count": len(history),
        "encrypted": bool(conversation.get("encrypted")),
    }


def _title(conversation: dict[str, Any]) -> str:
    title = str(conversation.get("title") or "").strip()
    if title:
        return title
    for message in conversation.get("history") or []:
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip().replace("\n", " ")[:40]
    return ""


async def _find_conversation(container, bot_id: str, cid: str) -> dict[str, Any]:
    items = await container.conversations.list_for_bot(bot_id, decrypt=True)
    for item in items:
        if str(item.get("id")) == cid:
            return item
    raise NotFound("对话不存在")


def _share_url(request: web.Request, token: str) -> str:
    return f"{request.scheme}://{request.host}/console/share/{token}"


def _share_payload(service, request: web.Request, row: dict[str, Any]) -> dict[str, Any]:
    payload = service.serialize(row)
    payload["url"] = _share_url(request, payload["token"])
    return payload


def _paging(request: web.Request) -> tuple[int, int]:
    try:
        page = max(1, int(request.query.get("page", 1)))
        page_size = max(1, min(100, int(request.query.get("page_size", 20))))
    except (TypeError, ValueError):
        raise ValidationError("page/page_size 必须是整数") from None
    return page, page_size


# -------------------------------------------------------- owner: history
@routes.get("/api/bots/{bot_id}/conversations")
async def list_conversations(request: web.Request) -> web.Response:
    container = container_of(request)
    _, bot = _owned(container, request)
    page, page_size = _paging(request)
    items = await container.conversations.list_for_bot(bot["id"], decrypt=True)
    total = len(items)
    start = (page - 1) * page_size
    window = items[start : start + page_size]
    return ok(
        {
            "items": [_summary(item) for item in window],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@routes.get("/api/bots/{bot_id}/conversations/{conversation_id}")
async def get_conversation(request: web.Request) -> web.Response:
    container = container_of(request)
    _, bot = _owned(container, request)
    conversation = await _find_conversation(
        container, bot["id"], request.match_info["conversation_id"]
    )
    return ok(
        {
            "conversation": {
                "id": conversation.get("id", ""),
                "title": _title(conversation),
                "created_at": int(conversation.get("created_at") or 0),
                "updated_at": int(conversation.get("updated_at") or 0),
                "message_count": len(conversation.get("history") or []),
                "history": conversation.get("history") or [],
                "encrypted": bool(conversation.get("encrypted")),
                "decrypt_error": bool(conversation.get("decrypt_error")),
            }
        }
    )


# ------------------------------------------------------- owner: sharing
@routes.post("/api/bots/{bot_id}/conversations/{conversation_id}/share")
async def create_share(request: web.Request) -> web.Response:
    container = container_of(request)
    user, bot = _owned(container, request)
    body = {}
    if request.can_read_body:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - empty body means "never expires"
            body = {}
    expires_hours: int | None = None
    raw = (body or {}).get("expires_hours") if isinstance(body, dict) else None
    if raw not in (None, "", 0, "0"):
        try:
            expires_hours = int(raw)
        except (TypeError, ValueError):
            raise ValidationError("expires_hours 必须是整数", field="expires_hours") from None
    conversation = await _find_conversation(
        container, bot["id"], request.match_info["conversation_id"]
    )
    service = shares_of(container)
    row = service.create(
        user_id=user["id"],
        bot_id=bot["id"],
        conversation_id=conversation["id"],
        expires_hours=expires_hours,
    )
    container.audit.log(
        actor_id=user["id"],
        actor_role=str(user.get("role") or "user"),
        action="conversation.share_created",
        target_type="conversation",
        target_id=conversation["id"],
        ip=client_ip(request),
        detail={"bot_id": bot["id"], "expires_hours": expires_hours or 0},
    )
    return ok({"share": _share_payload(service, request, row)})


@routes.get("/api/bots/{bot_id}/conversations/{conversation_id}/share")
async def get_share(request: web.Request) -> web.Response:
    container = container_of(request)
    user, bot = _owned(container, request)
    conversation = await _find_conversation(
        container, bot["id"], request.match_info["conversation_id"]
    )
    service = shares_of(container)
    row = service.current(
        user_id=user["id"],
        bot_id=bot["id"],
        conversation_id=conversation["id"],
    )
    if row is None:
        return ok({"share": None})
    return ok({"share": _share_payload(service, request, row)})


@routes.delete("/api/bots/{bot_id}/conversations/{conversation_id}/share")
async def delete_share(request: web.Request) -> web.Response:
    container = container_of(request)
    user, bot = _owned(container, request)
    conversation = await _find_conversation(
        container, bot["id"], request.match_info["conversation_id"]
    )
    revoked = shares_of(container).revoke(
        user_id=user["id"],
        bot_id=bot["id"],
        conversation_id=conversation["id"],
    )
    if revoked:
        container.audit.log(
            actor_id=user["id"],
            actor_role=str(user.get("role") or "user"),
            action="conversation.share_revoked",
            target_type="conversation",
            target_id=conversation["id"],
            ip=client_ip(request),
            detail={"bot_id": bot["id"]},
        )
    return ok({"revoked": True, "count": revoked})


# ------------------------------------------------------------ public view
@routes.get("/api/public/conversations/{token}")
async def public_conversation(request: web.Request) -> web.Response:
    container = container_of(request)
    service = shares_of(container)
    row, expired = service.resolve(request.match_info["token"])
    if row is None:
        raise NotFound("分享链接不存在或已撤销")
    if expired:
        raise AppError("分享链接已过期", code="share_expired", status=410)
    conversation = await _find_conversation(container, row["bot_id"], row["conversation_id"])
    return ok(
        {
            "conversation": {
                "id": conversation.get("id", ""),
                "title": _title(conversation),
                "created_at": int(conversation.get("created_at") or 0),
                "updated_at": int(conversation.get("updated_at") or 0),
                "message_count": len(conversation.get("history") or []),
                "history": conversation.get("history") or [],
                "decrypt_error": bool(conversation.get("decrypt_error")),
            },
            "share": {
                "token": row["token"],
                "created_at": int(row["created_at"]),
                "expires_at": int(row["expires_at"]),
            },
        }
    )


__all__ = ["routes", "shares_of"]
